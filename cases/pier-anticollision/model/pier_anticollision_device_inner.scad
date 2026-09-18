// 内部结构模型：去掉外包柔性膜，显示张拉整体支撑模块
$vpt = [0, 0, -2000];
$vpr = [60, 0, 40];
$vpd = 140000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

device(show_membrane = false);
