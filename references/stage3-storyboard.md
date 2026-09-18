# 阶段③ 分镜（选段规则 + 契约 + 确认门禁）

## 选段规则表（草案依据，不是硬约束）

| 交底书/图纸里的内容 | 推荐段落 | 说明 |
|---|---|---|
| 系统组成、技术方案、模块清单 | `explode` + `turntable` | 先看整体，再看分解 |
| 系统原理、工作过程、受力/运动 | `load_case` | 需要用机构解算驱动变形 |
| 施工方法、安装步骤 | `assembly` | 步序与交底书章节一致 |
| 可调/自适应特征（水位、角度、张紧、间隙） | `adjust` | 展示调节范围与极限位 |
| 多规格、尺寸系列 | `param_sweep` | 平滑扫描参数，直观显示差异 |
| 有益效果、与现有技术对比 | `comparison` | 需要对照模型，缺失则跳过并注明 |
| 立面/平面/剖面视图 | **附图**（不做视频段） | 正投影线稿更适合表达尺寸关系 |

段落数量建议 3~6 段，每段 12~25 s，整片 60~150 s。片头 6 s 左右，片尾 6~10 s
（片尾列 3~4 条核心优势最有效）。

## 分镜契约 `storyboard.json`

```json
{
  "title": "一种……装置", "subtitle": "三维演示动画", "keywords": "…",
  "confirmed": false, "voice": "female",
  "intro": { "lines": ["……，三维演示。"] },
  "outro": { "lines": ["优势1", "优势2", "优势3"] },
  "segments": [{
    "id": "load_case", "type": "load_case", "enabled": true,
    "purpose": "受力变形", "template": "seg_load_case.scad",
    "model": "model/device.scad",
    "defines": { "THETA": "-12", "PULL": "900" },
    "camera": {}, "narration": ["…", "…"], "duration_hint": 16
  }]
}
```

- `type` 必须是 8 类之一（或 `custom`，需自备模板）；`narration` 决定时长与字幕。
- `defines` 是传给模板的 `-D` 参数；模板会按旁白时间轴自动填 `T_*`。
- 渲染后 `storyboard.py` 会把 `timeline`（starts/ends/frames）写回每段，便于核对。

## 旁白写法

- 每段 2~4 句，每句 15~35 字；第一句点题，第二句讲机理，第三句讲效果。
- 一句话只讲一件事；术语与交底书保持一致（"撑杆"就别写成"支撑杆"）。
- 时间轴节点由旁白时长自动推导，因此**先写旁白再定动画**：
  "说到撞击时画面正好开始变形"就是靠 `T_LOAD = 第二句开始时刻 / 总时长` 实现的。

## 确认门禁

1. `storyboard.py draft` 生成草案（含选段依据的原文摘录）与人读版 `分镜.md`；
2. **与用户确认**段落、顺序、旁白（这一步必须做，渲染最耗时）；
3. `storyboard.py confirm` 写入 `confirmed: true`；
4. `storyboard.py render` 只渲染启用段落，帧缓存按 `video/frames/<id>/` 分目录，
   增删段落只重渲受影响部分。
