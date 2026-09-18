// 演示动画 ③：漂浮物撞击工况（撞击点位于铰节点以下，防撞杆反向转动）
// 时间轴节点由渲染脚本按旁白时间轴通过 -D 传入
SET_FN = 48;
SET_COIL_SEG = 6;
include <anticollision_lib.scad>

$vpt = [0, 0, -3000];
$vpr = [76, 0, 30];
$vpd = 145000;

T_APPROACH = is_undef(T_APPROACH) ? 0.05 : T_APPROACH;
T_LOAD     = is_undef(T_LOAD)     ? 0.20 : T_LOAD;
T_HOLD     = is_undef(T_HOLD)     ? 0.50 : T_HOLD;
T_UNLOAD   = is_undef(T_UNLOAD)   ? 0.65 : T_UNLOAD;
T_END      = is_undef(T_END)      ? 0.90 : T_END;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));

load   = smoothstep(($t - T_LOAD) / max(0.01, T_HOLD - T_LOAD));
unload = 1 - smoothstep(($t - T_UNLOAD) / max(0.01, T_END - T_UNLOAD));
phase  = min(load, unload);

approach = smoothstep(($t - T_APPROACH) / max(0.01, T_LOAD - T_APPROACH));
retreat  = smoothstep(($t - (T_UNLOAD + 0.03)) / max(0.01, T_END - T_UNLOAD - 0.03));
f_x      = 13100 + 11000 * (1 - approach) + 11000 * retreat - 600 * phase;

// 漂浮物：水面附近的块状漂浮体
module debris() {
    color("#B5651D") {
        translate([-1500, 0, -3200]) cube([3000, 3000, 2400], center = true);
        translate([-1500, 0, -1800]) cube([2200, 2200, 500], center = true);
    }
}

translate([f_x, 0, 0]) debris();
device(show_membrane = false, theta_deg = 8 * phase, pull = 600 * phase);
