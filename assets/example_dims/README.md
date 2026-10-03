# example_dims —— 尺寸核对夹具

给 `scripts/dim_check.py` 用的最小项目：`原始资料/drawing.dxf` 上的五个标注
（400 / 300 / %%c80 / 900 / 600）与 `model/device.scad` 的参数一一对应。
（`%%c` 是 DXF 里直径符号的标准写法，纯 ASCII，免得 R12 格式的编码歧义。）

```bash
python scripts/dim_check.py assets/example_dims --strict   # 应通过
python scripts/dim_check.py assets/example_dims --json
```

DXF 是手写的最小 ASCII 结构（HEADER / TABLES / BLOCKS / ENTITIES），
与 OpenSCAD 导出的线稿同格式，所以 `extract_dxf` 的两条读取路径
（ezdxf 与无依赖 ASCII 解析器）都能读。

为什么要单独做这条回归：`verify_vs_drawing.py` 把模型投影和图纸都按包围盒
归一化后比对，**两个数字差十倍也照样满分**——它只看形状。数值是否写对，
只能靠 `dim_check.py` 这类逐值比对来兜。
