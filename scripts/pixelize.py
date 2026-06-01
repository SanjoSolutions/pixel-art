"""Convert rendered PNGs to pixel art.

Steps:
  1. Resize to target resolution, or preserve input size
  2. Optional quantize to a limited color palette
  3. Optional alpha-based outline
  4. Optional preview upscale (NEAREST)

Palette sharing:
  When --share-palette-by-angle is set, frames that belong to the same angle
  (filename prefix before "_w") are quantized with a single shared palette.
  This keeps body pixels identical across wheel-animation frames (prevents
  flicker from median-cut choosing different palettes per frame).
"""
import argparse
import colorsys
import json
import math
import os
import re
from pathlib import Path
from collections import defaultdict
from PIL import Image, ImageFilter

ANGLE_GROUP = re.compile(r"^(.*?)(?:_w\d+)?$")


RESAMPLE_FILTERS = {
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "lanczos": Image.Resampling.LANCZOS,
    "nearest": Image.Resampling.NEAREST,
}

ALIGNMENTS = {
    "back-left",
    "back",
    "back-right",
    "left",
    "center",
    "none",
    "right",
    "front-left",
    "front",
    "front-right",
}

HORIZONTAL_ALIGNMENT_EDGE = {
    "back-left": "left",
    "left": "left",
    "front-left": "left",
    "back-right": "right",
    "right": "right",
    "front-right": "right",
}

VERTICAL_ALIGNMENT_EDGE = {
    "back-left": "back",
    "back": "back",
    "back-right": "back",
    "front-left": "front",
    "front": "front",
    "front-right": "front",
}

EDGE_GRIDLINE_PREFERENCE = {
    "left": "min",
    "back": "min",
    "right": "max",
    "front": "max",
}
PIXEL_DATA_ALIGNMENT_EDGES = {"left", "right", "front"}
ALIGNMENT_FIT_EPSILON = 0.5


def downscale(img: Image.Image, size: int,
              resample: Image.Resampling = Image.Resampling.LANCZOS) -> Image.Image:
    return img.resize((size, size), resample)


def _split_rgb_alpha(img: Image.Image):
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    r, g, b, a = img.split()
    return Image.merge("RGB", (r, g, b)), a.point(lambda v: 255 if v >= 128 else 0)


def binarize_alpha(img: Image.Image) -> Image.Image:
    rgb, alpha = _split_rgb_alpha(img)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def hue_distance(a: float, b: float) -> float:
    diff = abs(a - b)
    return min(diff, 1.0 - diff)


def normalized_rgb(color: tuple[int, int, int]) -> tuple[float, float, float]:
    return color[0] / 255.0, color[1] / 255.0, color[2] / 255.0


def hsl_color(color: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = normalized_rgb(color)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    return hue, saturation, lightness


def rgb_distance_squared(
    source: tuple[int, int, int],
    candidate: tuple[int, int, int],
) -> float:
    return sum((source[i] - candidate[i]) ** 2 for i in range(3))


def hsl_distance_squared(
    source: tuple[int, int, int],
    candidate: tuple[int, int, int],
) -> float:
    source_hue, source_saturation, source_lightness = hsl_color(source)
    candidate_hue, candidate_saturation, candidate_lightness = hsl_color(candidate)
    hue_weight = max(source_saturation, candidate_saturation, 0.05)
    hue = hue_distance(source_hue, candidate_hue) * hue_weight
    saturation = source_saturation - candidate_saturation
    lightness = source_lightness - candidate_lightness
    rgb = (rgb_distance_squared(source, candidate) ** 0.5) / 441.67295593
    return (
        (hue * 3.0) ** 2
        + (saturation * 0.9) ** 2
        + (lightness * 2.2) ** 2
        + (rgb * 0.25) ** 2
    )


def nearest_palette_color(
    color: tuple[int, int, int],
    palette: list[tuple[int, int, int]],
    distance: str,
) -> tuple[int, int, int]:
    if distance == "rgb":
        metric = rgb_distance_squared
    elif distance == "hsl":
        metric = hsl_distance_squared
    else:
        raise ValueError(f"Unsupported palette distance: {distance}")
    return min(palette, key=lambda candidate: metric(color, candidate))


def quantize_to_palette_rgba(
    img: Image.Image,
    palette: list[tuple[int, int, int]],
    distance: str,
) -> Image.Image:
    if not palette:
        raise ValueError("palette must not be empty")

    img = img.convert("RGBA")
    mapped: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    out_data = []
    for r, g, b, a in img.getdata():
        if a < 128:
            out_data.append((0, 0, 0, 0))
            continue
        source = (r, g, b)
        if source not in mapped:
            mapped[source] = nearest_palette_color(source, palette, distance)
        out_data.append((*mapped[source], 255))

    out = Image.new("RGBA", img.size)
    out.putdata(out_data)
    return out


def quantize_rgba(img: Image.Image, colors: int,
                  palette_ref: Image.Image | None = None,
                  palette_colors: list[tuple[int, int, int]] | None = None,
                  palette_distance: str = "pillow") -> Image.Image:
    """Quantize RGB while preserving alpha cutoff.

    If palette_ref is provided (a palette-mode image), apply that palette
    deterministically so identical RGB input produces identical output
    across calls.
    """
    if palette_ref is not None and palette_distance != "pillow":
        if palette_colors is None:
            raise ValueError("palette_colors is required for custom distance")
        return quantize_to_palette_rgba(img, palette_colors, palette_distance)

    rgb, a_bin = _split_rgb_alpha(img)
    if palette_ref is not None:
        q = rgb.quantize(palette=palette_ref, dither=Image.Dither.NONE)
    else:
        q = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                         dither=Image.Dither.NONE)
    q = q.convert("RGBA")
    q.putalpha(a_bin)
    return q


def build_shared_palette(images: list[Image.Image], colors: int) -> Image.Image:
    """Stack images vertically, then median-cut to a shared palette.

    Using the stack (rather than one arbitrary frame) means every color that
    appears in any frame is represented in the palette, so no frame gets
    unfairly penalized.
    """
    rgbs = [_split_rgb_alpha(im)[0] for im in images]
    w = rgbs[0].width
    h = rgbs[0].height
    stacked = Image.new("RGB", (w, h * len(rgbs)))
    for i, r in enumerate(rgbs):
        stacked.paste(r, (0, i * h))
    return stacked.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                            dither=Image.Dither.NONE)


def add_outline(img: Image.Image, color=(0, 0, 0, 255)) -> Image.Image:
    """Add 1px outline around the opaque silhouette."""
    alpha = img.split()[-1]
    # Dilate the alpha by 1 pixel using MaxFilter
    edge = alpha.filter(ImageFilter.MaxFilter(3))
    outline = Image.new("RGBA", img.size, color)
    outline.putalpha(edge)
    out = Image.alpha_composite(outline, img)
    return out


def trim_transparent(img: Image.Image, padding: int = 0,
                     grid_size: int = 0,
                     alignment_anchors: dict[str, dict[str, float]] | None = None,
                     alignment: str | None = None,
                     fixed_width: int | None = None) -> Image.Image:
    """Trim transparent borders, then round canvas up to a grid size."""
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img

    x0, y0, x1, y1 = bbox
    content_w = x1 - x0
    content_h = y1 - y0
    desired_w = content_w + padding * 2
    desired_h = content_h + padding * 2
    if fixed_width is not None:
        if img.width != fixed_width:
            raise ValueError(
                f"Rendered width is {img.width}px, expected {fixed_width}px"
            )
        desired_w = img.width
        crop_box = (
            0,
            max(0, y0 - padding),
            img.width,
            min(img.height, y1 + padding),
        )
    else:
        crop_box = (
            max(0, x0 - padding),
            max(0, y0 - padding),
            min(img.width, x1 + padding),
            min(img.height, y1 + padding),
        )
    crop = img.crop(crop_box)

    target_w, target_h = desired_w, desired_h
    if grid_size > 0:
        if fixed_width is None:
            target_w = max(grid_size, math.ceil(target_w / grid_size) * grid_size)
        target_h = max(grid_size, math.ceil(target_h / grid_size) * grid_size)

    base_x = (target_w - desired_w) // 2
    base_y = (target_h - desired_h) // 2
    if fixed_width is None:
        paste_x = base_x + padding - (x0 - crop_box[0])
    else:
        paste_x = 0
    paste_y = base_y + padding - (y0 - crop_box[1])
    horizontal_edge = HORIZONTAL_ALIGNMENT_EDGE.get(alignment or "")
    vertical_edge = VERTICAL_ALIGNMENT_EDGE.get(alignment or "")
    if alignment not in ("none", "center") and vertical_edge is None:
        vertical_edge = "back"

    if alignment_anchors is not None and grid_size > 0:
        if fixed_width is None and horizontal_edge is not None:
            if horizontal_edge in PIXEL_DATA_ALIGNMENT_EDGES:
                anchor_x = pixel_data_alignment_anchor(
                    horizontal_edge,
                    x0 - crop_box[0],
                    x1 - crop_box[0],
                )
                gridline_preference = "nearest"
            else:
                anchor_x = alignment_anchors.get(horizontal_edge, {}).get("x")
                if anchor_x is not None:
                    anchor_x -= crop_box[0]
                gridline_preference = EDGE_GRIDLINE_PREFERENCE[horizontal_edge]
            if anchor_x is not None:
                target_w, paste_x = aligned_anchor_axis(
                    target_w,
                    grid_size,
                    anchor_x,
                    x0 - crop_box[0],
                    x1 - crop_box[0],
                    paste_x,
                    gridline_preference,
                )
        if vertical_edge is not None:
            if vertical_edge in PIXEL_DATA_ALIGNMENT_EDGES:
                anchor_y = pixel_data_alignment_anchor(
                    vertical_edge,
                    y0 - crop_box[1],
                    y1 - crop_box[1],
                )
                gridline_preference = "nearest"
            else:
                anchor_y = alignment_anchors.get(vertical_edge, {}).get("y")
                if anchor_y is not None:
                    anchor_y -= crop_box[1]
                gridline_preference = EDGE_GRIDLINE_PREFERENCE[vertical_edge]
            if anchor_y is not None:
                target_h, paste_y = aligned_anchor_axis(
                    target_h,
                    grid_size,
                    anchor_y,
                    y0 - crop_box[1],
                    y1 - crop_box[1],
                    paste_y,
                    gridline_preference,
                )
    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    out.paste(crop, (paste_x, paste_y), crop)
    return out


def pixel_data_alignment_anchor(
    edge: str,
    content_start_in_crop: int,
    content_end_in_crop: int,
) -> int | None:
    if edge == "left":
        return content_start_in_crop
    if edge in ("right", "front"):
        return content_end_in_crop
    return None


def aligned_anchor_axis(
    target_length: int,
    grid_size: int,
    anchor_in_crop: float,
    content_start_in_crop: int,
    content_end_in_crop: int,
    preferred_offset: int,
    gridline_preference: str,
) -> tuple[int, int]:
    while True:
        min_gridline = max(
            0,
            math.ceil(
                (
                    anchor_in_crop
                    - content_start_in_crop
                    - ALIGNMENT_FIT_EPSILON
                ) / grid_size
            ),
        )
        max_gridline = min(
            target_length // grid_size,
            math.floor(
                (
                    target_length
                    - content_end_in_crop
                    + anchor_in_crop
                    + ALIGNMENT_FIT_EPSILON
                )
                / grid_size
            ),
        )
        if min_gridline <= max_gridline:
            if gridline_preference == "min":
                gridline = min_gridline
            elif gridline_preference == "max":
                gridline = max_gridline
            else:
                preferred_gridline = round(
                    (preferred_offset + anchor_in_crop) / grid_size
                )
                gridline = min(
                    max(preferred_gridline, min_gridline),
                    max_gridline,
                )
            return target_length, round(gridline * grid_size - anchor_in_crop)
        target_length += grid_size


def upscale_preview(img: Image.Image, factor: int) -> Image.Image:
    return img.resize((img.width * factor, img.height * factor), Image.Resampling.NEAREST)


def _angle_group_key(name: str) -> str:
    """Return the group key for shared-palette grouping.

    angle_000.png         -> "angle_000"  (solo group)
    angle_000_w00.png     -> "angle_000"  (shares palette with other _wXX)
    angle_000_w01.png     -> "angle_000"
    """
    stem = Path(name).stem
    if "_w" in stem:
        return stem.rsplit("_w", 1)[0]
    return stem


def scaled_anchor_pixel(
    pixel: dict,
    scale_x: float,
    scale_y: float,
) -> dict[str, float] | None:
    if "x" not in pixel and "y" not in pixel:
        return None
    scaled = {}
    if "x" in pixel:
        scaled["x"] = float(pixel["x"]) * scale_x
    if "y" in pixel:
        scaled["y"] = float(pixel["y"]) * scale_y
    return scaled


def load_alignment_anchors(
    path: Path,
    output_width: int,
    output_height: int,
) -> dict[str, dict[str, float]] | None:
    metadata_path = path.with_suffix(".anchor.json")
    if not metadata_path.exists():
        return None
    with metadata_path.open() as metadata_file:
        metadata = json.load(metadata_file)
    source_width = metadata.get("source_width", output_width)
    source_height = metadata.get("source_height", output_height)
    scale_x = output_width / source_width
    scale_y = output_height / source_height

    alignment_pixels = metadata.get("alignment_pixels")
    if isinstance(alignment_pixels, dict):
        anchors = {}
        for edge in ("left", "right", "back", "front"):
            pixel = alignment_pixels.get(edge)
            if not isinstance(pixel, dict):
                continue
            scaled = scaled_anchor_pixel(pixel, scale_x, scale_y)
            if scaled:
                anchors[edge] = scaled
        if anchors:
            return anchors
    raise ValueError(
        f"{metadata_path} does not contain alignment_pixels"
    )


def load_alignment_manifest(path_text: str | None) -> dict[str, str]:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    manifest = json.loads(path.read_text())
    alignments = {}
    for sprite in manifest.get("sprites", []):
        name = sprite.get("name")
        alignment = sprite.get("alignment")
        if alignment is None:
            continue
        if alignment not in ALIGNMENTS:
            raise SystemExit(
                f"{path} sprite {name} has invalid alignment {alignment!r}"
            )
        alignments[str(name)] = alignment
    return alignments


def load_fixed_width_manifest(path_text: str | None, tile_size: int) -> dict[str, int]:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    manifest = json.loads(path.read_text())
    widths = {}
    manifest_tile_size = int(manifest.get("tile_size") or tile_size)
    if manifest_tile_size <= 0:
        raise SystemExit(f"{path} has invalid tile_size {manifest_tile_size!r}")
    for sprite in manifest.get("sprites", []):
        if "width" not in sprite:
            continue
        name = sprite.get("name")
        try:
            width_cells = float(sprite["width"])
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"{path} sprite {name} has invalid width {sprite['width']!r}"
            ) from exc
        if width_cells <= 0 or abs(width_cells - round(width_cells)) > 0.0001:
            raise SystemExit(
                f"{path} sprite {name} width must be a whole positive cell count"
            )
        widths[str(name)] = round(width_cells * manifest_tile_size)
    return widths


def parse_prefix_int_rules(specs: list[str], option_name: str) -> list[tuple[str, int]]:
    rules = []
    for spec in specs:
        prefix, separator, value_text = spec.partition("=")
        if not separator or not prefix or not value_text:
            raise SystemExit(f"Invalid {option_name} {spec!r}; expected PREFIX=VALUE")
        try:
            value = int(value_text)
        except ValueError as exc:
            raise SystemExit(f"Invalid integer in {option_name} {spec!r}") from exc
        if value < 0:
            raise SystemExit(f"Value must be non-negative in {option_name} {spec!r}")
        rules.append((prefix, value))
    return rules


def prefix_rule_value(
    stem: str,
    rules: list[tuple[str, int]],
    default: int,
) -> int:
    value = default
    matched_prefix_len = -1
    for prefix, rule_value in rules:
        if stem.startswith(prefix) and len(prefix) > matched_prefix_len:
            value = rule_value
            matched_prefix_len = len(prefix)
    return value


def save_pixel(pixel: Image.Image, out_dir: Path, name: str, preview_scale: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    pixel.save(out_dir / name)
    if preview_scale > 1:
        preview = upscale_preview(pixel, preview_scale)
        preview_dir = out_dir.parent / f"{out_dir.name}_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview.save(preview_dir / name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--size", type=int, default=64, help="Pixel art target size")
    p.add_argument("--preserve-size", action="store_true",
                   help="Keep input dimensions instead of resizing to --size.")
    p.add_argument("--downscale-filter", choices=sorted(RESAMPLE_FILTERS),
                   default="lanczos",
                   help="Resampling filter when resizing to --size.")
    p.add_argument("--colors", type=int, default=16,
                   help="Palette size when --quantize is enabled.")
    p.add_argument("--quantize", action="store_true",
                   help="Reduce colors with median-cut quantization. "
                        "Off by default unless a palette option is used.")
    p.add_argument("--outline", action="store_true")
    p.add_argument("--trim-transparent", action="store_true",
                   help="Trim transparent borders after pixelization/outline.")
    p.add_argument("--trim-padding", type=int, default=0,
                   help="Transparent pixels to keep around trimmed content.")
    p.add_argument("--trim-padding-prefix", action="append", default=[],
                   metavar="PREFIX=VALUE",
                   help="Override --trim-padding for filenames starting with "
                        "PREFIX. Repeatable, e.g. wall=0.")
    p.add_argument("--trim-grid-size", type=int, default=0,
                   help="Round trimmed frame dimensions up to this grid size.")
    p.add_argument("--align-anchor-y-to-grid", action="store_true",
                   help="When --trim-transparent is enabled, read "
                        ".anchor.json sidecars next to input PNGs. Back "
                        "alignment uses the 3D bbox floor edge; left, right, "
                        "and front alignment use opaque pixel edges.")
    p.add_argument("--alignment-manifest",
                   help="Manifest with optional per-sprite alignment metadata. "
                        "Valid values: none, back-left, back, back-right, "
                        "left, center, right, front-left, front, front-right.")
    p.add_argument("--preview-scale", type=int, default=8,
                   help="Save a NEAREST-upscaled preview at Nx (0 to disable)")
    p.add_argument("--share-palette-by-angle", action="store_true",
                   help="Use one palette across frames of the same angle "
                        "(prevents flicker on static body pixels across wheel frames; "
                        "enables quantization)")
    p.add_argument("--share-palette", action="store_true",
                   help="Use one palette across ALL input frames "
                        "(stable colors across angles and wheel frames; "
                        "enables quantization)")
    p.add_argument("--palette-from", type=str, default=None,
                   help="Path to a palette image. Every unique opaque color in "
                        "the image becomes a palette slot (max 256). "
                        "Overrides --share-palette and enables quantization.")
    p.add_argument("--palette-distance", choices=("pillow", "rgb", "hsl"),
                   default="pillow",
                   help="Color distance for --palette-from. 'pillow' keeps "
                        "Pillow's palette matching; 'hsl' favors hue and "
                        "lightness for more stable LPC-style color choices.")
    args = p.parse_args()
    trim_padding_prefix = parse_prefix_int_rules(
        args.trim_padding_prefix,
        "--trim-padding-prefix",
    )
    alignment_by_name = load_alignment_manifest(args.alignment_manifest)
    fixed_width_by_name = load_fixed_width_manifest(
        args.alignment_manifest,
        args.trim_grid_size,
    )

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    files = sorted(in_dir.glob("*.png"))
    if not files:
        raise SystemExit(f"No PNGs in {in_dir}")

    quantize_enabled = (
        args.quantize
        or args.palette_from is not None
        or args.share_palette
        or args.share_palette_by_angle
    )

    # External palette: treat the image as a direct palette source —
    # every unique opaque RGB in it becomes a slot in the output palette.
    external_ref: Image.Image | None = None
    external_colors: list[tuple[int, int, int]] | None = None
    if args.palette_from:
        ref_img = Image.open(args.palette_from).convert("RGBA")
        colors: set[tuple[int, int, int]] = {
            (r, g, b) for r, g, b, a in ref_img.getdata() if a > 0
        }
        if not colors:
            raise SystemExit(f"No opaque pixels in {args.palette_from}")
        if len(colors) > 256:
            raise SystemExit(
                f"Palette image has {len(colors)} colors; PIL caps at 256")
        external_colors = sorted(colors)
        flat: list[int] = []
        for r, g, b in external_colors:
            flat += [r, g, b]
        flat += [0] * (768 - len(flat))  # pad to 256 entries
        external_ref = Image.new("P", (1, 1))
        external_ref.putpalette(flat)
        print(f"[palette] {len(colors)} colors from {args.palette_from}")

    # Group and resize up front so shared palettes are built from the same
    # frame data that will be pixelized.
    groups: dict[str, list[tuple[Path, Image.Image]]] = defaultdict(list)
    resample = RESAMPLE_FILTERS[args.downscale_filter]
    for f in files:
        img = Image.open(f).convert("RGBA")
        if args.preserve_size:
            small = img
        else:
            small = downscale(img, args.size, resample)
        if external_ref is not None:
            key = "_ext"
        elif quantize_enabled and args.share_palette:
            key = "_all"
        elif quantize_enabled and args.share_palette_by_angle:
            key = _angle_group_key(f.name)
        else:
            key = f.name
        groups[key].append((f, small))

    for key, entries in groups.items():
        small_frames = [s for _, s in entries]
        palette_ref = external_ref
        if quantize_enabled:
            if palette_ref is None and \
                    (args.share_palette or args.share_palette_by_angle) and \
                    len(small_frames) > 1:
                palette_ref = build_shared_palette(small_frames, args.colors)

        for path, small in entries:
            if quantize_enabled:
                pixel = quantize_rgba(
                    small,
                    args.colors,
                    palette_ref=palette_ref,
                    palette_colors=external_colors,
                    palette_distance=args.palette_distance,
                )
            else:
                pixel = binarize_alpha(small)
            if args.outline:
                pixel = add_outline(pixel)
            alignment_anchors = None
            alignment = alignment_by_name.get(path.stem)
            if args.align_anchor_y_to_grid:
                if not args.trim_transparent or args.trim_grid_size <= 0:
                    raise SystemExit(
                        "--align-anchor-y-to-grid requires "
                        "--trim-transparent and --trim-grid-size > 0"
                    )
                alignment_anchors = load_alignment_anchors(
                    path,
                    pixel.width,
                    pixel.height,
                )
            if args.trim_transparent:
                pixel = trim_transparent(
                    pixel,
                    padding=prefix_rule_value(
                        path.stem,
                        trim_padding_prefix,
                        args.trim_padding,
                    ),
                    grid_size=args.trim_grid_size,
                    alignment_anchors=alignment_anchors,
                    alignment=alignment,
                    fixed_width=fixed_width_by_name.get(path.stem),
                )
            save_pixel(pixel, out_dir, path.name, args.preview_scale)
            print(f"[pixel] {path.name} -> {out_dir}/{path.name}")


if __name__ == "__main__":
    main()
