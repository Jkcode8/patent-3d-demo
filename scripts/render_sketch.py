"""Turn extracted CAD entities into readable PNG views (matplotlib).

Input:  <extract_dir>/cad_entities.csv + cad_text.txt  (from extract_dwg.ps1 or
        extract_dxf.py — both write the same format)
Output: <out_dir>/views/<name>.png  +  views/index.json

Views are detected automatically by clustering entities along X (drawing sheets
usually place 立面/平面/剖面 side by side); pass ``--views`` to override:

    --views "立面:90000,80000,160000,160000;平面:115000,18000,165000,82000"
    --views auto            (default)
    --views all             (single view of the whole sheet)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager, patches
from matplotlib import pyplot as plt

LINE_RE = re.compile(r"^\[(?P<space>[^\]]+)\]\s+(?P<body>.*)$")
POINT_RE = re.compile(r"(-?\d+\.?\d*),(-?\d+\.?\d*)")
TEXT_RE = re.compile(
    r"^\[(?P<space>[^\]]+)\]\s+(?P<x>-?\d+\.?\d*),(?P<y>-?\d+\.?\d*),-?\d+\.?\d*\s+::\s+(?P<text>.*)$"
)
MTEXT_TAG = re.compile(r"\{[^;]*;")


def font_properties() -> font_manager.FontProperties:
    for name in ("Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC",
                 "PingFang SC", "Arial Unicode MS"):
        try:
            path = font_manager.findfont(
                font_manager.FontProperties(family=name), fallback_to_default=False
            )
            return font_manager.FontProperties(fname=path)
        except Exception:
            continue
    return font_manager.FontProperties()


def parse_entities(path: Path) -> list[tuple[str, str]]:
    rows = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE_RE.match(raw.strip())
        if match:
            rows.append((match.group("space"), match.group("body")))
    return rows


def parse_texts(path: Path) -> list[tuple[float, float, str]]:
    rows = []
    if not path.exists():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TEXT_RE.match(raw.strip())
        if not match:
            continue
        label = MTEXT_TAG.sub("", match.group("text")).replace("}", "").replace("\\P", "\n")
        rows.append((float(match.group("x")), float(match.group("y")), label.strip()))
    return rows


def entity_points(body: str) -> list[tuple[float, float]]:
    head = body.split(",")[0].upper()
    if head == "LINE":
        nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", body)]
        return [(nums[0], nums[1]), (nums[3], nums[4])] if len(nums) >= 5 else []
    if head == "CIRCLE":
        match = re.search(r"c=(-?\d+\.?\d*),(-?\d+\.?\d*),(-?\d+\.?\d*),r=(-?\d+\.?\d*)", body)
        if not match:
            return []
        cx, cy, r = float(match.group(1)), float(match.group(2)), float(match.group(4))
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if head == "ARC":
        match = re.search(
            r"c=(-?\d+\.?\d*),(-?\d+\.?\d*),(-?\d+\.?\d*),r=(-?\d+\.?\d*),", body)
        if not match:
            return []
        cx, cy, r = float(match.group(1)), float(match.group(2)), float(match.group(4))
        return [(cx - r, cy - r), (cx + r, cy + r)]
    return [(float(m.group(1)), float(m.group(2))) for m in POINT_RE.finditer(body)]


def _inside(points, limits, margin=1500.0) -> bool:
    x0, y0, x1, y1 = limits
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return not (max(xs) < x0 - margin or min(xs) > x1 + margin
                or max(ys) < y0 - margin or min(ys) > y1 + margin)


def draw(ax, entities, texts, fontprops, limits=None) -> None:
    for _space, body in entities:
        head = body.split(",")[0].upper()
        if head == "LINE":
            nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", body)]
            if len(nums) >= 5:
                pts = [(nums[0], nums[1]), (nums[3], nums[4])]
                if limits and not _inside(pts, limits):
                    continue
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color="#1b4f72", lw=0.9)
        elif head in {"LWPOLYLINE", "POLYLINE", "ACDBPOLYLINE", "SPLINE"}:
            pts = [(float(m.group(1)), float(m.group(2))) for m in POINT_RE.finditer(body)]
            if len(pts) < 2 or (limits and not _inside(pts, limits)):
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if "closed=True" in body or "closed=1" in body:
                xs, ys = xs + [pts[0][0]], ys + [pts[0][1]]
            ax.plot(xs, ys, color="#1f618d", lw=0.9)
        elif head == "CIRCLE":
            match = re.search(r"c=(-?\d+\.?\d*),(-?\d+\.?\d*),(-?\d+\.?\d*),r=(-?\d+\.?\d*)", body)
            if match:
                cx, cy, r = float(match.group(1)), float(match.group(2)), float(match.group(4))
                if limits and not _inside([(cx - r, cy - r), (cx + r, cy + r)], limits):
                    continue
                ax.add_patch(patches.Circle((cx, cy), r, fill=False, color="#b03a2e", lw=0.9))
        elif head == "ARC":
            match = re.search(
                r"c=(-?\d+\.?\d*),(-?\d+\.?\d*),(-?\d+\.?\d*),r=(-?\d+\.?\d*),(-?\d+\.?\d*)\.\.(-?\d+\.?\d*)",
                body)
            if match:
                cx, cy, r = float(match.group(1)), float(match.group(2)), float(match.group(4))
                start, end = float(match.group(5)), float(match.group(6))
                if limits and not _inside([(cx - r, cy - r), (cx + r, cy + r)], limits):
                    continue
                ax.add_patch(patches.Arc((cx, cy), 2 * r, 2 * r, theta1=start,
                                         theta2=end if end >= start else end + 360,
                                         color="#8e44ad", lw=0.9))

    for x, y, label in texts:
        if limits:
            x0, y0, x1, y1 = limits
            if not (x0 - 2000 <= x <= x1 + 2000 and y0 - 2000 <= y <= y1 + 2000):
                continue
        ax.text(x, y, label, fontproperties=fontprops, fontsize=9, color="#7b241c", va="bottom")


def auto_views(entities, texts, gap_ratio=0.06) -> dict[str, tuple[float, float, float, float]]:
    """Cluster the sheet into side-by-side views by finding X gaps."""
    boxes = []
    for _space, body in entities:
        pts = entity_points(body)
        if pts:
            boxes.append((min(p[0] for p in pts), max(p[0] for p in pts),
                          min(p[1] for p in pts), max(p[1] for p in pts)))
    for x, y, _label in texts:
        boxes.append((x, x, y, y))
    if not boxes:
        return {}

    boxes.sort()
    span = max(b[1] for b in boxes) - min(b[0] for b in boxes)
    gap = max(span * gap_ratio, 1000.0)
    clusters: list[list[tuple[float, float, float, float]]] = [[boxes[0]]]
    running_max = boxes[0][1]
    for box in boxes[1:]:
        if box[0] - running_max > gap:
            clusters.append([box])
        else:
            clusters[-1].append(box)
        running_max = max(running_max, box[1])

    views = {}
    for index, cluster in enumerate(clusters, start=1):
        x0 = min(b[0] for b in cluster)
        x1 = max(b[1] for b in cluster)
        y0 = min(b[2] for b in cluster)
        y1 = max(b[3] for b in cluster)
        pad_x, pad_y = (x1 - x0) * 0.05 + 500, (y1 - y0) * 0.05 + 500
        views[f"view{index}"] = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)
    return views


def parse_views(spec: str) -> dict[str, tuple[float, float, float, float]]:
    views = {}
    for chunk in spec.split(";"):
        if not chunk.strip():
            continue
        name, _, coords = chunk.partition(":")
        nums = [float(v) for v in coords.split(",")]
        if len(nums) != 4:
            raise ValueError(f"视角 {name!r} 需要 x0,y0,x1,y1")
        views[name.strip()] = tuple(nums)  # type: ignore[assignment]
    return views


def main() -> int:
    parser = argparse.ArgumentParser(description="CAD 图元 → 视图 PNG")
    parser.add_argument("extract_dir")
    parser.add_argument("--out", default=None, help="默认 <extract_dir>/views")
    parser.add_argument("--views", default="auto", help="auto | all | name:x0,y0,x1,y1;...")
    parser.add_argument("--dpi", type=int, default=110)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    extract_dir = Path(args.extract_dir).resolve()
    out_dir = Path(args.out) if args.out else extract_dir / "views"
    out_dir.mkdir(parents=True, exist_ok=True)

    entities = parse_entities(extract_dir / "cad_entities.csv")
    texts = parse_texts(extract_dir / "cad_text.txt")
    fontprops = font_properties()

    if args.views == "auto":
        views = auto_views(entities, texts)
    elif args.views == "all":
        views = {"all": None}                     # type: ignore[dict-item]
    else:
        views = parse_views(args.views)
    if not views:
        views = {"all": None}                     # type: ignore[dict-item]

    written = []
    for name, limits in views.items():
        fig, ax = plt.subplots(figsize=(12, 9))
        draw(ax, entities, texts, fontprops, limits=limits)
        if limits:
            ax.set_xlim(limits[0], limits[2])
            ax.set_ylim(limits[1], limits[3])
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.15, lw=0.4)
        ax.set_title(name, fontproperties=fontprops, fontsize=12)
        target = out_dir / f"{name}.png"
        fig.savefig(target, dpi=args.dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        written.append(str(target))

    index = {"extract_dir": str(extract_dir), "entities": len(entities),
             "texts": len(texts), "views": written}
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    if args.json:
        print(json.dumps(index, ensure_ascii=False, indent=2))
    else:
        print(f"图元 {len(entities)}、文字 {len(texts)} → {len(written)} 个视图：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
