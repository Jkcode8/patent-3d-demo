"""Parameter-proposal comparison for fast inventor iteration.

When an inventor asks for a design tweak ("把面板改成 XX", "撑杆加长一点"), the
old workflow was: change the model -> render -> send -> get feedback -> repeat.
That costs many round-trips.  This script batches *several* candidate parameter
sets and renders each in the two key states (bridge θ=0 and dam θ=90), then
stitches them into one side-by-side sheet so the inventor compares all options
at a glance and picks one — usually one round instead of N.

Proposals come from a JSON file (default ``<project>/proposals.json``):

    {
      "proposals": [
        {"name": "原方案",  "defines": {},                       "note": "基准"},
        {"name": "撑杆+15%", "defines": {"SET_STRUT_L": "11500"}, "note": "提高刚度"},
        {"name": "鱼腹加深", "defines": {"SET_CAMBER": "6000"},   "note": "跨中更高"}
      ],
      "view": "front-right-top-iso",     # optional, default iso
      "states": ["0", "90"]              # optional, theta values
    }

Output: ``figures/提案对比/提案对比.png`` + ``proposal_report.json``.

Usage:
    python proposal_compare.py <项目>                     # 读 proposals.json
    python proposal_compare.py <项目> --proposals x.json  # 指定提案文件
    python proposal_compare.py <项目> --inline '撑杆+15%=SET_STRUT_L=11500;鱼腹=SET_CAMBER=6000'
    python proposal_compare.py <项目> --states 0,90 --view front
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import (find_openscad, load_settings, project_paths, read_json, write_json)
from openscad_run import render_views

# 两状态标识（θ 值）→ 展示名
STATE_LABELS = {"0": "桥态 (θ=0)", "90": "坝态 (θ=90)"}
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _load_font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _parse_inline(spec: str) -> list[dict]:
    """``'撑杆=SET_STRUT_L=11500;鱼腹=SET_CAMBER=6000'`` → proposal list.

    Each item is ``name=K=V`` (one define per proposal); ``;`` separates
    proposals.  Useful for a quick one-off comparison without a JSON file.
    """
    proposals: list[dict] = []
    for item in spec.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, kv = item.split("=", 1)
        key, value = kv.split("=", 1)
        proposals.append({"name": name.strip(), "defines": {key.strip(): value.strip()}, "note": ""})
    return proposals


def _baseline_marker(proposal: dict) -> str:
    """A proposal is the baseline when its defines are empty."""
    return "基准" if not proposal.get("defines") else ""


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="参数提案对比：多组参数 × 两状态并排渲染，供发明人一次对比")
    parser.add_argument("project", nargs="?", default=None, help="项目目录（默认当前目录）")
    parser.add_argument("--proposals", default=None, help="提案 JSON 文件（默认 <项目>/proposals.json）")
    parser.add_argument("--inline", default=None,
                        help="快速对比，如 '撑杆=SET_STRUT_L=11500;鱼腹=SET_CAMBER=6000'")
    parser.add_argument("--view", default="front-right-top-iso",
                        help="渲染视角（默认 iso）")
    parser.add_argument("--states", default="0,90",
                        help="状态 θ 值，逗号分隔（默认 0,90 = 桥态+坝态）")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认 figures/提案对比）")
    parser.add_argument("--size", default=None, help="单图渲染尺寸 WxH（默认取 project 设置）")
    args = parser.parse_args()

    root = Path(args.project).resolve() if args.project else Path.cwd()
    paths = project_paths(root)
    settings = load_settings(root)
    model = paths["model"] / "device.scad"
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")

    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD（硬依赖），请设置 OPENSCAD_EXECUTABLE")

    # —— 装配提案 ——
    proposals: list[dict] = []
    if args.inline:
        proposals = _parse_inline(args.inline)
    else:
        prop_file = Path(args.proposals) if args.proposals else paths["root"] / "proposals.json"
        if not prop_file.is_absolute():
            prop_file = root / prop_file
        if not prop_file.exists():
            raise SystemExit(f"提案文件不存在：{prop_file}。请先写 proposals.json，"
                             f"或用 --inline '撑杆=SET_STRUT_L=11500' 快速对比")
        data = read_json(prop_file, {})
        proposals = data.get("proposals") if isinstance(data, dict) else None
        if not proposals:
            raise SystemExit(f"提案文件 {prop_file} 里没有 proposals 列表")
    if not proposals:
        raise SystemExit("没有可用提案")

    view = args.view
    states = [s.strip() for s in args.states.split(",") if s.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else paths["figures"] / "提案对比"
    if not out_dir.is_absolute():
        out_dir = root / out_dir

    # —— 逐提案 × 逐状态渲染 iso ——
    rendered: dict[str, dict[str, str]] = {}   # proposal -> state -> png
    errors: list[str] = []
    for pi, proposal in enumerate(proposals):
        name = str(proposal.get("name", f"方案{pi + 1}"))
        defines = dict(proposal.get("defines", {}) or {})
        rendered[name] = {}
        for state in states:
            theta_defines = {**defines, "SET_THETA": state}
            # 坝态常隐藏栏杆；桥态显示栏杆 —— 由模型自身 SET_THETA 逻辑处理，不额外干预
            per_dir = out_dir / f"_{pi}"
            result = render_views(model, per_dir, [view], theta_defines,
                                  settings, timeout=900)
            if not result.get("ok") or not result.get("views"):
                errors.append(f"[{name} @ {STATE_LABELS.get(state, state)}] "
                              f"{result.get('error', '渲染失败')}")
                continue
            rendered[name][state] = result["views"][0]
        # 清理单提案临时目录
        (out_dir / f"_{pi}").mkdir(parents=True, exist_ok=True)

    if errors:
        print("部分渲染失败：")
        for err in errors:
            print("  " + err)

    # —— 拼成并排对比大图 ——
    if not rendered:
        raise SystemExit("所有提案都渲染失败，无法生成对比图")
    # 取第一张成功图的尺寸作为网格单元
    sample = next(iter(rendered.values()))
    any_state = next(iter(sample.values()), None)
    if any_state is None:
        raise SystemExit("提案渲染均无成功图")
    with Image.open(any_state) as img:
        unit_w, unit_h = img.size
    n_states = len(states)
    n_props = len([p for p in proposals if rendered.get(str(p.get("name", "")))])
    # 实际行数：只算有渲染成功的提案
    ok_props = [p for p in proposals if rendered.get(str(p.get("name", f"方案{proposals.index(p) + 1}")))]
    n_rows = max(1, len(ok_props))
    header = 96
    gap = 18
    sheet_w = unit_w * n_states + gap * (n_states + 1)
    sheet_h = header + unit_h * n_rows + gap * (n_rows + 1)
    sheet = Image.new("RGB", (sheet_w, sheet_h), "#f4f6f9")
    draw = ImageDraw.Draw(sheet)
    font_title = _load_font(40)
    font_hdr = _load_font(34)
    font_note = _load_font(26)

    # 状态列标题
    for si, state in enumerate(states):
        x = gap + si * (unit_w + gap)
        draw.text((x + 8, 14), STATE_LABELS.get(state, f"θ={state}"),
                  fill="#12304F", font=font_hdr)
        draw.rectangle([x, 60, x + unit_w - 1, 60 + 4], fill="#c2c8d0")

    # 每行一个提案
    for ri, prop in enumerate(ok_props):
        name = str(prop.get("name", f"方案{proposals.index(prop) + 1}"))
        y = header + ri * (unit_h + gap)
        row_name = name + ("（基准）" if _baseline_marker(prop) else "")
        draw.text((gap + 2, y - 6), row_name, fill="#12304F", font=font_title)
        if prop.get("note"):
            note = prop["note"]
            draw.text((gap + 2, y - 2 + 44), note, fill="#5a6b7d", font=font_note)
        for si, state in enumerate(states):
            x = gap + si * (unit_w + gap)
            img_path = rendered[name].get(state)
            if not img_path:
                # 该状态失败 → 画占位块
                draw.rectangle([x, y, x + unit_w - 1, y + unit_h - 1],
                               outline="#d0d6dd", fill="#eceff3")
                draw.text((x + 12, y + unit_h // 2), "渲染失败",
                          fill="#b3261e", font=font_note)
                continue
            with Image.open(img_path) as img:
                sheet.paste(img, (x, y))
            draw.rectangle([x, y, x + unit_w - 1, y + unit_h - 1], outline="#c2c8d0")

    target = out_dir / "提案对比.png"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    report = {
        "view": view,
        "states": states,
        "proposals": [
            {"name": p.get("name"), "defines": p.get("defines"),
             "note": p.get("note"), "baseline": bool(not p.get("defines"))}
            for p in proposals
        ],
        "sheet": str(target),
        "per_render": {name: {st: (rendered[name].get(st) or "")
                              for st in states} for name in rendered},
        "errors": errors,
    }
    write_json(out_dir / "proposal_report.json", report)
    print(f"提案对比 → {target}")
    print(f"  提案 {len(ok_props)} 个 × 状态 {len(states)} 个"
          + (f"，{len(errors)} 个渲染失败" if errors else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
