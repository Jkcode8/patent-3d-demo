"""Cross-check drawing dimension annotations against the model's parameters.

``verify_vs_drawing`` answers "is the outline the right shape" — but it
normalises both sides to their bounding boxes, so a digit swap (drawing says
9000, the model says 900) still scores a perfect outline match.  This script
asks the complementary question: *do the numbers agree?*

It reads the annotations out of the drawing (``extract_dxf``'s ezdxf reader,
falling back to the dependency-free ASCII reader) and the length parameters out
of the ``.scad`` source, normalises units to millimetres and reports which
drawing values have a corresponding model parameter.

Usage:
    python dim_check.py <项目> [--drawing 图.dxf] [--model model/device.scad]
                        [--tol 0.01] [--strict] [--json]

``--strict`` makes unmatched annotations a non-zero exit, for CI/regression use;
by default this is an advisory report, because drawings carry plenty of numbers
that are not device dimensions (sheet numbers, radii of fillets, counts).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from config import project_paths

#: 图纸上出现这些标记的一律当角度处理，不参与长度比对
ANGLE_HINTS = ("°", "º", "度", "deg")
#: 参数名里出现这些词的一律当非长度（角度/圈数/分段数）跳过
NON_LENGTH_NAME = re.compile(r"THETA|ANGLE|DEG|RAD|TURN|SEG|_FN|FPS", re.IGNORECASE)

#: 直径/半径前缀 + 数字 + 可选单位（m / cm / mm，缺省按图纸惯例取 mm）
LENGTH_RE = re.compile(r"[φΦ∅ØRr]?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?", re.IGNORECASE)
#: 模型里的 `NAME = 数值;` / `NAME = is_undef(..) ? 数值 : ..;`
MODEL_LENGTH_RE = re.compile(
    r"^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(?:is_undef\([^)]*\)[ \t]*\?[ \t]*)?(\d+(?:\.\d+)?)\b",
    re.MULTILINE)
#: "4×φ20" 里的数量前缀，不是长度
COUNT_PREFIX_RE = re.compile(r"\d+\s*[×xX]\s*(?=[φΦ∅ØRr]?\s*\d)")
UNIT_FACTOR = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def normalize_length(value: float, unit: str | None) -> float:
    """Convert a drawing value to millimetres (unit-less is taken as mm)."""
    return value * UNIT_FACTOR.get((unit or "mm").lower(), 1.0)


def annotation_text(raw: str) -> str:
    """Strip ``extract_dxf``'s ``[Model] x,y,0 :: `` prefix if present."""
    return raw.split("::", 1)[-1].strip() if "::" in raw else raw.strip()


def annotated_lengths(annotations) -> list[tuple[float, str]]:
    """``[(mm, 原始标注), ...]`` from drawing text/dimension annotations."""
    found: list[tuple[float, str]] = []
    for raw in annotations:
        text = annotation_text(str(raw))
        if not text or any(hint in text for hint in ANGLE_HINTS):
            continue
        text = COUNT_PREFIX_RE.sub("", text)
        for match in LENGTH_RE.finditer(text):
            found.append((normalize_length(float(match.group(1)), match.group(2)), text))
    return found


def model_lengths(source: str) -> dict[str, float]:
    """Length-looking ``NAME = <number>`` parameters, in model units (mm)."""
    found: dict[str, float] = {}
    for match in MODEL_LENGTH_RE.finditer(source):
        name, value = match.group(1), float(match.group(2))
        if name.startswith("_") or NON_LENGTH_NAME.search(name):
            continue
        found.setdefault(name, value)
    return found


def match_lengths(model_values: dict[str, float], drawing_values,
                  tol: float = 0.01) -> dict:
    """Pair each drawing value with a model parameter, first-come first-served."""
    matched, unmatched, used = [], [], set()
    for value, source in drawing_values:
        hit = next((name for name, model_value in sorted(model_values.items())
                    if name not in used
                    and abs(model_value - value) <= tol * max(abs(value), 1.0)), None)
        if hit:
            used.add(hit)
            matched.append({"annotation": source, "value": value, "param": hit})
        else:
            unmatched.append({"annotation": source, "value": value})
    missing = [{"param": name, "value": value}
               for name, value in sorted(model_values.items()) if name not in used]
    return {"matched": matched, "unmatched_annotations": unmatched,
            "params_without_annotation": missing}


def find_drawing(root: Path) -> Path | None:
    """First DXF under 原始资料/ then _extract/ (same search order as the skill)."""
    for folder in ("原始资料", "_extract"):
        base = root / folder
        if not base.is_dir():
            continue
        for suffix in (".dxf", ".DXF"):
            hits = sorted(path for path in base.rglob(f"*{suffix}") if path.is_file())
            if hits:
                return hits[0]
    return None


def drawing_annotations(path: Path) -> list[str]:
    """Text + dimension annotations from a DXF (ezdxf, else minimal reader)."""
    from extract_dxf import read_minimal, read_with_ezdxf

    try:
        result = read_with_ezdxf(path)
    except Exception:
        result = {}
    if not result.get("texts") and not result.get("dims") and not result.get("hist"):
        # ezdxf 有时能"成功"读出一个空文档；退回无依赖解析器再试一次，
        # 免得把"没读到"变成一份静默通过的报告
        result = read_minimal(path)
    return list(result.get("texts") or []) + list(result.get("dims") or [])


def describe(report: dict) -> str:
    matched = report["matched"]
    unmatched = report["unmatched_annotations"]
    lines = [f"图纸标注 {report['drawing_values']} 个，"
             f"匹配上模型参数 {len(matched)} 个，"
             f"找不到对应 {len(unmatched)} 个"]
    if matched:
        lines.append("")
        lines.append("| 图纸标注 | 数值(mm) | 模型参数 |")
        lines.append("|---|---|---|")
        for item in matched:
            lines.append(f"| {item['annotation']} | {item['value']:g} | `{item['param']}` |")
    if unmatched:
        lines.append("")
        lines.append("模型里找不到对应数值的标注（可能是别的构件、图框数字，或**模型写错了**）：")
        for item in unmatched:
            lines.append(f"  - {item['annotation']} → {item['value']:g} mm")
    return "\n".join(lines)


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="图纸标注 ↔ 模型参数 数值核对")
    parser.add_argument("project")
    parser.add_argument("--drawing", default=None, help="默认取 原始资料/ 或 _extract/ 下的第一张 DXF")
    parser.add_argument("--model", default="model/device.scad")
    parser.add_argument("--tol", type=float, default=0.01, help="相对容差（默认 1%%）")
    parser.add_argument("--strict", action="store_true",
                        help="存在找不到对应的标注时以非零退出（CI 用）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    model = Path(args.model)
    if not model.is_absolute():
        model = paths["root"] / model
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")
    drawing = Path(args.drawing) if args.drawing else find_drawing(paths["root"])
    if drawing is None or not Path(drawing).exists():
        raise SystemExit("没有找到图纸：用 --drawing <文件.dxf> 指定，"
                         f"或把 DXF 放进 {paths['sources']}")

    model_values = model_lengths(model.read_text(encoding="utf-8", errors="replace"))
    drawing_values = annotated_lengths(drawing_annotations(Path(drawing)))
    report = {"model": str(model), "drawing": str(drawing), "tol": args.tol,
              "model_values": len(model_values), "drawing_values": len(drawing_values),
              **match_lengths(model_values, drawing_values, args.tol)}
    report["ok"] = not report["unmatched_annotations"]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(describe(report))
        print("")
        print(f"模型参数 {len(model_values)} 个，其中 "
              f"{len(model_values) - len(report['params_without_annotation'])} 个在图纸上有对应标注")
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
