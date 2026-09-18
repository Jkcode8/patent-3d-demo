---
name: patent-3d-demo
description: "把专利交底书与 CAD 图纸做成参数化三维模型、彩色/黑白附图与配音演示视频：图纸提取→三维建模→分镜（确认后渲染）→渲染出图→配音成片。| Patent 3D model, figures and narrated demo video pipeline."
license: MIT
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
metadata:
  version: "1.1.0"
  short-description: "专利交底书/图纸 → 三维模型 + 附图 + 配音演示视频"
  argument-hint: "[项目目录，默认当前目录；或直接给交底书/图纸路径]"
  user-invocable: true
---

# 专利三维演示（建模 → 附图 → 配音视频）

覆盖 **资料提取 → 三维建模 → 分镜 → 渲染附图 → 配音成片 → 交付说明** 全流程。
视频结构**不固定**：技能从交底书/图纸推导分镜草案，**确认后才渲染**；固化的是
8 类段落模板、选段规则与分镜契约。

脚本只依赖 OpenSCAD / ffmpeg / Python 库等通用工具，**不绑定某个智能体运行时**：
Codex、Claude Code 或其他支持 skills 的智能体都可直接使用（`agents/openai.yaml` 仅为 Codex 的 UI 元数据）。

## 触发条件

- 斜杠：`/专利三维演示`
- 关键词：`专利三维模型`、`三维演示视频`、`交底书三维图`、`把图纸做成三维`、
  `建个三维模型`（当上下文是专利/交底书/图纸时）

**与 `patent-disclosure-skill` 的分工**：那个技能负责专利点挖掘、查新与交底书文本；
本技能负责三维建模、附图与演示视频。两者可串联：交底书定稿 → 本技能出图与视频。

## Step 0 依赖自检（必做）

```bash
python <SKILL>/scripts/config.py --check        # 人类可读
python <SKILL>/scripts/config.py --check --json # 机器可读
```

`OpenSCAD` 是**硬依赖**（缺失即停止并给出安装指引）；其余按此降级，不阻塞：

| 缺失 | 降级 |
|---|---|
| ffmpeg | 只出动画 GIF，不出 MP4/配乐（提示用户安装） |
| edge-tts 或断网 | 改用 Windows SAPI 中文语音（离线） |
| AutoCAD COM | DWG 走 `extract_dxf.py`（需先另存 DXF），或按 PDF/图片判读 |
| numpy / Pillow / ezdxf | 分别降级：无配乐合成 / 无字幕与片头尾 / 无 DXF 解析 |

## 六阶段流程

```bash
SKILL=~/.codex/skills/patent-3d-demo

# ① 建项目骨架（原始资料/ _extract/ model/ figures/ video/ + storyboard.json）
python $SKILL/scripts/config.py init-project <项目目录>
#    把交底书、DWG/DXF、PDF 放进 <项目目录>/原始资料/

# ② 提取资料
python $SKILL/scripts/extract_doc.py <交底书.doc> <项目>/_extract     # .doc（OLE2）
powershell -File $SKILL/scripts/extract_dwg.ps1 -OutDir <项目>/_extract [-DwgPath <图.dwg>]
python $SKILL/scripts/extract_dxf.py <图.dxf> <项目>/_extract          # 无 CAD 时
python $SKILL/scripts/render_sketch.py <项目>/_extract                # 图元 → 视图 PNG

# ③ 建模（复制骨架改写，见 references/stage2-model.md）
#    产物：<项目>/model/device.scad（必须实现 device(theta,pull,water_z,step,explode,section)）
python $SKILL/scripts/openscad_run.py --project <项目> --model model/device.scad \
       --out-dir figures --angles front,top,front-right-top-iso --build-stl --json
#    建模自检：把模型正投影叠到原始图纸上核对比例/轮廓（强烈建议）
python $SKILL/scripts/verify_vs_drawing.py --project <项目> --views front,top
#    图纸在 原始资料/ 里会自动挑选；也可 --drawing 立面.dxf / --drawing-map front=…,top=…

# ④ 分镜草案 → 用户确认（门禁，未确认不得渲染）
python $SKILL/scripts/storyboard.py draft   <项目>     # → storyboard.json + 分镜.md
python $SKILL/scripts/storyboard.py check   <项目>     # 校验 + 列出将渲染的段落
python $SKILL/scripts/storyboard.py confirm <项目>     # 确认后才放行

# ⑤ 渲染与出图
python $SKILL/scripts/narration.py tts   <项目> [--voice female|male]   # 时间轴
python $SKILL/scripts/storyboard.py render <项目>                       # 逐段渲染帧
python $SKILL/scripts/lineart.py --model <项目>/model/device.scad \
       --out-dir <项目>/figures/黑白附图 --views front,top,side --formats svg,dxf,png
python $SKILL/scripts/make_figures.py    <项目>                         # 彩色/黑白附图合成

# ⑥ 成片与交付
python $SKILL/scripts/narration.py compose <项目>          # 字幕 + 分段 MP4/GIF
python $SKILL/scripts/final_film.py  <项目> [--music <曲子>|--no-music]  # 片头尾+配乐+混音
python $SKILL/scripts/make_delivery.py <项目>              # 说明.md + 交付清单
```

## 可选增强

| 需求 | 用法 |
|---|---|
| 英文/多语种配音 | `narration.py tts <项目> --language en-US`（声线自动切 `en-US-*`；字幕仍用原文） |
| 数字与单位读法规范化 | 默认开启：`φ1500`→"直径1500"、`1.5m`→"1.5米"、`16+16+17度`→"16度、16度、17度"、`−2.26m`→"负2.26米"（只改送去合成的文本，字幕不变） |
| 剖切轮廓线稿 | `lineart.py … --sections 2`（按模型高度均分切割，含外轮廓 + 剖切轮廓） |
| 爆炸状态线稿 | `lineart.py … --exploded <分离量>` |
| 图题与尺寸线 | `lineart.py` 默认给 PNG 加图题与总宽/总高标注（单位与模型一致） |
| 模板烟测 | `check_templates.py <项目> --frames 2 --render adjust`（8 类模板逐个实例化 + 语法/渲染） |
| 离线成片（无 TTS 环境） | `make_stub_narration.py <项目>` 生成占位旁白，再走 compose/final_film |
| 技能结构自检 | `check_skill_md.py .`（frontmatter 只允许 name/description/license/allowed-tools/metadata） |
| **模型↔图纸核对** | `verify_vs_drawing.py --project <项目> [--drawing 图.dxf] [--views front,top]` → 三栏比对图（原图｜模型投影｜叠加）+ `核对报告.json`（长宽比偏差 / 覆盖率 / IoU） |
| 参数扫描/剖切线稿 | `lineart.py … --define SET_XXX=值`（参数已能真正生效，见 references/troubleshooting.md） |
| **纯函数单元测试** | `python -m unittest discover -s tests -t .`（秒级；不需要 OpenSCAD/ffmpeg） |

**帧缓存**：`storyboard.py render` 把"实例化后的段落文件 + `-D` 参数 + 渲染设置"做哈希存入
`video/frames/<id>/_cache.json`；模型或参数一变即重渲，避免复用旧帧（此前只比对帧数）。

## 8 类段落模板（`assets/segments/`）

| 类型 | 用途 | 关键 `-D` |
|---|---|---|
| `turntable` | 整体旋转展示 | `TURNS` |
| `explode` | 爆炸/组成分解 | `EXPLODE_MM`、`T_OPEN/T_HOLD/T_CLOSE` |
| `assembly` | 装配顺序 | `A1..A5`（各步切换时刻） |
| `load_case` | 工况变形 | `THETA`、`PULL`、`T_LOAD/T_HOLD/T_UNLOAD/T_END` |
| `section` | 剖切展示 | `TURNS` |
| `adjust` | 调节/自适应 | `Z_LOW`、`Z_HIGH`、`T_RISE/T_TOP/T_FALL/T_DOWN` |
| `param_sweep` | 参数变化对比 | `V1`、`V2`（映射到模型 `SET_*` 参数） |
| `comparison` | 与现有技术对比 | `@MODEL_B@`（对照模型）、`SEP` |

**选段规则**（草案依据，非硬约束）见 `references/stage3-storyboard.md`：组成→`explode`、
原理/工况→`load_case`、施工方法→`assembly`、可调/自适应→`adjust`、尺寸系列→`param_sweep`、
有益效果对比→`comparison`、图纸立/平/剖→并入**附图**（不占视频段落）。

## 标准产出（每次交付）

```
<项目>/
├── model/device.scad(+ 派生段落的 .scad)   参数化源码
├── model/*.stl                             几何（流形校验通过）
├── figures/彩色附图/、黑白附图/（单色立体图 + 正投影线稿 SVG/DXF/PNG）
├── video/带配音版/、仅画面版/、GIF/、完整版.mp4、film_report.json
├── storyboard.json + 分镜.md               分镜契约与确认记录
└── 说明.md                                 参数来源、假设清单、复现命令
```

## 脚本不变量（脚本自动断言，失败即报错）

- 每句配音时长 ≤ 其时间槽（防叠音）——时间轴由 TTS 实际时长生成，换声线用 `voice_fit.py` 对齐；
- 成片中**人声高于纯配乐 ≥ 8 dB**（`final_film.py` 实测并写入 `film_report.json`）；
- 整片响度 −16 LUFS ±1 LU；STL 流形；渲染图非空且角度齐全；
- `storyboard.json` 中每段的 `type` 都有对应模板；**未确认分镜拒绝渲染**；
- 模型正投影与原图的长宽比偏差 ≤ 6%、轮廓覆盖率 ≥ 60%（`verify_vs_drawing.py`，阈值可调）；
- `SKILL.md` / `CHANGELOG.md` / `config.VERSION` 三处版本号一致（单元测试断言）。

## 参考文档（按需 Read）

| 文件 | 内容 |
|---|---|
| `references/stage1-extract.md` | 交底书/DWG/DXF/PDF 提取与降级链、编码坑 |
| `references/stage2-model.md` | 二维图→三维结构、参数取值与来源标注、`device()` 接口约定、机构运动学校验 |
| `references/stage3-storyboard.md` | 选段规则表、旁白写法、时长控制、分镜契约字段 |
| `references/stage4-figures.md` | 视角与构图、彩色/黑白、线稿与 CAD 协作、参数表与图例 |
| `references/stage5-video.md` | 时间轴对齐、字幕与片头尾、配乐与 ducking、编码与验收 |
| `references/troubleshooting.md` | 已踩过的坑（必读，能省数小时） |

## 示例

`assets/example_simple/` 是一个脱敏的「可调式护栏支架」示例，含模型、分镜与期望产出，
可用于回归验证：

```bash
python $SKILL/scripts/config.py init-project /tmp/demo
cp -r $SKILL/assets/example_simple/* /tmp/demo/
python $SKILL/scripts/storyboard.py check  /tmp/demo
python $SKILL/scripts/narration.py tts     /tmp/demo --voice female
python $SKILL/scripts/storyboard.py render /tmp/demo
python $SKILL/scripts/narration.py compose /tmp/demo
python $SKILL/scripts/final_film.py        /tmp/demo
python -m unittest discover -s tests -t .  # 纯函数单元测试（不用 OpenSCAD/ffmpeg）
```
