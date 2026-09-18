# patent-3d-demo — turn a patent disclosure + CAD drawings into a 3D demo

[![regression](https://github.com/Jkcode8/patent-3d-demo/actions/workflows/regression.yml/badge.svg)](https://github.com/Jkcode8/patent-3d-demo/actions/workflows/regression.yml)
[![full pipeline](https://github.com/Jkcode8/patent-3d-demo/actions/workflows/full-pipeline.yml/badge.svg)](https://github.com/Jkcode8/patent-3d-demo/actions/workflows/full-pipeline.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**中文文档**: [README.zh-CN.md](README.zh-CN.md)

An **AI-agent skill** (works with Codex, Claude Code, and other skill-capable agent runtimes):
**disclosure + drawings → parametric 3D model → colour / black-and-white figures → narrated demo video.**

![pipeline](docs/images/pipeline.png)

## Why

Explaining a patent's structure, working principle and construction method with a 3D video beats text — but doing it by hand is slow and hard to repeat. This skill turns the whole chain into a scripted pipeline, and encodes the failure modes we actually hit as assertions instead of leaving them to the final render.

## What it produces

| Stage | Output |
|---|---|
| ① Extract | disclosure text + embedded figures, CAD entities + text, drawing sheets as PNG views |
| ② Model | parametric `.scad` with a fixed `device(theta, pull, water_z, step, explode, section)` interface, manifold STL |
| ③ Storyboard | segment plan derived from the disclosure, **confirmed by you before any rendering** |
| ④ Figures | colour renders, monochrome renders, orthographic line art (SVG / **DXF** / PNG) + parameter table |
| ⑤ Video | per-sentence TTS → timeline → subtitles → title cards → music with ducking → loudness normalised MP4 |
| ⑥ Delivery | `说明.md`: parameter provenance, assumption list, reproduction commands |

## Example output (fictional, shipped for regression)

![example colour](docs/images/example-color.png)

## Case study: pier anti-collision device

A real use of this skill — a tensegrity-style pier anti-collision device (8 cable-linked modules, sliding sleeve, buoyancy box, outer membrane).

![case impact](cases/pier-anticollision/images/case-impact-deformation.png)

| | |
|---|---|
| ![case exploded](cases/pier-anticollision/images/case-exploded.png) | ![case section](cases/pier-anticollision/images/case-section.png) |

See [`cases/pier-anticollision/`](cases/pier-anticollision/README.md) — model source, figures, colour legend, assembly sequence and a 38 s video sample.

## Requirements

- **OpenSCAD** (required). Override the binary with `OPENSCAD_EXECUTABLE`.
- Optional, each with a documented fallback: `ffmpeg` (without it: GIF only), `edge-tts` + network (without it: Windows SAPI voice), `numpy` / `Pillow` / `ezdxf`, AutoCAD (without it: read DXF instead of DWG).

```bash
python scripts/config.py --check     # prints availability and the degradation path for each gap
```

## Install

```bash
# Codex
git clone https://github.com/Jkcode8/patent-3d-demo.git "${CODEX_HOME:-$HOME/.codex}/skills/patent-3d-demo"
# Claude Code / 其他支持 skills 的智能体：放到各自的 skills 目录，例如
git clone https://github.com/Jkcode8/patent-3d-demo.git ~/.claude/skills/patent-3d-demo
```

## Quick start

```bash
SKILL=~/.codex/skills/patent-3d-demo
python $SKILL/scripts/config.py init-project <project>
# copy the disclosure and drawings into <project>/原始资料/ then:
python $SKILL/scripts/extract_docx.py <disclosure.docx> <project>/_extract
powershell -File $SKILL/scripts/extract_dwg.ps1 -OutDir <project>/_extract -DwgPath <drawing.dwg>
python $SKILL/scripts/render_sketch.py <project>/_extract

# modelling: start from assets/model_lib.scad and implement device(...) in <project>/model/device.scad
python $SKILL/scripts/storyboard.py draft   <project>    # segment plan + narration draft
python $SKILL/scripts/storyboard.py confirm <project>    # gate: nothing renders before this
python $SKILL/scripts/narration.py tts      <project> --voice female|male
python $SKILL/scripts/storyboard.py render  <project>    # per-segment, cached frames
python $SKILL/scripts/make_figures.py       <project>
python $SKILL/scripts/narration.py compose  <project>
python $SKILL/scripts/final_film.py         <project>
python $SKILL/scripts/make_delivery.py      <project>
```

## Repository layout

```
patent-3d-demo/
├── SKILL.md            entry point: triggers, six stages, deliverables, invariants
├── agents/openai.yaml  UI metadata
├── references/         extraction / modelling / storyboard / figures / video / troubleshooting
├── scripts/            14 scripts (extractors, renderer, storyboard, narration, film, checks)
├── assets/             model skeleton · 8 segment templates · example_simple (with expected output)
├── cases/              real-world case study
└── docs/images/        artwork used by this README
```

## Optional extras

| Need | How |
|---|---|
| English / other languages | `narration.py tts <project> --language en-US` — voice switches to `en-US-*`, subtitles keep the original text |
| Natural reading of numbers and units | on by default: `φ1500`→"直径1500", `1.5m`→"1.5米", `16+16+17度`→"16度、16度、17度", `−2.26m`→"负2.26米" (only the synthesised text is rewritten) |
| Section outlines | `lineart.py … --sections 2` (cuts the model at equal heights, outer + cut outlines) |
| Exploded line art | `lineart.py … --exploded <distance>` |
| Titles and dimension lines | `lineart.py` adds a figure title plus overall width/height dimensions to the PNG |
| Template smoke test | `check_templates.py <project> --frames 2 --render adjust` (instantiates all 8 segment templates) |
| Offline film (no TTS) | `make_stub_narration.py <project>` writes placeholder cues, then run compose / final_film |
| Skill structure check | `check_skill_md.py .` (frontmatter limited to name/description/license/allowed-tools/metadata) |

**Frame cache**: `storyboard.py render` hashes the instantiated segment file, the `-D` values and the render
settings into `video/frames/<id>/_cache.json`, so a model or parameter change always re-renders — the previous
behaviour (comparing frame counts only) could silently reuse stale frames.

## Built-in invariants

The scripts assert instead of hoping: every narration line fits its time slot (no overlapping speech),
voice sits ≥ 8 dB above the music bed, the film lands at −16 LUFS ±1, STL is manifold,
**rendered frames are not blank** (a silent `include` failure once produced an all-white video),
and rendering is refused while the storyboard is unconfirmed.

## Example & CI

`assets/example_simple/` is a fictional "adjustable guardrail bracket" with model, storyboard and expected
output (film, figures, line-art DXF, self-check report). `regression.yml` rebuilds it on every push —
including the blank-frame check — while `full-pipeline.yml` runs the narrated end-to-end film on demand.

## Notes

- The shipped example is fictional; the case study is a real project included with the author's permission.
- Background music defaults to a synthesised bed. Drop a track into `音乐/` or pass `--music` to use your own
  (level-matched and ducked automatically).

## License

MIT
