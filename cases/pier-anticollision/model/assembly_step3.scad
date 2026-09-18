// 装配顺序 ③：张拉整体防撞模块组装（撑杆、弹簧、防撞杆、伸缩杆、套环）
$vpt = [0, 0, -2000];
$vpr = [60, 0, 40];
$vpd = 140000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

assembly_stage(3);
