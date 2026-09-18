"""Extract text and geometry from a DXF drawing (fallback when no AutoCAD COM).

Writes the same artefacts as ``extract_dwg.ps1`` so every downstream step works
unchanged: ``cad_summary.txt``, ``cad_text.txt``, ``cad_dims.txt``,
``cad_entities.csv``.

Uses ezdxf when installed; otherwise falls back to a minimal ASCII-DXF reader
that understands the entity types this workflow needs (TEXT/MTEXT/LINE/
LWPOLYLINE/POLYLINE/CIRCLE/ARC/INSERT).

Usage:
    python extract_dxf.py <file.dxf> <out_dir> [--json]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _fmt(point) -> str:
    values = [float(v) for v in point[:3]] if len(point) >= 3 else [float(point[0]), float(point[1]), 0.0]
    return "{0:.3f},{1:.3f},{2:.3f}".format(*values)


def read_with_ezdxf(path: Path) -> dict:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    summary: list[str] = [f"name: {path.name}", f"path: {path}", "reader: ezdxf",
                          f"dxfversion: {doc.dxfversion}"]
    texts: list[str] = []
    dims: list[str] = []
    geo: list[str] = []
    hist: Counter[str] = Counter()
    extents = None
    try:
        extents = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
    except Exception:
        pass
    if extents:
        summary.append(f"EXTMIN: {extents[0]}")
        summary.append(f"EXTMAX: {extents[1]}")

    for space_name, space in [("Model", doc.modelspace())] + [
        (f"Layout:{layout.name}", doc.layouts.get(layout.name))
        for layout in doc.layouts if layout.name.lower() != "model"
    ]:
        for entity in space:
            kind = entity.dxftype()
            hist[f"{space_name}/{kind}"] += 1
            try:
                if kind in ("TEXT", "MTEXT", "ATTRIB"):
                    texts.append(f"[{space_name}] {_fmt(entity.dxf.insert)} :: {entity.dxf.text}")
                elif kind == "DIMENSION":
                    measurement = entity.get_measurement() if hasattr(entity, "get_measurement") else ""
                    dims.append(f"[{space_name}] {kind} :: measurement={measurement} "
                                f"text={entity.dxf.get('text', '')} :: {_fmt(entity.dxf.defpoint)}")
                elif kind == "LINE":
                    geo.append(f"[{space_name}] LINE,{_fmt(entity.dxf.start)},{_fmt(entity.dxf.end)}")
                elif kind == "LWPOLYLINE":
                    pts = [f"{p[0]:.3f},{p[1]:.3f}" for p in entity.get_points("xy")]
                    geo.append(f"[{space_name}] LWPOLYLINE,closed={bool(entity.closed)},{' '.join(pts)}")
                elif kind == "POLYLINE":
                    pts = [f"{v.dxf.location.x:.3f},{v.dxf.location.y:.3f}" for v in entity.vertices]
                    geo.append(f"[{space_name}] POLYLINE,closed={bool(entity.is_closed)},{' '.join(pts)}")
                elif kind == "CIRCLE":
                    geo.append(f"[{space_name}] CIRCLE,c={_fmt(entity.dxf.center)},"
                               f"r={entity.dxf.radius:.3f}")
                elif kind == "ARC":
                    geo.append(f"[{space_name}] ARC,c={_fmt(entity.dxf.center)},r={entity.dxf.radius:.3f},"
                               f"{entity.dxf.start_angle:.3f}..{entity.dxf.end_angle:.3f}")
                elif kind == "INSERT":
                    geo.append(f"[{space_name}] INSERT,{entity.dxf.name},{_fmt(entity.dxf.insert)},"
                               f"scale=1,rot={entity.dxf.rotation}")
            except Exception as exc:                      # keep going on odd entities
                geo.append(f"[{space_name}] {kind},<error: {exc}>")

    return {"summary": summary, "texts": texts, "dims": dims, "geo": geo, "hist": hist}


def read_minimal(path: Path) -> dict:
    """Minimal ASCII-DXF reader (no dependencies)."""
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(raw) - 1, 2):
        pairs.append((raw[index].strip(), raw[index + 1].strip()))

    summary = [f"name: {path.name}", f"path: {path}", "reader: minimal-ascii"]
    texts: list[str] = []
    dims: list[str] = []
    geo: list[str] = []
    hist: Counter[str] = Counter()
    current: str | None = None
    data: dict[str, str] = {}
    vertices: list[str] = []

    def flush() -> None:
        nonlocal current, data, vertices
        if not current:
            return
        if current in {"SECTION", "ENDSEC", "TABLE", "ENDTAB", "LAYER", "LTYPE", "STYLE",
                       "VIEW", "VPORT", "BLOCK", "ENDBLK", "EOF", "HEADER", "CLASSES",
                       "OBJECTS", "DIMSTYLE", "APPID"}:
            current, data, vertices = None, {}, []
            return
        hist[f"Model/{current}"] += 1
        if current == "TEXT" and "1" in data:
            texts.append(f"[Model] {data.get('10', '0')},{data.get('20', '0')},0 :: {data['1']}")
        elif current == "MTEXT" and "1" in data:
            texts.append(f"[Model] {data.get('10', '0')},{data.get('20', '0')},0 :: {data['1']}")
        elif current == "LINE":
            geo.append(f"[Model] LINE,{data.get('10','0')},{data.get('20','0')},0,"
                       f"{data.get('11','0')},{data.get('21','0')},0")
        elif current in ("LWPOLYLINE", "POLYLINE") and vertices:
            geo.append(f"[Model] {current},closed={data.get('70', '0')},{' '.join(vertices)}")
        elif current == "CIRCLE":
            geo.append(f"[Model] CIRCLE,c={data.get('10','0')},{data.get('20','0')},0,"
                       f"r={data.get('40','0')}")
        elif current == "ARC":
            geo.append(f"[Model] ARC,c={data.get('10','0')},{data.get('20','0')},0,"
                       f"r={data.get('40','0')},{data.get('50','0')}..{data.get('51','0')}")
        current, data, vertices = None, {}, []

    for code, value in pairs:
        if code == "0":
            flush()
            current = value.upper() if value else None
            continue
        if current is None:
            continue
        if current in ("LWPOLYLINE", "POLYLINE") and code == "10":
            vertices.append(value)
        elif current in ("LWPOLYLINE", "POLYLINE") and code == "20" and vertices:
            vertices[-1] = f"{vertices[-1]},{value}"
        else:
            data[code] = value
    flush()

    return {"summary": summary, "texts": texts, "dims": dims, "geo": geo, "hist": hist}


def write_outputs(result: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = list(result["summary"]) + ["", "entity histogram:"]
    summary += [f"  {key} = {value}" for key, value in sorted(result["hist"].items())]
    (out_dir / "cad_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    (out_dir / "cad_text.txt").write_text("\n".join(result["texts"]), encoding="utf-8")
    (out_dir / "cad_dims.txt").write_text("\n".join(result["dims"]), encoding="utf-8")
    (out_dir / "cad_entities.csv").write_text("\n".join(result["geo"]), encoding="utf-8")
    return {"texts": len(result["texts"]), "dims": len(result["dims"]), "geometry": len(result["geo"])}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    as_json = "--json" in sys.argv
    try:
        result = read_with_ezdxf(path)
    except ImportError:
        result = read_minimal(path)
    except Exception as exc:
        print(f"ezdxf 读取失败（{exc}），改用最小 ASCII 解析器", file=sys.stderr)
        result = read_minimal(path)
    counts = write_outputs(result, out_dir)
    if as_json:
        print(json.dumps({"dxf": str(path), "out_dir": str(out_dir), **counts},
                         ensure_ascii=False, indent=2))
    else:
        print(f"文本 {counts['texts']} 条、标注 {counts['dims']} 条、图元 {counts['geometry']} 个 → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
