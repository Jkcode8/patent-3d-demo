// 撞击工况局部放大：漂浮物撞击状态
$vpt = [9500, 0, -500];
$vpr = [90, 0, 0];
$vpd = 52000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

intersection() {
    device(show_membrane = false, theta_deg = 8, pull = 600);
    translate([5000, -4500, -9500]) cube([11500, 9000, 21000]);
}
