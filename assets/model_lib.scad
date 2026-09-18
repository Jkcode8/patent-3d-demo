/* ===================================================================
   专利三维演示 —— 参数化模型骨架（复制到 <project>/model/device.scad 后改写）

   写作约定（8 类段落模板都依赖这套接口，改接口前先看 SKILL.md）：
     1. 顶部「参数区」集中所有尺寸，每个参数注明来源（图纸图元 / 交底书文字 / 假设）
     2. 每个构件一个 module，名字用 part_*，并按 PARTS 表登记
     3. 对外只暴露一个入口：device(theta, pull, water_z, step, explode, section)
        —— 段落模板通过 -D 传参驱动动画，不需要知道内部结构
     4. 颜色只用 tint()，SET_MONO=true 时自动变单色（专利黑白附图）
   =================================================================== */

$fn = is_undef(SET_FN) ? 64 : SET_FN;
coil_seg = is_undef(SET_COIL_SEG) ? 8 : SET_COIL_SEG;
colorize = is_undef(SET_MONO) ? true : !SET_MONO;

/* ---------------- 参数区（改成你的专利） ---------------- */
// 需要被 param_sweep 段落扫描的参数写成 SET_* 可覆盖形式
P_total     = is_undef(SET_P_TOTAL)  ? 1000 : SET_P_TOTAL;   // 来源：图纸 平面图 R500
P_height    = is_undef(SET_P_HEIGHT) ? 600  : SET_P_HEIGHT;  // 来源：图纸 立面图 高度
P_wall      = 40;     // 来源：交底书「壁厚」文字
P_slide     = 200;    // 来源：假设（可调行程）

/* ---------------- 构件配色（可整表替换） ---------------- */
C_BASE   = "#C7C4BE";  // 底座/基础
C_MAIN   = "#2F5FA8";  // 主体/框架
C_MOVING = "#FFB300";  // 运动件/滚轮
C_JOINT  = "#E03B2F";  // 铰接/节点
C_ROD    = "#00A6B8";  // 杆件
C_SLEEVE = "#9B59B6";  // 套环/衬套
C_STRUT  = "#3FBF6F";  // 撑杆
C_SPRING = "#F5D22B";  // 弹簧/弹性件
C_DAMPER = "#8C5A3C";  // 阻尼/液压件
C_CABLE  = "#D81B60";  // 索/链
C_SKIN   = "#4FA3C7";  // 柔性膜/覆层（半透明）
C_AUX    = "#6C7A89";  // 附属构件（浮箱/配重等）
C_CUT    = "#D2D2D2";  // 剖切面

module tint(c, alpha = 1.0) {
    if (colorize) color(c, alpha) children();
    else children();
}

/* ---------------- 通用几何helper ---------------- */
function cross3(a, b) = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
function unit3(v) = v / norm(v);
function clamp(x, lo, hi) = min(max(x, lo), hi);
function smoothstep(x) = x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));

// 任意两点间的圆柱
module tube(p1, p2, d, facets = 8) {
    v = p2 - p1;
    L = norm(v);
    if (L > 0.05)
        translate(p1)
            rotate([0, 0, atan2(v[1], v[0])])
                rotate([0, acos(clamp(v[2] / L, -1, 1)), 0])
                    cylinder(h = L, d = d, $fn = facets);
}

// 沿任意轴的螺旋弹簧（示意弹簧/索）
module coil(p1, p2, coil_r, wire_r, turns) {
    v = p2 - p1;
    dirv = unit3(v);
    helper = abs(dirv[2]) > 0.98 ? [1, 0, 0] : [0, 0, 1];
    ux = unit3(cross3(dirv, helper));
    uy = unit3(cross3(dirv, ux));
    steps = turns * coil_seg;
    for (i = [0 : steps - 1]) {
        a1 = 360 * i / coil_seg;
        a2 = 360 * (i + 1) / coil_seg;
        tube(p1 + v * (i / steps) + ux * coil_r * cos(a1) + uy * coil_r * sin(a1),
             p1 + v * ((i + 1) / steps) + ux * coil_r * cos(a2) + uy * coil_r * sin(a2),
             wire_r * 2, 6);
    }
}

module ring_band(ri, ro, h, z) {
    translate([0, 0, z]) difference() {
        cylinder(h = h, r = ro, center = true);
        cylinder(h = h + 2, r = ri, center = true);
    }
}

/* ---------------- 剖切：切割体要着色，否则布尔新面会丢颜色 ---------------- */
CUTTER_ENABLED = is_undef(SECTION) ? false : SECTION;
module section_cutter() {
    if (colorize) color(C_CUT) cutter_body();
    else cutter_body();
}
module cutter_body() {
    // 默认切掉 y<0 的一半；按需改方向/位置
    translate([-2.2*P_total, -2.2*P_total, -2*P_height])
        cube([4.4*P_total, 2.2*P_total, 4*P_height]);
}

/* ===================================================================
   构件：每个构件一个 module，并在下面的表里登记
   表字段：STEP 装配步序（1 起）| EXPLODE 爆炸方向向量 | COLOR 颜色
   =================================================================== */
N_PARTS = 4;

module part_base()   { tint(C_BASE)   cylinder(h = P_wall, r = P_total, $fn = 96); }
module part_column() { tint(C_MAIN)   cylinder(h = P_height, d = P_wall * 1.5, $fn = 48); }
module part_collar() { tint(C_SLEEVE) cylinder(h = P_wall, d = P_wall * 2.4, $fn = 48); }
module part_arm()    { tint(C_ROD)    tube([0, 0, P_height], [P_total * 0.8, 0, P_height], P_wall / 3, 12); }

function part_step(i) = i;
function part_explode(i) = i == 1 ? [0, 0, -1] : [0, 0, 1];
function part_color(i) = i == 1 ? C_BASE : (i == 2 ? C_MAIN : (i == 3 ? C_SLEEVE : C_ROD));

module part(i) {
    if (i == 1) part_base();
    else if (i == 2) part_column();
    else if (i == 3) part_collar();
    else if (i == 4) part_arm();
}

/* ===================================================================
   入口：段落模板只调用这个 module
     theta   : 主运动件转角（度）      —— load_case 用
     pull    : 径向/轴向位移（mm）     —— load_case 用
     water_z : 环境/水位等缓变量（mm） —— adjust 用
     step    : 装配步序（>=N_PARTS 为整机）—— assembly 用
     explode : 爆炸分离量（mm）        —— explode 用
     section : 是否半剖                —— section 用
     show_skin: 是否显示柔性覆层/外罩
   =================================================================== */
module device(theta = 0, pull = 0, water_z = 0, step = N_PARTS, explode = 0,
              section = false, show_skin = true) {
    apply_section() {
        translate([0, 0, water_z]) {
            for (i = [1 : N_PARTS]) {
                if (part_step(i) <= step) {
                    translate(part_explode(i) * explode) part(i);
                }
            }
        }
    }
}

module apply_section() {
    if (section) difference() { children(); section_cutter(); }
    else children();
}

/* 整机（默认参数）—— 供预检与导出 STL 使用 */
device();
