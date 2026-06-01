"""Update a generated grid manifest from a manually edited sprite sheet."""
import argparse
import copy
import json
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image


def validate_grid(path: Path, image: Image.Image, tile_size: int):
    if image.width % tile_size or image.height % tile_size:
        raise SystemExit(
            f"{path} is {image.size}; expected multiples of {tile_size}px"
        )


def rects_overlap(a: tuple[int, int, int, int],
                  b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def sprite_rect(sprite: dict) -> tuple[int, int, int, int]:
    return (
        int(sprite["x"]),
        int(sprite["y"]),
        int(sprite["x"]) + int(sprite["w"]),
        int(sprite["y"]) + int(sprite["h"]),
    )


def starts_with_any(name: str, prefixes: list[str]) -> bool:
    return any(name.startswith(prefix) for prefix in prefixes)


def set_sprite_position(sprite: dict, x: int, y: int, tile_size: int):
    sprite["x"] = x
    sprite["y"] = y
    sprite["grid_x"] = x // tile_size
    sprite["grid_y"] = y // tile_size


def crop_sprite(sheet: Image.Image, sprite: dict) -> Image.Image:
    return sheet.crop(sprite_rect(sprite))


def crop_index(
    sheet: Image.Image,
    sizes: set[tuple[int, int]],
    tile_size: int,
) -> dict[tuple[int, int], dict[bytes, list[tuple[int, int]]]]:
    indexes = {
        size: defaultdict(list)
        for size in sizes
    }
    for width, height in sizes:
        if width > sheet.width or height > sheet.height:
            continue
        for y in range(0, sheet.height - height + 1, tile_size):
            for x in range(0, sheet.width - width + 1, tile_size):
                key = sheet.crop((x, y, x + width, y + height)).tobytes()
                indexes[(width, height)][key].append((x, y))
    return indexes


def is_rect_free(
    rect: tuple[int, int, int, int],
    assigned_rects: list[tuple[int, int, int, int]],
) -> bool:
    return not any(rects_overlap(rect, assigned) for assigned in assigned_rects)


def choose_candidate(
    candidates: list[tuple[int, int]],
    sprite: dict,
    assigned_rects: list[tuple[int, int, int, int]],
) -> tuple[int, int] | None:
    original = (int(sprite["x"]), int(sprite["y"]))
    width = int(sprite["w"])
    height = int(sprite["h"])
    for x, y in candidates:
        if (x, y) != original:
            continue
        rect = (x, y, x + width, y + height)
        if is_rect_free(rect, assigned_rects):
            return x, y

    for x, y in sorted(candidates, key=lambda pos: (pos[1], pos[0])):
        rect = (x, y, x + width, y + height)
        if is_rect_free(rect, assigned_rects):
            return x, y
    return None


def cell_has_alpha(sheet: Image.Image, grid_x: int, grid_y: int,
                   tile_size: int) -> bool:
    x = grid_x * tile_size
    y = grid_y * tile_size
    tile = sheet.crop((x, y, x + tile_size, y + tile_size))
    return tile.getchannel("A").getbbox() is not None


def covered_cells(sprites: list[dict]) -> set[tuple[int, int]]:
    cells = set()
    for sprite in sprites:
        grid_x = int(sprite["grid_x"])
        grid_y = int(sprite["grid_y"])
        grid_w = int(sprite["grid_w"])
        grid_h = int(sprite["grid_h"])
        for y in range(grid_y, grid_y + grid_h):
            for x in range(grid_x, grid_x + grid_w):
                cells.add((x, y))
    return cells


def connected_components(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    pending = set(cells)
    components = []
    while pending:
        start = pending.pop()
        component = {start}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor not in pending:
                    continue
                pending.remove(neighbor)
                component.add(neighbor)
                queue.append(neighbor)
        components.append(component)
    return sorted(components, key=lambda comp: (
        min(y for _, y in comp),
        min(x for x, _ in comp),
    ))


def rectangular_components(
    component: set[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    min_x = min(x for x, _ in component)
    max_x = max(x for x, _ in component)
    min_y = min(y for _, y in component)
    max_y = max(y for _, y in component)
    full_rect = {
        (x, y)
        for y in range(min_y, max_y + 1)
        for x in range(min_x, max_x + 1)
    }
    if full_rect == component:
        return [(min_x, min_y, max_x + 1, max_y + 1)]
    return [
        (x, y, x + 1, y + 1)
        for x, y in sorted(component, key=lambda cell: (cell[1], cell[0]))
    ]


def find_placeholder_rects(
    sheet: Image.Image,
    sprites: list[dict],
    tile_size: int,
) -> list[tuple[int, int, int, int]]:
    columns = sheet.width // tile_size
    rows = sheet.height // tile_size
    occupied = {
        (x, y)
        for y in range(rows)
        for x in range(columns)
        if cell_has_alpha(sheet, x, y, tile_size)
    }
    uncovered = occupied - covered_cells(sprites)
    rects = []
    for component in connected_components(uncovered):
        rects.extend(rectangular_components(component))
    return rects


def placeholder_sprite(
    manifest_index: int,
    name_number: int,
    rect: tuple[int, int, int, int],
    tile_size: int,
    prefix: str,
) -> dict:
    grid_x0, grid_y0, grid_x1, grid_y1 = rect
    name = f"{prefix}_{name_number:03d}"
    grid_w = grid_x1 - grid_x0
    grid_h = grid_y1 - grid_y0
    return {
        "name": name,
        "file": f"{name}.png",
        "index": manifest_index,
        "x": grid_x0 * tile_size,
        "y": grid_y0 * tile_size,
        "w": grid_w * tile_size,
        "h": grid_h * tile_size,
        "grid_x": grid_x0,
        "grid_y": grid_y0,
        "grid_w": grid_w,
        "grid_h": grid_h,
        "placeholder": True,
    }


def update_positions(
    generated_sheet: Image.Image,
    edited_sheet: Image.Image,
    sprites: list[dict],
    tile_size: int,
) -> tuple[int, int]:
    sizes = {
        (int(sprite["w"]), int(sprite["h"]))
        for sprite in sprites
    }
    indexes = crop_index(edited_sheet, sizes, tile_size)
    assigned_rects = []
    moved = 0
    unmatched = 0

    for sprite in sorted(
        sprites,
        key=lambda item: (-int(item["w"]) * int(item["h"]), int(item["index"])),
    ):
        original = (int(sprite["x"]), int(sprite["y"]))
        generated_crop = crop_sprite(generated_sheet, sprite)
        candidates = indexes[(int(sprite["w"]), int(sprite["h"]))].get(
            generated_crop.tobytes(),
            [],
        )
        candidate = choose_candidate(candidates, sprite, assigned_rects)
        if candidate is None:
            unmatched += 1
            candidate = original
        elif candidate != original:
            moved += 1
        set_sprite_position(sprite, candidate[0], candidate[1], tile_size)
        assigned_rects.append(sprite_rect(sprite))
    return moved, unmatched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-manifest", required=True)
    parser.add_argument("--generated-sheet", required=True)
    parser.add_argument("--edited-sheet", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--placeholder-prefix", default="manual_placeholder")
    parser.add_argument("--include-reserved-prefix", action="append", default=[],
                        metavar="PREFIX",
                        help="Keep reserved generated-manifest entries whose "
                             "name starts with PREFIX as named manual sprites.")
    args = parser.parse_args()

    if args.tile_size <= 0:
        raise SystemExit("--tile-size must be positive")

    manifest_path = Path(args.generated_manifest)
    generated_sheet_path = Path(args.generated_sheet)
    edited_sheet_path = Path(args.edited_sheet)
    out_path = Path(args.out)

    manifest = json.loads(manifest_path.read_text())
    if "sprites" not in manifest:
        raise SystemExit(f"{manifest_path} does not contain a sprites list")

    generated_sheet = Image.open(generated_sheet_path).convert("RGBA")
    edited_sheet = Image.open(edited_sheet_path).convert("RGBA")
    validate_grid(generated_sheet_path, generated_sheet, args.tile_size)
    validate_grid(edited_sheet_path, edited_sheet, args.tile_size)

    manifest_sprites = copy.deepcopy(manifest["sprites"])
    sprites = [
        sprite for sprite in manifest_sprites
        if not sprite.get("reserved")
    ]
    reserved_sprites = []
    for sprite in manifest_sprites:
        if not sprite.get("reserved"):
            continue
        if not starts_with_any(sprite.get("name", ""), args.include_reserved_prefix):
            continue
        sprite.pop("reserved", None)
        sprite["manual"] = True
        reserved_sprites.append(sprite)

    moved, unmatched = update_positions(
        generated_sheet,
        edited_sheet,
        sprites,
        args.tile_size,
    )

    named_sprites = sprites + reserved_sprites
    placeholder_rects = find_placeholder_rects(
        edited_sheet,
        named_sprites,
        args.tile_size,
    )
    next_index = max(
        (int(sprite["index"]) for sprite in named_sprites),
        default=-1,
    ) + 1
    placeholders = []
    for offset, rect in enumerate(placeholder_rects, start=1):
        placeholders.append(
            placeholder_sprite(
                next_index + offset - 1,
                offset,
                rect,
                args.tile_size,
                args.placeholder_prefix,
            )
        )

    updated = copy.deepcopy(manifest)
    updated["image"] = edited_sheet_path.name
    updated["tile_size"] = args.tile_size
    updated["columns"] = edited_sheet.width // args.tile_size
    updated["rows"] = edited_sheet.height // args.tile_size
    updated["sprites"] = sorted(
        named_sprites + placeholders,
        key=lambda sprite: int(sprite["index"]),
    )
    updated["count"] = len(updated["sprites"])
    updated["manual_edits"] = {
        "moved_sprites": moved,
        "unmatched_generated_sprites": unmatched,
        "placeholder_sprites": len(placeholders),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(updated, indent=2) + "\n")
    print(
        f"[manifest] moved {moved}, placeholders {len(placeholders)}, "
        f"unmatched {unmatched} -> {out_path}"
    )


if __name__ == "__main__":
    main()
