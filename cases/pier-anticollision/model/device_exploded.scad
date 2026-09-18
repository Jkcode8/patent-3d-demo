// 爆炸图：各部件沿竖向分离（浮箱 → 套筒/万向滚珠 → 防撞模块 → 弹力索 → 外包膜）
$vpt = [0, 0, 5000];
$vpr = [60, 0, 40];
$vpd = 200000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

device(show_pier = false, explode = 10000);
