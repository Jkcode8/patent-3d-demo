// 段落模板：整体旋转展示（转台）
// -D TURNS=1  -D SET_FN=48
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
TURNS = is_undef(TURNS) ? 1 : TURNS;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 150000 : VPD;

// @MODEL@ 由 storyboard.py 实例化为项目模型的绝对路径
include <@MODEL@>;

$vpt = [0, 0, VPT_Z];
// $t 在 --animate N 下取 i/N，因此转满一圈后首尾帧正好相差一帧，循环无缝
$vpr = [68, 0, 360 * TURNS * $t];
$vpd = VPD;

device();
