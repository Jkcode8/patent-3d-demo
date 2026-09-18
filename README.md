# patent-3d-demo —— 专利三维演示技能

把**专利交底书 + CAD 图纸**变成**参数化三维模型、彩色/黑白附图、配音演示视频**的 Codex 技能。

> 一个 Codex Skill: 交底书/图纸 → 三维建模 → 分镜（确认后渲染）→ 渲染出图 → 配音成片。

## 它解决什么

专利交底书里的结构、工况、施工方法，用视频讲解比文字有效得多，但手工做三维演示既慢又难复现。
本技能把整条链路固化成可重复执行的流程，并把"踩过的坑"写成断言与检查清单。

## 能力

| 阶段 | 做什么 | 关键脚本 |
|---|---|---|
| ① 提取 | `.doc`(OLE2) / `.docx` / `.dwg`(AutoCAD COM) / `.dxf` / PDF → 正文、插图、图元、视图 PNG | `extract_doc.py` `extract_docx.py` `extract_dwg.ps1` `extract_dxf.py` `render_sketch.py` |
| ② 建模 | 由二维图读出三维结构，写出满足统一接口的参数化模型（含机构运动学求解校验） | `model_lib.scad` + `check_kinematics.py` |
| ③ 分镜 | 按交底书章节自动推导段落草案，**经你确认后**才渲染（8 类段落模板） | `storyboard.py` |
| ④ 出图 | 彩色立体图、单色立体图、正投影线稿（SVG/DXF/PNG，DXF 可直接进 CAD） | `openscad_run.py` `lineart.py` `make_figures.py` |
| ⑤ 成片 | 逐句 TTS → 时间轴 → 字幕 → 片头片尾 → 配乐（自动 duction）→ 响度归一 | `narration.py` `final_film.py` |
| ⑥ 交付 | `说明.md`：参数来源、假设清单、复现命令、环境信息 | `make_delivery.py` |

## 环境要求

- **OpenSCAD**（必需；本机为 `openscad.com`。可用 `OPENSCAD_EXECUTABLE` 指定）
- 可选：`ffmpeg`（无则只出 GIF）、`edge-tts` + 网络（无则用 Windows SAPI 语音）、
  `numpy` / `Pillow` / `ezdxf`、AutoCAD（有则直接读 DWG，无则改用 DXF）

自检：`python scripts/config.py --check` —— 会逐项给出可用性与**降级路径**。

## 安装

```bash
git clone https://github.com/Jkcode8/patent-3d-demo.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/patent-3d-demo"
```

## 快速开始

```bash
SKILL=~/.codex/skills/patent-3d-demo
python $SKILL/scripts/config.py init-project <项目目录>     # 建骨架
# 把交底书/图纸放进 <项目目录>/原始资料/
python $SKILL/scripts/extract_docx.py <交底书.docx> <项目>/_extract
powershell -File $SKILL/scripts/extract_dwg.ps1 -OutDir <项目>/_extract -DwgPath <图.dwg>
python $SKILL/scripts/render_sketch.py <项目>/_extract      # 图元 → 视图 PNG

# 建模：复制 assets/model_lib.scad 改成 <项目>/model/device.scad，实现 device(...) 接口
python $SKILL/scripts/storyboard.py draft   <项目>          # 分镜草案（含旁白草稿）
python $SKILL/scripts/storyboard.py confirm <项目>          # 确认后放行渲染
python $SKILL/scripts/narration.py tts      <项目> --voice female|male
python $SKILL/scripts/storyboard.py render  <项目>          # 逐段渲染（帧缓存可增量）
python $SKILL/scripts/make_figures.py       <项目>          # 彩色 + 黑白 + 线稿 + 参数表
python $SKILL/scripts/narration.py compose  <项目>          # 字幕 + 分段视频/GIF
python $SKILL/scripts/final_film.py         <项目>          # 片头尾 + 配乐 + 混音
python $SKILL/scripts/make_delivery.py      <项目>
```

## 目录结构

```
patent-3d-demo/
├── SKILL.md              技能主体（触发条件、六阶段、产出、不变量）
├── agents/openai.yaml    UI 元数据
├── references/           提取/建模/分镜/附图/视频/踩坑清单（按需读取）
├── scripts/              13 个可执行脚本
└── assets/
    ├── model_lib.scad    参数化模型骨架
    ├── segments/         8 类段落模板
    └── example_simple/   脱敏示例（可调式护栏支架）+ 期望产出
```

## 自检不变量

脚本会主动断言，而不是把问题留到成片：每句配音 ≤ 其时间槽（防叠音）、
人声高于纯配乐 ≥ 8 dB（防配乐盖人声）、整片 −16 LUFS ±1、STL 流形、
**渲染空白帧检测**、分镜未确认拒绝渲染。

## 示例

`assets/example_simple/` 是一个虚构的「可调式护栏支架」，含模型、分镜与期望产出
（成片、附图、线稿 DXF、自检报告），可用于回归验证与上手参考。

## 说明

- 示例为**脱敏的虚构装置**，仓库不含任何真实专利内容。
- 配乐默认由脚本合成；放入 `音乐/` 目录或 `--music` 指定即可改用自有曲子（会自动做电平归一与闪避）。

## License

MIT
