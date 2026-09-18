"""Write 说明.md (assumptions + reproduction commands) and a delivery index.

Usage:
    python make_delivery.py <project> [--json]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from config import detect_deps, load_settings, project_paths, read_json, write_json


def describe_tree(root: Path, limit: int = 40) -> list[str]:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or len(lines) >= limit:
            continue
        rel = path.relative_to(root)
        if any(part in {"frames", "captioned", "audio", "film", "segments"} for part in rel.parts):
            continue
        size = path.stat().st_size
        unit = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.0f} KB"
        lines.append(f"| `{rel.as_posix()}` | {unit} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="生成交付说明")
    parser.add_argument("project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    storyboard = read_json(paths["storyboard"], {}) or {}
    timeline = read_json(paths["video"] / "timeline.json", {}) or {}
    report = read_json(paths["video"] / "film_report.json", {}) or {}
    deps = detect_deps()
    settings = load_settings(paths["root"])

    rows = ["# 交付说明", "",
            f"- 项目：`{paths['root']}`",
            f"- 标题：{storyboard.get('title', '（未设置）')}",
            f"- 分镜：{'已确认' if storyboard.get('confirmed') else '**未确认**'}"
            f"（{len(storyboard.get('segments', []))} 段）",
            f"- 配音：{storyboard.get('voice', settings['voice'])} / 渲染 {settings['render_size']} @ {settings['fps']} fps",
            f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}", "",
            "## 段落与时长", "", "| # | 段落 | 类型 | 用途 | 时长 | 帧数 |", "|---|---|---|---|---|---|"]
    for index, seg in enumerate(storyboard.get("segments", []), start=1):
        entry = timeline.get(seg["id"], {})
        rows.append(f"| {index} | {seg['id']} | {seg['type']} | {seg.get('purpose', '')} | "
                    f"{entry.get('total', seg.get('duration_hint', ''))}s | {entry.get('frames', '')} |")

    if report:
        checks = report.get("checks", {})
        rows += ["", "## 成片与自检", "",
                 f"- 成片：`{report.get('film')}`（{report.get('seconds')}s，配乐：{report.get('music')}）",
                 f"- 人声 {checks.get('voice_db')} dB / 纯配乐 {checks.get('music_db')} dB"
                 f"（差 {checks.get('voice_above_music_db')} dB，要求 ≥ {settings['voice_above_music_db']}）",
                 f"- 整片响度 {checks.get('integrated_lufs')} LUFS（目标 {settings['loudnorm_i']}±1）"]

    rows += ["", "## 运行环境（本次）", "",
             f"- OpenSCAD：`{deps['openscad']}`",
             f"- ffmpeg：`{deps['ffmpeg']}`",
             f"- 语音引擎：{deps['engines']['voice']}；DWG 来源：{deps['engines']['dwg']}"]
    if deps["warnings"]:
        rows += ["- 降级项："] + [f"  - {item}" for item in deps["warnings"]]

    rows += ["", "## 产物清单", "", "| 文件 | 大小 |", "|---|---|"] + describe_tree(paths["root"])
    rows += ["", "## 复现命令", "", "```bash",
             f"python config.py init-project {paths['root']}",
             f"python extract_doc.py <交底书.doc> {paths['extract']}",
             f"python render_sketch.py {paths['extract']}",
             f"python storyboard.py draft {paths['root']}   # 改好旁白后 confirm",
             f"python narration.py tts {paths['root']} --voice {storyboard.get('voice', 'female')}",
             f"python storyboard.py render {paths['root']}",
             f"python make_figures.py {paths['root']}",
             f"python narration.py compose {paths['root']}",
             f"python final_film.py {paths['root']}",
             "```", ""]

    paths["notes"].write_text("\n".join(rows), encoding="utf-8")
    index = {"notes": str(paths["notes"]), "segments": len(storyboard.get("segments", [])),
             "confirmed": bool(storyboard.get("confirmed")), "film": report.get("film")}
    write_json(paths["root"] / "delivery.json", index)
    if args.json:
        print(json.dumps(index, ensure_ascii=False, indent=2))
    else:
        print(f"交付说明：{paths['notes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
