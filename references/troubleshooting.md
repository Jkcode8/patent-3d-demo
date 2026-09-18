# 已踩过的坑（按症状查）

这些坑都真实发生过，每条都给了判据与修法。

## 人声消失 / 只有配乐

- 症状：视频里只有音乐，听不到旁白；把音量开到最大也没用。
- 判据：混音结果的电平**恰好等于纯音乐**（句间空档与"说话段"电平几乎相同，甚至说话段更低）。
- 原因：ffmpeg 滤镜链里旁白同时接到**侧链**和**混音**两处，未 `asplit` 时第二路连接被静默丢弃。
- 修法：`[nar]asplit=2[nar_sc][nar_mix];` 再分别接 `sidechaincompress` 与 `amix`
  （见 `final_film.py: mix()`）。

## 配音"重复"（像两个人同时说话）

- 症状：某些句子结尾叠着下一句的开头。
- 判据：逐句量时长，**实际时长 > 槽位时长**。
- 原因：把语音对齐到既有时间轴时 `atempo` 比例写反。`atempo=X` 是"加快 X 倍"，
  比例应为 `自然时长 ÷ 目标时长`（不是反过来）。
- 修法：比例取自然/目标，输出再 `-t <槽位>` 裁剪并加 40 ms 淡出（见 `voice_fit.py`）。

## 全屏只有一个点 / 模型很小

- 症状：渲染出来几乎空白，模型只占几个像素。
- 原因：模板里 `$vpd`（机位距离）是按大型构件给的默认值，小模型（几百 mm）会缩成一点。
- 修法：按包围盒自适应：`$vpd ≈ 3.1 × 最大尺寸`，`$vpt` 取包围盒中心
  （`storyboard.py render` 已自动计算并注入）。

## `include "C:/..."` 解析失败

- 症状：`Parser error: syntax error in file , line N`，文件名是空的。
- 原因：OpenSCAD 的 `include "…"` 遇到**盘符冒号**会解析异常。
- 修法：改用尖括号 `include <C:/path/model.scad>;`（本技能的段落实例化已按此生成）。

## 渲染颜色全黄（改了 Color 不生效）

- 原因：渲染的是 STL（STL 不含颜色），或没写 `color()`。
- 修法：渲染 **.scad 源码**而非 STL；`color()` 只在 `--render` 下保留（本技能默认如此）。
  需要纯色黑白图时设 `SET_MONO=true`。

## 8 个机位渲染出来一模一样

- 原因：源文件里写了 `$vpt/$vpr/$vpd`，OpenSCAD 会**优先用它们并禁用 `--viewall`**。
- 修法：静帧渲染前把视口预设剥离（`openscad_run.render_source()` 已自动处理）；
  而**动画**要保留预设、且不能传 `--autocenter/--viewall`（否则每帧取景会抖）。

## 剖切面丢颜色 / 变成奇怪的颜色

- 原因：布尔运算新生成的面取"切割体"的颜色，切割体未着色时取默认色。
- 修法：把切割体显式着色（本技能用浅灰 `#D2D2D2`，符合制图习惯）。

## STL 被判为非流形（但实际没问题）

- 原因：OpenSCAD 默认导出**ASCII STL**，手写解析器遇到 `1.5e-07` 这类科学计数法会漏顶点。
- 修法：用 `scripts/stl_parser.py`（已含完整 ASCII/二进制解析，别自己写）。

## subprocess 捕获输出报 `UnicodeDecodeError`，`stderr` 变成 `None`

- 原因：Windows 下 Python 用系统 GBK 解码 ffmpeg/OpenSCAD 的 UTF-8 输出，读线程崩溃。
- 修法：`subprocess.run(..., capture_output=True, encoding="utf-8", errors="replace")`，
  **不要**用 `text=True`。

## git clone 卡死（fetch 库/子模块时）

- 原因：全局 git 配了失效代理（如 `http.proxy=127.0.0.1:7890` 而代理没开）。
- 修法：库下载改走 HTTPS tarball（本技能的示例不依赖 git）；若必须 clone，
  先 `git config --global --unset http.proxy https.proxy` 或用 `GIT_TERMINAL_PROMPT=0` + 超时。

## 文件名带全角括号导致 ffmpeg 报 `Illegal byte sequence`

- 修法：产物文件名避免 `（）`、`＋` 等全角符号；用下划线。

## 字幕断行难看（行首出现「、」「，」）

- 修法：断行优先在标点处（`narration.py: wrap_text` 已实现，标点处断行无惩罚）。
