"""Turn the extracted CAD view analysis into a modelling skeleton.

``stage1`` extraction produces ``_extract/views.json``: per-view bounding box
(size in mm), entity count and labelled part coordinates (e.g. 撑杆/拉索/面板
annotation text placed on the drawing).  This script turns that into a
``model/skeleton.json`` the modeller can start from — the part catalogue, where
each part sits in each view (normalised 0–1), which views agree about it, and
an overall dimension suggestion.  It does not do free-form geometry clustering;
it gives the starting bones so the parametric ``device.scad`` module split
comes from the drawing, not from scratch.

Usage:
    python sketch_to_skeleton.py <project> [--json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import project_paths, read_json, write_json

SKIP_LABELS = {"平面", "立面", "A", "B", "水流方向"}


def is_title_label(name: str) -> bool:
    """View titles (A-A（水坝状态）, B-B（桥梁状态）) are not parts."""
    return ("状态）" in name or "（水坝" in name or "（桥梁" in name
            or name.startswith("A-A") or name.startswith("B-B"))


def normalise(view: dict, label: list) -> dict:
    """Map a label (x, y, name) into 0–1 coordinates inside its view box."""
    x, y, name = float(label[0]), float(label[1]), str(label[2])
    bx0, by0, _bx1, _by1 = view["bb"]
    w, h = max(1.0, view["w"]), max(1.0, view["h"])
    return {"name": name, "x": round((x - bx0) / w, 3), "y": round((y - by0) / h, 3)}


def build_skeleton(root: Path, extract: dict) -> dict:
    views: list[dict] = []
    parts: dict[str, dict] = {}
    for view_name, view in extract.items():
        entry = {"name": view_name, "w": view["w"], "h": view["h"],
                 "n": view.get("n", 0)}
        views.append(entry)
        for raw in view.get("labels", []):
            if len(raw) < 3:
                continue
            pos = normalise(view, raw)
            if pos["name"] in SKIP_LABELS or is_title_label(pos["name"]) \
                    or not pos["name"].strip():
                continue
            part = parts.setdefault(pos["name"], {"name": pos["name"],
                                                  "views": {}, "occurrences": []})
            part["views"].setdefault(view_name, {"w": view["w"], "h": view["h"],
                                                 "x": pos["x"], "y": pos["y"]})
            part["occurrences"].append({"view": view_name,
                                        "x": pos["x"], "y": pos["y"]})

    # 融合：同一部件在多个视图的位置取均值，并给出"主视图"（出现次数最多，其次视图更宽者）
    part_list = []
    for part in parts.values():
        occ = part["occurrences"]
        by_view = part["views"]

        def view_count(v: str) -> int:
            return sum(1 for o in occ if o["view"] == v)

        main_view = max(by_view, key=lambda v: (view_count(v),
                                                by_view[v].get("w", 0), v))
        xs = [o["x"] for o in occ]
        ys = [o["y"] for o in occ]
        part_list.append({
            "name": part["name"],
            "views": sorted(by_view),
            "main_view": main_view,
            "x_norm": round(sum(xs) / len(xs), 3),
            "y_norm": round(sum(ys) / len(ys), 3),
            "occurrences": occ,
        })

    # 整体尺寸建议：平面给 X/Y 跨度，立面/剖视给 Z（高）参考
    plane = extract.get("平面")
    elevation = extract.get("立面")
    overall = {}
    if plane:
        overall["x_span"] = plane["w"]
        overall["y_span"] = plane["h"]
    if elevation:
        overall["z_height"] = elevation["h"]
    overall["note"] = ("由视图包围盒推算的总体尺寸建议；坐标原点/方向需按图纸对齐，"
                       "体块为建模起点而非精确几何")

    return {"project": root.name, "views": views, "parts": part_list,
            "overall": overall}


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="图纸标注 → 建模骨架 skeleton.json")
    parser.add_argument("project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    extract = read_json(paths["extract"] / "views.json")
    if not extract:
        raise SystemExit("缺少 _extract/views.json——先运行资料提取（stage1）生成视图分析")
    skeleton = build_skeleton(paths["root"], extract)
    target = paths["model"] / "skeleton.json"
    write_json(target, skeleton)

    lines = [f"# 建模骨架（{len(skeleton['parts'])} 个部件）", "",
             "| 部件 | 出现视图 | 主视图 | 归一化位置(x,y) |", "|---|---|---|---|"]
    for part in skeleton["parts"]:
        lines.append(f"| {part['name']} | {', '.join(part['views'])} | "
                     f"{part['main_view']} | {part['x_norm']}, {part['y_norm']} |")
    lines.append("")
    lines.append(f"总体建议：{json.dumps(skeleton['overall'], ensure_ascii=False)}")
    (paths["model"] / "skeleton.md").write_text("\n".join(lines), encoding="utf-8")

    if args.json:
        print(json.dumps(skeleton, ensure_ascii=False, indent=2))
    else:
        print(f"骨架：{len(skeleton['parts'])} 个部件 → {target}")
        for part in skeleton["parts"][:12]:
            print(f"  {part['name']:6s} 主视图 {part['main_view']:8s} "
                  f"({part['x_norm']}, {part['y_norm']})")
        if len(skeleton["parts"]) > 12:
            print(f"  … 共 {len(skeleton['parts'])} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
