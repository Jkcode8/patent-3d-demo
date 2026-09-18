/* ===================================================================
   示例（脱敏）：可调式护栏支架 —— 演示全流程用的虚构装置
   对应真实专利的结构：底座 + 立柱 + 可滑动套环 + 悬臂 + 斜撑 + 弹簧
   接口约定见 assets/model_lib.scad，本文件是"填好内容"的版本
   =================================================================== */

$fn = is_undef(SET_FN) ? 48 : SET_FN;
coil_seg = is_undef(SET_COIL_SEG) ? 6 : SET_COIL_SEG;
colorize = is_undef(SET_MONO) ? true : !SET_MONO;

/* 参数区（SET_* 可被 param_sweep 段落覆盖） */
BASE_L = is_undef(SET_BASE_L) ? 400 : SET_BASE_L;   // 来源：交底书「底座 400×300」
BASE_W = 300;
BASE_T = 20;
POST_D = is_undef(SET_POST_D) ? 80 : SET_POST_D;    // 来源：图纸 立柱 φ80
POST_H = 900;                                       // 来源：图纸 立柱高 900
COLLAR_D = 160;
COLLAR_H = 70;
ARM_L  = 600;
ARM_T  = 60;
SLIDE  = is_undef(SET_SLIDE) ? 350 : SET_SLIDE;     // 来源：假设（可调行程 350）

C_BASE   = "#C7C4BE";
C_MAIN   = "#2F5FA8";
C_SLEEVE = "#9B59B6";
C_ROD    = "#00A6B8";
C_STRUT  = "#3FBF6F";
C_SPRING = "#F5D22B";
C_CUT    = "#D2D2D2";

module tint(c, alpha = 1.0) {
    if (colorize) color(c, alpha) children();
    else children();
}

function clamp(x, lo, hi) = min(max(x, lo), hi);
function cross3(a, b) = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
function unit3(v) = v / norm(v);

module tube(p1, p2, d, facets = 10) {
    v = p2 - p1;
    L = norm(v);
    if (L > 0.05)
        translate(p1) rotate([0, 0, atan2(v[1], v[0])])
            rotate([0, acos(clamp(v[2] / L, -1, 1)), 0]) cylinder(h = L, d = d, $fn = facets);
}

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

/* ---------------- 构件（参数从 device() 逐级传入，便于段落模板驱动） ---------------- */
N_PARTS = 6;
COLLAR_BASE_Z = 320;               // 套环初始高度

module part_base() {
    tint(C_BASE) difference() {
        translate([0, 0, BASE_T / 2]) cube([BASE_L, BASE_W, BASE_T], center = true);
        for (sx = [-1, 1], sy = [-1, 1])
            translate([sx * BASE_L * 0.36, sy * BASE_W * 0.32, -1]) cylinder(h = BASE_T + 2, d = 18);
    }
}

module part_post() {
    tint(C_MAIN) translate([0, 0, BASE_T]) cylinder(h = POST_H, d = POST_D, $fn = 64);
}

module part_collar(z) {
    tint(C_SLEEVE) translate([0, 0, z])
        difference() {
            cylinder(h = COLLAR_H, d = COLLAR_D, center = true);
            cylinder(h = COLLAR_H + 2, d = POST_D + 6, center = true);
        }
}

module part_arm(z, theta) {
    tint(C_ROD) translate([0, 0, z]) rotate([0, 0, theta])
        translate([ARM_L / 2, 0, 0]) cube([ARM_L, ARM_T, ARM_T], center = true);
}

module part_strut(z, theta) {
    tip = [cos(theta) * ARM_L * 0.55 - sin(theta) * 0, sin(theta) * ARM_L * 0.55,
           z - 20];
    tint(C_STRUT) tube([BASE_L * 0.30, 0, BASE_T], tip, 26, 12);
}

module part_spring(z) {
    tint(C_SPRING) coil([POST_D * 0.9, 0, BASE_T + 40],
                        [POST_D * 0.9, 0, z - COLLAR_H], 26, 6, 9);
}

function part_step(i) = i;              // 装配顺序：底座→立柱→套环→悬臂→斜撑→弹簧
function part_explode(i) = [0, 0, i - 1];

module part(i, z, theta) {
    if (i == 1) part_base();
    else if (i == 2) part_post();
    else if (i == 3) part_collar(z);
    else if (i == 4) part_arm(z, theta);
    else if (i == 5) part_strut(z, theta);
    else if (i == 6) part_spring(z);
}

module cutter_body() {
    translate([-BASE_L, -BASE_L, -BASE_T]) cube([2 * BASE_L, BASE_L, 3 * POST_H]);
}
module apply_section(section) {
    if (section) difference() { children(); 
        if (colorize) color(C_CUT) cutter_body(); else cutter_body(); }
    else children();
}

/* ---------------- 入口 ---------------- */
module device(theta = 0, pull = 0, water_z = 0, step = N_PARTS, explode = 0,
              section = false, show_skin = true) {
    collar_z = COLLAR_BASE_Z + water_z;
    apply_section(section) {
        translate([0, 0, -pull * 0.5]) {
            for (i = [1 : N_PARTS])
                if (part_step(i) <= step)
                    translate(part_explode(i) * explode) part(i, collar_z, theta);
        }
    }
}

device();
