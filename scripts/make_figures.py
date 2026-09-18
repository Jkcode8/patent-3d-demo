"""Produce the figure set from the storyboard's ``figures`` block.

    figures/彩色附图/     color contact sheet + individual views
    figures/黑白附图/     monochrome render + orthographic line art (SVG/DXF/PNG)
    figures/参数表.md     parameters scraped from the model's parameter block

Usage:
    python make_figures.py <project> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import ASSETS, load_settings, project_paths, read_json
from lineart import main as lineart_main  # noqa: F401  (documented CLI entry)
from openscad_run import render_views

FONT_BOLD = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
             "/System/Library/Fonts/PingFang.ttc"]
PARAM_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([^;]+);\s*(?://\s*(.*))?$", re.MULTILINE)


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_BOLD:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def contact_sheet(images: list[Path], target: Path, title: str,
                  columns: int = 3, cell: int = 640) -> bool:
    existing = [p for p in images if p.exists()]
    if not existing:
        return False
    rows = (len(existing) + columns - 1) // columns
    header, bar = 90, 46
    sheet = Image.new("RGB", (columns * cell, header + rows * (cell + bar)), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((sheet.width / 2, 26), title, font=font(40), fill="#12304F", anchor="ma")
    for index, path in enumerate(existing):
        row, column = divmod(index, columns)
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell - 20, cell - 20))
        x = column * cell + (cell - image.width) // 2
        y = header + row * (cell + bar) + (cell - image.height) // 2
        sheet.paste(image, (x, y))
        draw.text((column * cell + cell / 2, header + row * (cell + bar) + cell + 10),
                  path.stem.split("__")[-1], font=font(28), fill="#3A6EA5", anchor="ma")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    return True


def parameter_table(model: Path) -> str:
    """Scrape ``P_x = value;  // 来源：…`` lines into a Markdown table."""
    if not model.exists():
        return "# 参数表\n\n（未找到模型文件）\n"
    lines = ["# 主要参数", "", "| 参数 | 取值 | 来源/说明 |", "|---|---|---|"]
    for match in PARAM_RE.finditer(model.read_text(encoding="utf-8", errors="replace")):
        name, value, note = match.group(1), match.group(2).strip(), (match.group(3) or "").strip()
        if not note:
            continue
        lines.append(f"| `{name}` | {value} | {note} |")
    if len(lines) == 4:
        lines.append("| — | — | 模型里未标注来源，请在参数区补 `// 来源：…` 注释 |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成附图（彩色 + 黑白 + 参数表）")
    parser.add_argument("project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    storyboard = read_json(paths["storyboard"], {}) or {}
    figures = storyboard.get("figures", {})
    model = paths["model"] / "device.scad"
    if not model.exists():
        raise SystemExit(f"未找到模型：{model}")

    color_views = figures.get("color_views", ["front-right-top-iso", "front", "top"])
    color_dir = paths["figures"] / "彩色附图"
    color_dir.mkdir(parents=True, exist_ok=True)
    result = render_views(model, color_dir, color_views, {}, settings)
    if not result.get("ok"):
        raise SystemExit(f"彩色渲染失败：{result.get('error')} {result.get('details', '')[:400]}")
    contact_sheet(sorted(color_dir.glob("*__*.png")), color_dir / "附图_彩色.png",
                  f"{storyboard.get('title', '')}　彩色立体图")

    blackwhite = figures.get("blackwhite", {})
    mono_dir = paths["figures"] / "黑白附图"
    mono_views = blackwhite.get("mono_views", ["front-right-top-iso"])
    render_views(model, mono_dir, mono_views, {"SET_MONO": "true"}, settings)
    contact_sheet(sorted(mono_dir.glob("*__*.png")), mono_dir / "附图_单色.png",
                  f"{storyboard.get('title', '')}　单色立体图")

    lineart_views = blackwhite.get("lineart_views", [])
    if lineart_views:
        import subprocess
        import sys
        subprocess.run([sys.executable, str(Path(__file__).with_name("lineart.py")),
                        "--model", str(model), "--out-dir", str(mono_dir),
                        "--views", ",".join(lineart_views), "--formats", "svg,dxf,png"],
                       check=False)

    (paths["figures"] / "参数表.md").write_text(parameter_table(model), encoding="utf-8")
    payload = {"color_dir": str(color_dir), "blackwhite_dir": str(mono_dir),
               "color_views": color_views, "mono_views": mono_views,
               "lineart_views": lineart_views, "ok": True}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"彩色附图 {len(color_views)} 张 → {color_dir}")
        print(f"黑白附图 {len(mono_views)} 张 + 线稿 {len(lineart_views)} 组 → {mono_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
