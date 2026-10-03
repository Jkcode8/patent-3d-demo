"""Parameter-change sanity check: what do dimension edits actually move?

Modelling bugs often hide in a parameter edit that silently does nothing —
the knob is read somewhere in the model, but the geometry it was supposed to
drive never changes.  This script renders the model twice per parameter
(without / with the override), compares the STL bounding box and volume, and
prints a small preview contact sheet, so a dead parameter is caught in
seconds instead of after a full video render.

Usage:
    python param_check.py <project> --param SET_BASE_L=500 --param SET_THETA=90
        [--size 640,480] [--fn 12] [--views front,top] [--json]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from config import load_settings, project_paths
from openscad_run import build_stl, render_views

DEFAULT_VIEWS = ["front-right-top-iso", "front", "top"]


def box_report(result: dict) -> dict:
    box, dims = result["bounding_box"], result["dimensions"]
    vol = (dims["x"] * dims["y"] * dims["z"])
    return {"min": box["min"], "max": box["max"], "x": dims["x"], "y": dims["y"],
            "z": dims["z"], "volume_mm3": round(vol), "facets": result["facets"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="参数变更→尺寸/渲染验证")
    parser.add_argument("project")
    parser.add_argument("--param", action="append", default=[],
                        help="参数覆盖，如 SET_BASE_L=500（可多次）")
    parser.add_argument("--size", default="640,480")
    parser.add_argument("--fn", type=int, default=12)
    parser.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    model = paths["model"] / "device.scad"
    if not model.exists():
        raise SystemExit(f"未找到模型：{model}")

    overrides: dict[str, str] = {}
    for item in args.param:
        key, _, value = item.partition("=")
        if not key:
            raise SystemExit(f"参数格式应为 KEY=VALUE：{item}")
        overrides[key.strip()] = value.strip()

    rows = []
    with tempfile.TemporaryDirectory(prefix="p3d_param_") as tmp:
        for label, defines in [("基准", {}), ("变更", overrides)]:
            stl = Path(tmp) / f"{label}.stl"
            result = build_stl(model, stl, defines, settings)
            if not result.get("ok"):
                raise SystemExit(f"{label} 构建失败：{result.get('details', '')[-300:]}")
            rows.append(box_report(result))

    base, changed = rows
    delta = {axis: round(changed[axis] - base[axis], 1)
             for axis in ("x", "y", "z")}
    volume_delta = round(changed["volume_mm3"] - base["volume_mm3"])
    payload = {
        "model": str(model), "params": overrides,
        "base": base, "changed": changed,
        "delta": delta, "volume_delta_mm3": volume_delta,
        "changed_size": any(abs(v) > 1e-6 for v in delta.values()),
    }

    # 缩略图预览（变更状态，快速三视图）
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    preview = paths["figures"] / "_preview"
    render_views(model, preview, views, {"SET_FN": str(args.fn)}, settings, size=args.size)
    payload["preview_dir"] = str(preview)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"基准 bbox {base['x']:.0f}×{base['y']:.0f}×{base['z']:.0f} mm  "
              f"体积 {base['volume_mm3']} mm³")
        print(f"变更 bbox {changed['x']:.0f}×{changed['y']:.0f}×{changed['z']:.0f} mm  "
              f"体积 {changed['volume_mm3']} mm³")
        print(f"Δx={delta['x']:.1f} Δy={delta['y']:.1f} Δz={delta['z']:.1f}  "
              f"Δ体积={volume_delta}")
        if not payload["changed_size"]:
            print("警告：参数未改变任何包围盒尺寸——检查参数名是否被模型读取，"
                  "或该参数只影响内部细节")
        print(f"预览 → {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
