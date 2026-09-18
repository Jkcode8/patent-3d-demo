// 段落模板：与现有技术对比（左：对照模型；右：本发明）
// 对照模型路径写在模板占位符 @MODEL_B@ 上，由 storyboard.py 实例化
// -D SEP=40000
SET_FN = is_undef(SET_FN) ? 40 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 5 : SET_COIL_SEG;
SEP = is_undef(SEP) ? 40000 : SEP;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 220000 : VPD;

include <@MODEL@>;

$vpt = [SEP / 2, 0, VPT_Z];
$vpr = [68, 0, 35];
$vpd = VPD;

// 本发明（右）
translate([SEP, 0, 0]) device();
// 对照模型（左）
translate([0, 0, 0]) include <@MODEL_B@>;
