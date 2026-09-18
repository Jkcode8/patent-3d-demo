"""Narration: TTS timeline, subtitles and per-segment video encoding.

Commands:
    tts     <project> [--voice female|male] [--engine edge|sapi]
            → per-cue audio in video/audio/, timeline in video/timeline.json
    render  <project> [--only id]      → delegate frame rendering to storyboard.py
    compose <project>                  → burn subtitles, encode 仅画面版 MP4 + GIF

The narration drives the timing: every cue is synthesised first, its real
duration becomes the slot, and the frame count follows from the total.  That
ordering makes overlapping speech impossible by construction; ``voice_fit.py``
is only needed when swapping the voice of an already-rendered film.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import (
    detect_deps,
    find_ffmpeg,
    load_settings,
    project_paths,
    read_json,
    write_json,
)

FONT_BOLD = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
             "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
FONT_REG = [r"C:\Windows\Fonts\msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
GAP_SECONDS = 0.35
TAIL_SECONDS = 0.9

# TTS 直接读原文会念歪："φ1500" "1.5m" "16+16+17度" "−2.26m" 等。
# 字幕仍用原文，只有送去合成的那份做规范化。
ZH_RULES: list[tuple[str, str]] = [
    (r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*度", r"\1度、\2度、\3度"),
    (r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)", r"\1度、\2度、\3度"),
    (r"φ\s*(\d+(?:\.\d+)?)", r"直径\1"),
    (r"Φ\s*(\d+(?:\.\d+)?)", r"直径\1"),
    (r"\bR\s*(\d+(?:\.\d+)?)", r"半径\1"),
    (r"(\d+(?:\.\d+)?)\s*m³/s", r"\1立方米每秒"),
    (r"(\d+(?:\.\d+)?)\s*m3/s", r"\1立方米每秒"),
    (r"(\d+(?:\.\d+)?)\s*mm\b", r"\1毫米"),
    (r"(\d+(?:\.\d+)?)\s*cm\b", r"\1厘米"),
    (r"(\d+(?:\.\d+)?)\s*m\b", r"\1米"),
    (r"(\d+(?:\.\d+)?)\s*kN\b", r"\1千牛"),
    (r"(\d+(?:\.\d+)?)\s*kPa\b", r"\1千帕"),
    (r"(\d+(?:\.\d+)?)\s*MPa\b", r"\1兆帕"),
    (r"(\d+(?:\.\d+)?)\s*°C", r"\1摄氏度"),
    (r"(\d+(?:\.\d+)?)\s*%", r"百分之\1"),
    (r"(\d+(?:\.\d+)?)\s*°", r"\1度"),
    (r"(?<=[\d出])[×xX](?=\d)", r"乘"),
    (r"[−–—]", r"负"),
    (r"[~～]", r"到"),
    (r"[·•]", r"、"),
]
EN_RULES: list[tuple[str, str]] = [
    (r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*degrees?", r"\1, \2 and \3 degrees"),
    (r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)", r"\1, \2 and \3 degrees"),
    (r"[φΦ]\s*(\d+(?:\.\d+)?)", r"diameter \1"),
    (r"\bR\s*(\d+(?:\.\d+)?)", r"radius \1"),
    (r"(\d+(?:\.\d+)?)\s*m³/s", r"\1 cubic metres per second"),
    (r"(\d+(?:\.\d+)?)\s*m3/s", r"\1 cubic metres per second"),
    (r"(\d+(?:\.\d+)?)\s*mm\b", r"\1 millimetres"),
    (r"(\d+(?:\.\d+)?)\s*m\b", r"\1 metres"),
    (r"(\d+(?:\.\d+)?)\s*kN\b", r"\1 kilonewtons"),
    (r"(\d+(?:\.\d+)?)\s*kPa\b", r"\1 kilopascals"),
    (r"(\d+(?:\.\d+)?)\s*MPa\b", r"\1 megapascals"),
    (r"(\d+(?:\.\d+)?)\s*%", r"\1 percent"),
    (r"(\d+(?:\.\d+)?)\s*°", r"\1 degrees"),
    (r"(?<=[\d])[×xX](?=\d)", r" by "),
    (r"[−–—]", r"minus "),
    (r"[~～]", r" to "),
]


def normalize_narration(text: str, language: str = "zh") -> str:
    """Rewrite units and symbols so the synthesised speech reads naturally."""
    rules = EN_RULES if language.lower().startswith("en") else ZH_RULES
    result = text
    for pattern, replacement in rules:
        result = re.sub(pattern, replacement, result)
    result = re.sub(r"\s{2,}", " ", result)
    result = re.sub(r"\s+([，。、；：,.!?])", r"\1", result)   # 标点前的空格
    return result.strip()


def voice_for(settings: dict, gender: str, language: str) -> str:
    """Pick the edge-tts voice for the requested gender and language."""
    table = settings["edge_voice"]
    if language.lower().startswith("en"):
        return table.get(f"en-{gender}", table.get("en-female", "en-US-AriaNeural"))
    return table.get(gender, table["female"])


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def media_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path)) as handle:
            return handle.getnframes() / float(handle.getframerate())
    ffprobe = find_ffmpeg("ffprobe")
    if not ffprobe:
        raise SystemExit("需要 ffprobe 读取音频时长；请安装 ffmpeg 或改用 --engine sapi")
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, encoding="utf-8", errors="replace", check=True)
    return float(out.stdout.strip())


def pick_sapi_voice(settings: dict, gender: str, available: list[str]) -> str | None:
    for wanted in settings["sapi_voice"].get(gender, []):
        for name in available:
            if wanted.split()[-1].lower() in name.lower():
                return name
    return available[0] if available else None


def cue_slots(durations: list[float]) -> dict:
    """Lay the cues out on the timeline: one after another, never overlapping.

    Each cue starts ``GAP_SECONDS`` after the previous one ended, and the whole
    segment keeps ``TAIL_SECONDS`` of silence so the last caption stays readable.
    Kept separate from the TTS loop so the arithmetic is unit-testable without
    any audio engine.
    """
    starts: list[float] = []
    cursor = 0.0
    for duration in durations:
        starts.append(round(cursor, 3))
        cursor += duration + GAP_SECONDS
    ends = [round(starts[i] + durations[i], 3) for i in range(len(durations))]
    total = round((ends[-1] if ends else 0.0) + TAIL_SECONDS, 3)
    return {"starts": starts, "ends": ends, "total": total}


def tts_edge(text: str, target: Path, voice: str, rate: int) -> None:
    subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice,
                    f"--rate={rate:+d}%", "--text", text, "--write-media", str(target)],
                   capture_output=True, encoding="utf-8", errors="replace", check=True)
    if not target.exists() or target.stat().st_size < 2000:
        raise SystemExit(f"edge-tts 未产生有效音频：{text[:30]}…")


def tts_sapi(text: str, target: Path, voice: str | None, rate: int) -> None:
    if sys.platform != "win32":
        raise SystemExit("SAPI 仅支持 Windows；请安装 edge-tts 或改用其它引擎")
    select = f"$s.SelectVoice('{voice}');" if voice else ""
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"{select}"
        f"$s.Rate = {max(-10, min(10, round(rate / 10)))};"
        f"$s.SetOutputToWaveFile('{target}');"
        f"$s.Speak([System.IO.File]::ReadAllText('{target.with_suffix('.txt')}',"
        "[System.Text.Encoding]::UTF8));"
        "$s.Dispose();"
    )
    target.with_suffix(".txt").write_text(text, encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True,
                   capture_output=True, encoding="utf-8", errors="replace")


def cmd_tts(args) -> int:
    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    storyboard = read_json(paths["storyboard"])
    if not storyboard:
        raise SystemExit("未找到 storyboard.json，请先 storyboard.py draft")
    deps = detect_deps()
    gender = args.voice or storyboard.get("voice") or settings["voice"]
    engine = args.engine or deps["engines"]["voice"]
    if engine is None:
        raise SystemExit("没有可用的语音引擎（edge-tts 需联网，或安装 SAPI 中文语音）")
    rate = int(settings["voice_rate"].get(gender, 12))
    language = args.language or storyboard.get("language") or settings.get("language", "zh-CN")
    if language.lower().startswith("en"):
        rate = int(settings["voice_rate"].get(gender, 12)) + 2   # 英文略快一点更自然
    audio_dir = paths["video"] / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fps = settings["fps"]

    timeline: dict[str, dict] = {}
    for seg in storyboard["segments"]:
        if not seg.get("enabled", True):
            continue
        cues = seg.get("narration") or []
        durations: list[float] = []
        spoken_lines: list[str] = []
        for index, line in enumerate(cues):
            suffix = ".mp3" if engine == "edge" else ".wav"
            target = audio_dir / f"{seg['id']}_{index}{suffix}"
            spoken = normalize_narration(line, language)
            spoken_lines.append(spoken)
            if engine == "edge":
                tts_edge(spoken, target, voice_for(settings, gender, language), rate)
            else:
                tts_sapi(spoken, target, pick_sapi_voice(settings, gender, deps["sapi_voices"]), rate)
            durations.append(media_duration(target))
        slots = cue_slots(durations)
        starts, ends, total = slots["starts"], slots["ends"], slots["total"]
        timeline[seg["id"]] = {
            "cues": cues, "durations": [round(d, 3) for d in durations],
            "spoken": spoken_lines, "language": language,
            "starts": starts, "ends": ends, "total": total,
            "frames": int(round(total * fps)), "engine": engine, "voice": gender,
        }
        print(f"{seg['id']:14s} {len(cues)} 句  {total:6.2f}s → {timeline[seg['id']]['frames']} 帧")

    # 片头/片尾旁白（各取第一句，成片阶段据此配音）
    for name in ("intro", "outro"):
        lines = (storyboard.get(name) or {}).get("lines") or []
        if not lines:
            continue
        suffix = ".mp3" if engine == "edge" else ".wav"
        target = audio_dir / f"{name}_0{suffix}"
        if engine == "edge":
            tts_edge(lines[0], target, settings["edge_voice"][gender], rate)
        else:
            tts_sapi(lines[0], target, pick_sapi_voice(settings, gender, deps["sapi_voices"]), rate)
        print(f"{name:14s} 1 句  {media_duration(target):6.2f}s")

    write_json(paths["video"] / "timeline.json", timeline)
    storyboard["voice"] = gender
    for seg in storyboard["segments"]:
        if seg["id"] in timeline:
            seg["timeline"] = {k: timeline[seg["id"]][k]
                               for k in ("starts", "ends", "total", "frames")}
    write_json(paths["storyboard"], storyboard)
    print(f"时间轴 → {paths['video'] / 'timeline.json'}（引擎 {engine}，声线 {gender}）")
    return 0


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
              max_width: int) -> list[str]:
    if draw.textlength(text, font=font) <= max_width:
        return [text]
    # 优先在标点处断行，其次才按视觉平衡断行（避免行首出现「、」「，」）
    punctuations = "，。；：、）】"
    candidates = [i + 1 for i, ch in enumerate(text) if ch in punctuations]
    candidates += [i for i, ch in enumerate(text) if ch == " "]
    if not candidates:
        candidates = list(range(6, len(text) - 4))

    def score(split: int) -> float:
        left, right = text[:split], text[split:]
        balance = abs(draw.textlength(left, font=font) - draw.textlength(right, font=font))
        penalty = 0.0 if (split and text[split - 1] in punctuations) else 0.25 * max_width
        return balance + penalty

    split = min(candidates, key=score)
    return [text[:split].rstrip("，。；：、"), text[split:].lstrip()]


def caption_frames(frames_dir: Path, out_dir: Path, title: str, entry: dict,
                   settings: dict) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise SystemExit(f"没有帧：{frames_dir}（先运行 storyboard.py render）")
    fps = settings["fps"]
    bar = int(settings["caption_bar"])
    for index, frame in enumerate(frames):
        moment = index / fps
        text = ""
        for start, end, cue in zip(entry["starts"], entry["ends"], entry["cues"]):
            if start - 0.05 <= moment <= end + GAP_SECONDS:
                text = cue
        image = Image.open(frame).convert("RGB")
        width, height = image.size
        overlay = Image.new("RGBA", (width, bar), (255, 255, 255, 236))
        draw = ImageDraw.Draw(overlay)
        draw.line([(0, 0), (width, 0)], fill="#2F5FA8", width=4)
        font = load_font(FONT_BOLD, settings["subtitle_font_px"])
        lines = wrap_text(draw, text, font, width - 160) if text else []
        y = 18 if len(lines) == 1 else 12
        for line in lines:
            draw.text((width / 2, y), line, font=font, fill="#12304F", anchor="ma")
            y += settings["subtitle_font_px"] + 14
        ImageDraw.Draw(image).text(
            (40, 30), title, font=load_font(FONT_BOLD, settings["title_font_px"]),
            fill="#12304F", stroke_width=3, stroke_fill="white")
        composed = Image.new("RGB", (width, height + bar), "white")
        composed.paste(image, (0, 0))
        composed.paste(overlay.convert("RGB"), (0, height))
        composed.save(out_dir / f"{index:05d}.png")
    return len(frames)


def cmd_compose(args) -> int:
    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    storyboard = read_json(paths["storyboard"])
    timeline = read_json(paths["video"] / "timeline.json")
    if not storyboard or not timeline:
        raise SystemExit("缺少 storyboard.json 或 timeline.json（先 draft/confirm/tts）")
    ffmpeg = find_ffmpeg("ffmpeg")
    fps = settings["fps"]
    out_dir = paths["video"] / "仅画面版"
    out_dir.mkdir(parents=True, exist_ok=True)
    gif_dir = paths["video"] / "GIF"
    gif_dir.mkdir(parents=True, exist_ok=True)

    order = 0
    report = []
    for seg in storyboard["segments"]:
        if not seg.get("enabled", True) or seg["id"] not in timeline:
            continue
        order += 1
        entry = timeline[seg["id"]]
        frames_dir = paths["video"] / "frames" / seg["id"]
        captioned = paths["video"] / "captioned" / seg["id"]
        count = caption_frames(frames_dir, captioned, f"{seg['purpose']}｜{storyboard['title']}",
                               entry, settings)
        mp4 = out_dir / f"{order:02d}_{seg['id']}.mp4"
        gif = gif_dir / f"{order:02d}_{seg['id']}.gif"
        if ffmpeg:
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                            "-start_number", "0", "-i", str(captioned / "%05d.png"),
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                            "-start_number", "0", "-i", str(captioned / "%05d.png"),
                            "-vf", "fps=12,scale=960:-1:flags=lanczos,split[a][b];"
                                   "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer",
                            "-loop", "0", str(gif)], check=True)
        report.append({"id": seg["id"], "frames": count, "mp4": str(mp4) if ffmpeg else None,
                       "gif": str(gif) if ffmpeg else None})
        print(f"{seg['id']:14s} {count:4d} 帧  {entry['total']:5.1f}s  → {mp4.name}")
    payload = {"segments": report, "video_dir": str(out_dir),
               "gif_dir": str(gif_dir) if ffmpeg else None}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_render(args) -> int:
    script = Path(__file__).with_name("storyboard.py")
    argv = [sys.executable, str(script), "render", args.project]
    if args.only:
        argv += ["--only", args.only]
    if args.force:
        argv += ["--force"]
    return subprocess.run(argv).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="配音、字幕与分段视频")
    sub = parser.add_subparsers(dest="command", required=True)

    tts = sub.add_parser("tts")
    tts.add_argument("project")
    tts.add_argument("--voice", choices=["female", "male"], default=None)
    tts.add_argument("--engine", choices=["edge", "sapi"], default=None)
    tts.add_argument("--language", default=None, help="zh-CN（默认）或 en-US")

    render = sub.add_parser("render")
    render.add_argument("project")
    render.add_argument("--only", default=None)
    render.add_argument("--force", action="store_true")

    compose = sub.add_parser("compose")
    compose.add_argument("project")
    compose.add_argument("--json", action="store_true")

    args = parser.parse_args()
    return {"tts": cmd_tts, "render": cmd_render, "compose": cmd_compose}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
