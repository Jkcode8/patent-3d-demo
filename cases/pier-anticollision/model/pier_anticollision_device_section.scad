// 半剖模型：切掉 y<0 部分，显示防撞套筒、万向滚珠与浮箱内部构造
$vpt = [0, 0, -2000];
$vpr = [70, 0, -130];
$vpd = 130000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

device_section();
