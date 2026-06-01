"""Headless Blender script: render a GLB/GLTF model from N angles.

Usage:
  blender -b -P render_blender.py -- --model PATH --out DIR [options]
"""
import bpy
import sys
import math
import os
import argparse
import json
from mathutils import Vector


PIXEL_SHADER_PREFIX = "Pixel Render "


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--angles", type=int, default=8)
    p.add_argument("--wheel-frames", type=int, default=1,
                   help="Animation frames for wheel rotation (>=1)")
    p.add_argument("--wheel-axis", choices=["x", "y", "z", "auto"], default="auto",
                   help="Local axis each wheel mesh rotates around. "
                        "'auto' picks the shortest mesh-local bbox dimension "
                        "(cylinder axis) per wheel. Kenney kit: x; some FBX "
                        "imports: z.")
    p.add_argument("--wheel-mask-out",
                   help="Optional directory for per-angle visible-wheel masks. "
                        "Use with scripts/freeze_non_wheel_pixels.py to keep "
                        "non-wheel pixels stable across wheel animation frames.")
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--elevation", type=float, default=30.0)
    p.add_argument("--margin", type=float, default=1.25,
                   help="Ortho scale = max_dim * margin")
    p.add_argument("--yaw", type=float, default=0.0,
                   help="Pre-rotate model around Z (degrees). Use to align "
                        "a non-standard forward axis to +X (e.g. +Y-forward "
                        "bicycle: pass -90).")
    p.add_argument("--lighting", choices=["center", "side"],
                   default="center",
                   help="'center' uses the centered vehicle light direction; "
                        "'side' uses the original side-biased direction.")
    p.add_argument("--material-color", action="append", default=[],
                   help="Override a material's Base Color by name, format "
                        "'MatName=rrggbb'. Repeatable. Needed for assets "
                        "whose materials were stripped on export (e.g. the "
                        "Public Transport pack's Blender-2.76 FBX has every "
                        "material at gray 0.8).")
    p.add_argument("--shader-to-rgb", action="store_true",
                   help="Convert materials to a Shader to RGB + Constant "
                        "ColorRamp toon shader for flat pixel-art lighting.")
    p.add_argument("--freestyle-outline", action="store_true",
                   help="Enable Freestyle outlines.")
    p.add_argument("--freestyle-thickness", type=float, default=1.0,
                   help="Freestyle line thickness in Blender pixels.")
    return p.parse_args(argv)


def parse_hex_rgb(s: str) -> tuple[float, float, float]:
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected 6-digit hex, got {s!r}")
    return (int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0)


def apply_material_colors(overrides: dict[str, tuple[float, float, float]]):
    """Set Principled BSDF Base Color for materials matched by name.

    Unknown names are warned about (typo protection). Materials without a
    Principled BSDF node are given one so the color actually shows.
    """
    for name, (r, g, b) in overrides.items():
        m = bpy.data.materials.get(name)
        if m is None:
            print(f"[material-color] WARNING: no material named {name!r}")
            continue
        m.use_nodes = True
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        # Legacy viewport color so solid-shade previews match.
        m.diffuse_color = (r, g, b, 1.0)
        print(f"[material-color] {name} -> #{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def srgb_to_linear_channel(value: float) -> float:
    value = clamp01(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def srgb_to_linear_color(
    color: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        srgb_to_linear_channel(color[0]),
        srgb_to_linear_channel(color[1]),
        srgb_to_linear_channel(color[2]),
        color[3],
    )


def material_base_color(material) -> tuple[float, float, float, float]:
    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
                color = node.inputs["Base Color"].default_value
                return color[0], color[1], color[2], color[3]
    color = material.diffuse_color
    return color[0], color[1], color[2], color[3]


def material_output_node(material):
    nodes = material.node_tree.nodes
    for node in nodes:
        if node.type == "OUTPUT_MATERIAL" and getattr(node, "is_active_output", False):
            return node
    for node in nodes:
        if node.type == "OUTPUT_MATERIAL":
            return node
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (580, 120)
    return output


def material_base_color_input(material):
    if not material.use_nodes or not material.node_tree:
        return None

    for node in material.node_tree.nodes:
        if node.name.startswith(PIXEL_SHADER_PREFIX):
            continue
        if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
            return node.inputs["Base Color"]
        if node.type == "BSDF_DIFFUSE" and "Color" in node.inputs:
            return node.inputs["Color"]
    return None


def mark_pixel_shader_node(node, role: str):
    node.name = f"{PIXEL_SHADER_PREFIX}{role}"
    node["pixel_shader_wrapper"] = True
    node["pixel_shader_role"] = role


def remove_pixel_shader_wrapper(material, output):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    wrapper_nodes = [
        node for node in nodes
        if node.get("pixel_shader_wrapper")
        or node.name.startswith(PIXEL_SHADER_PREFIX)
    ]
    shader_to_rgb = next(
        (
            node for node in wrapper_nodes
            if node.get("pixel_shader_role") == "Shader To RGB"
            or node.name.startswith(f"{PIXEL_SHADER_PREFIX}Shader To RGB")
        ),
        None,
    )
    original_shader = None
    if shader_to_rgb and shader_to_rgb.inputs["Shader"].is_linked:
        original_shader = shader_to_rgb.inputs["Shader"].links[0].from_socket
    elif output.inputs["Surface"].is_linked:
        original_shader = output.inputs["Surface"].links[0].from_socket

    for link in list(output.inputs["Surface"].links):
        links.remove(link)
    for node in wrapper_nodes:
        nodes.remove(node)
    return original_shader


def apply_shader_to_rgb_bands():
    for material in bpy.data.materials:
        base = material_base_color(material)
        base_linear = srgb_to_linear_color(base)
        color_input = material_base_color_input(material)
        material.use_nodes = True
        material.diffuse_color = base

        nodes = material.node_tree.nodes
        links = material.node_tree.links
        output = material_output_node(material)
        original_shader = remove_pixel_shader_wrapper(material, output)
        if original_shader is None:
            fallback = nodes.new("ShaderNodeBsdfDiffuse")
            mark_pixel_shader_node(fallback, "Fallback Diffuse")
            fallback.location = (-700, 120)
            fallback.inputs["Color"].default_value = base_linear
            if "Roughness" in fallback.inputs:
                fallback.inputs["Roughness"].default_value = 0.85
            original_shader = fallback.outputs["BSDF"]

        if color_input is not None and color_input.is_linked:
            color_source = color_input.links[0].from_socket
        else:
            color = nodes.new("ShaderNodeRGB")
            mark_pixel_shader_node(color, "Base Color")
            color.location = (-170, -120)
            color.outputs["Color"].default_value = base_linear
            color_source = color.outputs["Color"]

        shader_to_rgb = nodes.new("ShaderNodeShaderToRGB")
        mark_pixel_shader_node(shader_to_rgb, "Shader To RGB")
        shader_to_rgb.location = (-450, 120)

        ramp = nodes.new("ShaderNodeValToRGB")
        mark_pixel_shader_node(ramp, "Constant Light Bands")
        ramp.location = (-170, 120)
        ramp.color_ramp.interpolation = "CONSTANT"
        ramp.color_ramp.elements[0].position = 0.32
        ramp.color_ramp.elements[0].color = (0.55, 0.55, 0.55, 1.0)
        ramp.color_ramp.elements[1].position = 0.78
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        mid = ramp.color_ramp.elements.new(0.56)
        mid.color = (0.82, 0.82, 0.82, 1.0)

        multiply = nodes.new("ShaderNodeMixRGB")
        mark_pixel_shader_node(multiply, "Texture Light Bands")
        multiply.location = (90, 120)
        multiply.blend_type = "MULTIPLY"
        multiply.inputs["Fac"].default_value = 1.0

        emission = nodes.new("ShaderNodeEmission")
        mark_pixel_shader_node(emission, "Emission")
        emission.location = (340, 120)
        emission.inputs["Strength"].default_value = 1.0
        output.location = (580, 120)

        links.new(original_shader, shader_to_rgb.inputs["Shader"])
        links.new(shader_to_rgb.outputs["Color"], ramp.inputs["Fac"])
        links.new(color_source, multiply.inputs["Color1"])
        links.new(ramp.outputs["Color"], multiply.inputs["Color2"])
        links.new(multiply.outputs["Color"], emission.inputs["Color"])
        links.new(emission.outputs["Emission"], output.inputs["Surface"])


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.meshes):
        bpy.data.meshes.remove(block)


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise ValueError(f"Unsupported format: {ext}")


def world_bounds():
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No meshes found in imported model")
    mn = Vector((float("inf"),) * 3)
    mx = Vector((float("-inf"),) * 3)
    for o in meshes:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            mn.x, mn.y, mn.z = min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)
            mx.x, mx.y, mx.z = max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)
    return mn, mx


SIDE_LIGHT_X = -1.102
SIDE_LIGHT_Y = -8.874
SIDE_LIGHT_Z = 21.483
SIDE_LIGHT_ROTATION = (
    math.radians(30.03),
    math.radians(1.11),
    math.radians(-4.66),
)
def setup_world_lighting():
    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.0509, 0.0509, 0.0509, 1.0)
        bg.inputs["Strength"].default_value = 1.0


def add_soft_sun(location: tuple[float, float, float],
                 rotation: tuple[float, float, float]):
    bpy.ops.object.light_add(type="SUN", location=location)
    sun = bpy.context.object
    sun.data.energy = 1.0
    sun.data.color = (1.0, 1.0, 1.0)
    sun.data.angle = math.radians(157.38)
    if hasattr(sun.data, "shadow_soft_size"):
        sun.data.shadow_soft_size = 5.0
    sun.rotation_euler = rotation
    setup_world_lighting()
    return sun


def side_lighting_location(side_amount: float) -> tuple[float, float, float]:
    return (SIDE_LIGHT_X * side_amount, SIDE_LIGHT_Y, SIDE_LIGHT_Z)


def side_lighting_rotation(side_amount: float) -> tuple[float, float, float]:
    return (
        SIDE_LIGHT_ROTATION[0],
        SIDE_LIGHT_ROTATION[1],
        SIDE_LIGHT_ROTATION[2] * side_amount,
    )


def setup_side_lighting():
    # Matches the old LPC-style direction: soft sun from
    # behind-and-above the camera (camera is at -Y), very wide sun angle so
    # shadows are soft/painterly, near-black world so unlit surfaces are dark.
    add_soft_sun(side_lighting_location(1.0), side_lighting_rotation(1.0))


def setup_center_lighting():
    # Same light family as side, but centered on X so the lighting is less
    # side-biased. The old side preset is still available with --lighting side.
    add_soft_sun(side_lighting_location(0.0), side_lighting_rotation(0.0))


def setup_lighting(style: str = "center"):
    if style == "side":
        setup_side_lighting()
    else:
        setup_center_lighting()


def setup_color_management():
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def setup_pixel_filter():
    bpy.context.scene.render.filter_size = 0.01


def disable_compositor():
    scene = bpy.context.scene
    scene.render.use_compositing = False
    scene.use_nodes = False
    if hasattr(scene, "compositing_node_group"):
        scene.compositing_node_group = None


def setup_freestyle_outline(thickness: float = 1.0,
                            color: tuple[float, float, float] = (0, 0, 0)):
    scene = bpy.context.scene
    scene.render.use_freestyle = True
    view_layer = bpy.context.view_layer
    view_layer.use_freestyle = True
    settings = view_layer.freestyle_settings
    settings.crease_angle = math.radians(60.0)
    if not settings.linesets:
        settings.linesets.new("Pixel Art Outline")
    for line_set in settings.linesets:
        line_set.select_border = False
        line_style = line_set.linestyle
        line_style.thickness = thickness
        line_style.thickness_position = "CENTER"
        line_style.color = color


def make_emission_material(name: str, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0

    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    material.diffuse_color = color
    return material


def pick_engine():
    engines = [e.identifier for e in
               bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        if candidate in engines:
            return candidate
    return engines[0]


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    clear_scene()
    import_model(os.path.abspath(args.model))

    if args.material_color:
        overrides = {}
        for spec in args.material_color:
            name, _, hex_str = spec.partition("=")
            overrides[name] = parse_hex_rgb(hex_str)
        apply_material_colors(overrides)
    if args.shader_to_rgb:
        apply_shader_to_rgb_bands()

    mn, mx = world_bounds()
    center = (mn + mx) / 2
    size = mx - mn
    max_dim = max(size.x, size.y, size.z)

    # Camera — fixed. We rotate the object (below) instead of orbiting
    # the camera, so the sun's on-screen direction stays consistent across
    # every sprite angle.
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max_dim * args.margin
    cam.data.clip_start = 0.01
    cam.data.clip_end = max_dim * 100
    bpy.context.scene.camera = cam

    setup_lighting(args.lighting)

    # Parent all imported top-level objects to a pivot empty at the model
    # center; rotating the pivot rotates the whole vehicle in place while
    # camera + sun stay fixed in world space.
    top_level = [o for o in bpy.context.scene.objects
                 if o.parent is None and o.type not in ("CAMERA", "LIGHT")]
    bpy.ops.object.empty_add(location=center)
    pivot = bpy.context.object
    for o in top_level:
        if o is pivot:
            continue
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()

    scene = bpy.context.scene
    scene.render.engine = pick_engine()
    scene.render.resolution_x = args.size
    scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    setup_color_management()
    setup_pixel_filter()
    disable_compositor()
    if args.freestyle_outline:
        setup_freestyle_outline(args.freestyle_thickness)
    # EEVEE viewport sampling
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 32

    elev = math.radians(args.elevation)
    distance = max_dim * 4

    # Camera at -Y direction to match LPC reference (sun is oriented
    # assuming camera is south of the scene).
    cam.location = (
        center.x,
        center.y - distance * math.cos(elev),
        center.z + distance * math.sin(elev),
    )
    direction = Vector(center) - cam.location
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")

    # Rolling wheels: Kenney cars use "wheel-<front|back>-<left|right>";
    # decorative wheels like the SUV's spare are just "wheel-back" (no
    # left/right suffix) and must not roll. Other packs (e.g. Public
    # Transport bicycle) use "FrontWheel" / "BackWheel" — any name
    # ending in "wheel" also rolls.
    def is_rolling(name: str) -> bool:
        n = name.lower()
        if n.startswith("wheel"):
            return "left" in n or "right" in n
        return n.endswith("wheel")
    wheels = [o for o in bpy.context.scene.objects
              if o.type == "MESH" and is_rolling(o.name)]

    # Bake any bind rotation (e.g. FBX's axis conversion, which parks
    # the bicycle wheels at 90° Y) into the mesh data, so each wheel's
    # local frame is identity and its cylinder axis is a pure mesh-local
    # axis we can roll around with a plain Euler angle.
    bpy.ops.object.select_all(action="DESELECT")
    for w in wheels:
        w.select_set(True)
    if wheels:
        bpy.context.view_layer.objects.active = wheels[0]
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.ops.object.select_all(action="DESELECT")

    def wheel_local_sizes(obj) -> list[float]:
        verts = obj.data.vertices
        mins = [min(v.co[i] for v in verts) for i in range(3)]
        maxs = [max(v.co[i] for v in verts) for i in range(3)]
        return [maxs[i] - mins[i] for i in range(3)]

    def detect_wheel_axis(obj) -> int:
        """Return axis index (0/1/2) of the shortest mesh-local bbox side —
        the cylinder axle for a disc-shaped wheel mesh."""
        sizes = wheel_local_sizes(obj)
        return sizes.index(min(sizes))

    def detect_wheel_diameter(obj, axis: int) -> float:
        sizes = wheel_local_sizes(obj)
        return max(size for index, size in enumerate(sizes) if index != axis)

    if args.wheel_axis == "auto":
        wheel_axes = {w.name: detect_wheel_axis(w) for w in wheels}
    else:
        fixed = {"x": 0, "y": 1, "z": 2}[args.wheel_axis]
        wheel_axes = {w.name: fixed for w in wheels}
    wheel_diameters = {
        wheel.name: detect_wheel_diameter(wheel, wheel_axes[wheel.name])
        for wheel in wheels
    }
    reference_wheel_diameter = (
        max(wheel_diameters.values()) if wheel_diameters else 0.0
    )
    wheel_step_distance = (
        math.pi * reference_wheel_diameter / args.wheel_frames
        if args.wheel_frames > 1 and reference_wheel_diameter > 0.0
        else 0.0
    )
    wheel_angle_steps = {}
    for wheel in wheels:
        diameter = wheel_diameters[wheel.name]
        if diameter > 0.0 and wheel_step_distance > 0.0:
            wheel_angle_steps[wheel.name] = (
                2 * math.pi * wheel_step_distance / (math.pi * diameter)
            )
        elif args.wheel_frames > 1:
            wheel_angle_steps[wheel.name] = 2 * math.pi / args.wheel_frames
        else:
            wheel_angle_steps[wheel.name] = 0.0

    metrics_path = os.path.join(args.out, "wheel_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as metrics_file:
        json.dump(
            {
                "wheel_frames": args.wheel_frames,
                "wheel_reference": "largest_diameter",
                "wheel_step_distance_world": wheel_step_distance,
                "reference_wheel_diameter_world": reference_wheel_diameter,
                "ortho_scale_world": max_dim * args.margin,
                "wheel_diameters_world": wheel_diameters,
            },
            metrics_file,
            indent=2,
            sort_keys=True,
        )
        metrics_file.write("\n")

    mask_wheel_material = make_emission_material(
        "Pixel Wheel Mask White",
        (1.0, 1.0, 1.0, 1.0),
    )
    mask_body_material = make_emission_material(
        "Pixel Wheel Mask Occluder Black",
        (0.0, 0.0, 0.0, 1.0),
    )
    wheel_names = {wheel.name for wheel in wheels}

    def render_wheel_mask(mask_path: str):
        scene = bpy.context.scene
        original_filepath = scene.render.filepath
        original_use_freestyle = scene.render.use_freestyle
        original_layer_use_freestyle = bpy.context.view_layer.use_freestyle
        material_snapshots = [
            (obj, list(obj.data.materials))
            for obj in bpy.context.scene.objects
            if obj.type == "MESH"
        ]

        for wheel_obj in wheels:
            wheel_obj.rotation_mode = "XYZ"
            wheel_obj.rotation_euler = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()

        try:
            scene.render.filepath = mask_path
            scene.render.use_freestyle = False
            bpy.context.view_layer.use_freestyle = False
            for obj, _materials in material_snapshots:
                material = (
                    mask_wheel_material
                    if obj.name in wheel_names else mask_body_material
                )
                obj.data.materials.clear()
                obj.data.materials.append(material)
            bpy.ops.render.render(write_still=True)
        finally:
            for obj, materials in material_snapshots:
                obj.data.materials.clear()
                for material in materials:
                    obj.data.materials.append(material)
            scene.render.filepath = original_filepath
            scene.render.use_freestyle = original_use_freestyle
            bpy.context.view_layer.use_freestyle = original_layer_use_freestyle
            bpy.context.view_layer.update()

    yaw_rad = math.radians(args.yaw)
    for i in range(args.angles):
        az = 2 * math.pi * i / args.angles
        # Negative az keeps the angle-index→view mapping identical to the
        # previous camera-orbit convention (angle_000 = +X side, CCW).
        pivot.rotation_euler = (0.0, 0.0, -az + yaw_rad)
        bpy.context.view_layer.update()
        if args.wheel_mask_out:
            os.makedirs(args.wheel_mask_out, exist_ok=True)
            render_wheel_mask(
                os.path.join(args.wheel_mask_out, f"angle_{i:03d}.png")
            )

        for w in range(args.wheel_frames):
            for wheel_obj in wheels:
                wheel_obj.rotation_mode = "XYZ"
                rot = [0.0, 0.0, 0.0]
                rot[wheel_axes[wheel_obj.name]] = (
                    wheel_angle_steps[wheel_obj.name] * w
                )
                wheel_obj.rotation_euler = rot

            name = f"angle_{i:03d}.png" if args.wheel_frames == 1 \
                else f"angle_{i:03d}_w{w:02d}.png"
            scene.render.filepath = os.path.join(args.out, name)
            bpy.ops.render.render(write_still=True)
            print(f"[render] wrote {scene.render.filepath}")


if __name__ == "__main__":
    main()
