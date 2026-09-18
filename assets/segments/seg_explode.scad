// 段落模板：爆炸/组成分解（分离 → 保持 → 复位）
// -D MODEL=... -D EXPLODE_MM=12000 -D T_OPEN=0.15 -D T_HOLD=0.75 -D T_CLOSE=0.95
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
EXPLODE_MM = is_undef(EXPLODE_MM) ? 12000 : EXPLODE_MM;
T_OPEN  = is_undef(T_OPEN)  ? 0.15 : T_OPEN;
T_HOLD  = is_undef(T_HOLD)  ? 0.75 : T_HOLD;
T_CLOSE = is_undef(T_CLOSE) ? 0.95 : T_CLOSE;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 175000 : VPD;

include <@MODEL@>;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));
open  = smoothstep(($t - 0.02) / max(0.01, T_OPEN - 0.02));
close = smoothstep(($t - T_HOLD) / max(0.01, T_CLOSE - T_HOLD));
factor = open - close;

$vpt = [0, 0, VPT_Z];
$vpr = [62, 0, 30 + 20 * $t];
$vpd = VPD;

device(explode = EXPLODE_MM * factor);
