// 段落模板：参数变化对比（同一模型的结构参数从 V1 平滑扫到 V2）
// 用法：-D V1=800 -D V2=1200；模型里要被扫描的参数需写成
//       P_total = is_undef(SET_P_TOTAL) ? 1000 : SET_P_TOTAL;
SET_FN = is_undef(SET_FN) ? 40 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 5 : SET_COIL_SEG;
V1 = is_undef(V1) ? 800 : V1;
V2 = is_undef(V2) ? 1200 : V2;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 165000 : VPD;

function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));
SET_P_TOTAL = V1 + (V2 - V1) * smoothstep(($t - 0.30) / 0.40);

include <@MODEL@>;

$vpt = [0, 0, VPT_Z];
$vpr = [66, 0, 35 + 20 * $t];
$vpd = VPD;

device();
