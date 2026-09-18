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
import config  # noqa: E402
import lineart  # noqa: E402
import narration  # noqa: E402
import openscad_run  # noqa: E402
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
