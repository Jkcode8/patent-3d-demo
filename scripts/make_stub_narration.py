"""Generate a stub narration timeline so the whole video chain can run offline.

CI and smoke tests need ``narration.py compose`` and ``final_film.py`` without a
TTS service.  This writes a tone burst per cue (same duration model as real
speech) plus the timeline, so ducking, level checks and loudness behave like the
real thing.

Usage:
    python make_stub_narration.py <project> [--seconds-per-char 0.22] [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from config import find_ffmpeg, load_settings, project_paths, read_json, write_json

GAP_SECONDS = 0.35
TAIL_SECONDS = 0.9
TONE_HZ = 440.0
TONE_DBFS = -20.0


def tone_wav(path: Path, seconds: float, sr: int = 44100) -> None:
    samples = int(max(0.3, seconds) * sr)
    t = np.arange(samples) / sr
    envelope = np.minimum(1.0, np.minimum(t / 0.05, (samples / sr - t) / 0.08))
    signal = np.sin(2 * np.pi * TONE_HZ * t) * np.clip(envelope, 0, 1)
    signal *= 10 ** (TONE_DBFS / 20.0) / max(1e-9, np.max(np.abs(signal)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes((signal * 32767).astype("<i2").tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description="生成离线占位旁白（CI 用）")
    parser.add_argument("project")
    parser.add_argument("--seconds-per-char", type=float, default=0.22)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = project_paths(args.project)
    settings = load_settings(paths["root"])
    storyboard = read_json(paths["storyboard"], {}) or {}
    audio_dir = paths["video"] / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fps = settings["fps"]
    timeline: dict[str, dict] = {}

    for seg in storyboard.get("segments", []):
        if not seg.get("enabled", True):
            continue
        cues = seg.get("narration") or []
        durations = [round(max(2.0, len(line) * args.seconds_per_char), 3) for line in cues]
        starts, cursor = [], 0.0
        for duration in durations:
            starts.append(round(cursor, 3))
            cursor += duration + GAP_SECONDS
        ends = [round(starts[i] + durations[i], 3) for i in range(len(durations))]
        total = round((ends[-1] if ends else 0.0) + TAIL_SECONDS, 3)
        for index, duration in enumerate(durations):
            tone_wav(audio_dir / f"{seg['id']}_{index}.wav", duration)
        timeline[seg["id"]] = {
            "cues": cues, "spoken": cues, "language": "zh-CN",
            "durations": durations, "starts": starts, "ends": ends,
            "total": total, "frames": int(round(total * fps)),
            "engine": "stub", "voice": "stub",
        }
        print(f"{seg['id']:14s} {len(cues)} 句  {total:6.2f}s → {timeline[seg['id']]['frames']} 帧")

    # 片头/片尾占位（final_film 会按其实时长排布卡片）
    for name in ("intro", "outro"):
        lines = (storyboard.get(name) or {}).get("lines") or []
        if lines:
            tone_wav(audio_dir / f"{name}_0.wav",
                     max(2.0, len(lines[0]) * args.seconds_per_char))

    write_json(paths["video"] / "timeline.json", timeline)
    if args.json:
        print(json.dumps({"timeline": str(paths["video"] / "timeline.json"),
                          "segments": list(timeline)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
