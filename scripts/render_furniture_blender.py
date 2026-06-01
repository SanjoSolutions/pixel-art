"""Headless Blender script: render a folder of furniture models once each.

Usage:
  blender -b -P render_furniture_blender.py -- --model-dir PATH --out DIR
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from render_blender import (
    apply_shader_to_rgb_bands,
    disable_compositor,
    import_model,
    pick_engine,
    setup_color_management,
    setup_freestyle_outline,
    setup_pixel_filter,
    world_bounds,
)


def setup_lighting():
    """Use overhead sun so furniture is not lit from either side."""
    bpy.ops.object.light_add(type="SUN", location=(0.0, 0.0, 10.0))
    sun = bpy.context.object
    sun.data.energy = 1.0
    sun.data.color = (1.0, 1.0, 1.0)
    sun.data.angle = math.radians(157.38)
    if hasattr(sun.data, "shadow_soft_size"):
        sun.data.shadow_soft_size = 5.0
    sun.rotation_euler = (0.0, 0.0, 0.0)

    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.0509, 0.0509, 0.0509, 1.0)
        bg.inputs["Strength"].default_value = 1.0


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--pattern", default="*.obj")
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--elevation", type=float, default=60.0)
    p.add_argument("--margin", type=float, default=1.25)
    p.add_argument("--yaw", type=float, default=0.0,
                   help="Pre-rotate every model around Z (degrees).")
    p.add_argument("--pixels-per-unit", type=float, default=0.0,
                   help="Use a shared pixel scale instead of fitting each "
                        "model to --size. Intended to preserve furniture "
                        "proportions.")
    p.add_argument("--pixels-per-unit-prefix", action="append", default=[],
                   metavar="PREFIX=VALUE",
                   help="Override --pixels-per-unit for model names starting "
                        "with PREFIX. Repeatable, e.g. wall=80.")
    p.add_argument("--metadata-manifest",
                   help="Manifest with optional per-model render metadata, "
                        "including width cells and keepProportions.")
    p.add_argument("--tile-size", type=int, default=128,
                   help="Raw output grid size in pixels when using "
                        "--pixels-per-unit.")
    p.add_argument("--padding-pixels", type=int, default=16,
                   help="Raw transparent padding added around the projected "
                        "bounds before rounding to --tile-size.")
    p.add_argument("--write-floor-anchor-metadata", action="store_true",
                   help="Write .anchor.json sidecars with the projected "
                        "back-floor anchor. pixelize.py can use these to "
                        "align sprites to the tile grid after trimming.")
    p.add_argument("--shader-to-rgb", action="store_true",
                   help="Convert materials to a Shader to RGB + Constant "
                        "ColorRamp toon shader for flat pixel-art lighting.")
    p.add_argument("--freestyle-outline", action="store_true",
                   help="Enable Freestyle outlines.")
    p.add_argument("--freestyle-thickness", type=float, default=1.0,
                   help="Freestyle line thickness in Blender pixels.")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--limit", type=int, default=0,
                   help="Render only the first N models; useful for tests.")
    args = p.parse_args(argv)
    args.pixels_per_unit_prefix = parse_prefix_float_rules(
        args.pixels_per_unit_prefix
    )
    args.resize_metadata = load_resize_metadata(args.metadata_manifest)
    return args


def parse_prefix_float_rules(specs: list[str]) -> list[tuple[str, float]]:
    rules = []
    for spec in specs:
        prefix, separator, value_text = spec.partition("=")
        if not separator or not prefix or not value_text:
            raise SystemExit(
                f"Invalid --pixels-per-unit-prefix {spec!r}; expected PREFIX=VALUE"
            )
        try:
            value = float(value_text)
        except ValueError as exc:
            raise SystemExit(
                f"Invalid pixel scale in --pixels-per-unit-prefix {spec!r}"
            ) from exc
        if value <= 0:
            raise SystemExit(
                f"Pixel scale must be positive in --pixels-per-unit-prefix {spec!r}"
            )
        rules.append((prefix, value))
    return rules


def parse_positive_float(value, path: Path, name: str, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            f"{path} sprite {name} has invalid {field} {value!r}"
        ) from exc
    if parsed <= 0:
        raise SystemExit(
            f"{path} sprite {name} {field} must be positive, got {value!r}"
        )
    return parsed


def parse_cell_width(value, path: Path, name: str) -> float:
    width = parse_positive_float(value, path, name, "width")
    if abs(width - round(width)) > 0.0001:
        raise SystemExit(
            f"{path} sprite {name} width must be a whole cell count, got {value!r}"
        )
    return width


def parse_bool(value, path: Path, name: str, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    raise SystemExit(f"{path} sprite {name} has invalid {field} {value!r}")


def load_resize_metadata(manifest_path: str | None) -> dict[str, dict]:
    if not manifest_path:
        return {}
    path = Path(manifest_path)
    if not path.exists():
        return {}

    manifest = json.loads(path.read_text())
    metadata = {}
    for sprite in manifest.get("sprites", []):
        if "width" not in sprite:
            continue
        name = str(sprite.get("name") or "")
        if not name:
            raise SystemExit(f"{path} has width metadata on an unnamed sprite")
        if name in metadata:
            raise SystemExit(f"{path} has duplicate sprite metadata for {name}")
        metadata[name] = {
            "width": parse_cell_width(sprite.get("width"), path, name),
            "keepProportions": parse_bool(
                sprite.get("keepProportions", True),
                path,
                name,
                "keepProportions",
            ),
        }
    return metadata


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def configure_render(width: int, height: int):
    scene = bpy.context.scene
    scene.render.engine = pick_engine()
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    setup_color_management()
    setup_pixel_filter()
    disable_compositor()
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 32


def add_camera(center: Vector, max_dim: float, elevation: float, margin: float):
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max_dim * margin
    cam.data.clip_start = 0.01
    cam.data.clip_end = max_dim * 100
    bpy.context.scene.camera = cam

    elev = math.radians(elevation)
    distance = max_dim * 4
    cam.location = (
        center.x,
        center.y - distance * math.cos(elev),
        center.z + distance * math.sin(elev),
    )
    direction = Vector(center) - cam.location
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")
    return cam


def add_pivot(center: Vector, yaw: float):
    top_level = [
        o for o in bpy.context.scene.objects
        if o.parent is None and o.type not in ("CAMERA", "LIGHT")
    ]
    bpy.ops.object.empty_add(location=center)
    pivot = bpy.context.object
    for o in top_level:
        if o is pivot:
            continue
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()
    pivot.rotation_euler = (0.0, 0.0, math.radians(yaw))
    return pivot


def projected_bounds(cam):
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No meshes found in imported model")

    inv = cam.matrix_world.inverted()
    mn = Vector((float("inf"), float("inf")))
    mx = Vector((float("-inf"), float("-inf")))
    for obj in meshes:
        for corner in obj.bound_box:
            local = inv @ (obj.matrix_world @ Vector(corner))
            mn.x = min(mn.x, local.x)
            mn.y = min(mn.y, local.y)
            mx.x = max(mx.x, local.x)
            mx.y = max(mx.y, local.y)
    return mn, mx


def mesh_world_bbox_corners() -> list[Vector]:
    corners = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("No meshes found in imported model")
    return corners


def floor_bbox_corners() -> list[Vector]:
    bounds_min, bounds_max = world_bounds()
    return [
        Vector((bounds_min.x, bounds_min.y, bounds_min.z)),
        Vector((bounds_min.x, bounds_max.y, bounds_min.z)),
        Vector((bounds_max.x, bounds_min.y, bounds_min.z)),
        Vector((bounds_max.x, bounds_max.y, bounds_min.z)),
    ]


def average_vectors(vectors: list[Vector]) -> Vector:
    total = Vector((0.0, 0.0, 0.0))
    for vector in vectors:
        total += vector
    return total / len(vectors)


def floor_alignment_anchor_worlds(cam) -> dict[str, Vector]:
    floor_corners = floor_bbox_corners()
    inv = cam.matrix_world.inverted()
    projected = [(corner, inv @ corner) for corner in floor_corners]
    edge_specs = {
        "left": ("x", min(local.x for _, local in projected)),
        "right": ("x", max(local.x for _, local in projected)),
        "back": ("y", max(local.y for _, local in projected)),
        "front": ("y", min(local.y for _, local in projected)),
    }
    anchors = {}
    for edge, (axis, edge_value) in edge_specs.items():
        if axis == "x":
            candidates = [
                corner for corner, local in projected
                if abs(local.x - edge_value) <= 1e-5
            ]
        else:
            candidates = [
                corner for corner, local in projected
                if abs(local.y - edge_value) <= 1e-5
            ]
        anchors[edge] = average_vectors(candidates)
    return anchors


def world_to_render_pixel(cam, point: Vector, width: int, height: int) -> tuple[float, float]:
    scene = bpy.context.scene
    frame = cam.data.view_frame(scene=scene)
    min_x = min(v.x for v in frame)
    max_x = max(v.x for v in frame)
    min_y = min(v.y for v in frame)
    max_y = max(v.y for v in frame)
    local = cam.matrix_world.inverted() @ point
    pixel_x = (local.x - min_x) / (max_x - min_x) * width
    pixel_y = (max_y - local.y) / (max_y - min_y) * height
    return pixel_x, pixel_y


def write_floor_anchor_metadata(
    image_path: Path,
    anchor_worlds: dict[str, Vector],
    anchor_pixels: dict[str, tuple[float, float]],
    width: int,
    height: int,
    tile_size: int,
    render_metadata: dict,
):
    metadata_path = image_path.with_suffix(".anchor.json")
    back_pixel = anchor_pixels["back"]
    back_world = anchor_worlds["back"]
    metadata = {
        "type": "floor_bbox",
        "tile_size": tile_size,
        "pixel": {
            "x": round(back_pixel[0], 4),
            "y": round(back_pixel[1], 4),
        },
        "alignment_pixels": {
            edge: {
                "x": round(pixel[0], 4),
                "y": round(pixel[1], 4),
            }
            for edge, pixel in anchor_pixels.items()
        },
        "source_width": width,
        "source_height": height,
        "world": {
            "x": round(back_world.x, 6),
            "y": round(back_world.y, 6),
            "z": round(back_world.z, 6),
        },
        "alignment_world": {
            edge: {
                "x": round(world.x, 6),
                "y": round(world.y, 6),
                "z": round(world.z, 6),
            }
            for edge, world in anchor_worlds.items()
        },
        "render": render_metadata,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")


def ceil_to_multiple(value: float, multiple: int) -> int:
    return max(multiple, math.ceil(value / multiple) * multiple)


def fit_ortho_scale(cam, width: int, height: int, pixels_per_unit: float) -> float:
    scene = bpy.context.scene
    scene.render.resolution_x = width
    scene.render.resolution_y = height

    original_scale = cam.data.ortho_scale
    cam.data.ortho_scale = 1.0
    frame = cam.data.view_frame(scene=scene)
    cam.data.ortho_scale = original_scale

    frame_width = max(v.x for v in frame) - min(v.x for v in frame)
    frame_height = max(v.y for v in frame) - min(v.y for v in frame)
    target_width = width / pixels_per_unit
    target_height = height / pixels_per_unit
    return max(target_width / frame_width, target_height / frame_height)


def pixels_per_unit_for_model(model_path: Path, args) -> float:
    pixels_per_unit = args.pixels_per_unit
    matched_prefix_len = -1
    for prefix, value in args.pixels_per_unit_prefix:
        if model_path.stem.startswith(prefix) and len(prefix) > matched_prefix_len:
            pixels_per_unit = value
            matched_prefix_len = len(prefix)
    return pixels_per_unit


def resize_metadata_for_model(model_path: Path, args) -> dict | None:
    return args.resize_metadata.get(model_path.stem)


def render_cache_metadata_for_model(model_path: Path, args) -> dict:
    render_metadata = {
        "lighting": {
            "sun": "vertical",
            "energy": 1.0,
            "angle_degrees": 157.38,
        },
    }
    metadata = resize_metadata_for_model(model_path, args)
    if metadata is None:
        return render_metadata
    render_metadata["resize"] = {
        "width": metadata["width"],
        "keepProportions": metadata["keepProportions"],
        "pixels_per_unit": pixels_per_unit_for_model(model_path, args),
        "tile_size": args.tile_size,
        "target_width_pixels": target_width_pixels_for_model(model_path, args),
        "target_model_width_pixels": target_model_width_pixels_for_model(
            model_path,
            args,
        ),
        "freestyle_outline": freestyle_outline_for_model(model_path, args),
        "freestyle_thickness": (
            args.freestyle_thickness
            if freestyle_outline_for_model(model_path, args)
            else 0
        ),
    }
    return render_metadata


def top_level_render_objects():
    return [
        obj for obj in bpy.context.scene.objects
        if obj.parent is None and obj.type not in ("CAMERA", "LIGHT")
    ]


def scale_imported_model(center: Vector, scale: tuple[float, float, float]):
    objects = top_level_render_objects()
    if not objects:
        raise RuntimeError("No imported objects found to scale")
    transform = (
        Matrix.Translation(center)
        @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        @ Matrix.Translation(-center)
    )
    for obj in objects:
        obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()


def apply_resize_metadata(
    model_path: Path,
    args,
    center: Vector,
    size: Vector,
    pixels_per_unit: float,
):
    metadata = resize_metadata_for_model(model_path, args)
    if metadata is None:
        return
    if pixels_per_unit <= 0:
        raise RuntimeError(
            f"{model_path.stem} has width metadata, but --pixels-per-unit "
            "is not enabled"
        )
    if size.x <= 0:
        raise RuntimeError(f"Model has empty width: {model_path}")

    target_model_width_pixels = target_model_width_pixels_for_model(model_path, args)
    target_width_units = target_model_width_pixels / pixels_per_unit
    scale_x = target_width_units / size.x
    if metadata["keepProportions"]:
        scale = (scale_x, scale_x, scale_x)
    else:
        scale = (scale_x, 1.0, 1.0)
    scale_imported_model(center, scale)
    print(
        f"[resize] {model_path.name} width={metadata['width']:g} cell(s), "
        f"keepProportions={str(metadata['keepProportions']).lower()} "
        f"scale=({scale[0]:.4g}, {scale[1]:.4g}, {scale[2]:.4g})"
    )


def target_width_pixels_for_model(model_path: Path, args) -> int | None:
    metadata = resize_metadata_for_model(model_path, args)
    if metadata is None:
        return None
    return round(metadata["width"] * args.tile_size)


def target_model_width_pixels_for_model(model_path: Path, args) -> int | None:
    target_width_pixels = target_width_pixels_for_model(model_path, args)
    if target_width_pixels is None:
        return None
    outline_pixels = round(args.freestyle_thickness) \
        if freestyle_outline_for_model(model_path, args) else 0
    return max(1, target_width_pixels - outline_pixels)


def freestyle_outline_for_model(model_path: Path, args) -> bool:
    return args.freestyle_outline


def setup_render_effects_for_model(args, model_path: Path):
    if freestyle_outline_for_model(model_path, args):
        setup_freestyle_outline(args.freestyle_thickness)
        return
    scene = bpy.context.scene
    scene.render.use_freestyle = False
    bpy.context.view_layer.use_freestyle = False


def render_fixed_scale(model_path: Path, out_path: Path, args,
                       center: Vector, max_dim: float):
    cam = add_camera(center, max_dim, args.elevation, args.margin)
    setup_lighting()
    add_pivot(center, args.yaw)
    bpy.context.view_layer.update()
    anchor_worlds = floor_alignment_anchor_worlds(cam) \
        if args.write_floor_anchor_metadata else None

    mn, mx = projected_bounds(cam)
    projected_size = mx - mn
    pixels_per_unit = pixels_per_unit_for_model(model_path, args)
    target_width_pixels = target_width_pixels_for_model(model_path, args)
    if target_width_pixels is None:
        width = ceil_to_multiple(
            projected_size.x * pixels_per_unit + args.padding_pixels * 2,
            args.tile_size,
        )
    else:
        width = target_width_pixels
    height = ceil_to_multiple(
        projected_size.y * pixels_per_unit + args.padding_pixels * 2,
        args.tile_size,
    )

    screen_center = (mn + mx) / 2
    world_offset = cam.matrix_world.to_quaternion() @ Vector(
        (screen_center.x, screen_center.y, 0.0)
    )
    cam.location += world_offset
    cam.data.ortho_scale = fit_ortho_scale(cam, width, height, pixels_per_unit)

    configure_render(width, height)
    setup_render_effects_for_model(args, model_path)
    anchor_pixels = None
    if anchor_worlds is not None:
        anchor_pixels = {
            edge: world_to_render_pixel(cam, anchor_world, width, height)
            for edge, anchor_world in anchor_worlds.items()
        }
    bpy.context.scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    if anchor_worlds is not None and anchor_pixels is not None:
        write_floor_anchor_metadata(
            out_path,
            anchor_worlds,
            anchor_pixels,
            width,
            height,
            args.tile_size,
            render_cache_metadata_for_model(model_path, args),
        )
    print(
        f"[render] {model_path.name} -> {out_path} "
        f"({width}×{height}, {pixels_per_unit:g}px/unit)"
    )


def render_fit_square(model_path: Path, out_path: Path, args,
                      center: Vector, max_dim: float):
    configure_render(args.size, args.size)
    setup_render_effects_for_model(args, model_path)
    add_camera(center, max_dim, args.elevation, args.margin)
    setup_lighting()
    add_pivot(center, args.yaw)

    bpy.context.scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    print(f"[render] {model_path.name} -> {out_path}")


def render_model(model_path: Path, out_path: Path, args):
    clear_scene()
    import_model(os.path.abspath(model_path))
    if args.shader_to_rgb:
        apply_shader_to_rgb_bands()

    mn, mx = world_bounds()
    center = (mn + mx) / 2
    size = mx - mn
    pixels_per_unit = pixels_per_unit_for_model(model_path, args)
    apply_resize_metadata(model_path, args, center, size, pixels_per_unit)

    mn, mx = world_bounds()
    center = (mn + mx) / 2
    size = mx - mn
    max_dim = max(size.x, size.y, size.z)
    if max_dim <= 0:
        raise RuntimeError(f"Model has empty bounds: {model_path}")

    if args.pixels_per_unit > 0:
        render_fixed_scale(model_path, out_path, args, center, max_dim)
    else:
        render_fit_square(model_path, out_path, args, center, max_dim)


def anchor_metadata_ready(path: Path, expected_render_metadata: dict) -> bool:
    if not path.exists():
        return False
    try:
        metadata = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if metadata.get("render", {}) != expected_render_metadata:
        return False
    alignment_pixels = metadata.get("alignment_pixels")
    if not isinstance(alignment_pixels, dict):
        return False
    for edge in ("left", "right", "back", "front"):
        pixel = alignment_pixels.get(edge)
        if not isinstance(pixel, dict) or "x" not in pixel or "y" not in pixel:
            return False
    return True


def main():
    args = parse_args()
    model_dir = Path(args.model_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    models = sorted(model_dir.glob(args.pattern))
    if args.limit > 0:
        models = models[:args.limit]
    if not models:
        raise SystemExit(f"No models matched {model_dir}/{args.pattern}")

    print(f"[render] {len(models)} front-facing furniture models")
    for model_path in models:
        out_path = out_dir / f"{model_path.stem}.png"
        metadata_path = out_path.with_suffix(".anchor.json")
        render_cache_metadata = render_cache_metadata_for_model(model_path, args)
        metadata_ready = (
            (
                not args.write_floor_anchor_metadata
                and not render_cache_metadata
            )
            or (
                args.write_floor_anchor_metadata
                and anchor_metadata_ready(metadata_path, render_cache_metadata)
            )
        )
        if args.skip_existing and out_path.exists() and metadata_ready:
            print(f"[render] cached {out_path}")
            continue
        render_model(model_path, out_path, args)


if __name__ == "__main__":
    main()
