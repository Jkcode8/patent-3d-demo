/* ===================================================================
   一种自适应多重耗能桥墩防撞装置 —— 三维参数化模型（公共模块库）
   依据：① 专利交底书《一种自适应多重耗能桥墩防撞装置及其施工方法》
               （20260130，补充受力分析及耗能原理）
         ② CAD 图《一种多重耗能桥墩防撞装置及其施工方法20260130
                    --补充受力分析.dwg》

   结构组成（交底书 1.1）：
     1 张拉整体支撑模块：环向 8 个防撞模块（撑杆、弹簧、防撞杆、伸缩杆、
       铰节点、可滑动套环），模块间以环向弹力索串联成自应力平衡索网
     2 多重耗能模块：防撞套筒 + 万向滚珠（上下滑动 + 环向转动）、浮箱
     3 柔性防护模块：外包柔性膜（压条固定于防撞杆外侧）
     4 调节模块：弹力索张拉力可调

   机构运动学：防撞杆为刚体，通过上、下两根定长撑杆与铰节点相连，
   撑杆端部为可沿防撞杆滑动的套环 —— 即"刚性撑杆 + 滑动套环"约束。
   撞击时给定防撞杆转角 θ 与径向内移量 d，套环位置由约束方程求出，
   因此各弹簧的拉压、伸缩杆的伸缩均为几何协调结果，而非示意画法。

   坐标系：Z 轴向上，原点位于防撞套筒中部（约静水面），单位 mm
   =================================================================== */

$fn = is_undef(SET_FN) ? 64 : SET_FN;

/* ---------------- 主控参数（均取自 CAD 图几何量） ---------------- */
n            = 8;        // 防撞模块数量（环向均布）
pier_r       = 5000;     // 桥墩半径
pier_bot     = -32000;   // 桥墩底标高
pier_top     = 16000;    // 桥墩顶标高

sleeve_ri    = 5600;     // 防撞套筒内半径
sleeve_ro    = 6000;     // 防撞套筒外半径
sleeve_h     = 19000;    // 防撞套筒高度
roller_r     = 420;      // 万向滚珠半径
roller_rows  = [-7000, -2500, 2500, 7000];   // 万向滚珠标高

node_r       = 12900;    // 防撞杆中心半径（八边形外接圆）
rod_d        = 460;      // 防撞杆直径
rod_len      = 13000;    // 防撞杆长度
rod_z        = 1500;     // 防撞杆中心标高
collar_up_z  = 4900;     // 上滑动套环标高（初始状态）
collar_dn_z  = -4300;    // 下滑动套环标高（初始状态）
collar_h     = 320;
collar_d     = 1050;
hinge_r      = 6200;     // 铰节点中心半径（套筒外缘）
hinge_z      = 0;        // 铰节点标高

spring_coil_r  = 420;    // 弹簧2（竖向）螺旋半径
spring_wire_r  = 65;     // 弹簧丝半径
spring1_coil_r = 220;    // 弹簧1/3 螺旋半径
turns_spring2  = 9;      // 弹簧2 圈数
turns_spring13 = 7;      // 弹簧1/3 圈数
cable_d        = 300;    // 弹力索直径
strut_d        = 220;    // 撑杆直径
damper_d       = 300;    // 伸缩杆（液压阻尼杆）直径

pontoon_ri   = 6300;     // 浮箱内半径
pontoon_ro   = 8300;     // 浮箱外半径
pontoon_h    = 4200;     // 浮箱高度
pontoon_z    = -12200;   // 浮箱中心标高

membrane_r   = 14400;    // 外包膜（位于防撞杆外侧）
membrane_t   = 45;       // 外包膜厚度

coil_seg = is_undef(SET_COIL_SEG) ? 8 : SET_COIL_SEG;

/* ---------------- 构件配色（SET_MONO = true 时输出单色，供黑白附图用） ----------------
   colorize / tint() 只影响渲染外观；STL 导出不含颜色信息。 */
colorize = is_undef(SET_MONO) ? true : !SET_MONO;

C_PIER     = "#C7C4BE";   // 桥墩（混凝土灰）
C_SLEEVE   = "#2F5FA8";   // 防撞套筒（深蓝）
C_ROLLER   = "#FFB300";   // 万向滚珠（琥珀）
C_HINGE    = "#E03B2F";   // 铰节点（红）
C_ROD      = "#00A6B8";   // 防撞杆（青）
C_COLLAR   = "#9B59B6";   // 可滑动套环（紫）
C_STRUT    = "#3FBF6F";   // 撑杆（绿）
C_SPRING13 = "#F5D22B";   // 弹簧1、弹簧3（黄）
C_SPRING2  = "#F07B2F";   // 弹簧2（橙）
C_DAMPER   = "#8C5A3C";   // 伸缩杆／液压阻尼杆（棕）
C_CABLE    = "#D81B60";   // 环向弹力索（洋红）
C_MEMBRANE = "#4FA3C7";   // 外包柔性膜（天蓝，半透明）
C_PONTOON  = "#6C7A89";   // 浮箱（石板灰）

module tint(c, alpha = 1.0) {
    if (colorize) color(c, alpha) children();
    else children();
}

/* ---------------- 基础工具 ---------------- */
function cross(a, b) = [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]];
function unit(v) = v / norm(v);
function clamp(x, lo, hi) = min(max(x, lo), hi);

// 铰节点（固定在套筒上）
function HINGE() = [hinge_r, 0, hinge_z];
// 撑杆长度（初始状态下的定长）
function strut_len_up() = norm([node_r - hinge_r, 0, collar_up_z - hinge_z]);
function strut_len_dn() = norm([node_r - hinge_r, 0, collar_dn_z - hinge_z]);

// 防撞杆位姿：中心点 C、单位方向 u（theta：绕铰节点转角，pull：径向内移量）
function rod_center(pull_v) = [node_r - pull_v, 0, rod_z];
function rod_dir(theta_v) = [sin(theta_v), 0, cos(theta_v)];
function rod_point(sign, k, theta_v, pull_v) =
    let (C = rod_center(pull_v),
         u = rod_dir(theta_v),
         P = C + u * sign * (rod_len / 2 - 350),
         a = k * 360 / n)
    [P[0]*cos(a) - P[1]*sin(a), P[0]*sin(a) + P[1]*cos(a), P[2]];

// 套环在防撞杆上的位置参数 t：|C + t·u - H| = L，取靠近初始位置的解
function collar_param(C, u, L, t_ref) =
    let (H = HINGE(),
         w = C - H,
         b = w[0]*u[0] + w[1]*u[1] + w[2]*u[2],
         c = w[0]*w[0] + w[1]*w[1] + w[2]*w[2] - L*L,
         disc = b*b - c,
         sq = disc > 0 ? sqrt(disc) : 0,
         t1 = -b + sq,
         t2 = -b - sq)
    abs(t1 - t_ref) <= abs(t2 - t_ref) ? t1 : t2;

// 撞击影响权重：撞击方向为 +X（k=0 模块），按环向夹角余弦平方衰减
function impact_weight(k) = pow(max(0, cos(k * 360 / n)), 2);

module tube(p1, p2, d, facets = 8) {
    v = p2 - p1;
    L = norm(v);
    if (L > 0.05)
        translate(p1)
            rotate([0, 0, atan2(v[1], v[0])])
                rotate([0, acos(clamp(v[2] / L, -1, 1)), 0])
                    cylinder(h = L, d = d, $fn = facets);
}

module coil(p1, p2, coil_r, wire_r, turns) {
    v = p2 - p1;
    dirv = unit(v);
    helper = abs(dirv[2]) > 0.98 ? [1, 0, 0] : [0, 0, 1];
    ux = unit(cross(dirv, helper));
    uy = unit(cross(dirv, ux));
    steps = turns * coil_seg;
    for (i = [0 : steps - 1]) {
        a1 = 360 * i / coil_seg;
        a2 = 360 * (i + 1) / coil_seg;
        q1 = p1 + v * (i / steps) + ux * coil_r * cos(a1) + uy * coil_r * sin(a1);
        q2 = p1 + v * ((i + 1) / steps) + ux * coil_r * cos(a2) + uy * coil_r * sin(a2);
        tube(q1, q2, wire_r * 2, 6);
    }
}

module ring_band(ri, ro, h, z) {
    translate([0, 0, z])
        difference() {
            cylinder(h = h, r = ro, center = true);
            cylinder(h = h + 2, r = ri, center = true);
        }
}

module polygon_band(r_out, r_in, h, z, sides, phase = 0) {
    translate([0, 0, z])
        linear_extrude(height = h, center = true)
            difference() {
                polygon([for (i = [0 : sides - 1])
                    [r_out * cos(360 * i / sides + phase), r_out * sin(360 * i / sides + phase)]]);
                polygon([for (i = [0 : sides - 1])
                    [r_in * cos(360 * i / sides + phase), r_in * sin(360 * i / sides + phase)]]);
            }
}

/* ---------------- 各部件 ---------------- */
module pier() {
    tint(C_PIER) tube([0, 0, pier_bot], [0, 0, pier_top], 2 * pier_r, 96);
}

module sleeve() {
    tint(C_SLEEVE) ring_band(sleeve_ri, sleeve_ro, sleeve_h, 0);
    tint(C_SLEEVE) ring_band(sleeve_ri - 250, sleeve_ro + 300, 420,  sleeve_h / 2 - 210);
    tint(C_SLEEVE) ring_band(sleeve_ri - 250, sleeve_ro + 300, 420, -sleeve_h / 2 + 210);
}

module rollers() {
    tint(C_ROLLER)
        for (k = [0 : n - 1])
            rotate([0, 0, k * 360 / n])
                for (z = roller_rows)
                    translate([pier_r + roller_r, 0, z]) sphere(r = roller_r, $fn = 24);
}

module pontoon() {
    tint(C_PONTOON) ring_band(pontoon_ri, pontoon_ro, pontoon_h, pontoon_z);
}

module membrane(theta_v = 0, pull_v = 0) {
    tint(C_MEMBRANE, 0.62)
        polygon_band(membrane_r, membrane_r - membrane_t, rod_len - 400, rod_z, n);
}

/* ---------------- 张拉整体防撞模块（含变形状态） ----------------
   theta_v：防撞杆绕铰节点转角（+ 为杆顶向装置外侧转）
   pull_v ：防撞杆径向内移量（撞击方向内移）
   上、下套环位置由"定长撑杆 + 可滑动套环"约束求解
------------------------------------------------------------------ */
module crash_module(theta_v = 0, pull_v = 0, show_hinge = true) {
    C  = rod_center(pull_v);
    u  = rod_dir(theta_v);
    tU = collar_param(C, u, strut_len_up(), collar_up_z - rod_z);
    tD = collar_param(C, u, strut_len_dn(), collar_dn_z - rod_z);
    U  = C + tU * u;                       // 上滑动套环
    D  = C + tD * u;                       // 下滑动套环
    A1 = [sleeve_ro + 150, 0, hinge_z + 620];   // 弹簧1 弹簧套筒侧锚点
    A3 = [sleeve_ro + 150, 0, hinge_z - 620];   // 弹簧3 弹簧套筒侧锚点

    // 防撞杆
    tint(C_ROD) tube(C - u * (rod_len / 2), C + u * (rod_len / 2), rod_d, 16);

    // 上、下滑动套环
    tint(C_COLLAR) {
        tube(U - u * (collar_h / 2), U + u * (collar_h / 2), collar_d, 20);
        tube(D - u * (collar_h / 2), D + u * (collar_h / 2), collar_d, 20);
    }

    // 弹簧2：沿防撞杆连接上下滑动套环
    tint(C_SPRING2)
        coil(U - u * collar_h, D + u * collar_h,
             rod_d / 2 + spring_coil_r * 0.45, spring_wire_r, turns_spring2);

    // 撑杆1、撑杆2：铰节点 → 上/下滑动套环
    tint(C_STRUT) {
        tube(HINGE(), U, strut_d, 10);
        tube(HINGE(), D, strut_d, 10);
    }

    // 弹簧1、弹簧3：弹簧套筒锚点 → 上/下滑动套环
    tint(C_SPRING13) {
        coil(A1, U, spring1_coil_r, spring_wire_r, turns_spring13);
        coil(A3, D, spring1_coil_r, spring_wire_r, turns_spring13);
    }

    // 伸缩杆（液压阻尼杆）：铰节点 → 防撞杆中部
    tint(C_DAMPER) tube(HINGE(), C, damper_d, 12);

    // 铰接节点（万向球铰）
    if (show_hinge) tint(C_HINGE) translate(HINGE()) sphere(d = collar_d * 1.4, $fn = 20);
}

/* ---------------- 环向弹力索索网（随防撞杆变位） ---------------- */
module cables(theta_deg = 0, pull = 0) {
    tint(C_CABLE)
        for (k = [0 : n - 1]) {
            w1 = impact_weight(k);
            w2 = impact_weight(k + 1);
            tube(rod_point( 1, k,     theta_deg * w1, pull * w1),
                 rod_point( 1, k + 1, theta_deg * w2, pull * w2), cable_d, 8);
            tube(rod_point(-1, k,     theta_deg * w1, pull * w1),
                 rod_point(-1, k + 1, theta_deg * w2, pull * w2), cable_d, 8);
        }
}

/* ---------------- 总装 ----------------
   theta_deg / pull：撞击工况变形参数（0 = 初始状态）
   explode        ：爆炸图分离量（各部件沿竖向分离）
------------------------------------------------------------------ */
module device(show_membrane = true, show_pontoon = true, show_pier = true,
              theta_deg = 0, pull = 0, explode = 0) {
    z_pontoon  = -1.50 * explode;
    z_sleeve   = -0.50 * explode;
    z_module   =  1.00 * explode;
    z_cable    =  2.00 * explode;
    z_membrane =  3.00 * explode;

    if (show_pier) pier();
    if (show_pontoon) translate([0, 0, z_pontoon]) pontoon();
    translate([0, 0, z_sleeve]) { sleeve(); rollers(); }
    translate([0, 0, z_module])
        for (k = [0 : n - 1]) rotate([0, 0, k * 360 / n])
            crash_module(theta_deg * impact_weight(k), pull * impact_weight(k));
    translate([0, 0, z_cable]) cables(theta_deg, pull);
    if (show_membrane)
        translate([0, 0, z_membrane]) membrane(theta_deg, pull);
}

/* 半剖模型：切掉 y < 0 的一半，显示套筒、万向滚珠与内部构造 */
module _section_cutter() {
    // 切割体着色，使剖切面呈统一的浅灰（制图习惯），而不是默认色
    if (colorize) color("#D2D2D2") translate([-30000, -30000, -40000]) cube([60000, 30000, 90000]);
    else translate([-30000, -30000, -40000]) cube([60000, 30000, 90000]);
}

module device_section() {
    difference() {
        device(show_membrane = false);
        _section_cutter();
    }
}

/* 装配顺序：step = 1..5
   1 浮箱  2 防撞套筒（含万向滚珠）  3 张拉整体防撞模块
   4 环向弹力索张拉              5 外包柔性膜 */
module assembly_stage(step) {
    pier();
    if (step >= 1) pontoon();
    if (step >= 2) { sleeve(); rollers(); }
    if (step >= 3)
        for (k = [0 : n - 1]) rotate([0, 0, k * 360 / n]) crash_module();
    if (step >= 4) cables();
    if (step >= 5) membrane();
}
