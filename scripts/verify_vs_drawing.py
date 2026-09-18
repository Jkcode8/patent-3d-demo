"""Overlay a model's orthographic projection on the original drawing.

The modelling stage has one failure mode that no other check catches: the model
is manifold, renders fine, and still does not match the drawing — wrong
proportions, a missing member, a mirrored bracket.  This script projects the
model the way ``lineart.py`` does, loads the original CAD drawing (DXF / SVG /
PNG / JPG), brings both to a common frame and reports how well they agree.

    model.scad --OpenSCAD projection--> SVG polylines --\\
                                                          >-- normalise to the
    drawing.dxf|svg|png|jpg --> line art or ink mask ----/    ink bounding box
                                                                  |
                                    overlay PNG + metrics JSON <---+

Both sides are normalised to their own ink bounding box before comparing, so the
report measures **shape**: aspect-ratio error, how much of the model outline
lands on drawing ink (coverage), and mask IoU.  Absolute scale is deliberately
not judged — a drawing can be printed at any size — and dimensioned values still
need a human.  The report carries that ``caveat`` explicitly.

Usage:
    python verify_vs_drawing.py --project <项目> --views front,top [--json]
    python verify_vs_drawing.py --model model/device.scad --drawing 立面.dxf \\
        --out-dir figures/核对 --views front [--json]
    python verify_vs_drawing.py --project <项目> \\
        --drawing-map front=立面.png,top=平面.png

Exit code is 0 only when every requested view passes (``--no-fail`` downgrades
that to a warning for exploratory use).
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from config import find_openscad, load_settings, project_paths, read_json, write_json
from lineart import VIEW_ROTATIONS, svg_polylines, wrap_model, wrapper_defines
from openscad_run import run_cli

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
VECTOR_SUFFIXES = {".dxf", ".svg"}
LOOKUP_ORDER = [".dxf", ".svg", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"]
CAVEAT = (
    "按包围盒归一化后比对轮廓与比例：能发现比例失真、构件缺失或多余，"
    "但绝对尺寸与标注数值仍需人工核对（图纸可能非等比例打印）。"
)
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


# ------------------------------------------------------------------ 输入解析
def parse_drawing_map(spec: str | None) -> dict[str, str]:
    """``"front=立面.png, top=平面.png"`` → ``{"front": "立面.png", ...}``."""
    if not spec:
        return {}
    mapping: dict[str, str] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"--drawing-map 需要 view=路径 的形式，收到 {item!r}")
        view, path = item.split("=", 1)
        view, path = view.strip(), path.strip()
        if not view or not path:
            raise ValueError(f"--drawing-map 条目不完整：{item!r}")
        mapping[view] = path
    return mapping


def find_drawings(root: Path) -> list[Path]:
    """Candidate drawings under 原始资料/ and _extract/, vector formats first."""
    found: list[Path] = []
    seen: set[Path] = set()
    for folder in ("原始资料", "_extract"):
        base = root / folder
        if not base.is_dir():
            continue
        for suffix in LOOKUP_ORDER:
            for path in sorted(base.rglob(f"*{suffix}")):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    found.append(path)
    return found


# ------------------------------------------------------------------ 几何工具
def bounds(polylines: list[list[tuple[float, float]]]
           ) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for line in polylines:
        for x, y in line:
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def span_of(polylines: list[list[tuple[float, float]]]) -> tuple[float, float] | None:
    box = bounds(polylines)
    if box is None:
        return None
    return box[2] - box[0], box[3] - box[1]


def aspect_of(polylines: list[list[tuple[float, float]]]) -> float | None:
    span = span_of(polylines)
    if span is None:
        return None
    width, height = span
    if height <= 0:
        return None
    return width / height


def relative_error(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return abs(a - b) / max(a, b)


def to_math_coords(polylines: list[list[tuple[float, float]]]
                   ) -> list[list[tuple[float, float]]]:
    """Convert y-down (SVG) coordinates to y-up, the frame DXF and OpenSCAD use.

    Mixing the two conventions silently mirrors one side of the comparison; both
    the model projection and an SVG drawing are converted here so that a genuine
    mirror error in the model still shows up as a mismatch instead of cancelling
    out.
    """
    return [[(x, -y) for x, y in line] for line in polylines]


def sample_circle(cx: float, cy: float, radius: float, steps: int = 48
                  ) -> list[tuple[float, float]]:
    return [(cx + radius * math.cos(2 * math.pi * i / steps),
             cy + radius * math.sin(2 * math.pi * i / steps)) for i in range(steps + 1)]


def sample_arc(cx: float, cy: float, radius: float, start_deg: float, end_deg: float,
               steps: int = 36) -> list[tuple[float, float]]:
    """Arc through *start* → *end* degrees, going counter-clockwise (DXF convention)."""
    if end_deg <= start_deg:
        end_deg += 360.0
    span = end_deg - start_deg
    count = max(4, int(steps * span / 360.0))
    return [(cx + radius * math.cos(math.radians(start_deg + span * i / count)),
             cy + radius * math.sin(math.radians(start_deg + span * i / count)))
            for i in range(count + 1)]


def dxf_polylines_minimal(text: str) -> list[list[tuple[float, float]]]:
    """Parse LINE/LWPOLYLINE/POLYLINE/CIRCLE/ARC from ASCII DXF without ezdxf."""
    lines = [line.strip() for line in text.splitlines()]
    entities: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] | None = None
    for index in range(0, len(lines) - 1, 2):
        try:
            code = int(lines[index])
        except ValueError:
            continue
        value = lines[index + 1]
        if code == 0:
            current = [(code, value)]
            entities.append(current)
        elif current is not None:
            current.append((code, value))

    polylines: list[list[tuple[float, float]]] = []
    pending: list[tuple[float, float]] = []
    pending_closed = False

    def flush_pending() -> None:
        if len(pending) > 1:
            points = list(pending)
            if pending_closed:
                points.append(points[0])
            polylines.append(points)
        pending.clear()

    for entity in entities:
        kind = entity[0][1].upper()
        codes: dict[int, list[str]] = {}
        for code, value in entity[1:]:
            codes.setdefault(code, []).append(value)

        def number(code: int, default: float = 0.0, index: int = 0) -> float:
            values = codes.get(code) or []
            try:
                return float(values[index])
            except (IndexError, ValueError):
                return default

        if kind == "VERTEX":
            pending.append((number(10), number(20)))
            continue
        if kind in ("SEQEND", "ENDSEC", "EOF"):
            flush_pending()
            continue
        flush_pending()
        if kind == "LINE":
            polylines.append([(number(10), number(20)), (number(11), number(21))])
        elif kind == "LWPOLYLINE":
            xs = [float(v) for v in codes.get(10, []) if _is_number(v)]
            ys = [float(v) for v in codes.get(20, []) if _is_number(v)]
            points = list(zip(xs, ys))
            if len(points) > 1:
                if int(number(70)) & 1:
                    points.append(points[0])
                polylines.append(points)
        elif kind == "POLYLINE":
            pending_closed = bool(int(number(70)) & 1)
        elif kind == "CIRCLE":
            polylines.append(sample_circle(number(10), number(20), number(40)))
        elif kind == "ARC":
            polylines.append(sample_arc(number(10), number(20), number(40),
                                        number(50), number(51)))
    flush_pending()
    return polylines


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def dxf_polylines_ezdxf(path: Path) -> list[list[tuple[float, float]]]:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    polylines: list[list[tuple[float, float]]] = []
    for space in [doc.modelspace()] + [layout for layout in doc.layouts
                                       if layout.name.lower() != "model"]:
        for entity in space:
            kind = entity.dxftype()
            try:
                if kind == "LINE":
                    start, end = entity.dxf.start, entity.dxf.end
                    polylines.append([(start.x, start.y), (end.x, end.y)])
                elif kind == "LWPOLYLINE":
                    points = [(p[0], p[1]) for p in entity.get_points()]
                    if len(points) > 1:
                        polylines.append(points + [points[0]] if entity.closed else points)
                elif kind == "POLYLINE":
                    points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                    if len(points) > 1:
                        polylines.append(points + [points[0]] if entity.is_closed else points)
                elif kind == "CIRCLE":
                    centre = entity.dxf.center
                    polylines.append(sample_circle(centre.x, centre.y, entity.dxf.radius))
                elif kind == "ARC":
                    centre = entity.dxf.center
                    polylines.append(sample_arc(centre.x, centre.y, entity.dxf.radius,
                                                entity.dxf.start_angle, entity.dxf.end_angle))
                elif kind in ("SPLINE", "ELLIPSE"):
                    points = [(p.x, p.y) for p in entity.flattening(0.5)]
                    if len(points) > 1:
                        polylines.append(points)
            except Exception:  # 单个实体异常不应让整张图失败
                continue
    return polylines


def dxf_polylines(path: Path) -> list[list[tuple[float, float]]]:
    try:
        polylines = dxf_polylines_ezdxf(path)
        if polylines:
            return polylines
    except ImportError:
        pass
    except Exception:
        pass
    return dxf_polylines_minimal(path.read_text(encoding="utf-8", errors="replace"))


# ------------------------------------------------------------------ 栅格化
def normalise_polylines(polylines: list[list[tuple[float, float]]], size: int,
                        margin: int) -> list[list[tuple[float, float]]]:
    """Fit polylines into a ``size``×``size`` box, preserving aspect ratio."""
    box = bounds(polylines)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    span_x, span_y = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    scale = min((size - 2 * margin) / span_x, (size - 2 * margin) / span_y)
    off_x = (size - span_x * scale) / 2
    off_y = (size - span_y * scale) / 2
    return [[((x - x0) * scale + off_x, (y1 - y) * scale + off_y) for x, y in line]
            for line in polylines]


def rasterize(polylines: list[list[tuple[float, float]]], size: int = 1400,
              margin: int = 90, width: int = 3) -> Image.Image:
    """Draw polylines as black ink on white, bbox-normalised.  Ink is 0."""
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    for line in normalise_polylines(polylines, size, margin):
        if len(line) >= 2:
            draw.line(line, fill=0, width=width, joint="curve")
        elif line:
            x, y = line[0]
            draw.rectangle([x - 1, y - 1, x + 1, y + 1], fill=0)
    return image


def trim_frame(mask: Image.Image, ratio: float = 0.55) -> Image.Image:
    """Drop a drawing border/title frame: rows or columns that are nearly solid ink.

    Scanned or exported sheets usually carry a border plus a title block; left in
    place they define the bounding box and swamp the comparison.  Iteratively
    peeling solid edge rows/columns removes the frame while keeping the drawing.
    Expects and returns a canonical mask (ink is 0, background 255).
    """
    width, height = mask.size
    if width < 4 or height < 4:
        return mask
    pixels = mask.load()

    def row_ink(y: int) -> float:
        return sum(1 for x in range(width) if pixels[x, y] < 128) / width

    def column_ink(x: int) -> float:
        return sum(1 for y in range(height) if pixels[x, y] < 128) / height

    top, bottom, left, right = 0, height - 1, 0, width - 1
    while top < bottom and row_ink(top) >= ratio:
        top += 1
    while bottom > top and row_ink(bottom) >= ratio:
        bottom -= 1
    while left < right and column_ink(left) >= ratio:
        left += 1
    while right > left and column_ink(right) >= ratio:
        right -= 1
    if (top, bottom, left, right) == (0, height - 1, 0, width - 1):
        return mask
    return mask.crop((left, top, right + 1, bottom + 1))


def prepare_ink(image: Image.Image, size: int = 1400, margin: int = 90,
                threshold: int = 200, trim: bool = True) -> Image.Image | None:
    """Crop a drawing to its ink, scale it to fit the canvas.

    Returns a canonical mask (ink is 0, background 255) or ``None`` when the
    picture carries no detectable lines.
    """
    scale_up = max(1.0, size / max(image.size))
    if scale_up > 1.0:
        image = image.resize((int(image.width * scale_up), int(image.height * scale_up)),
                             Image.LANCZOS)
    ink = image.convert("L").point(lambda v: 0 if v < threshold else 255)
    if trim:
        ink = trim_frame(ink)
    box = ink_bbox(ink)
    if box is None:
        return None
    ink = ink.crop(box)
    span_x, span_y = max(ink.width, 1), max(ink.height, 1)
    scale = min((size - 2 * margin) / span_x, (size - 2 * margin) / span_y)
    target = (max(1, int(span_x * scale)), max(1, int(span_y * scale)))
    ink = ink.resize(target, Image.LANCZOS).point(lambda v: 0 if v < 150 else 255)
    canvas = Image.new("L", (size, size), 255)
    canvas.paste(ink, ((size - target[0]) // 2, (size - target[1]) // 2))
    return canvas


def ink_bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the *ink* of a canonical mask (ink is 0, background 255)."""
    return ImageChops.invert(mask.convert("L")).getbbox()


def ink_pixels(mask: Image.Image) -> int:
    """Number of ink pixels of a canonical mask (ink is 0, background 255)."""
    return mask.convert("L").histogram()[0]


def ink_bbox_span(mask: Image.Image) -> tuple[float, float] | None:
    box = ink_bbox(mask)
    if box is None:
        return None
    return float(box[2] - box[0]), float(box[3] - box[1])


def compare_masks(model_mask: Image.Image, drawing_mask: Image.Image,
                  tolerance: int = 4) -> dict:
    """Coverage/IoU of two ink masks, tolerant to a few pixels of line offset."""
    model_ink = model_mask.convert("L").point(lambda v: 255 if v < 128 else 0)
    drawing_ink = drawing_mask.convert("L").point(lambda v: 255 if v < 128 else 0)
    size = 2 * tolerance + 1
    model_near = model_ink.filter(ImageFilter.MaxFilter(size))
    drawing_near = drawing_ink.filter(ImageFilter.MaxFilter(size))
    # 这里的三张掩膜是「255＝墨迹」，与 canonical 相反，直接用直方图计数
    model_count = model_ink.histogram()[255]
    drawing_count = drawing_ink.histogram()[255]
    on_drawing = ImageChops.multiply(model_ink, drawing_near).histogram()[255]
    on_model = ImageChops.multiply(drawing_ink, model_near).histogram()[255]
    both = ImageChops.multiply(model_ink, drawing_ink).histogram()[255]
    union = model_count + drawing_count - both
    return {
        "coverage_model": round(on_drawing / model_count, 4) if model_count else 0.0,
        "coverage_drawing": round(on_model / drawing_count, 4) if drawing_count else 0.0,
        "iou": round(both / union, 4) if union else 0.0,
        "model_ink_px": model_count,
        "drawing_ink_px": drawing_count,
    }


def load_cjk_font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def comparison_sheet(drawing_mask: Image.Image, model_mask: Image.Image, size: int,
                     title: str, lines: list[str], ok: bool) -> Image.Image:
    """Three panels — 原图 | 模型投影 | 叠加 — with a metrics header."""
    gap, header = 24, 142
    width = size * 3 + gap * 4
    sheet = Image.new("RGB", (width, size + header + gap), "#f4f6f9")
    draw = ImageDraw.Draw(sheet)
    font = load_cjk_font(30)
    small = load_cjk_font(26)
    fonts = font or small

    grey = Image.new("RGB", (size, size), "white")
    grey.paste(Image.new("RGB", (size, size), "#7b8794"), (0, 0),
               drawing_mask.point(lambda v: 255 - v if v < 128 else 0))
    overlay = Image.new("RGB", (size, size), "white")
    overlay.paste(Image.new("RGB", (size, size), "#c7ccd4"), (0, 0),
                  drawing_mask.point(lambda v: 255 - v if v < 128 else 0))
    overlay.paste(Image.new("RGB", (size, size), "#d61f26"), (0, 0),
                  model_mask.point(lambda v: 255 - v if v < 128 else 0))
    model_rgb = Image.new("RGB", (size, size), "white")
    model_rgb.paste(Image.new("RGB", (size, size), "#2F5FA8"), (0, 0),
                    model_mask.point(lambda v: 255 - v if v < 128 else 0))

    panels = [("原图 drawing", grey), ("模型投影 model", model_rgb), ("叠加 overlay", overlay)]
    for index, (label, panel) in enumerate(panels):
        x = gap + index * (size + gap)
        sheet.paste(panel, (x, header))
        draw.rectangle([x, header, x + size - 1, header + size - 1], outline="#c2c8d0")
        draw.text((x + 12, header - 38), label, fill="#12304F", font=fonts)

    draw.text((gap, 16), title, fill="#12304F", font=fonts)
    draw.text((gap, 58), "   ".join(lines), fill="#1f7a3d" if ok else "#b3261e", font=small)
    return sheet


# ------------------------------------------------------------------ 主流程
def project_view(model: Path, view: str, defines: dict[str, str], settings: dict,
                 openscad: str, temp_dir: Path) -> tuple[list[list[tuple[float, float]]] | None, str]:
    rotation = VIEW_ROTATIONS.get(view)
    if rotation is None:
        return None, f"未知视角 {view}（可用：{', '.join(sorted(VIEW_ROTATIONS))}）"
    wrapper = wrap_model(model, rotation, temp_dir, wrapper_defines(settings, defines),
                         tag=f"verify_{view}")
    svg = temp_dir / f"verify_{view}.svg"
    argv = ["-o", str(svg), str(wrapper)]
    result = run_cli(openscad, argv, 600)
    if result.returncode != 0 or not svg.exists():
        return None, (result.stdout + result.stderr).strip()[-400:]
    polylines = svg_polylines(svg)
    if not polylines:
        return None, "投影未产生任何折线（模型可能为空或全在投影平面外）"
    return to_math_coords(polylines), ""


def drawing_side(path: Path, size: int, margin: int, trim: bool) -> tuple[dict, str]:
    """Return ``{"mask":…, "polylines":…, "kind":…}`` for one drawing file."""
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        polylines = dxf_polylines(path)
        if not polylines:
            return {}, "DXF 中未读到可用图元（LINE/LWPOLYLINE/POLYLINE/CIRCLE/ARC/SPLINE）"
        return {"kind": "dxf", "polylines": polylines,
                "mask": rasterize(polylines, size, margin)}, ""
    if suffix == ".svg":
        polylines = to_math_coords(svg_polylines(path))
        if not polylines:
            return {}, "SVG 中未读到 M/L 路径（曲线路径请先转成 DXF 或 PNG）"
        return {"kind": "svg", "polylines": polylines,
                "mask": rasterize(polylines, size, margin)}, ""
    if suffix in RASTER_SUFFIXES:
        try:
            image = Image.open(path)
            image.load()
        except Exception as error:  # 图片损坏或格式不支持
            return {}, f"无法读取图片：{error}"
        mask = prepare_ink(image, size, margin, trim=trim)
        if mask is None or ink_pixels(mask) == 0:
            return {}, "图片里没有检测到线条（阈值过严或图为空）"
        return {"kind": "raster", "polylines": None, "mask": mask}, ""
    return {}, f"不支持的图纸格式 {suffix}（支持 {', '.join(sorted(VECTOR_SUFFIXES | RASTER_SUFFIXES))}）"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="模型正投影 ↔ 原图 叠合核对（比例与轮廓自检）")
    parser.add_argument("--project", default=None, help="项目目录（默认当前目录）")
    parser.add_argument("--model", default=None, help="模型 .scad（默认 model/device.scad）")
    parser.add_argument("--drawing", default=None,
                        help="图纸文件（DXF/SVG/PNG/JPG）；auto=自动在 原始资料/ 里找")
    parser.add_argument("--drawing-map", default=None,
                        help="按视角指定图纸，如 front=立面.png,top=平面.png")
    parser.add_argument("--out-dir", default=None, help="输出目录（默认 figures/核对）")
    parser.add_argument("--views", default="front", help="视角，逗号分隔（front/top/side/…）")
    parser.add_argument("--define", action="append", default=[], help="传给模型的 -D 参数 K=V")
    parser.add_argument("--canvas", type=int, default=1400, help="比对画布边长（像素）")
    parser.add_argument("--min-coverage", type=float, default=0.6,
                        help="模型轮廓落在图纸线条上的最低比例（默认 0.6）")
    parser.add_argument("--max-aspect-error", type=float, default=0.06,
                        help="允许的长宽比相对偏差（默认 0.06＝6%%）")
    parser.add_argument("--no-trim", action="store_true",
                        help="图片图纸不做边框/图框自动裁除")
    parser.add_argument("--no-fail", action="store_true",
                        help="即使未通过也返回 0（探索性使用）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project).resolve() if args.project else Path.cwd()
    paths = project_paths(root)
    settings = load_settings(root)
    model = Path(args.model) if args.model else paths["model"] / "device.scad"
    if not model.is_absolute():
        model = (root / model) if (root / model).exists() else paths["model"] / model
    if not model.exists():
        raise SystemExit(f"模型不存在：{model}")
    openscad = find_openscad()
    if not openscad:
        raise SystemExit("未找到 OpenSCAD（硬依赖），请设置 OPENSCAD_EXECUTABLE")

    out_dir = Path(args.out_dir) if args.out_dir else paths["figures"] / "核对"
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        per_view = parse_drawing_map(args.drawing_map)
    except ValueError as error:
        raise SystemExit(str(error))

    candidates = find_drawings(root)
    if args.drawing and args.drawing != "auto":
        fallback = Path(args.drawing)
        if not fallback.is_absolute():
            fallback = (root / fallback) if (root / fallback).exists() else Path(args.drawing)
        if not fallback.exists():
            raise SystemExit(f"图纸不存在：{fallback}")
    elif args.drawing == "auto" or (not per_view and candidates):
        fallback = candidates[0] if candidates else None
    else:
        fallback = None
    if fallback is None and not per_view:
        raise SystemExit("没有可用的图纸：请用 --drawing <文件> 指定，"
                         f"或把图纸放进 {paths['sources']} 后重试")

    defines = dict(item.split("=", 1) for item in args.define)
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    title = (read_json(paths["storyboard"], {}) or {}).get("title", "") or model.stem

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="p3d_verify_") as tmp:
        temp_dir = Path(tmp)
        for view in views:
            entry: dict = {"view": view, "ok": False}
            drawing = per_view.get(view)
            drawing_path = Path(drawing) if drawing else fallback
            if drawing and not drawing_path.is_absolute() and not drawing_path.exists():
                drawing_path = root / drawing
            if drawing_path is None or not Path(drawing_path).exists():
                entry["error"] = f"视角 {view} 没有对应图纸"
                results.append(entry)
                continue
            drawing_path = Path(drawing_path)
            entry["drawing"] = str(drawing_path)

            polylines, error = project_view(model, view, defines, settings, openscad, temp_dir)
            if polylines is None:
                entry["error"] = f"模型投影失败：{error}"
                results.append(entry)
                continue
            model_mask = rasterize(polylines, args.canvas, 90)

            side, error = drawing_side(drawing_path, args.canvas, 90, not args.no_trim)
            if not side:
                entry["error"] = f"图纸解析失败：{error}"
                results.append(entry)
                continue
            entry["drawing_kind"] = side["kind"]

            drawing_span = (span_of(side["polylines"]) if side["polylines"]
                            else ink_bbox_span(side["mask"]))
            model_span = span_of(polylines)
            if not drawing_span or not model_span or min(model_span) <= 0 or min(drawing_span) <= 0:
                entry["error"] = "无法取得有效轮廓范围（模型或图纸尺寸为零）"
                results.append(entry)
                continue
            model_aspect = model_span[0] / model_span[1]
            drawing_aspect = drawing_span[0] / drawing_span[1]
            aspect_error = relative_error(model_aspect, drawing_aspect)
            metrics = compare_masks(model_mask, side["mask"])
            ok = (aspect_error is not None and aspect_error <= args.max_aspect_error
                  and metrics["coverage_model"] >= args.min_coverage)
            entry.update({
                "model_aspect": round(model_aspect, 4),
                "drawing_aspect": round(drawing_aspect, 4),
                "aspect_error": round(aspect_error, 4) if aspect_error is not None else None,
                **metrics,
                "ok": bool(ok),
                "caveat": CAVEAT,
            })
            lines = [
                f"aspect {model_aspect:.3f} vs {drawing_aspect:.3f}"
                f" (err {aspect_error * 100:.1f}%)",
                f"coverage {metrics['coverage_model'] * 100:.1f}%",
                f"IoU {metrics['iou'] * 100:.1f}%",
                "PASS" if ok else "CHECK",
            ]
            sheet = comparison_sheet(side["mask"], model_mask, args.canvas,
                                     f"{title} · {view} · {drawing_path.name}", lines, ok)
            target = out_dir / f"核对_{view}.png"
            sheet.save(target)
            entry["image"] = str(target)
            results.append(entry)

    payload = {
        "model": str(model),
        "drawings": {view: (per_view.get(view) or (str(fallback) if fallback else ""))
                     for view in views},
        "out_dir": str(out_dir),
        "thresholds": {"min_coverage": args.min_coverage,
                       "max_aspect_error": args.max_aspect_error},
        "views": results,
        "ok": all(r.get("ok") for r in results) and bool(results),
        "caveat": CAVEAT,
    }
    write_json(out_dir / "核对报告.json", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for entry in results:
            status = "OK  " if entry.get("ok") else "CHECK"
            if entry.get("error"):
                print(f"{entry['view']:6s} {status} {entry['error']}")
                continue
            print(f"{entry['view']:6s} {status} 长宽比 {entry['model_aspect']:.3f} vs "
                  f"{entry['drawing_aspect']:.3f}（偏差 {entry['aspect_error'] * 100:.1f}%）"
                  f"　轮廓覆盖率 {entry['coverage_model'] * 100:.1f}%"
                  f"　IoU {entry['iou'] * 100:.1f}%　→ {Path(entry['image']).name}")
        print(f"报告：{out_dir / '核对报告.json'}")
        if not payload["ok"]:
            print("提示：" + CAVEAT)
    if payload["ok"] or args.no_fail:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
