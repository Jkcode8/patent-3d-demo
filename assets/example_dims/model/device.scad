/* 尺寸核对夹具（脱敏）：参数值与 原始资料/drawing.dxf 上的标注一一对应。

   用途：`python scripts/dim_check.py assets/example_dims --strict`
   —— 图纸标注 ↔ 模型参数 的数值回归。真图纸带尺寸标注的很少能进 CI，
   所以这里用一份最小但结构合法的 DXF 把这条链路钉住。
   =================================================================== */
BASE_L = 400;                                       // 来源：图纸 400
BASE_W = 300;                                       // 来源：图纸 300
POST_D = is_undef(SET_POST_D) ? 80 : SET_POST_D;    // 来源：图纸 φ80
POST_H = 900;                                       // 来源：图纸 900
ARM_L  = 600;                                       // 来源：图纸 600

module device() {
    cube([BASE_L, BASE_W, POST_H]);
}

device();
