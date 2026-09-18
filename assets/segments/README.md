# 段落模板（8 类）

每个模板都是**很薄的驱动器**：用 `$t`（动画相位）与 `-D` 时间轴参数调用 `device(...)`。
模板里的 `include "@MODEL@"` 是占位符——`storyboard.py render` 会把模板实例化到
`<project>/video/segments/<id>.scad`，把 `@MODEL@`（以及对比段的 `@MODEL_B@`）
替换成真实的绝对路径后再渲染（OpenSCAD 的 `include` 只接受字面量路径，不能用变量）。

通用约定：

| 约定 | 说明 |
|---|---|
| `$t` | OpenSCAD 动画相位 0→1（`--animate N`） |
| `@MODEL@` | 由 `storyboard.py render` 替换为项目模型绝对路径 |
| `T_*` | 时间轴节点（0~1），由 `narration.py` 按旁白时间轴算出后通过 `-D` 传入 |
| `SET_FN` / `SET_COIL_SEG` | 精度覆盖，配置层默认 48 / 6 |

| 模板 | 用途 | 关键 `-D` 参数 |
|---|---|---|
| `seg_turntable.scad` | 整体旋转展示 | `TURNS`（转几圈，默认 1） |
| `seg_explode.scad` | 爆炸/组成分解 | `EXPLODE_MM`、`T_OPEN`、`T_HOLD`、`T_CLOSE` |
| `seg_assembly.scad` | 装配顺序（分步） | `A1..An`（各步切换时刻，0~1） |
| `seg_load_case.scad` | 工况变形（加载—保持—复位） | `T_LOAD`、`T_HOLD`、`T_UNLOAD`、`T_END`、`THETA`、`PULL` |
| `seg_section.scad` | 剖切/局部剖 | 无（固定半剖），可加 `TURNS` |
| `seg_adjust.scad` | 调节/自适应动作 | `T_RISE`、`T_TOP`、`T_FALL`、`T_DOWN`、`Z_LOW`、`Z_HIGH` |
| `seg_param_sweep.scad` | 参数变化对比（平滑扫描 `V1`→`V2`） | `V1`、`V2`（映射到模型里用 `SET_*` 暴露的参数） |
| `seg_comparison.scad` | 与现有技术对比（左对照 / 右本发明） | `@MODEL_B@`（对照模型路径）、`SEP`（并排间距） |
