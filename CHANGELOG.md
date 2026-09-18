# 更新日志 / Changelog

本文件记录 `patent-3d-demo` 技能的对外可见变化。
版本号同时出现在 `SKILL.md` 的 `metadata.version`，两者由单元测试强制一致。

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

[1.1.0]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.1.0
[1.0.0]: https://github.com/Jkcode8/patent-3d-demo/releases/tag/v1.0.0
