// 演示动画 ④：浮箱调节水位 —— 装置沿防撞套筒升降，保持与水面相适应的防护标高
// 时间轴节点由渲染脚本按旁白时间轴通过 -D 传入
SET_FN = 48;
SET_COIL_SEG = 6;
include <anticollision_lib.scad>

$vpt = [0, 0, 0];
$vpr = [70, 0, 35];
$vpd = 160000;

W_LOW  = -6000;    // 枯水位标高
W_HIGH = 8000;     // 洪水位标高

T_RISE = is_undef(T_RISE) ? 0.05 : T_RISE;
T_TOP  = is_undef(T_TOP)  ? 0.35 : T_TOP;
T_FALL = is_undef(T_FALL) ? 0.55 : T_FALL;
T_DOWN = is_undef(T_DOWN) ? 0.78 : T_DOWN;
T_SINK = is_undef(T_SINK) ? 0.85 : T_SINK;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));

rise = smoothstep(($t - T_RISE) / max(0.01, T_TOP - T_RISE));
fall = smoothstep(($t - T_FALL) / max(0.01, T_DOWN - T_FALL));

water_z = W_LOW + (W_HIGH - W_LOW) * (rise - fall);

// 检修充水：浮箱注水后装置相对水面下沉
sink     = smoothstep(($t - T_SINK) / 0.15);
device_z = water_z - 3500 * sink;

// 水面：用同心圆环表示水面（避免大面积透明面带来的渲染条纹，同时能看清水下结构）
for (r0 = [5200, 12000, 20000, 29000]) {
    color("#4FA3C7", r0 < 13000 ? 0.75 : 0.5) {
        $fn = 128;
        ring_band(r0, r0 + 1200, 40, water_z);
    }
}

pier();
translate([0, 0, device_z]) device(show_pier = false, show_membrane = true);
