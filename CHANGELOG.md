# 更新日志 / Changelog

本文件记录 `patent-3d-demo` 技能的对外可见变化。
版本号同时出现在 `SKILL.md` 的 `metadata.version`，两者由单元测试强制一致。

## [1.4.1] - 2026-10-03

### 修复 Fixed

- **模板烟测的相机默认值被模板自身默认值顶掉**：`check_templates.py` 自己复制了一份
  "把模型内联进模板"的逻辑，漏掉了 `storyboard.instantiate_source()` 的两步处理——
  ① 剥离调用方已提供参数对应的模板保护行，② 带着相机默认值重新实例化。于是
  `seg_adjust` 里的 `VPD = is_undef(VPD) ? 165000 : VPD;` 始终生效，按模型尺寸算出的
  自适应机位进不去，1 m 量级的示例模型被框成一个点、渲染成空白帧，CI 的
  「8 类段落模板烟测（语法 + 真渲染 2 帧）」因此失败（v1.4.0 引入）。现在
  `check_templates.py` 直接复用 `storyboard.instantiate_source()`，烟测校验的就是
  渲染器真正产出的那个文件，规则不再有第二份副本。
- **剖切线稿的 DXF 没有合并件**：v1.2.1 把剖切任务拆成 `_cut` / `_out` 两个 wrapper
  （为绕过 OpenSCAD SVG 导出只保留最后一个 projection 的问题）后，只把 SVG 合并回
  `*_section1.svg`，DXF 仍是一对 `*_section1_cut.dxf` + `*_section1_out.dxf`，
  与 CHANGELOG 写明的"合并回单个 SVG/DXF"以及 v1.1.0 的交付契约（CI 一直断言
  `device_front_section1.dxf` 存在）都不符。新增 `lineart.merge_dxf()`：两个文件同源
  同表头，拼接 ENTITIES 段即得到单个可直接进 AutoCAD 的 DXF；`entry["files"]["dxf"]`
  现在始终指向单文件交付件。
- **`--drawing` 被自动选图重构架空**：v1.4.0 的"多候选图纸自动选优"把每视图的候选
  组装改成 `--drawing-map` → `project.json` 固化 → 自动候选三条来源，却漏掉了
  `--drawing <文件>` 这条路径——解析它的 `fallback` 变量此后无人读取（v1.1.0 里
  是 `drawing_path = Path(drawing) if drawing else fallback`）。于是显式传的图纸只要
  不在 `原始资料/`、`_extract/` 下，就会被当成"没有任何可用图纸（已尝试 0 张）"，
  CI 的「模型与图纸叠合核对」与「负向对照」两步因此失败。新增
  `drawing_specs_for()`（可单测的纯函数）明确优先级：
  `--drawing-map` > `--drawing` > `project.json` > 自动候选。

### 新增 Added

- **回归测试** `CheckTemplatesInstantiationTests`：断言烟测实例化与 storyboard 同规则
  ——相机值真的写进生成文件、模板的大构件默认值被剥离、`include <@MODEL@>;` 已换成内联模型。
- **回归测试** `LineartTests` 新增 DXF 合并用例：合并件只保留一个 `ENTITIES` 段与一个
  `EOF`、断面和外轮廓都在，且无 ENTITIES 段的文件能安全降级。
- **回归测试** `DrawingVerificationTests` 新增选图优先级用例：`--drawing` 必须压过
  `project.json` 固化与自动候选，未提供时依次回落到固化图纸、自动候选（最多 6 张）。

## [1.4.0] - 2026-10-03

### 新增 Added（减人工介入 / 提速）

- **`proposal_compare.py` 参数提案对比**：多组参数 × 桥/坝两状态并排渲染
  `figures/提案对比/提案对比.png`（支持 `--inline` 快速对比与 `proposals.json`），
  发明人一次看多方案选一，减少来回反馈轮数。
- **图纸核对自动选图 + project.json 固化**：`verify_vs_drawing.py` 无 `--drawing-map`
  时自动对多张候选图纸逐一核对取最优（干净 PDF 视图优先）；支持在
  `<项目>/project.json` 的 `verify` 块固化每视图 `drawing`/`defines`/`crop`，
  重跑无需再人工传参。
- **DWG 无实例自动拉起**：`extract_dwg.ps1` 连接不到运行中的 AutoCAD 时自动
  `Start-Process acad.exe` 并等待 COM 注册（约 90s），仍失败才提示降级到 DXF/图片；
  脚本加 BOM 避免 PS5.1 对中文注释的 ANSI 误解析，并输出真实错误信息便于诊断。
- **成片版本号 + 自动备份 + 耗时统计**：`final_film.py` 固定输出 `完整版.mp4`，
  重跑前把上一版自动备份为 `完整版_<skill版本>_<yyyyMMdd_HHmmss>.mp4`，
  `film_report.json` 记录 `skill_version`/`assemble_seconds`/`backup_of_previous`；
  `make_delivery.py` 在 `说明.md` 自动写入「本次成片耗时」与端到端耗时估算。

### 修复 Fixed

- `verify_vs_drawing.py` 此前自动核对只取第一个候选图纸（`candidates[0]`），
  选错图时偏差可达 50%+；现改为多候选择优。
- `proposal_compare.py` 依赖完整 settings（`load_settings`），不再因只传
  `render_size` 触发 `KeyError: scad_fn`。

## [1.3.0] - 2026-10-02

### 新增 Added（建模环节工具链）

- **`model_preview.py` 建模快速预览**：低细分（默认 `$fn=12`）+ 小图（640×480）
  三视图（front/top/front-right-top-iso）秒出，`--watch` 监听模型文件（含同级
  `.scad`）变更自动重渲——改完即看，不用等全量视频渲染。
- **`sketch_to_skeleton.py` 图纸→建模骨架**：读取 stage1 的 `_extract/views.json`，
  把视图标注（撑杆/拉索/面板…）归一化到 0–1 坐标，给出每个部件的出现视图、
  主视图与整体尺寸建议，输出 `model/skeleton.json` + `skeleton.md`——建模的
  模块划分从图纸来，不凭记忆。自动过滤视图标题类标注（`A-A（水坝状态）` 等）。
- **`check_interference.py` 装配干涉检查**：模型 `device()` 支持 `group_only`
  （0=全部 / 1..5=部件组 / 子模块名），脚本按子模块逐一导出 STL 并两两比对
  包围盒重叠，分"高置信干涉（相对>0.35，需修）"与"贴靠/连接（0.05~0.35，人工
  确认）"两档；`river_bottom` 底板自动排除（所有部件都立在它上面，必然重叠）。
- **`param_check.py` 参数变更→尺寸验证**：对 `--param KEY=VALUE` 覆盖前后各构建
  一次模型，对比 STL 包围盒/体积差异并出小图预览；参数没改变任何尺寸会给出
  警告——死参数立刻现形。

### 修复 Fixed（关键渲染正确性）

- **段落参数被模板默认值覆盖（坝态不翻转的根因）**：模板的
  `THETA = is_undef(THETA) ? -10 : THETA;` 默认保护行在参数已前置写入时会被
  OpenSCAD **重复赋值后者胜出**覆盖，且 `is_undef()` 此时返回 true，最终取模板
  默认（实测 `THETA=90; THETA = is_undef(THETA)?-10:THETA;` → -10）。分镜给的
  `THETA=90` 从未生效——load_case/adjust 段一直只是 -10° 微倾、坝态没立起来、
  动画时间轴也用模板默认值。`instantiate_source()` 现在对调用方已提供的每个参数
  剥离模板对应保护行，前置值直达 `device()`。
- **字符串 defines 写入成裸标识符**：`GROUP_ONLY = struts;` 在 OpenSCAD 里是
  未定义变量引用（undef），导致 `check_interference.py` 导出的是整模型而非单
  子模块。字符串值现在带引号写入（`GROUP_ONLY = "struts";`）。

### 文档与约定

- `device()` 接口新增 `group_only` 参数与子模块命名约定（见 SKILL.md / 模型
  模板注释），干涉检查与快速预览均通过同一套前置参数通道。

## [1.2.1] - 2026-10-02

### 修复 Fixed（回归验证补漏）

- **剖切线稿仍是空框**：`lineart.py` 剖切任务把 `projection(cut=true)` 与 `cut=false`
  写进同一个 wrapper，OpenSCAD 的 SVG 导出**只保留最后一个投影**（实测 2026.09），
  断面被外轮廓吞掉。改为剖切任务拆分渲染（`_cut` 断面 / `_out` 外轮廓两个 wrapper），
  再用 `merge_svg()` 合并回单个 SVG/DXF，PNG 叠加两组折线——内部构件断面（端柱、
  梁、撑杆）现在真实可见。
- **`SET_MONO` 渲染仍是彩色**：即便 defines 前置生效、模型 `color()` 已关闭，OpenSCAD
  的 `--colorscheme Tomorrow` 仍会给默认材质上彩色（Monotone 也只是黄棕单色相）。
  现在 `SET_MONO` 渲染统一后置转灰度（PIL `convert("L")`），黑白附图是真正的灰阶图。
- **numpy 残留依赖卡住离线路径**：`make_figures.py` 有无用 `import numpy`
  （附图阶段在无 numpy 机器直接崩）、`make_stub_narration.py` 的占位音频依赖 numpy。
  前者删除，后者改为纯标准库（`array`+`math`）生成音调——离线 stub 不再需要 numpy。

## [1.2.0] - 2026-10-02

### 修复 Fixed（真实项目踩坑）

- **OpenSCAD `-D` 顶层参数失效**：模型常用的 `X = is_undef(SET_X) ? 默认 : SET_X;` 读不到
  `-D` 传值（按文本顺序求值，`is_undef` 时为真，回退值获胜）——`make_figures.py` 的单色图
  （`SET_MONO=1`）因此一直是彩色。新增 `openscad_run.inline_render_source()`：把 defines
  前置写入 wrapper 再渲染，`SET_*`/`colorize` 全部真正生效；彩色/单色附图与段落渲染统一走该路径。
- **OpenSCAD 全局变量前向引用 = undef**：`Brel`（液压杆上铰向量）前向引用后面才赋值的
  `Z_DECK`，导致铰点恒为 undef（曾被宽松处理掩盖）。修复为把 `Z_DECK` 前移到参数区，
  并在模型内注释说明该求值规则。
- **`verify_vs_drawing` 状态不匹配**：图纸显示坝态（立面）而模型默认桥态，首次投影必失败。
  新增 `--view-defines 'front=SET_THETA=90'`（按视角给模型状态参数）与
  `--crop-map 'front=0.05,0.1,0.95,0.85'`（裁掉坐标标注/标题栏干扰；分号分隔视角）。
- **top 线稿空框**：俯视投影被顶/底板盖成只剩外框。`lineart.py` 对 top/bottom 默认自动追加
  水平剖切任务（`--top-section 0` 关闭），输出内部构件断面 + 外轮廓。
- **机构铰点连接无自动检查**：新增 `scripts/check_mechanism.py`——模型导出铰点函数
  （`pivot_A/B/P(theta)` 等），脚本编译一次 wrapper 取 echo，断言点在线段上（`on_segment`）、
  杆长单调（`monotonic`）与长度范围（`length_bounds`），把发明人肉眼核对变成可复跑门禁。
- **依赖自检漏脚本依赖**：`detect_deps()` 原来只查硬编码清单，漏掉 `olefile`（.doc 提取）。
  现用 `ast` 扫描 `scripts/*.py` 的全部第三方 import（`scan_script_imports`），
  `config.py --check` 直接报告"脚本依赖但未安装：X（被 a.py、b.py 引用）"。
- **片头/片尾与内容段高度不一致**：`final_film.py` concat 前逐段 ffprobe 尺寸，
  与目标不一致的 letterbox 统一（`scale + pad`），消除成片高度跳变。
- **`final_film.py` numpy 缺失时崩在晦涩 traceback**：改为 import 时捕获，
  启动即给 `pip install numpy` 明确指引。

### 新增 Added

- `storyboard.py render --fast`：低分辨率 + 低细分粗剪（`fast_render_size`/`fast_scad_fn`），
  先看镜头方向再全量渲染；粗剪指纹独立，不污染正式帧缓存。
- `storyboard.py render --jobs N`：多段并行渲染（每段一个 OpenSCAD 子进程，多核提速）。
- `storyboard.py confirm --auto`：校验通过即自动确认，支持无人值守全自动流程。
- 特写视角 `front-right-top-iso-close`（同机位 2× 放大）；`draft` 默认列入彩色附图，
  用于展示液压杆等机构细节。
- 单元测试扩充至 54 个：`view-defines`/`crop-map` 解析与裁剪、`check_mechanism` 断言逻辑、
  `fast_settings`、`build_jobs`（top 自动剖切）、import 扫描、close 视角、inline defines。

### 变更 Changed

- `verify_vs_drawing.py`：`--crop-map` 条目用分号分隔（裁剪框本身含逗号）。
- `lineart.py`：任务构建提纯为 `build_jobs()`，可单测。
- `config.py`：`detect_deps()` 返回值新增 `script_imports`/`missing_imports` 字段；
  `DEFAULTS` 新增 `fast_render_size`/`fast_scad_fn`。
- 模型约定补充：OpenSCAD 全局变量**按文本顺序求值**，前向引用是 undef——参数区常量
  需放在使用之前（`references/troubleshooting.md` 已记录）。

## [1.1.0] - 2026-09-18

### 新增 Added

- `scripts/verify_vs_drawing.py`：把模型正投影与原始 CAD 图（DXF / SVG / PNG / JPG）按
  包围盒归一化后叠合比对，输出三栏比对图（原图 | 模型投影 | 叠加）与量化报告
  （长宽比偏差、覆盖率、IoU）。用于建模阶段的自检——模型比例画错时能立刻看出来，
  不依赖人眼盯两张图。
- `tests/`：纯函数单元测试（`python -m unittest discover -s tests -t .`），
  覆盖旁白规范化、声线选择、分镜选段与门禁、帧缓存指纹、机构求解、SVG/DXF 线稿解析、
  STL 流形、空白帧判定、版本号一致性。不依赖 OpenSCAD / ffmpeg，秒级可跑。
- `CHANGELOG.md`（本文件）。
- `.gitattributes`：仓库内统一 LF，消除 Windows 上每次提交的 CRLF 警告；
  GIF/PNG/MP4/DXF 等按类型区分处理。
- CI：`regression` 工作流新增单元测试步骤与 `verify_vs_drawing` 自检步骤。

### 变更 Changed

- `narration.py`：时间轴槽位计算抽成纯函数 `cue_slots()`，行为不变但可被单测覆盖
  （不叠音、起点递增、尾部留白）。
- `lineart.py`、`storyboard.py` 等脚本导出的辅助函数被 `verify_vs_drawing.py` 复用，
  未改动既有 CLI 行为。

### 说明 Notes

- `verify_vs_drawing.py` 做的是**比例与轮廓**核对：它按包围盒归一化后比对，因此
  能发现比例失真、构件缺失/多余，但不能替代带尺寸标注的人工核对（图纸的绝对比例
  与标注数值仍需人工确认）。报告 JSON 里带 `caveat` 字段说明这一点。

## [1.0.0] - 2026-09-18

### 新增 Added

- 六阶段流程：资料提取 → 三维建模 → 分镜草案（确认门禁）→ 渲染与附图 → 配音成片 → 交付说明。
- 8 类段落模板：`turntable` / `explode` / `assembly` / `load_case` / `section` /
  `adjust` / `param_sweep` / `comparison`。
- 脚本：`config` / `extract_doc` / `extract_docx` / `extract_dwg.ps1` / `extract_dxf` /
  `render_sketch` / `openscad_run` / `storyboard` / `lineart` / `make_figures` /
  `narration` / `final_film` / `make_delivery` / `check_kinematics` / 自检脚本若干。
- 帧缓存指纹、未确认分镜拒绝渲染、人声高于配乐 ≥8 dB、−16 LUFS、STL 流形、
  空白帧检测等自检不变量。
- 中英双语 README、GitHub Actions（`regression` + `full-pipeline`）、
  真实案例 `cases/pier-anticollision/`。

[1.4.1]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.4.1
[1.2.0]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.2.0
[1.1.0]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.1.0
[1.0.0]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.0.0
