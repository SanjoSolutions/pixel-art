"""Compose PNGs into a grid or tile-aligned packed sprite sheet."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image

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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cols", type=int, default=0,
                   help="Grid columns. Defaults to ceil(sqrt(frame count)).")
    p.add_argument("--pack", action="store_true",
                   help="Shelf-pack variable-sized images instead of using "
                        "same-sized grid cells.")
    p.add_argument("--tile-size", type=int, default=32,
                   help="Alignment size for --pack and manifest grid units.")
    p.add_argument("--max-width", type=int, default=1024,
                   help="Maximum sheet width for --pack.")
    p.add_argument("--pack-y-offset-prefix", action="append", default=[],
                   metavar="PREFIX=TILES",
                   help="Move packed sprites whose filename starts with "
                        "PREFIX vertically by TILES grid cells. Repeatable.")
    p.add_argument("--exclude-prefix", action="append", default=[],
                   metavar="PREFIX",
                   help="Skip PNGs whose filename starts with PREFIX. "
                        "Repeatable.")
    p.add_argument("--reserve-prefix", action="append", default=[],
                   metavar="PREFIX",
                   help="Reserve atlas space for PNGs whose filename starts "
                        "with PREFIX, but leave those pixels transparent. "
                        "Repeatable.")
    p.add_argument("--reserve-manifest",
                   help="Manifest with fixed manual sprite slots to reserve.")
    p.add_argument("--reserve-manifest-prefix", action="append", default=[],
                   metavar="PREFIX",
                   help="Reserve fixed slots from --reserve-manifest whose "
                        "sprite name starts with PREFIX. Repeatable.")
    p.add_argument("--manifest",
                   help="Optional JSON manifest with each sprite's cell.")
    p.add_argument("--metadata-manifest",
                   help="Manifest with optional per-sprite metadata to copy "
                        "into the generated manifest.")
    args = p.parse_args()
    metadata_by_name = load_manifest_metadata(args.metadata_manifest)

    in_dir = Path(args.in_dir)
    files = [
        path for path in sorted(in_dir.glob("*.png"))
        if not any(
            path.stem.startswith(prefix)
            for prefix in args.exclude_prefix
        )
    ]
    if not files:
        raise SystemExit(f"No PNGs in {in_dir}")

    frames = []
    for path in files:
        img = Image.open(path).convert("RGBA")
        reserved = any(
            path.stem.startswith(prefix)
            for prefix in args.reserve_prefix
        )
        frames.append((path, img, reserved))

    if args.pack:
        args.pack_y_offset_prefix = parse_prefix_int_rules(
            args.pack_y_offset_prefix,
            "--pack-y-offset-prefix",
        )
        pack(frames, args)
        return

    frame_w, frame_h = frames[0][1].size
    mismatched = [
        path.name for path, img, _ in frames
        if img.size != (frame_w, frame_h)
    ]
    if mismatched:
        raise SystemExit(
            f"All frames must be {frame_w}×{frame_h}; mismatched: "
            f"{', '.join(mismatched[:5])}"
        )

    cols = args.cols or math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGBA", (cols * frame_w, rows * frame_h), (0, 0, 0, 0))
    sprites = []

    for i, (path, img, reserved) in enumerate(frames):
        row, col = divmod(i, cols)
        x = col * frame_w
        y = row * frame_h
        if not reserved:
            sheet.paste(img, (x, y), img)
        sprite = {
            "name": path.stem,
            "file": path.name,
            "index": i,
            "row": row,
            "col": col,
            "x": x,
            "y": y,
            "w": frame_w,
            "h": frame_h,
            "grid_x": x // args.tile_size,
            "grid_y": y // args.tile_size,
            "grid_w": math.ceil(frame_w / args.tile_size),
            "grid_h": math.ceil(frame_h / args.tile_size),
        }
        if reserved:
            sprite["reserved"] = True
        add_sprite_metadata(sprite, metadata_by_name)
        sprites.append(sprite)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"[sheet] grid {cols}×{rows} ({sheet.width}×{sheet.height}) -> {out_path}")

    if args.manifest:
        manifest = {
            "image": out_path.name,
            "frame_width": frame_w,
            "frame_height": frame_h,
            "columns": cols,
            "rows": rows,
            "tile_size": args.tile_size,
            "count": len(sprites),
            "sprites": sprites,
        }
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"[manifest] {manifest_path}")


def round_up(value: int, multiple: int) -> int:
    return math.ceil(value / multiple) * multiple


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


def starts_with_any(name: str, prefixes: list[str]) -> bool:
    return any(name.startswith(prefix) for prefix in prefixes)


def sprite_optional_metadata(sprite: dict, path: Path) -> dict:
    name = sprite.get("name")
    metadata = {}
    alignment = sprite.get("alignment")
    if alignment is not None:
        if alignment not in ALIGNMENTS:
            raise SystemExit(
                f"{path} sprite {name} has invalid alignment {alignment!r}"
            )
        metadata["alignment"] = alignment
    if "width" in sprite:
        try:
            width = float(sprite["width"])
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"{path} sprite {name} has invalid width {sprite['width']!r}"
            ) from exc
        if width <= 0:
            raise SystemExit(
                f"{path} sprite {name} width must be positive, got {sprite['width']!r}"
            )
        metadata["width"] = width
    if "keepProportions" in sprite:
        if not isinstance(sprite["keepProportions"], bool):
            raise SystemExit(
                f"{path} sprite {name} has invalid keepProportions "
                f"{sprite['keepProportions']!r}"
            )
        metadata["keepProportions"] = sprite["keepProportions"]
    return metadata


def load_manifest_metadata(manifest_path: str | None) -> dict[str, dict]:
    if not manifest_path:
        return {}
    path = Path(manifest_path)
    if not path.exists():
        return {}

    manifest = json.loads(path.read_text())
    metadata = {}
    for sprite in manifest.get("sprites", []):
        name = sprite.get("name")
        sprite_metadata = sprite_optional_metadata(sprite, path)
        if not sprite_metadata:
            continue
        metadata[str(name)] = sprite_metadata
    return metadata


def add_sprite_metadata(sprite: dict, metadata_by_name: dict[str, dict]):
    metadata = metadata_by_name.get(sprite["name"])
    if metadata:
        sprite.update(metadata)


def load_manifest_reservations(
    manifest_path: str | None,
    prefixes: list[str],
    tile_size: int,
) -> list[dict]:
    if not manifest_path or not prefixes:
        return []
    path = Path(manifest_path)
    if not path.exists():
        return []

    manifest = json.loads(path.read_text())
    reservations = []
    for sprite in manifest.get("sprites", []):
        name = sprite.get("name", "")
        if sprite.get("placeholder") or not starts_with_any(name, prefixes):
            continue
        x = int(sprite["x"])
        y = int(sprite["y"])
        width = int(sprite["w"])
        height = int(sprite["h"])
        if x % tile_size or y % tile_size or width % tile_size or height % tile_size:
            raise SystemExit(
                f"{path} sprite {name} is not aligned to {tile_size}px tiles"
            )
        reservation = {
            "name": name,
            "file": sprite.get("file", f"{name}.png"),
            "x": x,
            "y": y,
            "w": width,
            "h": height,
            "grid_x": x // tile_size,
            "grid_y": y // tile_size,
            "grid_w": width // tile_size,
            "grid_h": height // tile_size,
            "reserved": True,
        }
        reservation.update(sprite_optional_metadata(sprite, path))
        reservations.append(reservation)
    return reservations


def overlaps(a: tuple[int, int, int, int],
             b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def placement_overlap(
    rect: tuple[int, int, int, int],
    placements,
) -> Path | None:
    for placed_path, placed_img, placed_x, placed_y_existing, _ in placements:
        placed_rect = (
            placed_x,
            placed_y_existing,
            placed_x + placed_img.width,
            placed_y_existing + placed_img.height,
        )
        if overlaps(rect, placed_rect):
            return placed_path
    return None


def pack(frames, args):
    tile = args.tile_size
    max_width = round_up(args.max_width, tile)
    x = y = row_h = 0
    sheet_w = 0
    sheet_h = 0
    sprites = []
    placements = []
    metadata_by_name = load_manifest_metadata(args.metadata_manifest)
    reservations = load_manifest_reservations(
        args.reserve_manifest,
        args.reserve_manifest_prefix,
        tile,
    )
    for reservation in reservations:
        img = Image.new("RGBA", (reservation["w"], reservation["h"]), (0, 0, 0, 0))
        path = Path(reservation["file"])
        placements.append((path, img, reservation["x"], reservation["y"], True))
        reservation["index"] = len(sprites)
        sprites.append(reservation)
        sheet_w = max(sheet_w, reservation["x"] + reservation["w"])
        sheet_h = max(sheet_h, reservation["y"] + reservation["h"])

    for i, (path, img, reserved) in enumerate(frames):
        if img.width % tile or img.height % tile:
            raise SystemExit(
                f"{path.name} is {img.width}×{img.height}; expected "
                f"multiples of {tile}px"
            )
        if img.width > max_width:
            raise SystemExit(
                f"{path.name} is wider than --max-width ({img.width} > {max_width})"
            )
        while True:
            if x and x + img.width > max_width:
                y += row_h or tile
                x = 0
                row_h = 0

            offset_y = prefix_rule_value(path.stem, args.pack_y_offset_prefix, 0) * tile
            placed_y = y + offset_y
            if placed_y < 0:
                raise SystemExit(
                    f"{path.name} offset places it above the sheet: y={placed_y}"
                )
            rect = (x, placed_y, x + img.width, placed_y + img.height)
            if placement_overlap(rect, placements) is None:
                break
            x += tile
        placements.append((path, img, x, placed_y, reserved))
        sprite = {
            "name": path.stem,
            "file": path.name,
            "index": len(sprites),
            "x": x,
            "y": placed_y,
            "w": img.width,
            "h": img.height,
            "grid_x": x // tile,
            "grid_y": placed_y // tile,
            "grid_w": img.width // tile,
            "grid_h": img.height // tile,
        }
        if reserved:
            sprite["reserved"] = True
        add_sprite_metadata(sprite, metadata_by_name)
        sprites.append(sprite)
        sheet_w = max(sheet_w, x + img.width)
        sheet_h = max(sheet_h, placed_y + img.height)
        row_h = max(row_h, img.height)
        x += img.width

    sheet_w = round_up(sheet_w, tile)
    sheet_h = round_up(max(y + row_h, sheet_h), tile)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    for _, img, px, py, reserved in placements:
        if not reserved:
            sheet.paste(img, (px, py), img)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"[sheet] packed {len(frames)} sprites ({sheet.width}×{sheet.height}) -> {out_path}")

    if args.manifest:
        manifest = {
            "image": out_path.name,
            "tile_size": tile,
            "columns": sheet.width // tile,
            "rows": sheet.height // tile,
            "count": len(sprites),
            "sprites": sprites,
        }
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"[manifest] {manifest_path}")


if __name__ == "__main__":
    main()
