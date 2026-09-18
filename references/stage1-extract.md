# 阶段① 资料提取（交底书 / 图纸 → 机器可读）

目标：把交底书正文、插图、CAD 图元与文字标注提取成后续可用的文件，**不修改原始文件**。

## 输入形态与处理

| 输入 | 处理 | 脚本 |
|---|---|---|
| `.doc`（Word 97 二进制） | OLE 复合文档 piece table 解析正文 + 扫描内嵌图片 | `extract_doc.py` |
| `.docx` | 用 python-docx 读段落与表格、从 `word/media/` 取图 | 直接读（或先转 Markdown） |
| `.dwg` | AutoCAD COM **只读**遍历（当前打开的图，或 `-DwgPath` 打开后关闭） | `extract_dwg.ps1` |
| `.dxf` | ezdxf 读取；缺 ezdxf 时用内置最小 ASCII 解析器 | `extract_dxf.py` |
| `.pdf` / 图片 | 渲染成 PNG 后逐页判读（线条图需要看图，不能只靠文字） | 目录读取 / 渲染工具 |

## DWG 提取注意

- 脚本只读 COM 属性，**不写回**图纸；若由脚本打开（`-DwgPath`），结束时（含出错）自动 `Close($false)`。
- 提取内容：文档信息/范围/图层、`TEXT`/`MTEXT` 全文及坐标、标注、直线/多段线/圆/弧/块参照几何。
- 图纸通常**没有尺寸标注**（DIM 为 0 条）时，尺寸来自图元坐标本身（单位 mm），
  建筑/桥梁图常见 EXTMAX 达数十万，说明是真实 mm。

## 输出（两种路径格式一致，下游通用）

```
_extract/
├── disclosure.txt      交底书正文（UTF-8）
├── media/              交底书内嵌插图
├── cad_summary.txt     文档信息、图层、图元直方图
├── cad_text.txt        [空间] x,y,z :: 文字
├── cad_dims.txt        标注（若有）
├── cad_entities.csv    [空间] 类型,几何参数
└── views/              render_sketch.py 生成的视图 PNG + index.json
```

## 视图切分

`render_sketch.py` 默认按 X 方向间隙聚类（图纸常把立面/平面/剖面并排），
也可手工指定：`--views "立面:90000,80000,160000,160000;平面:115000,18000,165000,82000"`。
**先看视图图**再决定建模：文字标注给出构件名称，图元给出相对位置与比例。

## 降级链

`DWG → AutoCAD COM` →（无 CAD）`DXF + ezdxf` →（无 DXF）`PDF/图片人工判读`。
任一环节缺失都要在交付说明里写明"哪些尺寸来自读图推断"。
