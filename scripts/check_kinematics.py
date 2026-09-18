"""Validate a parametric model against the force/state labels on a drawing.

When a drawing labels how each member behaves in a working case (受拉/受压, 伸长
or 缩短), the geometric model should reproduce that pattern.  This script sweeps
the driving parameters of a simple planar mechanism and reports which
combinations reproduce the labelled pattern, so the deformation used in the
video is traceable rather than guessed.

Mechanism model (rigid struts + collars sliding on a rod, exactly the situation
the common "hinged strut + sliding collar" arrangement):
    H  hinge node (fixed)          C  rod centre      u  rod direction
    L1, L2  fixed strut lengths to the upper / lower collars
Collar positions follow from  ``|C + t·u − H| = L``; every spring or damper
length is then geometry, not a drawing choice.

Usage:
    python check_kinematics.py params.json [--json]

params.json (all lengths mm, angles degrees):
{
  "hinge": [0, 0], "node_r": 800, "rod_z": 400,
  "collar_up_z": 700, "collar_dn_z": 100,
  "anchor_z": 60,
  "expected": {"spring1": "compress", "spring2": "stretch",
               "spring3": "stretch", "damper": "compress"},
  "sweep": {"theta": [-14, -12, -10, -8, -6], "pull": [300, 600, 900, 1200]}
}
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def solve(params: dict, theta_deg: float, pull: float) -> dict:
    hx, hz = params["hinge"]
    node_r, rod_z = params["node_r"], params["rod_z"]
    up_z, dn_z = params["collar_up_z"], params["collar_dn_z"]
    anchor_z = params.get("anchor_z", 0.0)
    sleeve_r = params.get("sleeve_ro", node_r * 0.5)

    th = math.radians(theta_deg)
    u = (math.sin(th), math.cos(th))
    cx, cz = node_r - pull, rod_z

    def dist(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1])

    def collar(length: float, t_ref: float) -> float:
        w = (cx - hx, cz - hz)
        b = w[0] * u[0] + w[1] * u[1]
        c = w[0] ** 2 + w[1] ** 2 - length ** 2
        disc = b * b - c
        sq = math.sqrt(disc) if disc > 0 else 0.0
        t1, t2 = -b + sq, -b - sq
        return t1 if abs(t1 - t_ref) <= abs(t2 - t_ref) else t2

    def point(t):
        return (cx + t * u[0], cz + t * u[1])

    t_up = collar(dist((node_r, up_z), (hx, hz)), up_z - rod_z)
    t_dn = collar(dist((node_r, dn_z), (hx, hz)), dn_z - rod_z)
    upper, lower = point(t_up), point(t_dn)
    a_up = (sleeve_r + 150, anchor_z)
    a_dn = (sleeve_r + 150, -anchor_z)

    return {
        "spring1": dist(a_up, upper) - dist(a_up, (node_r, up_z)),
        "spring2": (t_up - t_dn) - (up_z - dn_z),
        "spring3": dist(a_dn, lower) - dist(a_dn, (node_r, dn_z)),
        "damper": dist((hx, hz), (cx, cz)) - dist((hx, hz), (node_r, rod_z)),
        "collar_up_slide": t_up - (up_z - rod_z),
        "collar_dn_slide": t_dn - (dn_z - rod_z),
    }


STATE = {"compress": lambda d: d < -0.02, "stretch": lambda d: d > 0.02,
         "unchanged": lambda d: abs(d) <= 0.02}


def match(result: dict, expected: dict) -> tuple[bool, list[str]]:
    detail = []
    ok = True
    for member, want in expected.items():
        delta = result.get(member)
        if delta is None:
            continue
        good = STATE[want](delta)
        ok = ok and good
        sign = "拉" if delta > 0 else ("压" if delta < 0 else "不变")
        detail.append(f"{member}={delta:+.0f}mm({sign}){'✓' if good else '✗'}")
    return ok, detail


def main() -> int:
    parser = argparse.ArgumentParser(description="机构参数扫描与受力状态校验")
    parser.add_argument("params")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    expected = params.get("expected", {})
    sweep = params.get("sweep", {"theta": [0], "pull": [0]})
    matches, rows = 0, []
    for theta in sweep.get("theta", [0]):
        for pull in sweep.get("pull", [0]):
            result = solve(params, float(theta), float(pull))
            ok, detail = match(result, expected)
            matches += ok
            rows.append({"theta": theta, "pull": pull, "match": ok, "members": detail,
                         "raw": {k: round(v, 1) for k, v in result.items()}})
    payload = {"params": str(args.params), "combinations": len(rows),
               "matches": matches, "rows": rows}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{len(rows)} 组参数，{matches} 组与图纸标注一致")
        for row in rows:
            flag = "✓" if row["match"] else " "
            print(f"  {flag} θ={row['theta']:>5} pull={row['pull']:>6}  "
                  + "  ".join(row["members"]))
    return 0 if matches or not expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
