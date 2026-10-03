"""Smoke-test every segment template against a model (syntax + 2-frame render).

Catches template breakage that the example storyboard alone would miss, because
the example only exercises the segment types it declares.

Usage:
    python check_templates.py <project> [--frames 2] [--render ID] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from config import SEGMENTS, load_settings, project_paths
from openscad_run import camera_defaults, find_openscad, inline_model, render_views, run_cli
from storyboard import instantiate_source


def instantiate(template: Path, model: Path, target: Path, defines: dict) -> str:
    """Inline the model into a throwaway segment file (same rule as storyboard).

    Delegates to ``storyboard.instantiate_source`` rather than re-implementing
    the inlining: that function also drops the template's own
    ``X = is_undef(X) ? default : X;`` guard lines for the parameters the caller
    supplies, which is what lets the computed camera defaults reach ``device()``.
    Spelling the rule out a second time here (the v1.4.0 behaviour) lost the
    stripping, so ``seg_adjust`` kept its large-structure ``VPD = 165000`` and
    framed a 1 m bracket as a speck — caught by the blank-frame check.
    """
    body = re.sub(r"^\s*include\s*<@MODEL@>;\s*$", "",
                  template.read_text(encoding="utf-8"), flags=re.MULTILINE)
    text = instantiate_source(template.name, model.name, inline_model(model), body, defines)
    target.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    from config import enable_utf8_stdout
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="段落模板烟测")
    parser.add_argument("project")
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--render", default=None, help="额外真渲染该段落 id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    model = paths["model"] / "device.scad"
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")
    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD")
    work = paths["video"] / "template-smoke"
    work.mkdir(parents=True, exist_ok=True)

    results = []
    for template in sorted(SEGMENTS.glob("seg_*.scad")):
        generated = work / f"{template.stem}.scad"
        text = instantiate(template, model, generated, {})
        if "@MODEL_B@" in text:
            entry = {"template": template.name, "ok": True,
                     "note": "需要对照模型，跳过语法烟测"}
            results.append(entry)
            if not args.json:
                print(f"{template.name:26s} OK   {entry['note']}")
            continue
        checked = run_cli(openscad, ["--export-format", "echo", "-o", "-", str(generated)], 300)
        error = (checked.stdout + checked.stderr).strip()
        ok = checked.returncode == 0
        entry = {"template": template.name, "ok": ok}
        if not ok:
            entry["error"] = error[-400:]
        if args.render and template.stem == f"seg_{args.render}":
            # 相机默认值走与 storyboard 相同的通道：先按模型尺寸算 VPD/VPT_Z，
            # 再带着它们重新实例化（顺带剥离模板里硬编码的 $vpd 保护行），
            # 否则模板默认值会把自适应机位顶掉，小模型渲染成一点。
            defines = camera_defaults(generated, {}, settings)
            if defines:
                instantiate(template, model, generated, defines)
            rendered = render_views(generated, work / args.render, [], defines, settings,
                                    animate=args.frames)
            entry["render"] = {"ok": rendered.get("ok"), "frames": rendered.get("frames"),
                               "error": rendered.get("error")}
            ok = ok and bool(rendered.get("ok"))
            entry["ok"] = ok
        results.append(entry)
        if not args.json:
            print(f"{template.name:26s} {'OK' if entry['ok'] else 'FAIL'} "
                  f"{entry.get('note') or entry.get('error', '')[:60]}")

    payload = {"templates": results, "ok": all(r["ok"] for r in results)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
