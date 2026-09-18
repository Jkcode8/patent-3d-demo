// 段落模板：调节/自适应动作（升 → 保持 → 降 → 检修位）
// 可驱动两类被调量：高度/水位 water_z，以及角度 theta（如可旋转构件的转角调节）
// -D Z_LOW=-6000 -D Z_HIGH=8000 -D THETA_FROM=0 -D THETA_TO=49
// -D T_RISE=0.05 -D T_TOP=0.40 -D T_FALL=0.60 -D T_DOWN=0.80
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
Z_LOW  = is_undef(Z_LOW) ? -6000 : Z_LOW;
Z_HIGH = is_undef(Z_HIGH) ? 8000 : Z_HIGH;
T_RISE = is_undef(T_RISE) ? 0.05 : T_RISE;
T_TOP  = is_undef(T_TOP)  ? 0.40 : T_TOP;
T_FALL = is_undef(T_FALL) ? 0.60 : T_FALL;
T_DOWN = is_undef(T_DOWN) ? 0.80 : T_DOWN;
T_SINK = is_undef(T_SINK) ? 0.88 : T_SINK;
THETA_FROM = is_undef(THETA_FROM) ? 0 : THETA_FROM;
THETA_TO   = is_undef(THETA_TO)   ? 0 : THETA_TO;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 165000 : VPD;

include <@MODEL@>;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));
rise = smoothstep(($t - T_RISE) / max(0.01, T_TOP - T_RISE));
fall = smoothstep(($t - T_FALL) / max(0.01, T_DOWN - T_FALL));
sink = smoothstep(($t - T_SINK) / 0.10);
progress = rise - fall;
level = Z_LOW + (Z_HIGH - Z_LOW) * progress - 3500 * sink;
angle = THETA_FROM + (THETA_TO - THETA_FROM) * progress;

$vpt = [0, 0, VPT_Z];
$vpr = [70, 0, 35];
$vpd = VPD;

device(theta = angle, water_z = level);
