"""Build STL and render camera views with OpenSCAD (CLI first, MCP optional).

Why the CLI by default: the OpenSCAD MCP server is convenient but machine
specific (it needs a configured server and a fixed workspace).  Driving
``openscad`` directly needs nothing but the binary, which keeps this skill
portable.  ``--mode mcp`` uses the configured MCP server instead.

Colour note: STL files carry no colour, so rendering is done from the ``.scad``
source.  Any ``$vpt/$vpr/$vpd`` viewport preset in the source is stripped into a
temporary copy, otherwise those presets would override ``--viewall`` and every
camera angle would look the same.

Usage:
    python openscad_run.py --model model/pier.scad --out-dir figures \
        --angles front,top,front-right-top-iso --define THETA=-12 --json
    python openscad_run.py --model model/seg_turntable.scad --out-dir video/frames/tour \
        --animate 325 --define A1=0.16
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import (
    detect_deps,
    find_openscad,
    load_settings,
    project_paths,
)
from stl_parser import parse_stl

# label -> (translate, rotation)  (mirrors the OpenSCAD MCP camera set)
ANGLES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "front": ((0, -100, 0), (90, 0, 0)),
    "back": ((0, 100, 0), (90, 0, 180)),
    "left": ((-100, 0, 0), (90, 0, 270)),
    "right": ((100, 0, 0), (90, 0, 90)),
    "top": ((0, 0, 100), (0, 0, 0)),
    "bottom": ((0, 0, -100), (180, 0, 0)),
    "front-right-top-iso": ((80, -80, 80), (55, 0, 45)),
    "back-left-top-iso": ((-80, 80, 80), (55, 0, 225)),
}
VIEWPORT_RE = re.compile(r"^\s*\$vp[tdr]\s*=.*$", re.MULTILINE)
DEFAULT_CALL_RE = re.compile(r"^\s*device\(\)\s*;\s*$", re.MULTILINE)


def inline_model(model: Path) -> str:
    """Return the model source with its trailing default ``device();`` removed.

    Templates and line-art wrappers inline the model and then drive ``device()``
    themselves; a leftover top-level call draws geometry outside the projection
    and triggers "Mixing 2D and 3D objects" in OpenSCAD.  Matching whole lines
    (instead of the file tail) keeps working when the file ends with comments.
    """
    return DEFAULT_CALL_RE.sub("", model.read_text(encoding="utf-8"))


def render_source(model: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    """Return a model path safe to render (viewport presets removed)."""
    text = model.read_text(encoding="utf-8")
    stripped = VIEWPORT_RE.sub("", text)
    if stripped == text:
        return model, None
    temp_dir = tempfile.TemporaryDirectory(prefix="p3d_render_")
    target = Path(temp_dir.name) / model.name
    target.write_text(re.sub(r"\n{3,}", "\n\n", stripped), encoding="utf-8")
    for extra in model.parent.glob("*.scad"):      # keep sibling includes working
        if extra.name != model.name:
            shutil.copy2(extra, Path(temp_dir.name) / extra.name)
    return target, temp_dir


def camera_arg(label: str) -> str:
    _translate, rotation = ANGLES[label]
    return f"0,0,0,{rotation[0]},{rotation[1]},{rotation[2]},0"


def run_cli(openscad: str, argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([openscad] + argv, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)


def build_stl(model: Path, out_stl: Path, defines: dict[str, str],
              settings: dict, timeout: int = 900) -> dict:
    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD，请设置 OPENSCAD_EXECUTABLE")
    out_stl.parent.mkdir(parents=True, exist_ok=True)
    source, temp = render_source(model)
    argv: list[str] = ["-o", str(out_stl), "-D", f"SET_FN={settings['scad_fn']}",
                       "-D", f"SET_COIL_SEG={settings['scad_coil_seg']}"]
    argv += [item for key, value in defines.items() for item in ("-D", f"{key}={value}")]
    argv.append(str(source))
    try:
        result = run_cli(openscad, argv, timeout)
    finally:
        if temp:
            temp.cleanup()
    if result.returncode != 0 or not out_stl.exists():
        return {"ok": False, "error": "OpenSCAD 编译失败",
                "details": (result.stdout + result.stderr).strip()[-2000:]}
    return {"ok": True, "stl": str(out_stl), **stl_metadata(out_stl)}


def model_extent(model: Path, defines: dict[str, str], settings: dict) -> dict | None:
    """Bounding box of *model* (built once into a temp STL).

    Camera distance must scale with the part: the same template has to frame a
    900 mm bracket and a 48 m pier.  ``$vpd ≈ 3.1 × max_dimension`` matches the
    framing used for the civil-engineering models.
    """
    with tempfile.TemporaryDirectory(prefix="p3d_extent_") as tmp:
        result = build_stl(model, Path(tmp) / "extent.stl", defines, settings)
    if not result.get("ok"):
        return None
    box = result["bounding_box"]
    size = result["dimensions"]
    max_dim = max(size["x"], size["y"], size["z"]) or 1.0
    return {
        "size": size,
        "max_dim": max_dim,
        "center": [(box["min"][0] + box["max"][0]) / 2,
                   (box["min"][1] + box["max"][1]) / 2,
                   (box["min"][2] + box["max"][2]) / 2],
        "view_distance": round(max_dim * 3.1),
    }


_EXTENT_CACHE: dict[str, dict] = {}


def camera_defaults(model: Path, defines: dict[str, str], settings: dict) -> dict[str, str]:
    """``-D`` defaults that frame *model* regardless of its size.

    Templates ship with values tuned for large civil structures; a 1 m part
    would render as a speck (and trip the blank-frame check).  Callers inject
    these only when the storyboard does not override them.
    """
    key = str(model)
    if key not in _EXTENT_CACHE:
        _EXTENT_CACHE[key] = model_extent(model, defines, settings) or {}
    extent = _EXTENT_CACHE[key]
    if not extent:
        return {}
    return {"VPD": str(extent["view_distance"]),
            "VPT_Z": str(round(extent["center"][2]))}


def render_views(model: Path, out_dir: Path, angles: list[str], defines: dict[str, str],
                 settings: dict, timeout: int = 900, animate: int | None = None) -> dict:
    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD，请设置 OPENSCAD_EXECUTABLE")
    out_dir.mkdir(parents=True, exist_ok=True)
    size = settings["render_size"]
    written: list[str] = []
    if animate:
        # 逐帧动画使用模型里写好的 $vpt/$vpr/$vpd 固定机位，因此不做预设剥离，
        # 也不传 --autocenter/--viewall（否则每帧取景会随模型变化抖动）。
        target = out_dir / f"{model.stem}.png"
        argv = ["--animate", str(animate), "--imgsize", size, "--render",
                "--projection=p", "--colorscheme", "Tomorrow",
                "-D", f"SET_FN={settings['scad_fn']}",
                "-D", f"SET_COIL_SEG={settings['scad_coil_seg']}"]
        argv += [item for key, value in defines.items() for item in ("-D", f"{key}={value}")]
        argv += ["-o", str(target), str(model)]
        result = run_cli(openscad, argv, timeout)
        if result.returncode != 0:
            return {"ok": False, "error": "动画渲染失败",
                    "details": (result.stdout + result.stderr).strip()[-2000:]}
        rendered = sorted(out_dir.glob("*.png"))
        blank = [p.name for p in rendered[:: max(1, len(rendered) // 6)] if is_blank(p)]
        if not rendered:
            return {"ok": False, "error": "动画没有产生任何帧",
                    "details": (result.stdout + result.stderr).strip()[-1500:]}
        if blank:
            return {"ok": False, "error": f"有空白帧（{', '.join(blank[:3])}）——模型很可能没被加载",
                    "details": (result.stdout + result.stderr).strip()[-1500:]}
        return {"ok": True, "frames": len(rendered), "dir": str(out_dir)}

    source, temp = render_source(model)
    try:
        for label in angles:
            if label not in ANGLES:
                raise SystemExit(f"未知视角 {label!r}，可选：{', '.join(ANGLES)}")
            target = out_dir / f"{model.stem}__{label}.png"
            argv = [f"--camera={camera_arg(label)}", "--imgsize", size, "--autocenter",
                    "--viewall", "--render", "--projection=p", "--colorscheme", "Tomorrow",
                    "-D", f"SET_FN={settings['scad_fn']}",
                    "-D", f"SET_COIL_SEG={settings['scad_coil_seg']}"]
            argv += [item for key, value in defines.items() for item in ("-D", f"{key}={value}")]
            argv += ["-o", str(target), str(source)]
            result = run_cli(openscad, argv, timeout)
            if result.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
                return {"ok": False, "error": f"视角 {label} 渲染失败",
                        "details": (result.stdout + result.stderr).strip()[-1500:]}
            if is_blank(target):
                return {"ok": False, "error": f"视角 {label} 渲染结果为空白（模型未加载？）",
                        "details": (result.stdout + result.stderr).strip()[-1500:]}
            written.append(str(target))
    finally:
        if temp:
            temp.cleanup()
    return {"ok": True, "views": written, "count": len(written)}


def is_blank(png: Path, threshold: float = 0.004) -> bool:
    """True when a render contains almost no geometry.

    Catches the failure mode where OpenSCAD exits 0 but draws nothing (for
    example when an ``include`` silently fails), which would otherwise be
    stitched into the final video as white frames.
    """
    try:
        from PIL import Image

        with Image.open(png) as image:
            small = image.convert("L").resize((96, 96))
            pixels = small.load()
            total = 96 * 96
            dark = sum(1 for y in range(96) for x in range(96) if pixels[x, y] < 235)
        return dark / total < threshold
    except Exception:
        return False


def stl_metadata(path: Path) -> dict:
    """Facet count, bounding box and manifold check (shared STL parser)."""
    meta = parse_stl(path)
    box = meta.bounding_box
    dims = box.dimensions
    return {
        "facets": meta.facet_count,
        "vertices": meta.vertex_count,
        "is_manifold": meta.is_manifold,
        "file_bytes": meta.file_size_bytes,
        "volume_cm3": meta.volume_cm3,
        "surface_area_cm2": meta.surface_area_cm2,
        "bounding_box": {"min": [round(box.min_x, 2), round(box.min_y, 2), round(box.min_z, 2)],
                         "max": [round(box.max_x, 2), round(box.max_y, 2), round(box.max_z, 2)]},
        "dimensions": {"x": round(dims[0], 2), "y": round(dims[1], 2), "z": round(dims[2], 2)},
    }


def run_via_mcp(root: Path, model: Path, out_dir: Path, angles: list[str],
                defines: dict[str, str], animate: int | None) -> dict:
    """Optional path: drive the configured OpenSCAD MCP server over stdio."""
    import asyncio
    import os

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = os.environ.get("OPENSCAD_MCP_COMMAND")
    if not server:
        return {"ok": False, "error": "未配置 OPENSCAD_MCP_COMMAND，无法使用 --mode mcp"}
    env = dict(os.environ)
    env.setdefault("OPENSCAD_WORKSPACE", str(root))
    params = StdioServerParameters(command=server,
                                   args=os.environ.get("OPENSCAD_MCP_ARGS", "").split() or ["-m", "openscad_mcp_server"],
                                   env=env)

    async def call() -> dict:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("init", {})
                if animate:
                    return {"ok": True, "note": "MCP 模式不支持逐帧动画，请使用 CLI 模式"}
                await session.call_tool("build-stl", {"scad_file": model.name})
                result = await session.call_tool("render-images",
                                                 {"stl_file": model.name, "angles": angles})
                return {"ok": True, "blocks": len(result.content)}

    return asyncio.run(call())


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenSCAD 构建与渲染")
    parser.add_argument("--model", required=True, help=".scad 模型（可为相对项目路径）")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--angles", default="front-right-top-iso",
                        help="逗号分隔；可选 " + ",".join(ANGLES))
    parser.add_argument("--define", action="append", default=[], help="K=V，可重复")
    parser.add_argument("--animate", type=int, default=None, help="渲染 N 帧动画（用 $t）")
    parser.add_argument("--build-stl", action="store_true")
    parser.add_argument("--mode", choices=["cli", "mcp"], default="cli")
    parser.add_argument("--only-frames", action="store_true",
                        help="只渲染帧，不校验 STL（动画段落用）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project).resolve() if args.project else Path.cwd()
    settings = load_settings(root)
    model = Path(args.model)
    if not model.is_absolute():
        model = (root / args.model) if (root / args.model).exists() else (project_paths(root)["model"] / args.model)
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")
    out_dir = Path(args.out_dir) if Path(args.out_dir).is_absolute() else root / args.out_dir
    defines = dict(item.split("=", 1) for item in args.define)

    if args.mode == "mcp":
        payload = run_via_mcp(root, model, out_dir, args.angles.split(","), defines, args.animate)
    elif args.animate:
        payload = render_views(model, out_dir, [], defines, settings, animate=args.animate)
    else:
        payload = {}
        if args.build_stl:
            payload["build"] = build_stl(model, out_dir / f"{model.stem}.stl", defines, settings)
            if not payload["build"].get("ok"):
                print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload["build"]["details"])
                return 1
        payload.update(render_views(model, out_dir, args.angles.split(","), defines, settings))

    payload["deps"] = {k: v for k, v in detect_deps()["engines"].items()}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload.get("build"):
            build = payload["build"]
            print(f"STL: {build.get('stl')}  面片 {build.get('facets')}  流形 {build.get('is_manifold')}")
        print(f"渲染: {payload.get('count', payload.get('frames', 0))} 个 → {out_dir}")
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
