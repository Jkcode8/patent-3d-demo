"""Set the OpenSCAD viewport presets ($vpt / $vpr / $vpd) in the wrapper models.

The presets make the GUI frame the model correctly when it is opened directly
(OpenSCAD uses them for the interactive view; the MCP render pipeline renders
the STL through a generated ``import()`` wrapper and is unaffected).

Usage:
    python set_viewport.py [project_root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# file -> (view point, view rotation, view distance)
FULL = ("[0, 0, -2000]", "[60, 0, 40]", "140000")
ZOOM = ("[9500, 0, -500]", "[90, 0, 0]", "52000")
SECTION = ("[0, 0, -2000]", "[70, 0, -130]", "130000")
EXPLODED = ("[0, 0, 5000]", "[60, 0, 40]", "200000")

PRESETS: dict[str, tuple[str, str, str]] = {
    "pier_anticollision_device.scad": FULL,
    "pier_anticollision_device_inner.scad": FULL,
    "impact_initial.scad": FULL,
    "impact_ship.scad": FULL,
    "impact_debris.scad": FULL,
    "assembly_step1.scad": FULL,
    "assembly_step2.scad": FULL,
    "assembly_step3.scad": FULL,
    "assembly_step4.scad": FULL,
    "assembly_step5.scad": FULL,
    "pier_anticollision_device_section.scad": SECTION,
    "device_exploded.scad": EXPLODED,
    "impact_zoom_initial.scad": ZOOM,
    "impact_zoom_ship.scad": ZOOM,
    "impact_zoom_debris.scad": ZOOM,
}

VPT = re.compile(r"^\s*\\?\[?[^=\n]*\$?vpt[^=\n]*=\s*\[[^\]]*\];", re.MULTILINE)
VPR = re.compile(r"^\s*\\?\[?[^=\n]*vpr[^=\n]*=\s*\[[^\]]*\];", re.MULTILINE)
VPD = re.compile(r"^\s*\\?\[?[^=\n]*vpd[^=\n]*=\s*\d+\s*;", re.MULTILINE)
# Lines mangled by an earlier bad sed-style rewrite, e.g. "\[0, 0, 0] = [0, 0, 0];"
MANGLED = re.compile(
    r"^\s*\\\s*\[[^\]]*\]\s*=\s*\[[^\]]*\]\s*;\s*$"
    r"|^\s*\\\s*\d+\s*=\s*\d+\s*;\s*$",
    re.MULTILINE,
)
ORPHAN_COMMENT = re.compile(r"^\s*//\s*视口预设.*$", re.MULTILINE)


def set_preset(path: Path, preset: tuple[str, str, str]) -> None:
    point, rotation, distance = preset
    text = path.read_text(encoding="utf-8")

    # Drop any existing (possibly mangled) viewport lines ...
    text = VPT.sub("", text)
    text = VPR.sub("", text)
    text = VPD.sub("", text)
    text = MANGLED.sub("", text)
    text = ORPHAN_COMMENT.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # ... and insert a clean block after the leading comment lines.
    lines = text.splitlines()
    index = 0
    while index < len(lines) and lines[index].lstrip().startswith("//"):
        index += 1
    block = [
        "$vpt = %s;" % point,
        "$vpr = %s;" % rotation,
        "$vpd = %s;  // 视口预设：打开后按 F5 即定位到模型" % distance,
        "",
    ]
    lines[index:index] = block
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"preset set: {path.name}  {point} {rotation} {distance}")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    working = root / "working"
    for name, preset in PRESETS.items():
        target = working / name
        if not target.exists():
            print(f"missing: {target}")
            continue
        set_preset(target, preset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
