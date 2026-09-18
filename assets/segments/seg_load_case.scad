// 段落模板：工况变形（加载 → 保持 → 复位）
// -D MODEL=... -D THETA=-12 -D PULL=900 -D T_LOAD=0.28 -D T_HOLD=0.57 -D T_UNLOAD=0.72 -D T_END=0.89
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
THETA   = is_undef(THETA) ? -10 : THETA;
PULL    = is_undef(PULL) ? 800 : PULL;
T_LOAD   = is_undef(T_LOAD)   ? 0.20 : T_LOAD;
T_HOLD   = is_undef(T_HOLD)   ? 0.50 : T_HOLD;
T_UNLOAD = is_undef(T_UNLOAD) ? 0.66 : T_UNLOAD;
T_END    = is_undef(T_END)    ? 0.87 : T_END;
VPT_Z = is_undef(VPT_Z) ? -1000 : VPT_Z;
VPD   = is_undef(VPD) ? 150000 : VPD;

include <@MODEL@>;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));
load   = smoothstep(($t - T_LOAD) / max(0.01, T_HOLD - T_LOAD));
unload = 1 - smoothstep(($t - T_UNLOAD) / max(0.01, T_END - T_UNLOAD));
phase  = min(load, unload);

$vpt = [0, 0, VPT_Z];
$vpr = [76, 0, 30];
$vpd = VPD;

device(theta = THETA * phase, pull = PULL * phase);
