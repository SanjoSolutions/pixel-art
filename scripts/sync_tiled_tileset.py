"""Synchronize a Tiled JSON tileset with a tilesheet image."""
import argparse
import json
import os
from pathlib import Path

from PIL import Image


def posix_relative_path(path: Path, base: Path) -> str:
    try:
        rel_path = os.path.relpath(path, base)
    except ValueError:
        return path.as_posix()
    return Path(rel_path).as_posix()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tileset", required=True,
                        help="Tiled .tsj JSON file to update or create.")
    parser.add_argument("--image", required=True,
                        help="Tilesheet image path.")
    parser.add_argument("--tile-size", type=int, default=32,
                        help="Tile width and height in pixels.")
    parser.add_argument("--tile-width", type=int,
                        help="Tile width in pixels. Overrides --tile-size.")
    parser.add_argument("--tile-height", type=int,
                        help="Tile height in pixels. Overrides --tile-size.")
    parser.add_argument("--image-ref",
                        help="Image path to write into the tileset. Defaults "
                             "to a relative path from the tileset directory.")
    args = parser.parse_args()

    tile_width = args.tile_width or args.tile_size
    tile_height = args.tile_height or args.tile_size
    if tile_width <= 0 or tile_height <= 0:
        raise SystemExit("Tile dimensions must be positive")

    tileset_path = Path(args.tileset)
    image_path = Path(args.image)
    image = Image.open(image_path)
    if image.width % tile_width or image.height % tile_height:
        raise SystemExit(
            f"{image_path} is {image.width}×{image.height}; expected multiples "
            f"of {tile_width}×{tile_height}px"
        )

    if tileset_path.exists():
        data = json.loads(tileset_path.read_text())
    else:
        data = {
            "type": "tileset",
            "version": "1.10",
            "tiledversion": "1.12.2-2-geb83ddb9",
            "name": image_path.stem,
            "margin": 0,
            "spacing": 0,
        }

    data.setdefault("type", "tileset")
    data.setdefault("version", "1.10")
    data.setdefault("name", image_path.stem)
    data.setdefault("margin", 0)
    data.setdefault("spacing", 0)
    data["columns"] = image.width // tile_width
    data["image"] = args.image_ref or posix_relative_path(
        image_path,
        tileset_path.parent or Path("."),
    )
    data["imageheight"] = image.height
    data["imagewidth"] = image.width
    data["tileheight"] = tile_height
    data["tilewidth"] = tile_width
    data["tilecount"] = data["columns"] * (image.height // tile_height)

    tileset_path.parent.mkdir(parents=True, exist_ok=True)
    tileset_path.write_text(json.dumps(data, indent=2) + "\n")
    print(
        f"[tileset] {tileset_path}: {data['columns']} columns, "
        f"{data['tilecount']} tiles, {image.width}×{image.height}"
    )


if __name__ == "__main__":
    main()
