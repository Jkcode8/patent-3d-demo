// 段落模板：剖切/局部剖展示
// -D MODEL=... -D TURNS=0.5
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
TURNS = is_undef(TURNS) ? 0.5 : TURNS;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 150000 : VPD;

include <@MODEL@>;

$vpt = [0, 0, VPT_Z];
$vpr = [72, 0, -130 + 360 * TURNS * $t];
$vpd = VPD;

device(section = true);
