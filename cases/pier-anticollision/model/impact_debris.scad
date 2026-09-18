// 撞击工况：漂浮物撞击状态
//   漂浮物在铰节点以下撞击，防撞杆绕铰节点反向转动（杆底偏向桥墩、杆顶向外），
//   防撞杆径向内移量较小 → 伸缩杆受压、弹簧反向变形。
$vpt = [0, 0, -2000];
$vpr = [60, 0, 40];
$vpd = 140000;  // 视口预设：打开后按 F5 即定位到模型


include <anticollision_lib.scad>

device(show_membrane = false, theta_deg = 8, pull = 600);
