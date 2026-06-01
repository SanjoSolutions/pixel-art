"""Create the reusable Blender render template for this project.

Usage:
  blender -b -P scripts/create_pixel_render_template_blend.py -- \
    --out pixel_render_template.blend
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
HELPER_SCRIPT = SCRIPT_DIR / "pixel_render_template.py"


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(ROOT / "pixel_render_template.blend"),
        help="Path for the generated .blend template.",
    )
    return parser.parse_args(argv)


def clear_startup_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for datablocks in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.curves,
        bpy.data.collections,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def load_helper_namespace() -> tuple[str, dict]:
    helper_source = HELPER_SCRIPT.read_text()
    namespace = {
        "__name__": "pixel_render_template_embedded",
        "__file__": str(HELPER_SCRIPT),
    }
    exec(compile(helper_source, str(HELPER_SCRIPT), "exec"), namespace)
    return helper_source, namespace


def add_text_block(name: str, body: str, use_module: bool = False) -> bpy.types.Text:
    existing = bpy.data.texts.get(name)
    if existing is not None:
        bpy.data.texts.remove(existing)
    text = bpy.data.texts.new(name)
    text.write(body)
    text.use_module = use_module
    return text


def configure_default_view(helper_namespace: dict) -> None:
    scene = bpy.context.scene
    helper_namespace["set_default_scene_settings"](scene)
    helper_namespace["configure_render"](scene, 128, 128)
    helper_namespace["ensure_origin_empty"]()
    helper_namespace["ensure_sun"]()
    camera = helper_namespace["ensure_camera"](scene)

    elevation = math.radians(scene.pixel_render_elevation)
    center = Vector((0.0, 0.0, 0.5))
    distance = 4.0
    camera.location = (
        center.x,
        center.y - distance * math.cos(elevation),
        center.z + distance * math.sin(elevation),
    )
    helper_namespace["point_camera_at"](camera, center)
    camera.data.ortho_scale = 2.0
    camera.data.clip_end = 100.0
    scene.render.filepath = "//pixel_render.png"


def add_usage_notes() -> None:
    notes = """Pixel Render Template
=====================

1. Import a GLB/GLTF/OBJ/FBX model into this file.
2. If Blender asks about Python scripts, choose Allow Execution.
3. Press F12 or Render > Render Image.

The embedded pixel_render_template.py script auto-runs before render when
trusted. It frames all visible mesh objects and applies the same settings as
the furniture regeneration path:

- 60 degree orthographic camera from -Y
- 64 pixels per Blender unit
- 32 px grid rounding with 16 px transparent padding
- transparent PNG / RGBA output
- Standard color management
- Blender filter size 0.01
- Shader-to-RGB constant light bands
- overhead soft sun
- 1 px black Freestyle outlines

If auto-run is disabled, open the Text Editor, select pixel_render_template.py,
click Run Script, then use the Pixel Render Template panel in Render Properties.
"""
    add_text_block("README_pixel_render_template", notes)


def main() -> None:
    args = parse_args()
    out_path = Path(args.out).resolve()

    bpy.context.preferences.filepaths.save_version = 0
    clear_startup_scene()
    helper_source, helper_namespace = load_helper_namespace()
    helper_namespace["register"]()
    configure_default_view(helper_namespace)
    add_text_block("pixel_render_template.py", helper_source, use_module=True)
    add_usage_notes()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_path), compress=True)
    print(f"[template] wrote {out_path}")


if __name__ == "__main__":
    main()
