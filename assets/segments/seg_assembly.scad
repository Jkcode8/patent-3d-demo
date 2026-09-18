// 段落模板：装配顺序（按 A1..An 分步显示）
// -D MODEL=... -D A1=0.16 -D A2=0.33 -D A3=0.50 -D A4=0.73  -D N_STEPS=4
SET_FN = is_undef(SET_FN) ? 48 : SET_FN;
SET_COIL_SEG = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
N_STEPS = is_undef(N_STEPS) ? 4 : N_STEPS;
VPT_Z = is_undef(VPT_Z) ? 0 : VPT_Z;
VPD   = is_undef(VPD) ? 150000 : VPD;

include <@MODEL@>;

function step_at(t) =
    let (a1 = is_undef(A1) ? 0.16 : A1,
         a2 = is_undef(A2) ? 0.33 : A2,
         a3 = is_undef(A3) ? 0.50 : A3,
         a4 = is_undef(A4) ? 0.73 : A4,
         a5 = is_undef(A5) ? 0.88 : A5)
    t < a1 ? 1 : (t < a2 ? 2 : (t < a3 ? 3 : (t < a4 ? 4 : (t < a5 ? 5 : 6))));

$vpt = [0, 0, VPT_Z];
$vpr = [62, 0, 25 + 25 * $t];
$vpd = VPD;

device(step = min(step_at($t), N_PARTS));
