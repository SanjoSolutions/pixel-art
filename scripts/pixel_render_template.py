"""Reusable Blender scene helper for matching this repo's sprite render path.

This file is embedded into ``pixel_render_template.blend`` by
``scripts/create_pixel_render_template_blend.py``. In Blender, run this text
block once (or allow trusted auto-run scripts) after importing a model. The
registered render hook then frames visible mesh objects and applies the same
settings used by the furniture regeneration pipeline.
"""

from __future__ import annotations

import math
from typing import Iterable

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector


CAMERA_NAME = "Pixel Render Camera"
SUN_NAME = "Pixel Render Sun"
ORIGIN_NAME = "MODEL_ORIGIN"
HELPER_COLLECTION_NAME = "Pixel Render Helpers"
PIXEL_SHADER_PREFIX = "Pixel Render "
SIDE_LIGHT_X = -1.102
SIDE_LIGHT_Y = -8.874
SIDE_LIGHT_Z = 21.483
SIDE_LIGHT_ROTATION = (
    math.radians(30.03),
    math.radians(1.11),
    math.radians(-4.66),
)


DEFAULTS = {
    "pixel_render_pixels_per_unit": 64.0,
    "pixel_render_tile_size": 32,
    "pixel_render_padding_pixels": 16,
    "pixel_render_elevation": 60.0,
    "pixel_render_light_side": 0.0,
    "pixel_render_shader_to_rgb": True,
    "pixel_render_freestyle_outline": True,
    "pixel_render_freestyle_thickness": 1.0,
}

LEGACY_PROPERTY_NAMES = (
    "pixel_render_auto_prepare",
    "pixel_render_live_update",
    "pixel_render_fixed_scale",
    "pixel_render_fit_square_size",
    "pixel_render_margin",
)
_LIVE_UPDATE_IN_PROGRESS = False


def scene_setting(scene: bpy.types.Scene, name: str):
    return getattr(scene, name, scene.get(name, DEFAULTS[name]))


def set_default_scene_settings(scene: bpy.types.Scene) -> None:
    for name in LEGACY_PROPERTY_NAMES:
        if name in scene:
            del scene[name]
    for name, value in DEFAULTS.items():
        if name not in scene:
            scene[name] = value


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def srgb_to_linear_channel(value: float) -> float:
    value = clamp01(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def srgb_to_linear_color(color: Iterable[float]) -> tuple[float, float, float, float]:
    red, green, blue, alpha = color
    return (
        srgb_to_linear_channel(red),
        srgb_to_linear_channel(green),
        srgb_to_linear_channel(blue),
        alpha,
    )


def material_base_color(material: bpy.types.Material) -> tuple[float, float, float, float]:
    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
                color = node.inputs["Base Color"].default_value
                return color[0], color[1], color[2], color[3]
    color = material.diffuse_color
    return color[0], color[1], color[2], color[3]


def material_output_node(material: bpy.types.Material) -> bpy.types.Node:
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


def material_base_color_input(material: bpy.types.Material):
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


def mark_pixel_shader_node(node: bpy.types.Node, role: str) -> None:
    node.name = f"{PIXEL_SHADER_PREFIX}{role}"
    node["pixel_shader_wrapper"] = True
    node["pixel_shader_role"] = role


def remove_pixel_shader_wrapper(
    material: bpy.types.Material,
    output: bpy.types.Node,
    require_wrapper: bool = False,
):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    wrapper_nodes = [
        node for node in nodes
        if node.get("pixel_shader_wrapper")
        or node.name.startswith(PIXEL_SHADER_PREFIX)
    ]
    if require_wrapper and not wrapper_nodes:
        return None

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
    if original_shader is not None and original_shader.node in wrapper_nodes:
        original_shader = None

    for link in list(output.inputs["Surface"].links):
        links.remove(link)
    for node in wrapper_nodes:
        nodes.remove(node)
    return original_shader


def apply_shader_to_rgb_bands(materials: Iterable[bpy.types.Material]) -> None:
    for material in materials:
        if material is None:
            continue

        base_color = material_base_color(material)
        base_linear = srgb_to_linear_color(base_color)
        color_input = material_base_color_input(material)
        material.use_nodes = True
        material.diffuse_color = base_color

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
        mid_band = ramp.color_ramp.elements.new(0.56)
        mid_band.color = (0.82, 0.82, 0.82, 1.0)

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


def remove_shader_to_rgb_bands(materials: Iterable[bpy.types.Material]) -> None:
    for material in materials:
        if material is None or not material.use_nodes or not material.node_tree:
            continue

        output = material_output_node(material)
        original_shader = remove_pixel_shader_wrapper(
            material,
            output,
            require_wrapper=True,
        )
        if original_shader is not None:
            material.node_tree.links.new(original_shader, output.inputs["Surface"])


def helper_collection() -> bpy.types.Collection:
    collection = bpy.data.collections.get(HELPER_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(HELPER_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(collection)
    collection["pixel_render_helper"] = True
    return collection


def move_to_helper_collection(obj: bpy.types.Object) -> None:
    collection = helper_collection()
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for current_collection in list(obj.users_collection):
        if current_collection != collection:
            current_collection.objects.unlink(obj)
    obj["pixel_render_helper"] = True


def ensure_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    camera = bpy.data.objects.get(CAMERA_NAME)
    if camera is None or camera.type != "CAMERA":
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        camera.name = CAMERA_NAME
        camera.data.name = f"{CAMERA_NAME} Data"
    camera.data.type = "ORTHO"
    camera.data.clip_start = 0.01
    scene.camera = camera
    move_to_helper_collection(camera)
    return camera


def ensure_sun(scene: bpy.types.Scene) -> bpy.types.Object:
    sun = bpy.data.objects.get(SUN_NAME)
    if sun is None or sun.type != "LIGHT":
        bpy.ops.object.light_add(type="SUN")
        sun = bpy.context.object
        sun.name = SUN_NAME
        sun.data.name = f"{SUN_NAME} Data"
    side_amount = clamp01(float(scene_setting(scene, "pixel_render_light_side")))
    sun.location = (SIDE_LIGHT_X * side_amount, SIDE_LIGHT_Y, SIDE_LIGHT_Z)
    sun.rotation_euler = (
        SIDE_LIGHT_ROTATION[0],
        SIDE_LIGHT_ROTATION[1],
        SIDE_LIGHT_ROTATION[2] * side_amount,
    )
    sun.data.type = "SUN"
    sun.data.energy = 1.0
    sun.data.color = (1.0, 1.0, 1.0)
    sun.data.angle = math.radians(157.38)
    if hasattr(sun.data, "shadow_soft_size"):
        sun.data.shadow_soft_size = 5.0
    move_to_helper_collection(sun)
    return sun


def ensure_origin_empty() -> bpy.types.Object:
    origin = bpy.data.objects.get(ORIGIN_NAME)
    if origin is None:
        bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 0.0, 0.0))
        origin = bpy.context.object
        origin.name = ORIGIN_NAME
    origin.empty_display_size = 0.5
    move_to_helper_collection(origin)
    return origin


def object_is_in_helper_collection(obj: bpy.types.Object) -> bool:
    return any(
        collection.get("pixel_render_helper")
        for collection in obj.users_collection
    )


def render_meshes(scene: bpy.types.Scene) -> list[bpy.types.Object]:
    return [
        obj
        for obj in scene.objects
        if obj.type == "MESH"
        and not obj.hide_render
        and not obj.get("pixel_render_helper")
        and not object_is_in_helper_collection(obj)
    ]


def materials_for_meshes(meshes: Iterable[bpy.types.Object]) -> set[bpy.types.Material]:
    materials = set()
    for mesh_object in meshes:
        for slot in mesh_object.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
    return materials


def world_bounds(meshes: Iterable[bpy.types.Object]) -> tuple[Vector, Vector]:
    bounds_min = Vector((float("inf"), float("inf"), float("inf")))
    bounds_max = Vector((float("-inf"), float("-inf"), float("-inf")))
    for mesh_object in meshes:
        for corner in mesh_object.bound_box:
            world_corner = mesh_object.matrix_world @ Vector(corner)
            bounds_min.x = min(bounds_min.x, world_corner.x)
            bounds_min.y = min(bounds_min.y, world_corner.y)
            bounds_min.z = min(bounds_min.z, world_corner.z)
            bounds_max.x = max(bounds_max.x, world_corner.x)
            bounds_max.y = max(bounds_max.y, world_corner.y)
            bounds_max.z = max(bounds_max.z, world_corner.z)
    return bounds_min, bounds_max


def projected_bounds(
    camera: bpy.types.Object,
    meshes: Iterable[bpy.types.Object],
) -> tuple[Vector, Vector]:
    camera_inverse = camera.matrix_world.inverted()
    projected_min = Vector((float("inf"), float("inf")))
    projected_max = Vector((float("-inf"), float("-inf")))
    for mesh_object in meshes:
        for corner in mesh_object.bound_box:
            local_corner = camera_inverse @ (mesh_object.matrix_world @ Vector(corner))
            projected_min.x = min(projected_min.x, local_corner.x)
            projected_min.y = min(projected_min.y, local_corner.y)
            projected_max.x = max(projected_max.x, local_corner.x)
            projected_max.y = max(projected_max.y, local_corner.y)
    return projected_min, projected_max


def ceil_to_multiple(value: float, multiple: int) -> int:
    return max(multiple, math.ceil(value / multiple) * multiple)


def pick_engine() -> str:
    engines = [
        engine.identifier
        for engine in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    ]
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        if candidate in engines:
            return candidate
    return engines[0]


def setup_color_management(scene: bpy.types.Scene) -> None:
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def setup_pixel_filter(scene: bpy.types.Scene) -> None:
    scene.render.filter_size = 0.01


def disable_compositor(scene: bpy.types.Scene) -> None:
    scene.render.use_compositing = False
    scene.use_nodes = False
    if hasattr(scene, "compositing_node_group"):
        scene.compositing_node_group = None


def setup_world(scene: bpy.types.Scene) -> None:
    world = scene.world or bpy.data.worlds.new("Pixel Render World")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.0509, 0.0509, 0.0509, 1.0)
        background.inputs["Strength"].default_value = 1.0


def setup_freestyle_outline(scene: bpy.types.Scene) -> None:
    use_outline = bool(scene_setting(scene, "pixel_render_freestyle_outline"))
    scene.render.use_freestyle = use_outline
    bpy.context.view_layer.use_freestyle = use_outline
    if not use_outline:
        return

    settings = bpy.context.view_layer.freestyle_settings
    if not settings.linesets:
        settings.linesets.new("Pixel Art Outline")
    for line_set in settings.linesets:
        line_set.linestyle.thickness = scene_setting(
            scene,
            "pixel_render_freestyle_thickness",
        )
        line_set.linestyle.thickness_position = "CENTER"
        line_set.linestyle.color = (0.0, 0.0, 0.0)


def configure_render(scene: bpy.types.Scene, width: int, height: int) -> None:
    scene.render.engine = pick_engine()
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    setup_color_management(scene)
    setup_pixel_filter(scene)
    disable_compositor(scene)
    setup_world(scene)
    setup_freestyle_outline(scene)
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 32


def point_camera_at(camera: bpy.types.Object, center: Vector) -> None:
    direction = center - camera.location
    camera.rotation_mode = "QUATERNION"
    camera.rotation_quaternion = direction.to_track_quat("-Z", "Y")


def fit_ortho_scale(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    width: int,
    height: int,
    pixels_per_unit: float,
) -> float:
    scene.render.resolution_x = width
    scene.render.resolution_y = height

    original_scale = camera.data.ortho_scale
    camera.data.ortho_scale = 1.0
    frame = camera.data.view_frame(scene=scene)
    camera.data.ortho_scale = original_scale

    frame_width = max(vertex.x for vertex in frame) - min(vertex.x for vertex in frame)
    frame_height = max(vertex.y for vertex in frame) - min(vertex.y for vertex in frame)
    target_width = width / pixels_per_unit
    target_height = height / pixels_per_unit
    return max(target_width / frame_width, target_height / frame_height)


def prepare_template_scene(scene: bpy.types.Scene | None = None) -> tuple[int, int]:
    scene = scene or bpy.context.scene
    set_default_scene_settings(scene)
    ensure_origin_empty()
    ensure_sun(scene)

    meshes = render_meshes(scene)
    if not meshes:
        configure_render(scene, 128, 128)
        raise RuntimeError("Import or unhide at least one mesh object before rendering.")

    materials = materials_for_meshes(meshes)
    if scene_setting(scene, "pixel_render_shader_to_rgb"):
        apply_shader_to_rgb_bands(materials)
    else:
        remove_shader_to_rgb_bands(materials)

    bounds_min, bounds_max = world_bounds(meshes)
    center = (bounds_min + bounds_max) / 2
    size = bounds_max - bounds_min
    max_dimension = max(size.x, size.y, size.z)
    if max_dimension <= 0:
        raise RuntimeError("Imported mesh bounds are empty.")

    elevation = math.radians(scene_setting(scene, "pixel_render_elevation"))
    distance = max_dimension * 4
    camera = ensure_camera(scene)
    camera.data.clip_end = max(max_dimension * 100, 100.0)
    camera.location = (
        center.x,
        center.y - distance * math.cos(elevation),
        center.z + distance * math.sin(elevation),
    )
    point_camera_at(camera, center)
    bpy.context.view_layer.update()

    projected_min, projected_max = projected_bounds(camera, meshes)
    projected_size = projected_max - projected_min
    pixels_per_unit = float(scene_setting(scene, "pixel_render_pixels_per_unit"))
    tile_size = int(scene_setting(scene, "pixel_render_tile_size"))
    padding_pixels = int(scene_setting(scene, "pixel_render_padding_pixels"))
    width = ceil_to_multiple(
        projected_size.x * pixels_per_unit + padding_pixels * 2,
        tile_size,
    )
    height = ceil_to_multiple(
        projected_size.y * pixels_per_unit + padding_pixels * 2,
        tile_size,
    )

    screen_center = (projected_min + projected_max) / 2
    world_offset = camera.matrix_world.to_quaternion() @ Vector(
        (screen_center.x, screen_center.y, 0.0)
    )
    camera.location += world_offset
    camera.data.ortho_scale = fit_ortho_scale(
        scene,
        camera,
        width,
        height,
        pixels_per_unit,
    )

    configure_render(scene, width, height)
    print(
        "[pixel-render-template] prepared "
        f"{len(meshes)} mesh object(s), output {width}x{height}"
    )
    return width, height


class PIXEL_RENDER_OT_prepare(bpy.types.Operator):
    bl_idname = "pixel_render.prepare"
    bl_label = "Prepare Pixel Render"
    bl_description = "Frame imported meshes and apply the repo's Blender render settings"

    def execute(self, context: bpy.types.Context):
        try:
            width, height = prepare_template_scene(context.scene)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Pixel render prepared at {width}x{height}")
        return {"FINISHED"}


class PIXEL_RENDER_PT_template(bpy.types.Panel):
    bl_label = "Pixel Render Template"
    bl_idname = "PIXEL_RENDER_PT_template"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        layout.operator("pixel_render.prepare", icon="RENDER_STILL")
        layout.prop(scene, "pixel_render_pixels_per_unit")
        layout.prop(scene, "pixel_render_tile_size")
        layout.prop(scene, "pixel_render_padding_pixels")
        layout.prop(scene, "pixel_render_elevation")
        layout.prop(scene, "pixel_render_light_side")
        layout.prop(scene, "pixel_render_shader_to_rgb")
        layout.prop(scene, "pixel_render_freestyle_outline")
        layout.prop(scene, "pixel_render_freestyle_thickness")


@persistent
def pixel_render_auto_prepare_handler(scene: bpy.types.Scene | None = None, *_args) -> None:
    scene = scene or bpy.context.scene
    try:
        prepare_template_scene(scene)
    except Exception as exc:
        print(f"[pixel-render-template] skipped auto-prepare: {exc}")


def pixel_render_settings_update(scene: bpy.types.Scene, _context: bpy.types.Context) -> None:
    global _LIVE_UPDATE_IN_PROGRESS
    if _LIVE_UPDATE_IN_PROGRESS:
        return
    try:
        _LIVE_UPDATE_IN_PROGRESS = True
        prepare_template_scene(scene)
    except Exception as exc:
        print(f"[pixel-render-template] skipped live update: {exc}")
    finally:
        _LIVE_UPDATE_IN_PROGRESS = False


CLASSES = (
    PIXEL_RENDER_OT_prepare,
    PIXEL_RENDER_PT_template,
)


def register_properties() -> None:
    bpy.types.Scene.pixel_render_pixels_per_unit = bpy.props.FloatProperty(
        name="Pixels Per Unit",
        min=0.001,
        default=DEFAULTS["pixel_render_pixels_per_unit"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_tile_size = bpy.props.IntProperty(
        name="Tile Size",
        min=1,
        default=DEFAULTS["pixel_render_tile_size"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_padding_pixels = bpy.props.IntProperty(
        name="Padding Pixels",
        min=0,
        default=DEFAULTS["pixel_render_padding_pixels"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_elevation = bpy.props.FloatProperty(
        name="Camera Elevation",
        default=DEFAULTS["pixel_render_elevation"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_light_side = bpy.props.FloatProperty(
        name="Side Light Amount",
        description="Blend lighting from centered (0) to side-biased (1)",
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        default=DEFAULTS["pixel_render_light_side"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_shader_to_rgb = bpy.props.BoolProperty(
        name="Shader To RGB Bands",
        default=DEFAULTS["pixel_render_shader_to_rgb"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_freestyle_outline = bpy.props.BoolProperty(
        name="Freestyle Outline",
        default=DEFAULTS["pixel_render_freestyle_outline"],
        update=pixel_render_settings_update,
    )
    bpy.types.Scene.pixel_render_freestyle_thickness = bpy.props.FloatProperty(
        name="Outline Thickness",
        min=0.0,
        default=DEFAULTS["pixel_render_freestyle_thickness"],
        update=pixel_render_settings_update,
    )


def unregister_properties() -> None:
    for name in (*DEFAULTS, *LEGACY_PROPERTY_NAMES):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def register() -> None:
    unregister_handler()
    unregister_properties()
    register_properties()
    for blender_class in CLASSES:
        try:
            bpy.utils.register_class(blender_class)
        except ValueError:
            pass
    bpy.app.handlers.render_init.append(pixel_render_auto_prepare_handler)
    set_default_scene_settings(bpy.context.scene)
    print("[pixel-render-template] registered")


def unregister_handler() -> None:
    for handlers in (bpy.app.handlers.render_init, bpy.app.handlers.render_pre):
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == "pixel_render_auto_prepare_handler":
                handlers.remove(handler)


def unregister() -> None:
    unregister_handler()
    for blender_class in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(blender_class)
        except RuntimeError:
            pass
    unregister_properties()
    print("[pixel-render-template] unregistered")


if __name__ == "__main__":
    register()
    try:
        prepare_template_scene(bpy.context.scene)
    except RuntimeError as error:
        print(f"[pixel-render-template] {error}")
