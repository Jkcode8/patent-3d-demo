"""Import an STL into Blender and frame it in the viewport.

Usage (GUI, keeps Blender open):
    blender-launcher.exe --python open_stl_in_blender.py -- <file.stl>

Usage (background self-test, prints stats and exits):
    blender.exe --background --python open_stl_in_blender.py -- <file.stl> --check
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

DEFAULT_STL = Path.cwd() / "model" / "device.stl"


def import_stl(path: Path) -> list[str]:
    """Import *path*, returning the names of the imported objects."""
    before = set(bpy.data.objects.keys())
    try:
        bpy.ops.wm.stl_import(filepath=str(path))
    except AttributeError:
        bpy.ops.import_mesh.stl(filepath=str(path))
    return sorted(set(bpy.data.objects.keys()) - before)


def frame_view() -> bool:
    """Zoom the 3D viewport to the imported geometry (GUI only)."""
    screen = getattr(bpy.context, "screen", None)
    if screen is None:
        return False
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        window = next((r for r in area.regions if r.type == "WINDOW"), None)
        try:
            with bpy.context.temp_override(area=area, region=window):
                bpy.ops.view3d.view_selected(use_all_regions=False)
                area.spaces[0].shading.type = "SOLID"
            return True
        except Exception:
            return False
    return False


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    check_only = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")]
    stl = Path(paths[0]) if paths else DEFAULT_STL

    if not stl.exists():
        print(f"STL not found: {stl}")
        return 1

    bpy.ops.wm.read_factory_settings(use_empty=True)
    names = import_stl(stl)
    total = sum(len(bpy.data.objects[n].data.polygons) for n in names
                if bpy.data.objects[n].type == "MESH")
    print(f"imported {stl.name}: objects={names} faces={total}")

    if check_only:
        return 0

    # OpenSCAD and Blender are both Z-up, so no axis fix-up is applied.
    if not frame_view():
        print("viewport not framed automatically — press . (Numpad period) to zoom to the model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
