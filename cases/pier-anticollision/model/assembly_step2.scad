// 装配顺序 ②：防撞套筒（含万向滚珠滑移机构）安装
$vpt = [0, 0, -2000];
$vpr = [60, 0, 40];
$vpd = 140000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

assembly_stage(2);
