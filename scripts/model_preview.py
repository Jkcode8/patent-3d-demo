"""Modelling fast-preview loop: low-cost thumbnails that re-render on save.

The render pipeline (``storyboard.py render``) is built for final output; this
script is the modelling counterpart.  It renders a small three-view preview
with coarse tessellation (``$fn`` dropped to ~12) so a geometry edit can be
checked in seconds instead of waiting for a full 1920 px render.  ``--watch``
polls the model file (and sibling ``.scad`` includes) and re-renders whenever
any of them changes — a save-to-see loop for iterative modelling.

Usage:
    python model_preview.py <model> [--size 640,480] [--fn 12]
        [--views front,top,front-right-top-iso] [--watch] [--json]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from config import load_settings, project_paths
from openscad_run import render_views


def render_once(model: Path, out_dir: Path, views: list[str], size: str,
                fn: int, settings: dict) -> dict:
    defines = {"SET_FN": str(fn)}
    started = time.time()
    result = render_views(model, out_dir, views, defines, settings, size=size)
    result["render_seconds"] = round(time.time() - started, 2)
    return result


def watch(model: Path, out_dir: Path, views: list[str], size: str,
          fn: int, settings: dict, poll: float = 0.6) -> int:
    def stamp() -> tuple[float, ...]:
        paths = [model] + sorted(model.parent.glob("*.scad"))
        return tuple(p.stat().st_mtime_ns for p in paths if p.exists())

    last = stamp()
    print(f"监听 {model}（改文件即自动重渲，Ctrl+C 退出）")
    while True:
        time.sleep(poll)
        now = stamp()
        if now != last:
            last = now
            print(f"\n检测到变更 @ {time.strftime('%H:%M:%S')}")
            render_once(model, out_dir, views, size, fn, settings)


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="建模快速预览（低细分小图，--watch 自动重渲）")
    parser.add_argument("model", help=".scad 模型路径（可相对项目）")
    parser.add_argument("--out-dir", default=None, help="默认 <项目>/figures/_preview")
    parser.add_argument("--views", default="front,top,front-right-top-iso",
                        help="逗号分隔视角，默认三视图")
    parser.add_argument("--size", default="640,480")
    parser.add_argument("--fn", type=int, default=12, help="预览细分（$fn），默认 12")
    parser.add_argument("--watch", action="store_true")
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
    out_dir = Path(args.out_dir) if args.out_dir else project_paths(root)["figures"] / "_preview"
    views = [v.strip() for v in args.views.split(",") if v.strip()]

    if args.watch:
        return watch(model, out_dir, views, args.size, args.fn, settings)

    result = render_once(model, out_dir, views, args.size, args.fn, settings)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if not result.get("ok"):
        print(f"预览渲染失败：{result.get('error')}")
        print((result.get("details") or "")[-600:])
        return 1
    print(f"预览 {result.get('count')} 张 → {out_dir}  （{result['render_seconds']}s，$fn={args.fn}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
