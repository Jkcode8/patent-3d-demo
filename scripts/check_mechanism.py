"""Check mechanism invariants (hinge connectivity, monotonic travel, length bounds).

A patent mechanism is usually described in prose — "the hydraulic ram pivots on
a bracket; one end always stays attached to the arm".  Those are geometric facts
this script turns into a repeatable gate: the model exports its hinge points as
functions, OpenSCAD evaluates them for a sweep of the driving parameter, and the
script asserts the stated relationships.

Model contract
--------------
The model must define functions returning the hinge coordinates for a given
parameter value.  2D (``[y, z]``) or 3D (``[x, y, z]``) both work; a constant
point is just a function ignoring the argument::

    function pivot_B(theta) = [By(theta), Bz(theta)];   // moves with theta
    function pivot_A(theta) = [22460, 14730];           // fixed anchor

Config (mechanism.json)
-----------------------
.. code-block:: json

    {
      "param": {"name": "theta", "values": [0, 30, 45, 60, 90]},
      "points": {"A": "pivot_A", "B": "pivot_B", "P": "pivot_P"},
      "on_segment": [{"point": "B", "from": "arm_low", "to": "pivot_P", "tol": 50}],
      "monotonic": [{"a": "A", "b": "B", "want": "increasing"}],
      "length_bounds": [{"a": "A", "b": "B", "min": 7000, "max": 21000}],
      "defines": {"SET_THETA": "0"}
    }

Assertions
----------
* ``on_segment``  — point stays on (within ``tol`` of) the segment from→to at every
  parameter value.  Catches "hinge no longer attached to the arm" regressions.
* ``monotonic``  — the distance between two points changes monotonically as the
  parameter sweeps (``increasing`` / ``decreasing`` / ``constant``).  Catches a
  hydraulic ram that would need to telescope in and out twice per stroke.
* ``length_bounds`` — the distance stays inside [min, max] for every sample.

Usage::

    python check_mechanism.py --model model/device.scad --config mechanism.json [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from pathlib import Path

from config import find_openscad, load_settings, project_paths, read_json
from openscad_run import inline_model, run_cli

ECHO_RE = re.compile(r'ECHO: "MECH_CHK", "(?P<name>[^"]+)", "(?P<value>\[[^\]]*\])"')
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


# ---------------------------------------------------------------- 纯函数（可单测）
def parse_vector(text: str) -> list[float] | None:
    values = NUMBER_RE.findall(text)
    if not values:
        return None
    return [float(v) for v in values]


def dist_to_segment(p: tuple[float, ...], a: tuple[float, ...],
                    b: tuple[float, ...]) -> float:
    """Distance from point *p* to segment a–b (any dimension ≥ 2)."""
    ab = tuple(q - r for q, r in zip(b, a))
    ap = tuple(q - r for q, r in zip(p, a))
    length_sq = sum(v * v for v in ab)
    if length_sq <= 1e-12:
        return math.dist(p, a)
    t = sum(x * y for x, y in zip(ap, ab)) / length_sq
    t = max(0.0, min(1.0, t))
    closest = tuple(a[i] + t * ab[i] for i in range(len(a)))
    return math.dist(p, closest)


def check_on_segment(samples: dict[str, list[list[float]]],
                     spec: dict, tol: float) -> tuple[bool, list[dict]]:
    """Assert ``point`` stays within *tol* of segment from→to at every sample."""
    results: list[dict] = []
    point, fr, to = spec["point"], spec["from"], spec["to"]
    if point not in samples or fr not in samples or to not in samples:
        return False, [{"error": f"on_segment 缺少点：{point}/{fr}/{to}（配置里的 points 必须都定义）"}]
    ok = True
    for index, (pp, ff, tt) in enumerate(zip(samples[point], samples[fr], samples[to])):
        dist = dist_to_segment(tuple(pp), tuple(ff), tuple(tt))
        results.append({"sample": index, "point": pp, "dist": round(dist, 1),
                        "ok": dist <= tol})
        ok = ok and dist <= tol
    return ok, results


def check_monotonic(values: list[float], want: str) -> tuple[bool, list[dict]]:
    """Assert the sample series is monotonic (tolerating tiny numerical noise)."""
    eps = 1e-6
    results = [{"value": round(v, 1)} for v in values]
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if not deltas:
        return want == "constant", results
    if want == "increasing":
        ok = all(d >= -eps for d in deltas) and max(deltas) > eps
    elif want == "decreasing":
        ok = all(d <= eps for d in deltas) and min(deltas) < -eps
    else:
        ok = all(abs(d) <= eps for d in deltas)
    return ok, results


def check_length_bounds(values: list[float], spec: dict) -> tuple[bool, list[dict]]:
    ok = True
    results = []
    for value in values:
        within = spec["min"] <= value <= spec["max"]
        ok = ok and within
        results.append({"value": round(value, 1), "ok": within})
    return ok, results


def parse_config(raw: dict) -> dict:
    """Validate the config shape and return it (raises ValueError on misuse)."""
    if not isinstance(raw, dict) or "param" not in raw or "points" not in raw:
        raise ValueError("配置需要 param 与 points 字段（参见 SKILL.md 的 mechanism.json 示例）")
    param = raw["param"]
    if not isinstance(param, dict) or "name" not in param or not param.get("values"):
        raise ValueError("param 需要 {\"name\": ..., \"values\": [..]} 形式")
    if not isinstance(raw["points"], dict) or not raw["points"]:
        raise ValueError("points 至少需要一个函数映射，如 {\"B\": \"pivot_B\"}")
    return raw


# ---------------------------------------------------------------- OpenSCAD 驱动
def build_wrapper(model: Path, defines: dict[str, str], points: dict[str, str],
                  param_values: list[float], temp_dir: Path) -> Path:
    """Wrapper that inlines the model and echoes every hinge point for every value."""
    source = inline_model(model)
    calls = []
    for value in param_values:
        for name, fn in points.items():
            calls.append(f'echo("MECH_CHK", "{name}", str({fn}({value})));')
    preamble = "\n".join(f"{key} = {value};" for key, value in sorted(defines.items()))
    wrapper = temp_dir / "mechanism_check.scad"
    wrapper.write_text(
        f"// generated by check_mechanism.py（模型已内联）\n{preamble}\n{source}\n"
        f"{''.join(calls)}\n"
        # 最小占位几何：保证 OpenSCAD 正常编译输出（无 CSG 时会警告且 exit != 0）
        f"translate([-0.001, -0.001, -0.001]) cube([0.002, 0.002, 0.002]);\n",
        encoding="utf-8")
    return wrapper


def run_samples(model: Path, config: dict, settings: dict) -> dict[str, list[list[float]]]:
    """Compile the wrapper once and return ``name -> [coords per param value]``."""
    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD，请设置 OPENSCAD_EXECUTABLE")
    param = config["param"]
    points: dict[str, str] = config["points"]
    with tempfile.TemporaryDirectory(prefix="p3d_mech_") as tmp:
        temp_dir = Path(tmp)
        wrapper = build_wrapper(model, config.get("defines", {}), points,
                                [float(v) for v in param["values"]], temp_dir)
        result = run_cli(openscad, ["-o", str(temp_dir / "out.stl"), str(wrapper)], 300)
    if result.returncode != 0:
        raise SystemExit("OpenSCAD 求值失败：\n" + (result.stdout + result.stderr).strip()[-2000:])
    samples: dict[str, list[list[float]]] = {name: [] for name in points}
    for match in ECHO_RE.finditer(result.stdout):
        name, text = match.group("name"), match.group("value")
        if name in samples:
            coords = parse_vector(text)
            if coords:
                samples[name].append(coords)
    for name, values in samples.items():
        if len(values) != len(param["values"]):
            raise SystemExit(
                f"点 {name} 只采到 {len(values)}/{len(param['values'])} 个值"
                f"（模型是否导出函数 {points[name]}？）")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="机构几何断言（铰点连接/杆长单调/长度范围）")
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", required=True, help="mechanism.json 路径")
    parser.add_argument("--project", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project).resolve() if args.project else Path.cwd()
    settings = load_settings(root)
    model = Path(args.model)
    if not model.is_absolute():
        model = (root / args.model) if (root / args.model).exists() else project_paths(root)["model"] / args.model
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / args.config
    config = parse_config(read_json(config_path))

    param = config["param"]
    samples = run_samples(model, config, settings)
    report: dict = {
        "model": str(model),
        "param": param["name"],
        "samples": param["values"],
        "checks": [],
        "ok": True,
    }
    for spec in config.get("on_segment", []):
        ok, details = check_on_segment(samples, spec, float(spec.get("tol", 50)))
        report["checks"].append({"type": "on_segment", "spec": spec,
                                 "ok": ok, "details": details})
        report["ok"] = report["ok"] and ok
    for spec in config.get("monotonic", []):
        a, b, want = spec["a"], spec["b"], spec.get("want", "increasing")
        lengths = [math.dist(aa, bb) for aa, bb in zip(samples[a], samples[b])]
        ok, details = check_monotonic(lengths, want)
        report["checks"].append({"type": "monotonic", "spec": spec,
                                 "lengths": [round(v, 1) for v in lengths],
                                 "ok": ok, "details": details})
        report["ok"] = report["ok"] and ok
    for spec in config.get("length_bounds", []):
        a, b = spec["a"], spec["b"]
        lengths = [math.dist(aa, bb) for aa, bb in zip(samples[a], samples[b])]
        ok, details = check_length_bounds(lengths, spec)
        report["checks"].append({"type": "length_bounds", "spec": spec,
                                 "lengths": [round(v, 1) for v in lengths],
                                 "ok": ok, "details": details})
        report["ok"] = report["ok"] and ok
    if not report["checks"]:
        report["ok"] = False
        report["checks"].append({"error": "配置里没有任何断言（on_segment/monotonic/length_bounds）"})

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"机构检查：{model.name}　参数 {param['name']}∈{param['values']}")
        for check in report["checks"]:
            spec = check.get("spec", {})
            if "lengths" in check:
                print(f"  [{'PASS' if check['ok'] else 'FAIL'}] {check['type']} {spec}  "
                      f"杆长 {check['lengths']}")
            else:
                print(f"  [{'PASS' if check['ok'] else 'FAIL'}] {check['type']} {spec}")
        print("全部通过" if report["ok"] else "存在失败断言")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
