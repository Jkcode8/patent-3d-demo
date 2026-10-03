"""Unit tests for patent-3d-demo's pure helpers.

    python -m unittest discover -s tests -t .

These cover the logic that decides *what* to render and *whether it is right* —
narration normalisation, timeline layout, storyboard selection and gating, frame
cache fingerprints, mechanism solving, drawing/geometry parsing and the
version invariants.  They deliberately need neither OpenSCAD nor ffmpeg, so they
run in about a second and can gate every commit; the end-to-end behaviour is
covered by .github/workflows/regression.yml instead.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_kinematics  # noqa: E402
import check_interference  # noqa: E402
import check_mechanism  # noqa: E402
import config  # noqa: E402
import lineart  # noqa: E402
import narration  # noqa: E402
import openscad_run  # noqa: E402
import param_check  # noqa: E402
import sketch_to_skeleton  # noqa: E402
import storyboard  # noqa: E402
import verify_vs_drawing as verify  # noqa: E402

SETTINGS = config.load_settings(ROOT)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def mask(size: int = 300, segments=(), width: int = 3) -> Image.Image:
    """Canonical mask (ink is 0, background 255) with the given segments drawn."""
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    for points in segments:
        draw.line(list(points), fill=0, width=width)
    return image


class NarrationTests(unittest.TestCase):
    def test_zh_units_read_naturally(self):
        cases = {
            "φ1500 的立柱": "直径1500 的立柱",
            "φ 80 的杆": "直径80 的杆",
            "立柱高 1.5m": "立柱高 1.5米",
            "角度 16+16+17度": "角度 16度、16度、17度",
            "位移 −2.26m": "位移 负2.26米",
            "提升 30%": "提升 百分之30",
            "宽 2×3": "宽 2乘3",
            "行程 1~2mm": "行程 1到2毫米",
            "承压 50kN": "承压 50千牛",
            "流量 120m³/s": "流量 120立方米每秒",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(narration.normalize_narration(raw), expected)

    def test_zh_collapses_whitespace_before_punctuation(self):
        self.assertEqual(narration.normalize_narration("多个   空格 ，标点 "), "多个 空格，标点")

    def test_english_rules(self):
        cases = {
            "column φ1500": "column diameter 1500",
            "height 1.5m": "height 1.5 metres",
            "force 50kN": "force 50 kilonewtons",
            "gain 30%": "gain 30 percent",
            "width 2x3": "width 2 by 3",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(narration.normalize_narration(raw, "en-US"), expected)

    def test_voice_selection_follows_gender_and_language(self):
        self.assertEqual(narration.voice_for(SETTINGS, "female", "zh-CN"),
                         "zh-CN-XiaoxiaoNeural")
        self.assertEqual(narration.voice_for(SETTINGS, "male", "zh-CN"),
                         "zh-CN-YunyangNeural")
        self.assertEqual(narration.voice_for(SETTINGS, "male", "en-US"), "en-US-GuyNeural")
        # 未知性别回落到默认女声，而不是抛异常
        self.assertEqual(narration.voice_for(SETTINGS, "robot", "zh-CN"),
                         "zh-CN-XiaoxiaoNeural")

    def test_offline_sapi_voice_matching(self):
        available = ["Microsoft Huihui Desktop", "Microsoft Kangkang"]
        self.assertEqual(narration.pick_sapi_voice(SETTINGS, "female", available),
                         "Microsoft Huihui Desktop")
        self.assertEqual(narration.pick_sapi_voice(SETTINGS, "male", available),
                         "Microsoft Kangkang")
        self.assertEqual(narration.pick_sapi_voice(SETTINGS, "female", []), None)
        # 一个都不匹配时退回第一个可用声线，避免无声成片
        self.assertEqual(narration.pick_sapi_voice(SETTINGS, "female", ["Some Voice"]),
                         "Some Voice")

    def test_cue_slots_never_overlap_and_keep_a_tail(self):
        durations = [2.0, 3.5, 1.25]
        slots = narration.cue_slots(durations)
        self.assertEqual(slots["starts"][0], 0.0)
        for index in range(1, len(durations)):
            self.assertGreaterEqual(slots["starts"][index], slots["ends"][index - 1])
            # 句间留白恰好是 GAP_SECONDS
            self.assertAlmostEqual(slots["starts"][index] - slots["ends"][index - 1],
                                   narration.GAP_SECONDS, places=3)
        self.assertAlmostEqual(slots["total"], slots["ends"][-1] + narration.TAIL_SECONDS, places=3)
        self.assertEqual(narration.cue_slots([])["total"], narration.TAIL_SECONDS)


class StoryboardTests(unittest.TestCase):
    def test_split_sections_on_numbered_headings(self):
        text = ("一、系统组成\n装置包括底座与立柱。\n"
                "二、工作原理\n受力后构件变形。\n"
                "三、施工方法\n按顺序安装。\n")
        sections = storyboard.split_sections(text)
        self.assertEqual(len(sections), 3)
        self.assertTrue(sections[0].startswith("一、系统组成"))
        self.assertTrue(sections[2].startswith("三、施工方法"))
        self.assertEqual(storyboard.split_sections("   "), [])

    def test_draft_picks_segments_that_match_the_disclosure(self):
        text = ("一、系统组成\n本装置包括底座、立柱与套环。\n"
                "二、工作原理\n受撞击后构件变形耗能。\n"
                "三、施工方法\n按以下步骤安装。\n"
                "四、调节方式\n可随水位调节高度。\n")
        segments = storyboard.propose_segments(text, "测试装置")
        kinds = [seg["type"] for seg in segments]
        self.assertTrue({"explode", "load_case", "assembly", "adjust"}.issubset(set(kinds)),
                        kinds)
        self.assertEqual(len(kinds), len(set(kinds)), "同一类型不应重复出段")
        for seg in segments:
            self.assertIn(seg["type"], storyboard.TEMPLATES)
            self.assertEqual(seg["template"], storyboard.TEMPLATES[seg["type"]])
            self.assertTrue(seg["narration"] and all(seg["narration"]))
            self.assertTrue((config.SEGMENTS / seg["template"]).exists())

    def test_draft_always_returns_something(self):
        segments = storyboard.propose_segments("", "空交底书")
        self.assertEqual([seg["type"] for seg in segments], ["turntable"])

    def test_every_documented_type_has_a_template(self):
        expected = {"turntable", "explode", "assembly", "load_case",
                    "section", "adjust", "param_sweep", "comparison"}
        self.assertEqual(set(storyboard.TEMPLATES), expected)
        for name in storyboard.TEMPLATES.values():
            self.assertTrue((config.SEGMENTS / name).is_file(), name)

    def test_validate_reports_each_kind_of_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = config.project_paths(tmp)
            write(paths["model"] / "device.scad", "module device() {}\n")
            good = {"segments": [{"id": "turntable", "type": "turntable",
                                  "template": storyboard.TEMPLATES["turntable"],
                                  "model": "model/device.scad",
                                  "narration": ["这是本专利装置。"]}]}
            self.assertEqual(storyboard.validate(paths, good), [])

            bad = json.loads(json.dumps(good))
            bad["segments"][0]["type"] = "flow"
            bad["segments"][0]["template"] = "seg_nope.scad"
            bad["segments"][0]["narration"] = []
            bad["segments"][0]["model"] = "model/missing.scad"
            problems = " | ".join(storyboard.validate(paths, bad))
            self.assertIn("未知类型", problems)
            self.assertIn("缺少旁白", problems)
            self.assertIn("模型不存在", problems)
            self.assertIn("模板不存在", problems)

    def test_validate_flags_an_empty_storyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = config.project_paths(tmp)
            self.assertTrue(storyboard.validate(paths, {}))
            self.assertIn("没有任何段落", storyboard.validate(paths, {"segments": []})[0])

    def test_instantiate_puts_parameters_before_the_model(self):
        text = storyboard.instantiate_source("seg_turntable.scad", "device.scad",
                                             "#MODEL_BODY\ndevice();\n",
                                             "$vpr = [0, 0, 0];\ndevice();\n",
                                             {"SET_SLIDE": "900", "TURNS": "2"})
        self.assertLess(text.index("SET_SLIDE = 900;"), text.index("#MODEL_BODY"))
        self.assertLess(text.index("TURNS = 2;"), text.index("#MODEL_BODY"))
        self.assertEqual(text.count("#MODEL_BODY"), 1)

    def test_frame_fingerprint_tracks_everything_that_changes_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write(Path(tmp) / "seg.scad", "device();\n")
            base = storyboard.frame_fingerprint(source, {"TURNS": "1"}, SETTINGS)
            self.assertEqual(base, storyboard.frame_fingerprint(source, {"TURNS": "1"}, SETTINGS))
            self.assertNotEqual(base, storyboard.frame_fingerprint(source, {"TURNS": "2"}, SETTINGS))
            write(source, "device();\n// 模型改了\n")
            self.assertNotEqual(base, storyboard.frame_fingerprint(source, {"TURNS": "1"}, SETTINGS))
            write(source, "device();\n")
            coarser = dict(SETTINGS, render_size="640,480")
            self.assertNotEqual(base, storyboard.frame_fingerprint(source, {"TURNS": "1"}, coarser))


class KinematicsTests(unittest.TestCase):
    PARAMS = {"hinge": [0, 0], "node_r": 800, "rod_z": 400,
              "collar_up_z": 700, "collar_dn_z": 100, "anchor_z": 60}

    def test_pulling_the_rod_compresses_the_damper(self):
        rest = check_kinematics.solve(self.PARAMS, 0, 0)
        pulled = check_kinematics.solve(self.PARAMS, 0, 300)
        self.assertAlmostEqual(rest["damper"], 0.0, places=6)
        self.assertLess(pulled["damper"], 0.0)
        # 拉得越远压得越狠：单调性保证动画不会来回抖
        self.assertLess(check_kinematics.solve(self.PARAMS, 0, 600)["damper"],
                        pulled["damper"])

    def test_match_accepts_the_drawing_labels_and_rejects_the_opposite(self):
        result = check_kinematics.solve(self.PARAMS, -8, 90)
        labels = {"spring1": "stretch", "spring2": "stretch",
                  "spring3": "compress", "damper": "compress"}
        ok, detail = check_kinematics.match(result, labels)
        self.assertTrue(ok, detail)
        wrong, _ = check_kinematics.match(result, {"damper": "stretch"})
        self.assertFalse(wrong)


class DrawingVerificationTests(unittest.TestCase):
    def test_drawing_map_parsing(self):
        self.assertEqual(verify.parse_drawing_map("front=立面.png, top=平面.dxf"),
                         {"front": "立面.png", "top": "平面.dxf"})
        self.assertEqual(verify.parse_drawing_map(None), {})
        with self.assertRaises(ValueError):
            verify.parse_drawing_map("front立面.png")

    def test_minimal_dxf_reader_extracts_common_entities(self):
        dxf = "\n".join([
            "0", "SECTION", "2", "ENTITIES",
            "0", "LINE", "8", "0",
            "10", "0.0", "20", "0.0", "11", "100.0", "21", "50.0",
            "0", "LWPOLYLINE", "8", "0", "90", "3", "70", "1",
            "10", "0.0", "20", "0.0", "10", "10.0", "20", "0.0", "10", "10.0", "20", "10.0",
            "0", "CIRCLE", "8", "0", "10", "5.0", "20", "5.0", "40", "2.5",
            "0", "ARC", "8", "0", "10", "0.0", "20", "0.0", "40", "5.0",
            "50", "0.0", "51", "90.0",
            "0", "ENDSEC", "0", "EOF",
        ])
        polylines = verify.dxf_polylines_minimal(dxf)
        self.assertEqual(len(polylines), 4)
        self.assertEqual(len(polylines[0]), 2)                     # LINE
        self.assertEqual(len(polylines[1]), 4)                     # 闭合 LWPOLYLINE
        self.assertEqual(polylines[1][0], polylines[1][-1])
        self.assertGreater(len(polylines[2]), 8)                    # CIRCLE 采样
        self.assertGreater(len(polylines[3]), 3)                    # ARC 采样

    def test_arc_and_circle_sampling_endpoints(self):
        circle = verify.sample_circle(0.0, 0.0, 10.0, steps=8)
        self.assertAlmostEqual(circle[0][0], 10.0, places=6)
        self.assertAlmostEqual(circle[-1][0], circle[0][0], places=6)
        arc = verify.sample_arc(0.0, 0.0, 10.0, 0.0, 90.0)
        self.assertAlmostEqual(arc[0][0], 10.0, places=6)
        self.assertAlmostEqual(arc[-1][1], 10.0, places=6)
        # 起止角写反（350°→10°）也要绕过去，而不是返回一条零长线段
        wrapped = verify.sample_arc(0.0, 0.0, 10.0, 350.0, 10.0)
        self.assertGreater(len(wrapped), 3)

    def test_to_math_coords_flips_the_svg_y_axis(self):
        self.assertEqual(verify.to_math_coords([[(1.0, 2.0), (3.0, 4.0)]]),
                         [[(1.0, -2.0), (3.0, -4.0)]])

    def test_normalise_keeps_aspect_ratio_and_fits_the_canvas(self):
        rectangle = [[(10.0, 10.0), (210.0, 10.0), (210.0, 110.0), (10.0, 110.0), (10.0, 10.0)]]
        mapped = verify.normalise_polylines(rectangle, size=400, margin=50)
        points = [point for line in mapped for point in line]
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        self.assertGreaterEqual(min(xs), 49.0)
        self.assertLessEqual(max(xs), 351.0)
        self.assertGreaterEqual(min(ys), 49.0)
        self.assertLessEqual(max(ys), 351.0)
        self.assertAlmostEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 2.0, places=3)

    def test_rasterize_draws_ink_for_a_rectangle(self):
        rectangle = [[(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0), (0.0, 0.0)]]
        image = verify.rasterize(rectangle, size=300, margin=20)
        self.assertGreater(verify.ink_pixels(image), 100)
        self.assertIsNotNone(verify.ink_bbox(image))

    def test_matching_masks_score_high_and_shifted_masks_stay_tolerated(self):
        straight = [[(80, 150), (220, 150)]]
        same = verify.compare_masks(mask(segments=straight), mask(segments=straight))
        self.assertGreaterEqual(same["coverage_model"], 0.99)
        self.assertGreaterEqual(same["iou"], 0.99)
        shifted = verify.compare_masks(mask(segments=straight),
                                       mask(segments=[[(82, 150), (222, 150)]]))
        self.assertGreaterEqual(shifted["coverage_model"], 0.99)
        far = verify.compare_masks(mask(segments=straight),
                                   mask(segments=[[(80, 40), (220, 40)]]))
        self.assertLess(far["coverage_model"], 0.1)

    def test_trim_frame_removes_a_sheet_border(self):
        bordered = mask(size=200, segments=[])
        ImageDraw.Draw(bordered).rectangle([0, 0, 199, 199], outline=0, width=4)
        ImageDraw.Draw(bordered).line([(60, 100), (140, 100)], fill=0, width=3)
        trimmed = verify.trim_frame(bordered)
        self.assertLess(trimmed.size[0], bordered.size[0])
        self.assertLess(trimmed.size[1], bordered.size[1])
        self.assertIsNotNone(verify.ink_bbox(trimmed))

    def test_prepare_ink_rejects_a_blank_picture(self):
        blank = Image.new("RGB", (400, 400), "white")
        self.assertIsNone(verify.prepare_ink(blank, size=300, margin=20))
        drawing = Image.new("RGB", (400, 400), "white")
        ImageDraw.Draw(drawing).line([(50, 50), (350, 300)], fill="black", width=5)
        prepared = verify.prepare_ink(drawing, size=300, margin=20)
        self.assertIsNotNone(prepared)
        self.assertGreater(verify.ink_pixels(prepared), 50)

    def test_view_defines_parsing(self):
        self.assertEqual(verify.parse_view_defines("front=SET_THETA=90; top=SET_THETA=0"),
                         {"front": {"SET_THETA": "90"}, "top": {"SET_THETA": "0"}})
        self.assertEqual(verify.parse_view_defines(None), {})
        with self.assertRaises(ValueError):
            verify.parse_view_defines("front=90")           # 缺 K=V 的第二段
        with self.assertRaises(ValueError):
            verify.parse_view_defines("front")              # 缺 view=K=V

    def test_crop_parsing(self):
        self.assertEqual(verify.parse_crop_map("front=0.05,0.1,0.95,0.85; top=0.1,0.1,0.9,0.9"),
                         {"front": (0.05, 0.1, 0.95, 0.85),
                          "top": (0.1, 0.1, 0.9, 0.9)})
        self.assertEqual(verify.parse_crop_map(None), {})
        self.assertEqual(verify.parse_crop_box("0.1,0.1,0.9,0.9"), (0.1, 0.1, 0.9, 0.9))
        self.assertIsNone(verify.parse_crop_box(None))
        with self.assertRaises(ValueError):
            verify.parse_crop_box("0.1,0.1,0.9")            # 缺坐标
        with self.assertRaises(ValueError):
            verify.parse_crop_box("0.9,0.1,0.1,0.9")        # x0 >= x1

    def test_crop_mask_keeps_the_subject_and_drops_the_label(self):
        drawing = Image.new("L", (400, 400), 255)
        draw = ImageDraw.Draw(drawing)
        draw.rectangle([120, 120, 280, 280], outline=0, width=4)   # 主体
        draw.point((20, 20), fill=0)                               # 标注（包围盒角落）
        draw.point((30, 26), fill=0)
        prepared = verify.prepare_ink(drawing, size=300, margin=20)
        self.assertIsNotNone(prepared)
        cropped = verify.crop_mask(prepared, (0.2, 0.2, 0.8, 0.8), size=300)
        box = verify.ink_bbox(cropped)
        self.assertIsNotNone(box)
        # 裁剪后内容重铺居中：边缘留白而非贴着角落的标注
        self.assertGreater(box[0], 5)
        self.assertGreater(box[1], 5)
        # 未裁剪时是原样返回
        self.assertIs(verify.crop_mask(prepared, None, size=300), prepared)

    def test_span_and_aspect_helpers(self):
        rectangle = [[(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0)]]
        self.assertEqual(verify.span_of(rectangle), (200.0, 100.0))
        self.assertAlmostEqual(verify.aspect_of(rectangle), 2.0)
        self.assertIsNone(verify.span_of([]))
        self.assertEqual(verify.relative_error(1.0, 2.0), 0.5)
        self.assertIsNone(verify.relative_error(None, 2.0))


class LineartTests(unittest.TestCase):
    def test_wrapper_defines_merge_settings_and_overrides(self):
        merged = lineart.wrapper_defines(SETTINGS, {"SET_SLIDE": "900", "EXTRA": "1"})
        self.assertEqual(merged["SET_FN"], str(SETTINGS["scad_fn"]))
        self.assertEqual(merged["SET_COIL_SEG"], str(SETTINGS["scad_coil_seg"]))
        self.assertEqual(merged["SET_SLIDE"], "900")
        self.assertEqual(merged["EXTRA"], "1")
        # 用户传入的 SET_FN 覆盖设置里的默认值
        self.assertEqual(lineart.wrapper_defines(SETTINGS, {"SET_FN": "8"})["SET_FN"], "8")

    def test_wrapper_writes_defines_before_the_model_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            model = write(temp / "device.scad", "#MODEL_BODY\ndevice();\n")
            wrapper = lineart.wrap_model(model, lineart.VIEW_ROTATIONS["front"], temp,
                                         {"SET_BASE_L": "2000"}, tag="t")
            text = wrapper.read_text(encoding="utf-8")
            self.assertLess(text.index("SET_BASE_L = 2000;"), text.index("#MODEL_BODY"))
            self.assertIn("projection(cut = false)", text)

    def test_known_views_are_available(self):
        for view in ("front", "back", "side", "top", "bottom"):
            self.assertIn(view, lineart.VIEW_ROTATIONS)

    def test_top_view_gets_an_auto_section_cut(self):
        jobs = lineart.build_jobs(["front", "top"], None, 0, 1,
                                  lambda: (0.0, 100.0))
        by_view = [(job["view"], job["cut"], job["cut_z"]) for job in jobs]
        self.assertIn(("front", False, None), by_view)
        # top 视图默认带一个水平剖切，剖切面在 Z≈60（0.4+0.4/2）
        self.assertIn(("top", False, None), by_view)
        cuts = [job for job in jobs if job["view"] == "top" and job["cut"]]
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0]["cut_z"], 60.0)

    def test_no_auto_section_when_extent_unavailable(self):
        jobs = lineart.build_jobs(["top"], None, 0, 1, lambda: None)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["suffix"], "")

    def test_top_section_off_and_explicit_sections_keep_old_behaviour(self):
        jobs = lineart.build_jobs(["front", "top"], None, 2, 0,
                                  lambda: (0.0, 100.0))
        cuts = [j for j in jobs if j["cut"]]
        # 显式 --sections=2 对每个视图都加；--top-section=0 不加额外剖切
        self.assertEqual(len(cuts), 2 * 2)
        self.assertEqual(sorted(j["view"] for j in cuts), ["front", "front", "top", "top"])

    def test_exploded_jobs_are_added_per_view(self):
        jobs = lineart.build_jobs(["front", "top"], 300.0, 0, 0, lambda: None)
        suffixes = [j["suffix"] for j in jobs]
        self.assertEqual(suffixes.count("_exploded"), 2)


class RenderGuardTests(unittest.TestCase):
    def test_is_blank_detects_empty_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "blank.png"
            Image.new("RGB", (200, 200), "white").save(blank)
            self.assertTrue(openscad_run.is_blank(blank))
            drawn = Path(tmp) / "drawn.png"
            image = Image.new("RGB", (200, 200), "white")
            ImageDraw.Draw(image).rectangle([40, 40, 160, 160], fill="#2F5FA8")
            image.save(drawn)
            self.assertFalse(openscad_run.is_blank(drawn))

    def test_inline_model_strips_only_the_trailing_default_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = write(Path(tmp) / "device.scad",
                          "module device() { cube(1); }\ndevice();\n// 尾部注释\n")
            inlined = openscad_run.inline_model(model)
            self.assertNotIn("\ndevice();", inlined)
            self.assertIn("// 尾部注释", inlined)

    def test_camera_arg_matches_the_preset_table(self):
        self.assertEqual(openscad_run.camera_arg("front"), "0,0,0,90,0,0,0")
        with self.assertRaises(KeyError):
            openscad_run.camera_arg("no-such-angle")

    def test_close_angle_exists_and_carries_a_camera_distance(self):
        self.assertIn("front-right-top-iso-close", openscad_run.ANGLES)
        self.assertTrue(openscad_run.camera_arg("front-right-top-iso-close", 2000)
                        .endswith(",2000"))
        # 未给 dist 时保持 viewall 语义（兼容旧调用）
        self.assertTrue(openscad_run.camera_arg("front-right-top-iso-close").endswith(",0"))

    def test_inline_defines_wrapper_puts_assignments_before_the_model(self):
        from openscad_run import inline_render_source

        with tempfile.TemporaryDirectory() as tmp:
            model = write(Path(tmp) / "device.scad",
                          "module device() { cube(1); }\ndevice();\n")
            wrapper, handle = inline_render_source(model, {"SET_MONO": "true"})
            try:
                text = wrapper.read_text(encoding="utf-8")
                self.assertLess(text.index("SET_MONO = true;"), text.index("module device"))
            finally:
                if handle:
                    handle.cleanup()


class MechanismCheckTests(unittest.TestCase):
    def test_parse_vector_extracts_numbers(self):
        self.assertEqual(check_mechanism.parse_vector("[1.0, 2.0]"), [1.0, 2.0])
        self.assertEqual(check_mechanism.parse_vector("[14991.9, 14783.1]"),
                         [14991.9, 14783.1])
        self.assertEqual(check_mechanism.parse_vector("[-1.5e3, 2.25E2]"), [-1500.0, 225.0])
        self.assertIsNone(check_mechanism.parse_vector("[undef, undef]"))

    def test_dist_to_segment(self):
        self.assertAlmostEqual(check_mechanism.dist_to_segment((5, 5), (0, 0), (10, 0)), 5.0)
        self.assertAlmostEqual(check_mechanism.dist_to_segment((5, 0), (0, 0), (10, 0)), 0.0)
        # 投影在端点外时取到端点的距离
        self.assertAlmostEqual(check_mechanism.dist_to_segment((15, 0), (0, 0), (10, 0)), 5.0)
        self.assertAlmostEqual(check_mechanism.dist_to_segment((1, 1, 1), (0, 0, 0), (0, 0, 0)),
                               math.sqrt(3.0), places=6)

    def test_on_segment_inside_and_outside(self):
        samples = {
            "B": [[5.0, 5.0], [6.0, 6.0]],
            "P": [[0.0, 0.0], [0.0, 0.0]],
            "E": [[10.0, 10.0], [10.0, 10.0]],
        }
        ok, details = check_mechanism.check_on_segment(
            samples, {"point": "B", "from": "P", "to": "E", "tol": 1.0}, 1.0)
        self.assertTrue(ok)
        self.assertTrue(all(d["dist"] <= 1.0 for d in details))
        # 第二个样本掉到线段外（到线距离 ~5.66）→ 断言失败
        bad = dict(samples, B=[[5.0, 5.0], [6.0, 14.0]])
        ok, details = check_mechanism.check_on_segment(
            bad, {"point": "B", "from": "P", "to": "E", "tol": 1.0}, 1.0)
        self.assertFalse(ok)

    def test_monotonic(self):
        self.assertTrue(check_mechanism.check_monotonic([1, 2, 3, 4], "increasing")[0])
        self.assertFalse(check_mechanism.check_monotonic([4, 3, 2, 1], "increasing")[0])
        self.assertTrue(check_mechanism.check_monotonic([4, 3, 2, 1], "decreasing")[0])
        self.assertTrue(check_mechanism.check_monotonic([1, 1, 1], "constant")[0])
        self.assertFalse(check_mechanism.check_monotonic([1, 1, 1], "increasing")[0])
        # 数值噪声容忍：1e-6 以内的小回摆不算破坏单调
        self.assertTrue(check_mechanism.check_monotonic([1, 2, 2.0000005, 3], "increasing")[0])
        self.assertTrue(check_mechanism.check_monotonic([1], "constant")[0])

    def test_length_bounds(self):
        ok, details = check_mechanism.check_length_bounds([10, 15, 20], {"min": 5, "max": 25})
        self.assertTrue(ok)
        self.assertTrue(all(d["ok"] for d in details))
        ok, _ = check_mechanism.check_length_bounds([10, 15, 30], {"min": 5, "max": 25})
        self.assertFalse(ok)

    def test_parse_config_validates_shape(self):
        good = {"param": {"name": "theta", "values": [0, 90]}, "points": {"B": "pivot_B"}}
        self.assertEqual(check_mechanism.parse_config(good), good)
        with self.assertRaises(ValueError):
            check_mechanism.parse_config({"points": {"B": "pivot_B"}})
        with self.assertRaises(ValueError):
            check_mechanism.parse_config({"param": {"name": "theta"}, "points": {}})


class StoryboardFastSettingsTests(unittest.TestCase):
    def test_fast_settings_lower_resolution_and_tessellation(self):
        fast = storyboard.fast_settings(SETTINGS)
        self.assertEqual(fast["render_size"], SETTINGS.get("fast_render_size", "960,720"))
        self.assertEqual(fast["scad_fn"], SETTINGS.get("fast_scad_fn", SETTINGS["scad_fn"]))
        self.assertNotEqual(fast["render_size"], SETTINGS["render_size"])
        # 其余设置保持不变（fps 等）
        self.assertEqual(fast["fps"], SETTINGS["fps"])

    def test_fast_settings_accept_custom_defaults(self):
        custom = dict(SETTINGS, fast_render_size="640,480", fast_scad_fn=12)
        fast = storyboard.fast_settings(custom)
        self.assertEqual(fast["render_size"], "640,480")
        self.assertEqual(fast["scad_fn"], 12)


class InstantiateGuardTests(unittest.TestCase):
    """1.3.0：模板默认保护行不得覆盖前置参数（THETA=90 → -10 的根因回归）。"""

    TEMPLATE = (
        "SET_FN = is_undef(SET_FN) ? 48 : SET_FN;\n"
        "THETA = is_undef(THETA) ? -10 : THETA;\n"
        "VPD   = is_undef(VPD) ? 150000 : VPD;\n"
        "device(theta = THETA * phase);\n"
    )

    def test_provided_param_guard_line_is_dropped(self):
        out = storyboard.instantiate_source("t", "m.scad", "module device() {}\n",
                                            self.TEMPLATE, {"THETA": "90"})
        self.assertNotIn("is_undef(THETA)", out)
        self.assertIn("THETA = 90;", out)

    def test_missing_param_keeps_template_default(self):
        out = storyboard.instantiate_source("t", "m.scad", "module device() {}\n",
                                            self.TEMPLATE, {"THETA": "90"})
        self.assertIn("is_undef(VPD)", out)          # 未提供 → 保留默认保护行

    def test_guard_line_with_comment_is_also_dropped(self):
        template = "THETA = is_undef(THETA) ? -10 : THETA;   // 默认微倾\n"
        out = storyboard.instantiate_source("t", "m.scad", "module device() {}\n",
                                            template, {"THETA": "90"})
        self.assertNotIn("is_undef(THETA)", out)

    def test_all_guards_dropped_when_all_params_provided(self):
        defines = {"THETA": "90", "PULL": "900", "T_LOAD": "0.25"}
        out = storyboard.instantiate_source("t", "m.scad", "module device() {}\n",
                                            self.TEMPLATE + "PULL = is_undef(PULL) ? 800 : PULL;\n"
                                            "T_LOAD = is_undef(T_LOAD) ? 0.20 : T_LOAD;\n",
                                            defines)
        for key in defines:
            self.assertNotIn(f"is_undef({key})", out)


class SkeletonTests(unittest.TestCase):
    """1.3.0：sketch_to_skeleton 视图标注 → 骨架。"""

    VIEWS = {
        "平面": {"w": 1000, "h": 500, "n": 2,
                 "bb": [0, 0, 1000, 500],
                 "labels": [[200, 100, "面板"], [300, 400, "A-A（水坝状态）"]]},
        "立面": {"w": 1000, "h": 800, "n": 1,
                 "bb": [0, 0, 1000, 800],
                 "labels": [[250, 300, "面板"]]},
    }

    def test_title_labels_are_filtered_out(self):
        self.assertTrue(sketch_to_skeleton.is_title_label("A-A（水坝状态）"))
        self.assertTrue(sketch_to_skeleton.is_title_label("B-B（桥梁状态）"))
        self.assertFalse(sketch_to_skeleton.is_title_label("撑杆"))

    def test_parts_are_clustered_across_views(self):
        skeleton = sketch_to_skeleton.build_skeleton(Path("proj"), self.VIEWS)
        names = [p["name"] for p in skeleton["parts"]]
        self.assertIn("面板", names)
        self.assertNotIn("A-A（水坝状态）", names)
        panel = next(p for p in skeleton["parts"] if p["name"] == "面板")
        self.assertEqual(sorted(panel["views"]), ["平面", "立面"])
        self.assertIn(panel["main_view"], ["平面", "立面"])   # 同出现次数无主次
        # 归一化位置为两视图均值
        self.assertAlmostEqual(panel["x_norm"], (200 / 1000 + 250 / 1000) / 2, places=3)
        self.assertEqual(skeleton["overall"]["x_span"], 1000)
        self.assertEqual(skeleton["overall"]["z_height"], 800)


class InterferenceTests(unittest.TestCase):
    """1.3.0：check_interference 包围盒重叠与分档。"""

    def test_box_overlap_zero_when_disjoint(self):
        a = {"min": [0, 0, 0], "max": [10, 10, 10]}
        b = {"min": [20, 0, 0], "max": [30, 10, 10]}
        overlap, smaller = check_interference.box_overlap(a, b)
        self.assertEqual(overlap, 0.0)
        self.assertGreater(smaller, 0)

    def test_box_overlap_full_nesting(self):
        a = {"min": [0, 0, 0], "max": [100, 100, 100]}
        b = {"min": [20, 20, 20], "max": [80, 80, 80]}
        overlap, smaller = check_interference.box_overlap(a, b)
        self.assertAlmostEqual(overlap, 60 ** 3)
        self.assertAlmostEqual(smaller, 60 ** 3)

    def test_group_names_cover_all_submodules(self):
        self.assertEqual(len(check_interference.SUBMODULES), 12)
        self.assertNotIn("river_bottom", check_interference.SUBMODULES)  # 底板排除


class ParamCheckTests(unittest.TestCase):
    """1.3.0：param_check 尺寸报告。"""

    def test_box_report_derives_volume(self):
        result = {"bounding_box": {"min": [0, 0, 0], "max": [10, 20, 30]},
                  "dimensions": {"x": 10, "y": 20, "z": 30}, "facets": 42}
        report = param_check.box_report(result)
        self.assertEqual(report["volume_mm3"], 6000)
        self.assertEqual(report["facets"], 42)


class ConfigImportScanTests(unittest.TestCase):
    def test_scan_script_imports_finds_third_party_dependencies(self):
        deps = config.scan_script_imports(SCRIPTS)
        self.assertIn("numpy", deps)
        self.assertIn("final_film.py", deps["numpy"])
        self.assertIn("PIL", deps)
        self.assertNotIn("os", deps)            # 标准库不报告
        self.assertNotIn("re", deps)

    def test_detect_deps_reports_missing_imports_key(self):
        report = config.detect_deps()
        self.assertIsInstance(report["script_imports"], dict)
        self.assertIsInstance(report["missing_imports"], dict)
        # 本机常见的缺失项（olefile/ezdxf 等）会出现在警告里
        joined = "\n".join(report["warnings"])
        self.assertIn("脚本依赖但未安装", joined)


class RepositoryInvariantTests(unittest.TestCase):
    def test_version_is_consistent_across_skill_changelog_and_config(self):
        frontmatter = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        skill_version = re.search(r'version:\s*"([^"]+)"', frontmatter).group(1)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        latest = re.search(r"^##\s*\[([^\]]+)\]", changelog, re.MULTILINE).group(1)
        self.assertEqual(skill_version, config.VERSION)
        self.assertEqual(latest, config.VERSION)
        example = json.loads((ROOT / "assets/example_simple/project.json").read_text("utf-8"))
        self.assertEqual(example["version"], config.VERSION)

    def test_scripts_named_in_skill_md_exist(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        referenced = set(re.findall(r"scripts/([A-Za-z0-9_]+\.(?:py|ps1))", text))
        self.assertTrue(referenced)
        missing = sorted(name for name in referenced if not (SCRIPTS / name).is_file())
        self.assertEqual(missing, [])

    def test_no_crlf_in_the_git_index(self):
        if shutil.which("git") is None:
            self.skipTest("git 不可用")
        result = subprocess.run(["git", "ls-files", "--eol"], cwd=ROOT,
                                capture_output=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            self.skipTest("不是 git 检出目录")
        offenders = [line for line in result.stdout.splitlines()
                     if line.split()[0] in ("i/crlf", "i/mixed")]
        self.assertEqual(offenders, [], "索引里存在 CRLF 文件，请检查 .gitattributes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
