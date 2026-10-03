"""Assembly interference check: export each sub-module and detect box overlaps.

The model's ``device()`` entry accepts ``group_only`` — a group number (1..5)
or a sub-module name (panel/girders/stringers/struts/cable/railings/
end_columns/arms/hydraulic/river_walls/pivot_bracket/hydro_bracket).  This
script builds one STL per sub-module through the same parameter channel and
reports pairwise bounding-box overlaps in two tiers:

  * high-confidence interference (relative overlap > ``--hit``): parts whose
    boxes overlap a lot — the strut-through-girder / cable-through-beam class
    of modelling error that only shows up in renders after minutes of waiting;
  * touch/connection (relative > ``--touch``): deliberate hinge or seating
    contact, worth a human glance, not an error.

``river_bottom`` (the ground plane) is excluded: every part stands on it, so
its box trivially overlaps everything.

Usage:
    python check_interference.py <project> [--theta 0|90] [--hit 0.35]
        [--touch 0.05] [--json]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from config import load_settings, project_paths
from openscad_run import build_stl

SUBMODULES = {
    "river_walls": "河岸墙", "pivot_bracket": "牛腿", "hydro_bracket": "液压杆牛腿",
    "end_columns": "端柱", "arms": "支臂", "hydraulic": "液压杆",
    "panel": "面板", "girders": "横梁", "stringers": "纵梁",
    "struts": "撑杆", "cable": "拉索", "railings": "栏杆",
}
# 基础承托件：所有活动件都立/搭在其上，bbox 必然重叠——不参与高置信判定，
# 只在"贴靠/接触"档里带过（若与基础件真穿模，会由其它成对检查暴露）。
BASES = {"river_walls"}


def box_overlap(a: dict, b: dict) -> tuple[float, float]:
    spans = []
    for axis in range(3):
        lo = max(a["min"][axis], b["min"][axis])
        hi = min(a["max"][axis], b["max"][axis])
        spans.append(max(0.0, hi - lo))
    overlap = spans[0] * spans[1] * spans[2]

    def volume(box: dict) -> float:
        d = [box["max"][i] - box["min"][i] for i in range(3)]
        return max(1e-9, d[0] * d[1] * d[2])

    return overlap, min(volume(a), volume(b))


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="按子模块导出 STL 并检测装配干涉（包围盒粗筛）")
    parser.add_argument("project")
    parser.add_argument("--theta", type=float, default=0,
                        help="状态角（0=桥态，90=坝态），默认 0")
    parser.add_argument("--hit", type=float, default=0.35,
                        help="高置信干涉的相对重叠阈值，默认 0.35")
    parser.add_argument("--touch", type=float, default=0.05,
                        help="贴靠/连接提示阈值，默认 0.05")
    parser.add_argument("--ignore-pairs", default=None,
                        help="声明已知设计连接对（逗号分隔 a,b），如 "
                             "end_columns,panel,struts,girders——这些对不报高置信")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ignored: set[frozenset[str]] = set()
    if args.ignore_pairs:
        tokens = [t.strip() for t in args.ignore_pairs.split(",") if t.strip()]
        for index in range(0, len(tokens) - 1, 2):
            ignored.add(frozenset((tokens[index], tokens[index + 1])))

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    model = paths["model"] / "device.scad"
    if not model.exists():
        raise SystemExit(f"未找到模型：{model}")

    base = {"SET_THETA": str(int(args.theta))}
    boxes: dict[str, dict] = {}
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="p3d_interf_") as tmp:
        for name, label in SUBMODULES.items():
            out_stl = Path(tmp) / f"{name}.stl"
            # 字符串值必须带引号写入前置：GROUP_ONLY = struts; 会被当成变量引用（undef）
            result = build_stl(model, out_stl,
                               {**base, "GROUP_ONLY": f'"{name}"'}, settings)
            if not result.get("ok"):
                errors.append(f"{label}({name}): {result.get('details', '')[-200:]}")
                continue
            boxes[name] = result["bounding_box"]
            if not args.json:
                size = result["dimensions"]
                print(f"{label:6s} {result['facets']:6d} 面片  "
                      f"{size['x']:.0f}×{size['y']:.0f}×{size['z']:.0f} mm")

    if errors:
        for line in errors:
            print("构建失败:", line[:180])
        return 1

    if not boxes:
        print("没有任何子模块成功构建")
        return 1

    hits: list[dict] = []
    touches: list[dict] = []
    for left in sorted(boxes):
        for right in sorted(boxes):
            if left >= right:
                continue
            overlap, smaller = box_overlap(boxes[left], boxes[right])
            if overlap <= 0:
                continue
            relative = overlap / smaller if smaller else 0.0
            item = {"a": left, "b": right, "a_name": SUBMODULES[left],
                    "b_name": SUBMODULES[right],
                    "overlap_mm3": round(overlap), "relative": round(relative, 3)}
            if left in BASES or right in BASES:
                touches.append(item)               # 与基础承托件的接触
            elif frozenset((left, right)) in ignored:
                touches.append(item)               # 调用方声明为设计连接
            elif relative > args.hit:
                hits.append(item)
            elif relative > args.touch:
                touches.append(item)

    payload = {"model": str(model), "theta": args.theta,
               "hit_threshold": args.hit, "touch_threshold": args.touch,
               "boxes": {k: {"name": SUBMODULES[k], "bbox": boxes[k]}
                         for k in sorted(boxes)},
               "interferences": hits, "touches": touches,
               "ok": not hits}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if hits:
            print("\n[高置信干涉] 建议修复：")
            for item in sorted(hits, key=lambda x: -x["relative"]):
                print(f"  {item['a_name']} × {item['b_name']}  "
                      f"重叠 {item['overlap_mm3']} mm³（相对 {item['relative']}）")
        else:
            print(f"\n未发现高置信干涉（θ={args.theta:.0f}°，{len(boxes)} 个子模块）")
        if touches:
            print("\n[贴靠/连接] 设计连接或贴合，人工确认即可：")
            for item in sorted(touches, key=lambda x: -x["relative"])[:12]:
                print(f"  {item['a_name']} × {item['b_name']}  "
                      f"重叠 {item['overlap_mm3']} mm³（相对 {item['relative']}）")
            if len(touches) > 12:
                print(f"  … 共 {len(touches)} 对")
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
