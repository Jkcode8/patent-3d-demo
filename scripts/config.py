"""Central configuration, dependency detection and degradation policy.

Every other script in this skill imports from here, so paths, defaults and
fallbacks live in exactly one place.  Nothing is hard-coded to one machine:
paths come from environment variables, PATH lookup or well-known install
locations, and every capability has a documented fallback.

Usage:
    python config.py --check [--json]          # dependency report
    python config.py init-project <dir>        # create the project layout
    python config.py paths <dir>               # print the layout as JSON
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"
SEGMENTS = ASSETS / "segments"
# 单一版本来源：SKILL.md 的 metadata.version、CHANGELOG.md 最新条目与本常量由
# tests/test_units.py 强制一致，避免发版时漏改某一处。
VERSION = "1.1.0"

# ----------------------------------------------------------------- defaults
DEFAULTS: dict = {
    # render / video
    "render_size": "1920,1440",
    "fps": 20,
    "caption_bar": 150,
    "title_font_px": 38,
    "subtitle_font_px": 46,
    "seg_seconds_min": 8,
    "seg_seconds_max": 30,
    "intro_seconds": 6.0,
    "outro_seconds": 6.5,
    # narration
    "voice": "female",                       # female | male
    "voice_rate": {"female": 12, "male": 15},  # percent
    "edge_voice": {
        "female": "zh-CN-XiaoxiaoNeural",
        "male": "zh-CN-YunyangNeural",
        "en-female": "en-US-AriaNeural",
        "en-male": "en-US-GuyNeural",
    },
    "sapi_voice": {
        "female": ["Microsoft Xiaoxiao", "Microsoft Huihui", "Microsoft Yaoyao"],
        "male": ["Microsoft Kangkang", "Microsoft Yunyang"],
    },
    "language": "zh-CN",
    # music
    "music_bed_rms_db": -33.0,               # bed level after normalisation
    "voice_above_music_db": 8.0,             # invariant checked before delivery
    "loudnorm_i": -16.0,
    "loudnorm_tp": -1.5,
    "loudnorm_lra": 11.0,
    # geometry / quality
    "scad_fn": 48,
    "scad_coil_seg": 6,
    "lineart_views": ["front", "top", "side", "iso"],
}

# ----------------------------------------------------------------- layout
LAYOUT = {
    "sources": "原始资料",
    "extract": "_extract",
    "model": "model",
    "figures": "figures",
    "video": "video",
}
STORYBOARD = "storyboard.json"
STORYBOARD_MD = "分镜.md"
NOTES = "说明.md"


def _first_existing(candidates: list[str | None]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.expandvars(candidate.strip().strip('"'))
        if os.path.isfile(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _glob_first(patterns: list[str]) -> str | None:
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), reverse=True)
        if hits:
            return hits[0]
    return None


# ----------------------------------------------------------------- finders
def find_openscad() -> str | None:
    """OpenSCAD CLI. Prefers ``openscad.com`` on Windows: it forwards the
    child's stdout/stderr and exit code, which ``openscad.exe`` does not."""
    if os.name == "nt":
        names = ["openscad.com", "openscad.exe", "openscad"]
        patterns = [
            r"C:\Program Files\OpenSCAD\openscad.com",
            r"C:\Program Files (x86)\OpenSCAD\openscad.com",
            r"D:\AI\OpenSCAD-*\OpenSCAD-*\openscad.com",
            r"*:\OpenSCAD-*\OpenSCAD-*\openscad.com",
            r"*:\OpenSCAD\openscad.com",
        ]
    else:
        names = ["openscad"]
        patterns = [
            "/usr/bin/openscad",
            "/usr/local/bin/openscad",
            "/opt/homebrew/bin/openscad",
            "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
        ]
    return _first_existing([os.environ.get("OPENSCAD_EXECUTABLE")] + names) or _glob_first(patterns)


def find_ffmpeg(name: str = "ffmpeg") -> str | None:
    env = os.environ.get(name.upper())
    if env:
        path = Path(env)
        if path.is_dir():
            path = path / f"{name}.exe"
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        winget = os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*"
            r"\ffmpeg-*\bin"
        )
        hit = _glob_first([f"{winget}\\{name}.exe"])
        if hit:
            return hit
    return None


def has_autocad() -> bool:
    """True when AutoCAD exposes its COM ProgID (Windows only)."""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "AutoCAD.Application"):
            return True
    except OSError:
        return False


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def network_ok(host: str = "speech.platform.bing.com", port: int = 443,
               timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def list_sapi_voices() -> list[str]:
    """Names of installed Windows SAPI voices (empty on other platforms)."""
    if os.name != "nt":
        return []
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
        ".GetInstalledVoices()|%{$_.VoiceInfo.Name}"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def detect_deps() -> dict:
    """Probe the machine and decide which engine each stage will use."""
    openscad = find_openscad()
    ffmpeg, ffprobe = find_ffmpeg("ffmpeg"), find_ffmpeg("ffprobe")
    mods = {name: module_available(name) for name in
            ("numpy", "PIL", "ezdxf", "edge_tts", "docx", "pypdf", "fitz")}
    autocad = has_autocad()
    sapi = list_sapi_voices() if os.name == "nt" else []
    online = network_ok() if mods["edge_tts"] else False

    voice_engine = "edge" if (mods["edge_tts"] and online) else ("sapi" if sapi else None)
    return {
        "openscad": openscad,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "autocad_com": autocad,
        "sapi_voices": sapi,
        "network": online,
        "modules": mods,
        "engines": {
            "figure": "ffmpeg" if ffmpeg else None,
            "video": "ffmpeg" if ffmpeg else "none",          # no ffmpeg => GIF only
            "gif": "ffmpeg" if ffmpeg else ("pillow" if mods["PIL"] else "none"),
            "voice": voice_engine,
            "dwg": "autocad-com" if autocad else "dxf",
            "lineart": "openscad-projection" if openscad else "none",
        },
        "blocking": [] if openscad else ["OpenSCAD 未找到：无法建模/渲染"],
        "warnings": [
            msg for msg in [
                None if ffmpeg else "未找到 ffmpeg：只能输出动画 GIF，无法合成 MP4/配乐",
                None if voice_engine else "无可用语音引擎：edge-tts 不可用且未安装 SAPI 中文语音",
                None if autocad else "无 AutoCAD COM：DWG 需先另存为 DXF 或提供 PDF/图片",
                None if mods["numpy"] else "未安装 numpy：无法合成配乐与电平校验",
                None if mods["PIL"] else "未安装 Pillow：无法绘制字幕/片头片尾",
                None if mods["ezdxf"] else "未安装 ezdxf：DXF 解析不可用",
            ] if msg
        ],
    }


def describe(deps: dict) -> str:
    lines = ["依赖自检", "=" * 46]
    lines.append(f"OpenSCAD      : {deps['openscad'] or '未找到'}")
    lines.append(f"ffmpeg        : {deps['ffmpeg'] or '未找到'}")
    lines.append(f"AutoCAD COM   : {'可用' if deps['autocad_com'] else '不可用'}")
    lines.append(f"edge-tts/网络 : {'可用' if deps['network'] else '不可用'}")
    lines.append(f"SAPI 语音     : {len(deps['sapi_voices'])} 个"
                 + (f"（{', '.join(deps['sapi_voices'][:3])}…）" if deps["sapi_voices"] else ""))
    mods = ", ".join(f"{k}={'有' if v else '无'}" for k, v in deps["modules"].items())
    lines.append(f"Python 模块   : {mods}")
    lines.append("-" * 46)
    for key, value in deps["engines"].items():
        lines.append(f"engines.{key:9s}: {value}")
    if deps["blocking"]:
        lines.append("-" * 46)
        for item in deps["blocking"]:
            lines.append(f"[阻塞] {item}")
    if deps["warnings"]:
        lines.append("-" * 46)
        for item in deps["warnings"]:
            lines.append(f"[降级] {item}")
    return "\n".join(lines)


# ----------------------------------------------------------------- project
def project_paths(root: str | Path) -> dict[str, Path]:
    root = Path(root).expanduser().resolve()
    paths = {"root": root}
    for key, name in LAYOUT.items():
        paths[key] = root / name
    paths["storyboard"] = root / STORYBOARD
    paths["storyboard_md"] = root / STORYBOARD_MD
    paths["notes"] = root / NOTES
    paths["config"] = root / "project.json"
    return paths


def init_project(root: str | Path) -> dict[str, Path]:
    paths = project_paths(root)
    for key in ("sources", "extract", "model", "figures", "video"):
        paths[key].mkdir(parents=True, exist_ok=True)
    for sub in ("frames", "audio", "带配音版", "仅画面版", "GIF", "配乐"):
        (paths["video"] / sub).mkdir(parents=True, exist_ok=True)
    if not paths["config"].exists():
        paths["config"].write_text(
            json.dumps({"skill": "patent-3d-demo", "version": VERSION},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return paths


def load_settings(root: str | Path) -> dict:
    """Defaults, overridden by <project>/project.json."""
    settings = json.loads(json.dumps(DEFAULTS))
    config_file = project_paths(root)["config"]
    if config_file.exists():
        try:
            settings.update(json.loads(config_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return settings


def read_json(path: str | Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: str | Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="patent-3d-demo configuration")
    parser.add_argument("--check", action="store_true", help="dependency report (default)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("command", nargs="?",
                        help="check | init-project | paths（省略时等同 check）")
    parser.add_argument("project", nargs="?", help="项目目录")
    args = parser.parse_args()
    if args.check or args.command in (None, "check"):
        deps = detect_deps()
        if args.json:
            print(json.dumps(deps, ensure_ascii=False, indent=2))
        else:
            print(describe(deps))
        return 1 if deps["blocking"] else 0
    if args.command == "init-project":
        if not args.project:
            parser.error("init-project 需要项目目录")
        paths = init_project(args.project)
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "paths":
        if not args.project:
            parser.error("paths 需要项目目录")
        print(json.dumps({k: str(v) for k, v in project_paths(args.project).items()},
                         ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
