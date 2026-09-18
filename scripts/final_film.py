"""Assemble the final narrated film: title cards + narration + ducked music.

Reads ``storyboard.json`` (segment order, titles, intro/outro lines) and
``video/timeline.json`` (cue timings) plus the video-only segment files from
``video/仅画面版/``.  Produces ``video/带配音版/`` and one combined film.

Two invariants are checked before the film is accepted:
  * the voice sits at least ``voice_above_music_db`` above the music-only level
    (otherwise the bed masks the narration);
  * the integrated loudness lands within 1 LU of ``loudnorm_i``.

Usage:
    python final_film.py <project> [--music <file>|--no-music]
                         [--voice female|male] [--cards intro+outro] [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import (
    find_ffmpeg,
    load_settings,
    project_paths,
    read_json,
    write_json,
)

MUSIC_DIRS = ("音乐", "_music")
LOOP_XFADE = 1.5
FONT_BOLD = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
             "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_BOLD:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def run(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


def duration_of(ffprobe: str, path: Path) -> float:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, encoding="utf-8", errors="replace", check=True)
    return float(out.stdout.strip())


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path)) as handle:
        sr, channels = handle.getframerate(), handle.getnchannels()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    samples = data.astype(np.float64) / 32768.0
    return sr, samples.reshape(-1, channels) if channels > 1 else samples


def write_wav(path: Path, sr: int, samples: np.ndarray) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    payload = (clipped * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1 if clipped.ndim == 1 else clipped.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(payload.tobytes())


def normalise_rms(path: Path, target_db: float) -> None:
    sr, samples = read_wav(path)
    rms = float(np.sqrt(np.mean(samples ** 2))) or 1e-9
    gain = (10 ** (target_db / 20.0)) / rms
    peak = float(np.max(np.abs(samples))) or 1e-9
    if peak * gain > 0.95:
        gain = 0.95 / peak
    write_wav(path, sr, samples * gain)


def reverb(signal: np.ndarray, sr: int, decay: float = 2.6, wet: float = 0.45) -> np.ndarray:
    length = int(decay * sr)
    rng = np.random.default_rng(20260918)
    impulse = rng.standard_normal(length) * np.exp(-np.arange(length) / (decay * sr / 3.2))
    impulse[: int(0.015 * sr)] = 0.0
    impulse /= np.sqrt(np.sum(impulse ** 2))
    nfft = 1 << (len(signal) + length - 1).bit_length()
    tail = np.fft.irfft(np.fft.rfft(signal, nfft) * np.fft.rfft(impulse, nfft), nfft)[: len(signal)]
    return signal + wet * tail / (np.max(np.abs(tail)) or 1.0) * np.max(np.abs(signal))


def build_music(total: float, path: Path, sr: int = 44100) -> None:
    """Ambient bed used when the user supplies no track (Am–F–C–G + drone + melody)."""
    chords = [
        (110.00, [110.00, 164.81, 220.00, 261.63, 329.63], 659.25),
        (87.31, [87.31, 130.81, 174.61, 220.00, 261.63], 698.46),
        (130.81, [130.81, 196.00, 261.63, 329.63, 392.00], 783.99),
        (98.00, [98.00, 146.83, 196.00, 246.94, 293.66], 659.25),
    ]
    n = int(total * sr)
    time = np.arange(n) / sr
    left, right = np.zeros(n), np.zeros(n)
    span = 8.0
    for detune, target in ((0.9985, left), (1.0015, right)):
        target += 0.085 * np.sin(2 * np.pi * (chords[0][0] / 2) * detune * time)
        target += 0.045 * np.sin(2 * np.pi * chords[0][0] * detune * time)
    for index in range(int(math.ceil(total / span))):
        start, end = int(index * span * sr), min(n, int((index + 1) * span * sr))
        if end <= start:
            break
        idx = np.arange(end - start) / sr
        length = (end - start) / sr
        swell = np.clip(np.minimum(idx / 2.8, (length - idx) / 2.0), 0, 1)
        _root, chord, melody = chords[index % len(chords)]
        for voice, freq in enumerate(chord):
            gain = 0.075 / (1 + 0.55 * voice)
            left[start:end] += gain * np.sin(2 * np.pi * freq * 0.999 * idx) * swell
            right[start:end] += gain * np.sin(2 * np.pi * freq * 1.001 * idx) * swell
        mel = np.clip(np.minimum(idx / 2.0, (length - idx) / 2.0), 0, 1)
        left[start:end] += 0.11 * np.sin(2 * np.pi * melody * idx) * mel
        right[start:end] += 0.11 * np.sin(2 * np.pi * melody * 1.0008 * idx) * mel
        for beat in range(2):
            b0, b1 = start + int(beat * 4 * sr), min(end, start + int((beat * 4 + 1.8) * sr))
            if b1 <= b0:
                continue
            bidx = np.arange(b1 - b0) / sr
            thump = np.exp(-bidx * 3.0) * (0.5 * np.sin(2 * np.pi * 52 * bidx)
                                           + 0.22 * np.sin(2 * np.pi * 104 * bidx))
            left[b0:b1] += 0.16 * thump
            right[b0:b1] += 0.16 * thump
    left, right = reverb(left, sr), reverb(right, sr)
    fade_in, fade_out = int(2.5 * sr), int(3.5 * sr)
    for channel in (left, right):
        channel[:fade_in] *= np.linspace(0, 1, fade_in)
        channel[-fade_out:] *= np.linspace(1, 0, fade_out)
    peak = max(np.max(np.abs(left)), np.max(np.abs(right))) or 1.0
    write_wav(path, sr, np.stack([left / peak * 0.72, right / peak * 0.72], axis=1))


def build_user_music(source: Path, total: float, path: Path, ffmpeg: str) -> str:
    raw = path.with_suffix(".raw.wav")
    run([ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-ac", "2", "-ar", "44100",
         "-c:a", "pcm_s16le", str(raw)])
    sr, track = read_wav(raw)
    raw.unlink(missing_ok=True)
    if track.ndim == 1:
        track = np.stack([track, track], axis=1)
    want, fade = int(total * sr), int(LOOP_XFADE * sr)
    if len(track) >= want:
        bed, note = track[:want].copy(), "整曲截取"
    else:
        pieces, loops = [track], int(np.ceil(want / max(1, len(track) - fade))) + 1
        for _ in range(loops):
            previous, closing = pieces[-1], track
            overlap = min(fade, len(previous), len(closing))
            ramp = np.linspace(0.0, 1.0, overlap)[:, None]
            blended = previous[-overlap:] * (1 - ramp) + closing[:overlap] * ramp
            pieces[-1] = previous[:-overlap]
            pieces += [blended, closing[overlap:]]
        bed = np.concatenate(pieces, axis=0)[:want]
        if len(bed) < want:
            bed = np.pad(bed, ((0, want - len(bed)), (0, 0)))
        note = f"{len(track) / sr:.0f}s 循环拼接"
    fade_in = fade_out = int(1.5 * sr)
    bed[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    bed[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    write_wav(path, sr, bed)
    return note


def find_user_music(root: Path, explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for folder in [root / name for name in MUSIC_DIRS] + [root]:
        if not folder.is_dir():
            continue
        for pattern in ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.aac", "*.ogg"):
            for candidate in sorted(folder.glob(pattern)):
                if candidate.stat().st_size > 40_000 and not candidate.name.startswith(
                        ("tts", "track_", "narration", "sil_", "sample")):
                    return candidate
    return None


def gradient(width: int, height: int) -> Image.Image:
    top, bottom = np.array([255, 255, 255]), np.array([228, 238, 247])
    column = np.linspace(0, 1, height).reshape(-1, 1)
    rows = (top[None, :] * (1 - column) + bottom[None, :] * column).astype("uint8")
    return Image.fromarray(np.repeat(rows[:, None, :], width, axis=1), "RGB")


def card_frames(kind: str, count: int, out_dir: Path, storyboard: dict,
                settings: dict, width: int, height: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    background = gradient(width, height)
    white = Image.new("RGB", (width, height), "white")
    accent = "#2F5FA8"
    total_seconds = count / settings["fps"]
    for index in range(count):
        moment = index / settings["fps"]
        alpha = min(min(1.0, moment / 0.8), min(1.0, max(0.0, (total_seconds - moment) / 0.8)))
        drift = int(26 * (1 - min(1.0, moment / 0.8)))
        card = background.copy()
        draw = ImageDraw.Draw(card)
        draw.rectangle([0, 0, width, 12], fill=accent)

        def text(y: int, content: str, size: int, colour: str) -> None:
            draw.text((width / 2, y + drift), content, font=font(size), fill=colour, anchor="ma")

        if kind == "intro":
            text(int(height * 0.28), storyboard["title"], 104, "#12304F")
            text(int(height * 0.38), storyboard.get("subtitle", "三维演示动画"), 56, accent)
            draw.line([(width / 2 - 460, int(height * 0.45)), (width / 2 + 460, int(height * 0.45))],
                      fill=accent, width=3)
            text(int(height * 0.48), storyboard.get("keywords", ""), 44, "#3A6EA5")
            text(int(height * 0.66), "专利技术交底演示", 40, "#6B7C8C")
        else:
            text(int(height * 0.20), "谢 谢 观 看", 116, "#12304F")
            draw.line([(width / 2 - 420, int(height * 0.31)), (width / 2 + 420, int(height * 0.31))],
                      fill=accent, width=3)
            for row, line in enumerate(storyboard.get("outro", {}).get("lines", [])):
                text(int(height * 0.38) + row * 96, line, 46, "#1B3A5C")
            text(int(height * 0.80), storyboard["title"], 40, "#3A6EA5")
        Image.blend(white, card, alpha).save(out_dir / f"{index:05d}.png")


def narration_track(clips: list[tuple[Path | None, float]], total: float,
                    target: Path, ffmpeg: str) -> None:
    """Place each clip at its start time and pad to exactly *total* seconds."""
    present = [(clip, start) for clip, start in clips if clip is not None]
    argv = [ffmpeg, "-y", "-loglevel", "error"]
    for clip, _ in present:
        argv += ["-i", str(clip)]
    filters, labels = [], []
    for index, (_, start) in enumerate(present):
        delay = int(round(start * 1000))
        filters.append(f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=44100:"
                       f"channel_layouts=mono,adelay={delay}|{delay}[a{index}]")
        labels.append(f"[a{index}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(present)}:duration=longest:normalize=0[mix]")
    filters.append(f"[mix]apad=whole_dur={total:.3f}[out]")
    argv += ["-filter_complex", ";".join(filters), "-map", "[out]",
             "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(target)]
    run(argv)


def mix(bed: Path, narration: Path, out: Path, ffmpeg: str, settings: dict) -> None:
    """Music under narration; narration is split so it can drive the sidechain."""
    filters = (
        "[0:a]volume=1.0,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[bg];"
        "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono,"
        "volume=6dB,acompressor=threshold=0.05:ratio=3:attack=6:release=200,"
        "aformat=channel_layouts=stereo[nar];"
        # 旁白同时供给侧链与混音：必须 asplit，否则第二路会被丢弃（人声消失）
        "[nar]asplit=2[nar_sc][nar_mix];"
        "[bg][nar_sc]sidechaincompress=threshold=0.02:ratio=12:attack=6:release=380[duck];"
        "[duck][nar_mix]amix=inputs=2:duration=first:normalize=0[mixed];"
        f"[mixed]loudnorm=I={settings['loudnorm_i']}:TP={settings['loudnorm_tp']}:"
        f"LRA={settings['loudnorm_lra']}[a]"
    )
    run([ffmpeg, "-y", "-loglevel", "error", "-i", str(bed), "-i", str(narration),
         "-filter_complex", filters, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(out)])


def measure_invariants(film: Path, ffmpeg: str, ffprobe: str, settings: dict,
                       speech_at: float, music_at: float, window: float = 2.0) -> dict:
    """Compare narration vs music-only loudness and read back the integrated LUFS."""
    def window_rms(moment: float) -> float:
        with np.errstate(all="ignore"):
            out = subprocess.run(
                [ffmpeg, "-v", "error", "-ss", f"{max(0.0, moment):.2f}", "-t", f"{window}",
                 "-i", str(film), "-ac", "1", "-ar", "16000", "-f", "wav", "-"],
                capture_output=True, check=True)
        with wave.open(__import__("io").BytesIO(out.stdout)) as handle:
            data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        samples = data.astype(np.float64) / 32768.0
        return 20 * math.log10(float(np.sqrt(np.mean(samples ** 2))) + 1e-9)

    voice_db, music_db = window_rms(speech_at), window_rms(music_at)
    loud = subprocess.run([ffmpeg, "-hide_banner", "-i", str(film), "-filter:a",
                           "loudnorm=print_format=json", "-f", "null", "-"],
                          capture_output=True, encoding="utf-8", errors="replace")
    match = __import__("re").search(r'"input_i"\s*:\s*"(-?[\d.]+)"', loud.stderr)
    integrated = float(match.group(1)) if match else float("nan")
    return {
        "voice_db": round(voice_db, 1),
        "music_db": round(music_db, 1),
        "voice_above_music_db": round(voice_db - music_db, 1),
        "integrated_lufs": integrated,
        "voice_ok": (voice_db - music_db) >= settings["voice_above_music_db"],
        "loudness_ok": abs(integrated - settings["loudnorm_i"]) <= 1.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="合成带配音+配乐+片头片尾的成片")
    parser.add_argument("project")
    parser.add_argument("--music", default=None)
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--cards", default="intro+outro")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    storyboard = read_json(paths["storyboard"])
    timeline = read_json(paths["video"] / "timeline.json")
    if not storyboard or not timeline:
        raise SystemExit("缺少 storyboard.json 或 timeline.json")
    ffmpeg, ffprobe = find_ffmpeg("ffmpeg"), find_ffmpeg("ffprobe")
    if not ffmpeg:
        raise SystemExit("未找到 ffmpeg：只能输出动画 GIF，无法合成配乐成片")

    segments = [s for s in storyboard["segments"] if s.get("enabled", True) and s["id"] in timeline]
    # 片头/片尾时长按实际旁白长度排布，并留出纯配乐尾巴（供电平校验与收尾）
    audio_dir = paths["video"] / "audio"
    engine_suffix = ".mp3" if timeline[segments[0]["id"]]["engine"] == "edge" else ".wav"

    def card_length(name: str, fallback: float, tail: float) -> float:
        voice = audio_dir / f"{name}_0{engine_suffix}"
        if voice.exists():
            return round(1.2 + duration_of(ffprobe, voice) + tail, 2)
        return fallback

    intro_len = card_length("intro", settings["intro_seconds"], 2.0)
    outro_len = card_length("outro", settings["outro_seconds"], 2.5)
    part_lengths = [intro_len] + [timeline[s["id"]]["total"] for s in segments] + [outro_len]
    total = sum(part_lengths)

    work = paths["video"] / "film"
    work.mkdir(parents=True, exist_ok=True)
    music = work / "music.wav"
    if args.no_music:
        note = "未使用配乐"
        write_wav(music, 44100, np.zeros((int(total * 44100), 2)))
    else:
        user_music = find_user_music(paths["root"], args.music)
        if user_music:
            note = build_user_music(user_music, total, music, ffmpeg) + f"（{user_music.name}）"
        else:
            build_music(total, music)
            note = "内置合成铺底"
    normalise_rms(music, settings["music_bed_rms_db"])

    parts: list[tuple[str, float, float]] = []
    cursor = 0.0
    for name, length in zip(["intro"] + [s["id"] for s in segments] + ["outro"], part_lengths):
        parts.append((name, cursor, length))
        cursor += length

    fps, size = settings["fps"], settings["render_size"]
    width = int(size.split(",")[0])
    height = int(size.split(",")[1])
    out_dir = paths["video"] / "带配音版"
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    report = []

    for index, (name, offset, length) in enumerate(parts):
        part_dir = work / name
        part_dir.mkdir(parents=True, exist_ok=True)
        clips: list[tuple[Path | None, float]] = []
        if name in ("intro", "outro"):
            voice_file = audio_dir / f"{name}_0{engine_suffix}"
            if not voice_file.exists():
                print(f"提示：{name} 旁白缺失（{voice_file.name}），该段将只有配乐")
            else:
                clips = [(voice_file, 1.2)]
            frames_dir = part_dir / "frames"
            if not any(frames_dir.glob("*.png")):
                card_frames(name, int(round(length * fps)), frames_dir, storyboard,
                            settings, width, height)
            video = part_dir / "video.mp4"
            run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                 "-start_number", "0", "-i", str(frames_dir / "%05d.png"),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p", str(video)])
        else:
            entry = timeline[name]
            suffix = engine_suffix
            for cue_index, start in enumerate(entry["starts"]):
                audio = audio_dir / f"{name}_{cue_index}{suffix}"
                if audio.exists():
                    clips.append((audio, start))
            video_only = sorted((paths["video"] / "仅画面版").glob(f"*_{name}.mp4"))
            if not video_only:
                raise SystemExit(f"缺少分段视频：{name}（先运行 narration.py compose）")
            video = video_only[0]

        narration = part_dir / "narration.wav"
        narration_track(clips, length, narration, ffmpeg)
        bed = part_dir / "music.wav"
        run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{offset:.3f}", "-t", f"{length:.3f}",
             "-i", str(music), "-c:a", "pcm_s16le", str(bed)])
        normalise_rms(bed, settings["music_bed_rms_db"])
        mixed = part_dir / "mixed.m4a"
        mix(bed, narration, mixed, ffmpeg, settings)

        final = out_dir / f"{index:02d}_{name}.mp4"
        run([ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-i", str(mixed),
             "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(final)])
        produced.append(final)
        report.append({"part": name, "seconds": round(duration_of(ffprobe, final), 2),
                       "file": final.name})

    listing = work / "concat.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in produced), encoding="utf-8")
    film = paths["video"] / "完整版.mp4"
    run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(film)])

    # 取样窗口：片头旁白（人声） vs 片尾最后的纯配乐尾巴
    speech_at = parts[0][1] + 1.2
    music_at = max(0.0, total - 1.5)
    checks = measure_invariants(film, ffmpeg, ffprobe, settings, speech_at, music_at, window=1.4)
    payload = {"film": str(film), "seconds": round(duration_of(ffprobe, film), 2),
               "music": note, "parts": report, "checks": checks, "ok": bool(checks["voice_ok"])}
    write_json(paths["video"] / "film_report.json", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"成片：{film}  {payload['seconds']}s  配乐：{note}")
        print(f"人声 {checks['voice_db']} dB / 纯配乐 {checks['music_db']} dB "
              f"（差 {checks['voice_above_music_db']} dB，要求 ≥ "
              f"{settings['voice_above_music_db']}）")
        print(f"整片响度 {checks['integrated_lufs']} LUFS"
              f"（目标 {settings['loudnorm_i']}±1）")
        if not checks["voice_ok"]:
            print("警告：配乐可能盖住人声，可降低 music_bed_rms_db 或提高 voice_rate")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
