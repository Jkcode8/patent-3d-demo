"""Storyboard: draft, validate, confirm and render the video segments.

The video structure is *not* fixed: it is derived per patent from the disclosure
and drawings, written to ``storyboard.json`` + ``分镜.md``, and must be confirmed
before any rendering happens (rendering is the expensive step).

Usage:
    python storyboard.py draft   <project>            # 生成分镜草案
    python storyboard.py check   <project> [--json]   # 校验并列出将渲染的段落
    python storyboard.py confirm <project>            # 确认分镜（开启渲染门禁）
    python storyboard.py render  <project> [--only id] [--figures] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from config import (
    SEGMENTS,
    VERSION,
    load_settings,
    project_paths,
    read_json,
    write_json,
)

# 交底书/图纸关键词 → 段落类型（草案依据，不是硬约束）
RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"组成|构成|包括|模块|部件|结构形式|系统组成"), "explode", "组成与分解"),
    (re.compile(r"原理|工作过程|受力|变形|工况|运动|耗能|加载"), "load_case", "工作原理/工况"),
    (re.compile(r"施工|安装|装配|施工方法|步骤|工序"), "assembly", "施工/装配顺序"),
    (re.compile(r"调节|自适应|可调|水位|角度|张紧|间隙|升降|滑动"), "adjust", "调节与自适应"),
    (re.compile(r"不同尺寸|参数|系列|多种规格|规格"), "param_sweep", "参数变化对比"),
    (re.compile(r"对比|现有技术|传统|改进|优势|有益效果"), "comparison", "与现有技术对比"),
    (re.compile(r"剖面|截面|剖切|剖视"), "section", "剖切展示"),
    (re.compile(r"整体|外观|立体|三维|结构"), "turntable", "整体展示"),
]
SECTION_RE = re.compile(r"^\s*(?:[一二三四五六七八九十]+[、.]|\d+(?:\.\d+)*[、.\s])", re.MULTILINE)
TEMPLATES = {
    "turntable": "seg_turntable.scad",
    "explode": "seg_explode.scad",
    "assembly": "seg_assembly.scad",
    "load_case": "seg_load_case.scad",
    "section": "seg_section.scad",
    "adjust": "seg_adjust.scad",
    "param_sweep": "seg_param_sweep.scad",
    "comparison": "seg_comparison.scad",
}
CACHE_FILE = "_cache.json"


def instantiate_source(template_name: str, model_name: str, model_source: str,
                       template_text: str, defines: dict) -> str:
    """Assemble one runnable segment file.

    The parameter assignments go *before* the model source on purpose.  OpenSCAD
    applies ``-D`` values after a file's top-level assignments, so a model that
    derives a parameter from one — the usual
    ``BASE_L = is_undef(SET_BASE_L) ? 400 : SET_BASE_L;`` idiom — never sees it
    and silently keeps the fallback.  Written into the file, the fallback
    expression and everything derived from it pick the value up.
    """
    preamble = "\n".join(f"{key} = {value};" for key, value in sorted(defines.items()))
    return (f"// 由 {template_name} 实例化：模型 {model_name} 已内联\n"
            f"{preamble}\n{model_source}\n/* ===== 段落驱动 ===== */\n{template_text}")


def frame_fingerprint(source: Path, defines: dict, settings: dict) -> str:
    """Hash everything that changes the rendered frames.

    The instantiated segment file already contains the inlined model, so hashing
    it covers model edits; defines, render size and tessellation settings cover
    the rest.  Counting frames alone (the previous behaviour) silently reused
    stale frames whenever a change did not alter the frame count.
    """
    digest = hashlib.sha1()
    digest.update(source.read_bytes())
    digest.update(json.dumps(defines, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    digest.update(f"{settings['render_size']}|{settings['scad_fn']}|"
                  f"{settings['scad_coil_seg']}".encode("utf-8"))
    return digest.hexdigest()[:16]
DEFAULT_NARRATION = {
    "turntable": ["这是本专利的{title}。", "装置由{parts}组成，整体结构如图所示。"],
    "explode": ["将各组成部分分解展示。", "{parts}依次装配，形成完整装置。"],
    "assembly": ["施工时按以下顺序安装。", "各部件就位后完成调试验收。"],
    "load_case": ["工作时，载荷按图示传递。", "各构件协同变形，实现预期功能。"],
    "section": ["剖面展示了内部构造。", "内部各构件的相对位置关系如图。"],
    "adjust": ["装置可随工况自适应调节。", "调节范围覆盖设计要求。"],
    "param_sweep": ["通过改变参数可获得不同规格。", "系列化参数便于适配不同场景。"],
    "comparison": ["与传统方案相比，本方案在结构与效果上均有改进。", "对比可见其优势。"],
}


def disclosure_text(paths: dict[str, Path]) -> str:
    for name in ("disclosure.txt", "交底书.txt"):
        candidate = paths["extract"] / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
    for candidate in paths["sources"].glob("*.txt"):
        return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def split_sections(text: str) -> list[str]:
    if not text.strip():
        return []
    marks = [m.start() for m in SECTION_RE.finditer(text)]
    if not marks:
        return [text]
    marks.append(len(text))
    return [text[marks[i]:marks[i + 1]].strip() for i in range(len(marks) - 1)]


def propose_segments(text: str, title: str) -> list[dict]:
    """Score the selection rules against the disclosure and build a draft."""
    sections = split_sections(text)
    segments: list[dict] = []
    used: set[str] = set()
    for pattern, kind, purpose in [(RULES[-1][0], "turntable", "整体展示")] + [
        (p, k, u) for p, k, u in RULES[:-1]
    ]:
        hits = [s for s in sections if pattern.search(s)]
        if not hits or kind in used:
            continue
        used.add(kind)
        excerpt = re.sub(r"\s+", " ", hits[0])[:160]
        template = DEFAULT_NARRATION[kind]
        segments.append({
            "id": kind,
            "type": kind,
            "enabled": True,
            "purpose": purpose,
            "template": TEMPLATES[kind],
            "model": "model/device.scad",
            "defines": {},
            "camera": {},
            "narration": [line.format(title=title, parts="各组成部分") for line in template],
            "source_excerpt": excerpt,
            "duration_hint": 16,
        })
    if not segments:
        segments.append({
            "id": "turntable", "type": "turntable", "enabled": True,
            "purpose": "整体展示", "template": TEMPLATES["turntable"],
            "model": "model/device.scad", "defines": {}, "camera": {},
            "narration": [line.format(title=title, parts="各组成部分")
                          for line in DEFAULT_NARRATION["turntable"]],
            "source_excerpt": "", "duration_hint": 16,
        })
    return segments


def cmd_draft(args) -> int:
    paths = project_paths(args.project)
    text = disclosure_text(paths)
    title = args.title or "本专利装置"
    if not text and (paths["extract"] / "cad_text.txt").exists():
        text = (paths["extract"] / "cad_text.txt").read_text(encoding="utf-8", errors="replace")
    segments = propose_segments(text, title)
    storyboard = {
        "skill": "patent-3d-demo",
        "version": VERSION,
        "project": str(paths["root"]),
        "title": title,
        "subtitle": "三维演示动画",
        "keywords": "参数化结构 · 工作原理 · 施工方法",
        "confirmed": False,
        "created": datetime.now().isoformat(timespec="seconds"),
        "voice": load_settings(paths["root"])["voice"],
        "intro": {"lines": [f"{title}，三维演示。"]},
        "outro": {"lines": [f"以上是{title}的三维演示，感谢观看。"]},
        "figures": {
            "color_views": ["front-right-top-iso", "front", "top"],
            "blackwhite": {"mono_views": ["front-right-top-iso", "front"],
                           "lineart_views": ["front", "top", "side"]},
        },
        "segments": segments,
    }
    write_json(paths["storyboard"], storyboard)
    write_storyboard_md(paths["storyboard_md"], storyboard, paths["extract"])
    print(f"分镜草案：{paths['storyboard']}\n人读版：{paths['storyboard_md']}\n"
          f"段落数 {len(segments)}（{', '.join(s['id'] for s in segments)}）")
    print("下一步：请确认/修改旁白与段落，然后 `storyboard.py confirm <project>` 再渲染。")
    return 0


def write_storyboard_md(target: Path, storyboard: dict, extract_dir: Path) -> None:
    lines = [f"# {storyboard['title']} —— 分镜草案", "",
             f"- 项目：{storyboard['project']}",
             f"- 状态：{'已确认' if storyboard.get('confirmed') else '**未确认（不可渲染）**'}",
             f"- 配音：{storyboard.get('voice')}", "",
             "| # | 段落 id | 类型 | 目的 | 模板 | 建议时长 | 旁白（草稿） |",
             "|---|---|---|---|---|---|---|"]
    for index, seg in enumerate(storyboard["segments"], start=1):
        narration = " ".join(seg.get("narration", []))
        lines.append(f"| {index} | {seg['id']} | {seg['type']} | {seg['purpose']} | "
                     f"{seg['template']} | {seg.get('duration_hint', 16)}s | {narration} |")
    lines += ["", "## 选段依据", ""]
    for seg in storyboard["segments"]:
        excerpt = seg.get("source_excerpt", "")
        if excerpt:
            lines.append(f"- **{seg['id']}**（{seg['purpose']}）：对应交底书内容「{excerpt}…」")
    lines += ["", "## 素材", "",
              f"- 提取结果：`{extract_dir.name}/`（正文、插图、图元 CSV、视图 PNG）",
              "- 模型：`model/device.scad`（参数化源码）",
              "- 附图：彩色渲染 + 单色立体图 + 正投影线稿（SVG/DXF/PNG）", ""]
    target.write_text("\n".join(lines), encoding="utf-8")


def validate(paths: dict[str, Path], storyboard: dict) -> list[str]:
    problems: list[str] = []
    if not storyboard:
        return [f"未找到 {paths['storyboard']}，请先运行 storyboard.py draft"]
    for index, seg in enumerate(storyboard.get("segments", []), start=1):
        seg_id = seg.get("id", f"#{index}")
        kind = seg.get("type", "")
        if kind not in TEMPLATES and kind != "custom":
            problems.append(f"段落 {seg_id}：未知类型 {kind!r}")
        template = SEGMENTS / (seg.get("template") or TEMPLATES.get(kind, ""))
        if kind != "custom" and not template.exists():
            problems.append(f"段落 {seg_id}：模板不存在 {template.name}")
        if not seg.get("narration"):
            problems.append(f"段落 {seg_id}：缺少旁白")
        model = Path(seg.get("model", ""))
        if seg.get("enabled", True) and model.suffix and not (paths["root"] / model).exists() \
                and not (paths["model"] / model.name).exists():
            problems.append(f"段落 {seg_id}：模型不存在 {model}")
    if not storyboard.get("segments"):
        problems.append("分镜里没有任何段落")
    return problems


def cmd_check(args) -> int:
    paths = project_paths(args.project)
    storyboard = read_json(paths["storyboard"])
    problems = validate(paths, storyboard or {})
    enabled = [s for s in (storyboard or {}).get("segments", []) if s.get("enabled", True)]
    payload = {
        "storyboard": str(paths["storyboard"]),
        "confirmed": bool((storyboard or {}).get("confirmed")),
        "segments_total": len((storyboard or {}).get("segments", [])),
        "segments_enabled": [s["id"] for s in enabled],
        "problems": problems,
        "render_allowed": bool((storyboard or {}).get("confirmed")) and not problems,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"分镜：{payload['storyboard']}")
        print(f"已确认：{'是' if payload['confirmed'] else '否'}"
              f"　段落：{payload['segments_total']}（启用 {len(enabled)}）")
        print("将渲染：" + (", ".join(payload["segments_enabled"]) or "（无）"))
        if problems:
            print("问题：")
            for item in problems:
                print(f"  - {item}")
        if not payload["confirmed"]:
            print("门禁：分镜未确认，渲染被拒绝。确认命令：storyboard.py confirm <project>")
    return 0 if not problems else 1


def cmd_confirm(args) -> int:
    paths = project_paths(args.project)
    storyboard = read_json(paths["storyboard"])
    if not storyboard:
        raise SystemExit("未找到 storyboard.json，请先 draft")
    problems = validate(paths, storyboard)
    if problems and not args.force:
        for item in problems:
            print(f"  - {item}")
        raise SystemExit("存在上述问题，未确认（可用 --force 强制确认）")
    storyboard["confirmed"] = True
    storyboard["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(paths["storyboard"], storyboard)
    write_storyboard_md(paths["storyboard_md"], storyboard, paths["extract"])
    print(f"已确认分镜：{len(storyboard['segments'])} 段，可以进入渲染。")
    return 0


def cmd_render(args) -> int:
    paths = project_paths(args.project)
    storyboard = read_json(paths["storyboard"])
    if not storyboard:
        raise SystemExit("未找到 storyboard.json")
    if not storyboard.get("confirmed") and not args.allow_unconfirmed:
        raise SystemExit("分镜未确认，渲染被拒绝。先 `storyboard.py confirm <project>`"
                         "（或加 --allow-unconfirmed 仅做冒烟测试）")
    problems = validate(paths, storyboard)
    if problems:
        for item in problems:
            print(f"  - {item}")
        raise SystemExit("分镜校验未通过")

    timeline = read_json(paths["root"] / "video" / "timeline.json", {}) or {}
    import openscad_run  # 延迟导入，避免无 OpenSCAD 时 check 也失败

    settings = load_settings(paths["root"])
    seg_dir = paths["video"] / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for seg in storyboard["segments"]:
        if not seg.get("enabled", True):
            continue
        if args.only and seg["id"] not in args.only.split(","):
            continue
        frames_dir = paths["video"] / "frames" / seg["id"]
        count = (seg.get("timeline") or timeline.get(seg["id"]) or {}).get("frames")
        defines = {k: str(v) for k, v in (seg.get("defines") or {}).items()}
        model = paths["model"] / Path(seg.get("model", "model/device.scad")).name
        if not model.exists():
            model = (paths["root"] / seg.get("model", "")).resolve()

        # 实例化：把模型源码内联进来（不用 include —— OpenSCAD 打不开含非 ASCII 路径的 include，
        # 但同一文件作为主文件却能正常解析；内联对任意路径都稳）。模型末尾的默认 device(); 去掉，
        # 由段落模板决定姿态。
        template = SEGMENTS / seg["template"]
        generated = seg_dir / f"{seg['id']}.scad"
        if not template.exists():
            results.append({"id": seg["id"], "status": "failed",
                            "error": f"模板缺失 {template.name}"})
            continue
        model_source = openscad_run.inline_model(model)
        template_text = template.read_text(encoding="utf-8")
        template_text = re.sub(r"^\s*include\s*<@MODEL@>;\s*$", "", template_text,
                               flags=re.MULTILINE)
        if "@MODEL_B@" in template_text:
            other = seg.get("model_b")
            if not other:
                results.append({"id": seg["id"], "status": "failed",
                                "error": "comparison 段需要在分镜里给出 model_b（对照模型路径）"})
                continue
            template_text = template_text.replace(
                "@MODEL_B@", (paths["root"] / other).resolve().as_posix())
        generated.write_text(instantiate_source(template.name, model.name, model_source,
                                                template_text, defines), encoding="utf-8")

        # 机位随模型尺寸自适应：模板默认值是按大型构件给的，小模型会缩成一点
        if "VPD" not in defines and model.exists():
            cameras = {name: value
                       for name, value in openscad_run.camera_defaults(generated, defines,
                                                                       settings).items()
                       if name not in defines}
            if cameras:
                defines.update(cameras)
                # 相机默认值也是参数：重写一次，让它们走同一套"前置赋值"通道
                generated.write_text(
                    instantiate_source(template.name, model.name, model_source,
                                       template_text, defines), encoding="utf-8")

        if count:
            fingerprint = frame_fingerprint(generated, defines, settings)
            manifest = read_json(frames_dir / CACHE_FILE, {}) or {}
            cached = len(list(frames_dir.glob("*.png"))) if frames_dir.exists() else 0
            if (manifest.get("fingerprint") == fingerprint
                    and manifest.get("frames") == count
                    and cached >= count and not args.force):
                results.append({"id": seg["id"], "frames": cached, "status": "cached"})
                continue
            payload = openscad_run.render_views(generated, frames_dir, [], defines, settings,
                                                animate=count)
            if payload.get("ok"):
                write_json(frames_dir / CACHE_FILE,
                           {"fingerprint": fingerprint, "frames": count,
                            "rendered_at": datetime.now().isoformat(timespec="seconds")})
        else:
            payload = {"ok": False, "error": "缺少时间轴（先运行 narration.py tts）"}
        results.append({"id": seg["id"], "status": "rendered" if payload.get("ok") else "failed",
                        "frames": payload.get("frames"), "error": payload.get("error")})

    payload = {"segments": results,
               "ok": all(r["status"] in ("rendered", "cached") for r in results)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"{item['id']:14s} {item['status']:9s} 帧 {item.get('frames')} "
                  f"{item.get('error') or ''}")
    return 0 if payload["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="分镜（storyboard）管理")
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft")
    draft.add_argument("project")
    draft.add_argument("--title", default=None)

    check = sub.add_parser("check")
    check.add_argument("project")
    check.add_argument("--json", action="store_true")

    confirm = sub.add_parser("confirm")
    confirm.add_argument("project")
    confirm.add_argument("--force", action="store_true")

    render = sub.add_parser("render")
    render.add_argument("project")
    render.add_argument("--only", default=None, help="逗号分隔的段落 id")
    render.add_argument("--force", action="store_true")
    render.add_argument("--allow-unconfirmed", action="store_true")
    render.add_argument("--json", action="store_true")

    args = parser.parse_args()
    return {"draft": cmd_draft, "check": cmd_check, "confirm": cmd_confirm,
            "render": cmd_render}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
