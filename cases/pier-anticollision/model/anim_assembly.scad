// 演示动画 ③：装配顺序（浮箱 → 防撞套筒+万向滚珠 → 张拉整体模块 → 弹力索张拉 → 外包柔性膜）
// 用法：openscad -o frames\as_%04d.png --animate 60 anim_assembly.scad
SET_FN = 48;
SET_COIL_SEG = 6;
include <anticollision_lib.scad>

$vpt = [0, 0, -2000];
$vpr = [62, 0, 25 + 25 * $t];   // 缓慢环视
$vpd = 150000;

A1 = is_undef(A1) ? 0.20 : A1;
A2 = is_undef(A2) ? 0.40 : A2;
A3 = is_undef(A3) ? 0.55 : A3;
A4 = is_undef(A4) ? 0.75 : A4;

step = $t < A1 ? 1 : ($t < A2 ? 2 : ($t < A3 ? 3 : ($t < A4 ? 4 : 5)));

assembly_stage(step);
