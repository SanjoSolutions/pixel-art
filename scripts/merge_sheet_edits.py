"""Merge manual tile edits from an existing atlas into a regenerated atlas."""
import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageChops


def tile_changed(a: Image.Image, b: Image.Image) -> bool:
    diff = ImageChops.difference(a, b)
    return any(channel.getbbox() is not None for channel in diff.split())


def copy_file(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def validate_grid(path: Path, image: Image.Image, tile_size: int):
    if image.width % tile_size or image.height % tile_size:
        raise SystemExit(
            f"{path} is {image.size}; expected multiples of {tile_size}px"
        )


def crop_tile_or_transparent(
    image: Image.Image,
    box: tuple[int, int, int, int],
    tile_size: int,
) -> Image.Image:
    if box[0] >= image.width or box[1] >= image.height:
        return Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
    return image.crop(box)


def save_preview(sheet: Image.Image, preview_path: Path, scale: int):
    if scale <= 1:
        return
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview = sheet.resize(
        (sheet.width * scale, sheet.height * scale),
        Image.Resampling.NEAREST,
    )
    preview.save(preview_path)


def sprite_cells(sprite: dict, tile_size: int) -> set[tuple[int, int]]:
    grid_x = int(sprite["x"]) // tile_size
    grid_y = int(sprite["y"]) // tile_size
    grid_w = int(sprite["w"]) // tile_size
    grid_h = int(sprite["h"]) // tile_size
    return {
        (x, y)
        for y in range(grid_y, grid_y + grid_h)
        for x in range(grid_x, grid_x + grid_w)
    }


def adjacent_cells(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    adjacent = set()
    for x, y in cells:
        adjacent.update({
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
        })
    return adjacent


def sprite_rect(sprite: dict) -> tuple[int, int, int, int]:
    return (
        int(sprite["x"]),
        int(sprite["y"]),
        int(sprite["w"]),
        int(sprite["h"]),
    )


def load_manifest(path_text: str | None) -> dict | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def moved_generated_cells(
    edited_manifest: dict | None,
    generated_manifest: dict | None,
    tile_size: int,
    migrated_prefixes: list[str],
) -> set[tuple[int, int]]:
    if not edited_manifest or not generated_manifest:
        return set()

    generated_by_name = {
        sprite["name"]: sprite
        for sprite in generated_manifest.get("sprites", [])
        if not sprite.get("placeholder")
    }
    cells = set()
    for sprite in edited_manifest.get("sprites", []):
        if sprite.get("placeholder"):
            continue
        generated_sprite = generated_by_name.get(sprite.get("name"))
        if generated_sprite is None:
            continue
        if sprite_rect(sprite) == sprite_rect(generated_sprite):
            continue
        name = sprite.get("name", "")
        if generated_sprite.get("reserved") and not name.startswith(
            tuple(migrated_prefixes)
        ):
            continue
        cells.update(sprite_cells(sprite, tile_size))
    return cells


def ignored_placeholder_cells(
    edited_manifest: dict | None,
    tile_size: int,
    preserve_adjacent_prefixes: list[str],
) -> set[tuple[int, int]]:
    if not edited_manifest or not preserve_adjacent_prefixes:
        return set()

    placeholder_cells = set()
    preserved_named_cells = set()
    for sprite in edited_manifest.get("sprites", []):
        cells = sprite_cells(sprite, tile_size)
        if sprite.get("placeholder"):
            placeholder_cells.update(cells)
            continue
        name = sprite.get("name", "")
        if name.startswith(tuple(preserve_adjacent_prefixes)):
            preserved_named_cells.update(cells)

    preserved_placeholder_cells = placeholder_cells & adjacent_cells(
        preserved_named_cells
    )
    pending = list(preserved_placeholder_cells)
    while pending:
        cell = pending.pop()
        for neighbor in adjacent_cells({cell}):
            if neighbor not in placeholder_cells:
                continue
            if neighbor in preserved_placeholder_cells:
                continue
            preserved_placeholder_cells.add(neighbor)
            pending.append(neighbor)
    return placeholder_cells - preserved_placeholder_cells


def manifest_cell_owners(
    manifest: dict | None,
    tile_size: int,
) -> dict[tuple[int, int], list[dict]]:
    if not manifest:
        return {}

    owners = {}
    for sprite in manifest.get("sprites", []):
        for cell in sprite_cells(sprite, tile_size):
            owners.setdefault(cell, []).append(sprite)
    return owners


def cell_would_overwrite_different_generated_sprite(
    cell: tuple[int, int],
    edited_cell_owners: dict[tuple[int, int], list[dict]],
    generated_cell_owners: dict[tuple[int, int], list[dict]],
) -> bool:
    generated_sprites = [
        sprite
        for sprite in generated_cell_owners.get(cell, [])
        if not sprite.get("placeholder") and not sprite.get("reserved")
    ]
    if not generated_sprites:
        return False

    edited_sprite_names = {
        sprite.get("name")
        for sprite in edited_cell_owners.get(cell, [])
        if not sprite.get("placeholder")
    }
    generated_sprite_names = {
        sprite.get("name")
        for sprite in generated_sprites
    }
    return not bool(edited_sprite_names & generated_sprite_names)


def migrate_moved_sprites(
    merged: Image.Image,
    edited: Image.Image,
    edited_manifest: dict | None,
    generated_manifest: dict | None,
    prefixes: list[str],
) -> int:
    if not edited_manifest or not generated_manifest or not prefixes:
        return 0

    generated_by_name = {
        sprite["name"]: sprite
        for sprite in generated_manifest.get("sprites", [])
        if not sprite.get("placeholder")
    }
    migrated = 0
    for sprite in edited_manifest.get("sprites", []):
        name = sprite.get("name", "")
        if sprite.get("placeholder") or not name.startswith(tuple(prefixes)):
            continue
        generated_sprite = generated_by_name.get(name)
        if generated_sprite is None:
            continue
        old_x, old_y, old_w, old_h = sprite_rect(sprite)
        new_x, new_y, new_w, new_h = sprite_rect(generated_sprite)
        if (old_x, old_y, old_w, old_h) == (new_x, new_y, new_w, new_h):
            continue
        crop_w = min(old_w, new_w, max(0, edited.width - old_x))
        crop_h = min(old_h, new_h, max(0, edited.height - old_y))
        if crop_w <= 0 or crop_h <= 0:
            continue
        edited_crop = edited.crop((old_x, old_y, old_x + crop_w, old_y + crop_h))
        merged.paste(edited_crop, (new_x, new_y))
        migrated += 1
    return migrated


def copy_reserved_sprites(
    merged: Image.Image,
    edited: Image.Image,
    edited_manifest: dict | None,
    generated_manifest: dict | None,
    prefixes: list[str],
) -> int:
    if not edited_manifest or not generated_manifest or not prefixes:
        return 0

    generated_by_name = {
        sprite["name"]: sprite
        for sprite in generated_manifest.get("sprites", [])
        if sprite.get("reserved")
    }
    copied = 0
    for sprite in edited_manifest.get("sprites", []):
        name = sprite.get("name", "")
        if sprite.get("placeholder") or not name.startswith(tuple(prefixes)):
            continue
        generated_sprite = generated_by_name.get(name)
        if generated_sprite is None:
            continue
        old_x, old_y, old_w, old_h = sprite_rect(sprite)
        new_x, new_y, new_w, new_h = sprite_rect(generated_sprite)
        crop_w = min(old_w, new_w, max(0, edited.width - old_x))
        crop_h = min(old_h, new_h, max(0, edited.height - old_y))
        if crop_w <= 0 or crop_h <= 0:
            continue
        edited_crop = edited.crop((old_x, old_y, old_x + crop_w, old_y + crop_h))
        merged.paste(edited_crop, (new_x, new_y))
        copied += 1
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edited-sheet", required=True,
                        help="Sheet that may contain manual edits.")
    parser.add_argument("--baseline-sheet", required=True,
                        help="Generated sheet from the previous build.")
    parser.add_argument("--generated-sheet", required=True,
                        help="Newly generated sheet from this build.")
    parser.add_argument("--edited-manifest",
                        help="Manifest matching --edited-sheet; when set, "
                             "old named sprites that moved in the new "
                             "generated manifest are not preserved as manual "
                             "tiles.")
    parser.add_argument("--generated-manifest",
                        help="Manifest matching --generated-sheet.")
    parser.add_argument("--migrate-moved-sprite-prefix", action="append", default=[],
                        metavar="PREFIX",
                        help="Copy edited pixels for moved named sprites whose "
                             "name starts with PREFIX into the new generated "
                             "position before preserving tile edits. Repeatable.")
    parser.add_argument("--preserve-placeholder-adjacent-prefix",
                        action="append", default=[], metavar="PREFIX",
                        help="Preserve edited placeholder tiles only when they "
                             "are adjacent to an edited named sprite whose name "
                             "starts with PREFIX. Repeatable. When omitted, all "
                             "placeholder edits are preserved.")
    parser.add_argument("--preserve-reserved-prefix",
                        action="append", default=[], metavar="PREFIX",
                        help="Always copy edited pixels for reserved manifest "
                             "sprites whose name starts with PREFIX. Repeatable.")
    parser.add_argument("--out", required=True,
                        help="Final merged sheet path.")
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--preview-out")
    parser.add_argument("--preview-scale", type=int, default=0)
    args = parser.parse_args()

    edited_path = Path(args.edited_sheet)
    baseline_path = Path(args.baseline_sheet)
    generated_path = Path(args.generated_sheet)
    out_path = Path(args.out)

    if args.tile_size <= 0:
        raise SystemExit("--tile-size must be positive")
    if not generated_path.exists():
        raise SystemExit(f"Missing generated sheet: {generated_path}")

    generated = Image.open(generated_path).convert("RGBA")
    validate_grid(generated_path, generated, args.tile_size)

    if not edited_path.exists():
        copy_file(generated_path, out_path)
        if args.preview_out:
            save_preview(generated, Path(args.preview_out), args.preview_scale)
        print("[sheet-edits] no edited sheet found; using generated sheet")
        return

    edited = Image.open(edited_path).convert("RGBA")
    validate_grid(edited_path, edited, args.tile_size)

    if baseline_path.exists():
        baseline = Image.open(baseline_path).convert("RGBA")
        validate_grid(baseline_path, baseline, args.tile_size)
    else:
        baseline = generated
        print(
            "[sheet-edits] no previous generated baseline; comparing edited "
            "sheet against current generated sheet"
        )

    out_width = max(generated.width, edited.width)
    out_height = max(generated.height, edited.height)
    merged = Image.new("RGBA", (out_width, out_height), (0, 0, 0, 0))
    merged.paste(generated, (0, 0))

    edited_manifest = load_manifest(args.edited_manifest)
    generated_manifest = load_manifest(args.generated_manifest)
    migrated_sprites = migrate_moved_sprites(
        merged,
        edited,
        edited_manifest,
        generated_manifest,
        args.migrate_moved_sprite_prefix,
    )
    copied_reserved_sprites = copy_reserved_sprites(
        merged,
        edited,
        edited_manifest,
        generated_manifest,
        args.preserve_reserved_prefix,
    )

    changed_tiles = 0
    tile = args.tile_size
    ignored_moved_cells = moved_generated_cells(
        edited_manifest,
        generated_manifest,
        tile,
        args.migrate_moved_sprite_prefix,
    )
    ignored_placeholder_edit_cells = ignored_placeholder_cells(
        edited_manifest,
        tile,
        args.preserve_placeholder_adjacent_prefix,
    )
    edited_cell_owners = manifest_cell_owners(edited_manifest, tile)
    generated_cell_owners = manifest_cell_owners(generated_manifest, tile)
    for y in range(0, edited.height, tile):
        for x in range(0, edited.width, tile):
            cell = (x // tile, y // tile)
            if (
                cell in ignored_moved_cells
                or cell in ignored_placeholder_edit_cells
                or cell_would_overwrite_different_generated_sprite(
                    cell,
                    edited_cell_owners,
                    generated_cell_owners,
                )
            ):
                continue
            box = (x, y, x + tile, y + tile)
            edited_tile = edited.crop(box)
            baseline_tile = crop_tile_or_transparent(baseline, box, tile)
            if not tile_changed(edited_tile, baseline_tile):
                continue
            merged.paste(edited_tile, (x, y))
            changed_tiles += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(out_path)
    if args.preview_out:
        save_preview(merged, Path(args.preview_out), args.preview_scale)
    print(
        f"[sheet-edits] preserved {changed_tiles} manually edited tile(s), "
        f"migrated {migrated_sprites} moved sprite(s), "
        f"copied {copied_reserved_sprites} reserved sprite(s)"
    )


if __name__ == "__main__":
    main()
