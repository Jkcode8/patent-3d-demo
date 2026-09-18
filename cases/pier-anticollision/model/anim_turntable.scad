// 演示动画 ①：整机 360° 转台（外包膜半透明，可见内部张拉整体结构）
// 用法：openscad -o frames\tt_%04d.png --animate 60 anim_turntable.scad
SET_FN = 48;
SET_COIL_SEG = 6;
include <anticollision_lib.scad>

$vpt = [0, 0, -2000];
// 90 帧时 $t 走满 0→1，取 89/90 使首尾帧相差 4°，循环无缝
$vpr = [68, 0, 360 * $t * 89 / 90];
$vpd = 150000;

device();
