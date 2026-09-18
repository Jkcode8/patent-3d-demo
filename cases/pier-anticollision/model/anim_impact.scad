// 演示动画 ②：船舶撞击 → 防撞杆绕铰节点转动、套环滑动、弹簧与伸缩杆变形 → 自复位
// 用法：openscad -o frames\im_%04d.png --animate 96 anim_impact.scad
SET_FN = 48;
SET_COIL_SEG = 6;
include <anticollision_lib.scad>

$vpt = [0, 0, -1000];
$vpr = [72, 0, 30];
$vpd = 150000;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));

// 各时间轴节点由渲染脚本按旁白时间轴通过 -D 传入
T_APPROACH = is_undef(T_APPROACH) ? 0.05 : T_APPROACH;
T_LOAD     = is_undef(T_LOAD)     ? 0.15 : T_LOAD;
T_HOLD     = is_undef(T_HOLD)     ? 0.45 : T_HOLD;
T_UNLOAD   = is_undef(T_UNLOAD)   ? 0.60 : T_UNLOAD;
T_END      = is_undef(T_END)      ? 0.85 : T_END;

// 加载段与复位段合成变形相位
load   = smoothstep(($t - T_LOAD) / max(0.01, T_HOLD - T_LOAD));
unload = 1 - smoothstep(($t - T_UNLOAD) / max(0.01, T_END - T_UNLOAD));
phase  = min(load, unload);

// 船舶进退：接近 → 顶推 → 退出
approach = smoothstep(($t - T_APPROACH) / max(0.01, T_LOAD - T_APPROACH));
retreat  = smoothstep(($t - (T_UNLOAD + 0.03)) / max(0.01, T_END - T_UNLOAD - 0.03));
bow_x    = 13100 + 9000 * (1 - approach) + 9000 * retreat - 900 * phase;

module ship() {
    colour = "#8FA3B0";
    L = 32000;   // 船长（船首在 x = 0，船身在 +x 侧）
    W = 13000;   // 船宽
    H = 10000;   // 型深（水面上下各半）
    color(colour) {
        // 船体
        translate([L / 2, 0, -1000]) cube([L, W, H], center = true);
        // 船首楔形
        hull() {
            translate([0, 0, -1000]) cube([1, 3000, H], center = true);
            translate([6000, 0, -1000]) cube([1, W, H], center = true);
        }
        // 上层建筑
        translate([L - 7000, 0, 6000]) cube([9000, 9000, 6000], center = true);
    }
}

translate([bow_x, 0, 0]) ship();
device(show_membrane = false, theta_deg = -12 * phase, pull = 900 * phase);
