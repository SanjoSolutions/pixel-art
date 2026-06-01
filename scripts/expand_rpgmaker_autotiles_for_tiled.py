#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


TILE_SIZE = 32
SUBTILE_SIZE = TILE_SIZE // 2


def terrain_quarter(first: bool, second: bool, diagonal: bool, outer: tuple[int, int], first_edge: tuple[int, int], second_edge: tuple[int, int], full: tuple[int, int], inner: tuple[int, int]) -> tuple[int, int]:
    if first and second:
        return full if diagonal else inner
    if first:
        return first_edge
    if second:
        return second_edge
    return outer


def terrain_combinations() -> list[tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]]:
    return [combination for _, combination in terrain_variants()]


def terrain_variants() -> list[tuple[int, tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]]]:
    combinations = []
    seen = set()
    for mask in range(256):
        n = bool(mask & 1)
        e = bool(mask & 2)
        s = bool(mask & 4)
        w = bool(mask & 8)
        nw = bool(mask & 16) and n and w
        ne = bool(mask & 32) and n and e
        se = bool(mask & 64) and s and e
        sw = bool(mask & 128) and s and w
        top_left = terrain_quarter(n, w, nw, (0, 2), (0, 4), (2, 2), (2, 4), (2, 0))
        top_right = terrain_quarter(n, e, ne, (3, 2), (3, 4), (1, 2), (1, 4), (3, 0))
        bottom_left = terrain_quarter(s, w, sw, (0, 5), (0, 3), (2, 5), (2, 3), (2, 1))
        bottom_right = terrain_quarter(s, e, se, (3, 5), (3, 3), (1, 5), (1, 3), (3, 1))
        combination = (top_left, top_right, bottom_left, bottom_right)
        if combination not in seen:
            seen.add(combination)
            combinations.append((mask, combination))
    return combinations


def wall_combinations() -> list[tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]]:
    return [combination for _, combination in wall_variants()]


def wang_id_from_terrain_mask(mask: int) -> list[int]:
    n = 1 if mask & 1 else 0
    e = 1 if mask & 2 else 0
    s = 1 if mask & 4 else 0
    w = 1 if mask & 8 else 0
    nw = 1 if mask & 16 and n and w else 0
    ne = 1 if mask & 32 and n and e else 0
    se = 1 if mask & 64 and s and e else 0
    sw = 1 if mask & 128 and s and w else 0
    return [n, ne, e, se, s, sw, w, nw]


def wang_id_from_wall_edges(top: bool, right: bool, bottom: bool, left: bool) -> list[int]:
    return [1 if top else 0, 0, 1 if right else 0, 0, 1 if bottom else 0, 0, 1 if left else 0, 0]


def wall_variants() -> list[tuple[list[int], tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]]]:
    combinations = []
    edge_states = (
        (False, False),
        (True, False),
        (True, True),
        (False, True),
    )
    for row in range(4):
        for column in range(4):
            top_left = (0 if column in {0, 3} else 2, 0 if row in {0, 3} else 2)
            top_right = (1 if column in {0, 1} else 3, top_left[1])
            bottom_left = (top_left[0], 1 if row in {0, 1} else 3)
            bottom_right = (top_right[0], bottom_left[1])
            top, bottom = edge_states[row]
            left, right = edge_states[column]
            combinations.append((wang_id_from_wall_edges(top, right, bottom, left), (top_left, top_right, bottom_left, bottom_right)))
    return combinations


def copy_combination(source: Image.Image, target: Image.Image, source_offset: tuple[int, int], target_offset: tuple[int, int], combination: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]) -> None:
    target_quarters = ((0, 0), (1, 0), (0, 1), (1, 1))
    for source_subtile, target_quarter in zip(combination, target_quarters):
        source_x = source_offset[0] + source_subtile[0] * SUBTILE_SIZE
        source_y = source_offset[1] + source_subtile[1] * SUBTILE_SIZE
        target_x = target_offset[0] + target_quarter[0] * SUBTILE_SIZE
        target_y = target_offset[1] + target_quarter[1] * SUBTILE_SIZE
        subtile = source.crop((source_x, source_y, source_x + SUBTILE_SIZE, source_y + SUBTILE_SIZE))
        target.paste(subtile, (target_x, target_y))


def expand_autotile(source: Image.Image, target: Image.Image, source_offset: tuple[int, int], target_offset: tuple[int, int], combinations: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]], columns: int) -> None:
    for index, combination in enumerate(combinations):
        target_x = target_offset[0] + index % columns * TILE_SIZE
        target_y = target_offset[1] + index // columns * TILE_SIZE
        copy_combination(source, target, source_offset, (target_x, target_y), combination)


def expand_a2(source: Image.Image) -> Image.Image:
    combinations = terrain_combinations()
    target = Image.new("RGBA", (8 * 7 * TILE_SIZE, 4 * 7 * TILE_SIZE))
    for row in range(4):
        for column in range(8):
            source_offset = (column * 2 * TILE_SIZE, row * 3 * TILE_SIZE)
            target_offset = (column * 7 * TILE_SIZE, row * 7 * TILE_SIZE)
            expand_autotile(source, target, source_offset, target_offset, combinations, 7)
    return target


def expand_a4(source: Image.Image) -> Image.Image:
    terrain = terrain_combinations()
    wall = wall_combinations()
    target = Image.new("RGBA", (8 * 7 * TILE_SIZE, (7 + 4 + 7 + 4 + 7 + 4) * TILE_SIZE))
    source_y = 0
    target_y = 0
    for group in range(3):
        for column in range(8):
            expand_autotile(source, target, (column * 2 * TILE_SIZE, source_y), (column * 7 * TILE_SIZE, target_y), terrain, 7)
        source_y += 3 * TILE_SIZE
        target_y += 7 * TILE_SIZE
        for column in range(8):
            expand_autotile(source, target, (column * 2 * TILE_SIZE, source_y), (column * 4 * TILE_SIZE, target_y), wall, 4)
        source_y += 2 * TILE_SIZE
        target_y += 4 * TILE_SIZE
    return target


def has_pixels(image: Image.Image, box: tuple[int, int, int, int]) -> bool:
    alpha = image.crop(box).getchannel("A")
    return alpha.getbbox() is not None


def wang_color(name: str, tile: int) -> dict[str, int | float | str]:
    return {
        "color": "#c9824a",
        "name": name,
        "probability": 1,
        "tile": tile,
    }


def wang_set(name: str, type_: str, tile: int, wangtiles: list[dict[str, int | list[int]]]) -> dict[str, int | str | list[dict[str, int | float | str]] | list[dict[str, int | list[int]]]]:
    return {
        "name": name,
        "type": type_,
        "tile": tile,
        "colors": [wang_color(name, tile)],
        "wangtiles": wangtiles,
    }


def tile_id(columns: int, x: int, y: int) -> int:
    return y * columns + x


def block_tile_id(columns: int, block_x: int, block_y: int, local_index: int, block_columns: int) -> int:
    return tile_id(columns, block_x + local_index % block_columns, block_y + local_index // block_columns)


def terrain_wangtiles(columns: int, block_x: int, block_y: int) -> list[dict[str, int | list[int]]]:
    return [
        {
            "tileid": block_tile_id(columns, block_x, block_y, index, 7),
            "wangid": wang_id_from_terrain_mask(mask),
        }
        for index, (mask, _) in enumerate(terrain_variants())
    ]


def wall_wangtiles(columns: int, block_x: int, block_y: int) -> list[dict[str, int | list[int]]]:
    return [
        {
            "tileid": block_tile_id(columns, block_x, block_y, index, 4),
            "wangid": wang_id,
        }
        for index, (wang_id, _) in enumerate(wall_variants())
    ]


def terrain_representative(columns: int, block_x: int, block_y: int) -> int:
    variants = terrain_variants()
    full_index = next(index for index, (mask, _) in enumerate(variants) if wang_id_from_terrain_mask(mask) == [1] * 8)
    return block_tile_id(columns, block_x, block_y, full_index, 7)


def wall_representative(columns: int, block_x: int, block_y: int) -> int:
    full_index = next(index for index, (wang_id, _) in enumerate(wall_variants()) if wang_id == [1, 0, 1, 0, 1, 0, 1, 0])
    return block_tile_id(columns, block_x, block_y, full_index, 4)


def a2_wangsets(image: Image.Image, columns: int) -> list[dict[str, int | str | list]]:
    sets = []
    for row in range(4):
        for column in range(8):
            block_x = column * 7
            block_y = row * 7
            box = (block_x * TILE_SIZE, block_y * TILE_SIZE, (block_x + 7) * TILE_SIZE, (block_y + 7) * TILE_SIZE)
            if not has_pixels(image, box):
                continue
            name = f"A2 terrain {row + 1}-{column + 1}"
            sets.append(wang_set(name, "mixed", terrain_representative(columns, block_x, block_y), terrain_wangtiles(columns, block_x, block_y)))
    return sets


def a4_wangsets(image: Image.Image, columns: int) -> list[dict[str, int | str | list]]:
    sets = []
    for group in range(3):
        terrain_y = group * 11
        wall_y = terrain_y + 7
        for column in range(8):
            terrain_x = column * 7
            terrain_box = (terrain_x * TILE_SIZE, terrain_y * TILE_SIZE, (terrain_x + 7) * TILE_SIZE, (terrain_y + 7) * TILE_SIZE)
            if has_pixels(image, terrain_box):
                terrain_name = f"A4 terrain {group + 1}-{column + 1}"
                sets.append(wang_set(terrain_name, "mixed", terrain_representative(columns, terrain_x, terrain_y), terrain_wangtiles(columns, terrain_x, terrain_y)))
            wall_x = column * 4
            wall_box = (wall_x * TILE_SIZE, wall_y * TILE_SIZE, (wall_x + 4) * TILE_SIZE, (wall_y + 4) * TILE_SIZE)
            if has_pixels(image, wall_box):
                wall_name = f"A4 wall {group + 1}-{column + 1}"
                sets.append(wang_set(wall_name, "edge", wall_representative(columns, wall_x, wall_y), wall_wangtiles(columns, wall_x, wall_y)))
    return sets


def build_wangsets(sheet_type: str, image: Image.Image, columns: int) -> list[dict[str, int | str | list]]:
    if sheet_type == "A2":
        return a2_wangsets(image, columns)
    if sheet_type == "A4":
        return a4_wangsets(image, columns)
    return []


def write_tileset(path: Path, name: str, image_path: Path, image: Image.Image, sheet_type: str) -> None:
    columns = image.width // TILE_SIZE
    tilecount = columns * (image.height // TILE_SIZE)
    tileset = {
        "type": "tileset",
        "version": "1.10",
        "tiledversion": "1.12.2-2-geb83ddb9",
        "name": name,
        "tilewidth": TILE_SIZE,
        "tileheight": TILE_SIZE,
        "spacing": 0,
        "margin": 0,
        "tilecount": tilecount,
        "columns": columns,
        "image": image_path.name,
        "imagewidth": image.width,
        "imageheight": image.height,
    }
    wangsets = build_wangsets(sheet_type, image, columns)
    if wangsets:
        tileset["wangsets"] = wangsets
    path.write_text(json.dumps(tileset, indent=2) + "\n", encoding="utf-8")


def convert(source: Path, out_dir: Path, name: str) -> None:
    suffix = source.stem[-2:].upper()
    image = Image.open(source).convert("RGBA")
    if suffix == "A2":
        expanded = expand_a2(image)
    elif suffix == "A4":
        expanded = expand_a4(image)
    else:
        raise ValueError(f"Unsupported RPG Maker autotile sheet: {source}")
    output_png = out_dir / f"{name}_{suffix}_tiled.png"
    output_tsj = out_dir / f"{name}_{suffix}_tiled.tsj"
    expanded.save(output_png)
    write_tileset(output_tsj, f"{name}_{suffix}_tiled", output_png, expanded, suffix)
    print(f"Wrote {output_png}")
    print(f"Wrote {output_tsj}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("output/rpg-maker"))
    parser.add_argument("--out-dir", type=Path, default=Path("output/tiled"))
    parser.add_argument("--prefix", default="interior_furniture")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("A2", "A4"):
        source = args.source_dir / f"{args.prefix}_{suffix}.png"
        if source.exists():
            convert(source, args.out_dir, args.prefix)


if __name__ == "__main__":
    main()
