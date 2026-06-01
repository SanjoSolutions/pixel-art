#!/usr/bin/env python3
import argparse
import io
import json
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image


API_URL = "https://ambientcg.com/api/v2/full_json"
LIST_URL = (
    "https://ambientcg.com/list"
    "?category=WoodFloor&type=material%2Cdecal%2Catlas&sort=popular"
)
DEFAULT_TYPES = "Material,Decal,Atlas"
DEFAULT_CATEGORY = "WoodFloor"
DEFAULT_SORT = "Popular"
USER_AGENT = "pixel-car-renderer ambientCG wood floor tile builder"


def request_url(url: str, timeout: int = 120):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def iter_values(value):
    if isinstance(value, dict):
        yield from value.values()
    elif isinstance(value, list):
        yield from value


def fetch_assets(category: str, data_types: str, sort: str) -> list[dict]:
    params = {
        "category": category,
        "type": data_types,
        "sort": sort,
        "include": "downloadData,previewData",
        "limit": "250",
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with request_url(url, timeout=60) as response:
        data = json.load(response)
    assets = data.get("foundAssets", [])
    expected = int(data.get("numberOfResults", len(assets)))
    if expected != len(assets):
        raise RuntimeError(
            f"Expected {expected} assets from AmbientCG, got {len(assets)}. "
            "Increase the API limit or add pagination."
        )
    return assets


def download_entries(asset: dict) -> list[dict]:
    entries = []
    for folder in iter_values(asset.get("downloadFolders")):
        for category in iter_values(folder.get("downloadFiletypeCategories")):
            entries.extend(category.get("downloads", []))
    return entries


def choose_zip_download(asset: dict) -> tuple[dict | None, str | None]:
    by_attribute = {
        entry.get("attribute"): entry for entry in download_entries(asset)
    }
    if "1K-PNG" in by_attribute:
        return by_attribute["1K-PNG"], "zip-png"
    if "1K-JPG" in by_attribute:
        return by_attribute["1K-JPG"], "zip-jpg-fallback"
    return None, None


def preview_color_url(asset: dict) -> str | None:
    for preview in asset.get("previewLinks", []):
        url = preview.get("url", "")
        parsed = urllib.parse.urlsplit(url)
        fragment = urllib.parse.parse_qs(parsed.fragment)
        for key in ("color_url", "texture_url"):
            for value in fragment.get(key, []):
                first_url = value.split(",", 1)[0]
                if "_Color." in first_url or first_url.lower().endswith((".jpg", ".png", ".webp")):
                    return first_url

    preview_image = asset.get("previewImage") or {}
    return (
        preview_image.get("1024-PNG")
        or preview_image.get("1024-JPG-FFFFFF")
        or preview_image.get("512-PNG")
        or preview_image.get("512-JPG-FFFFFF")
    )


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def find_color_member(zip_file: zipfile.ZipFile, extensions: tuple[str, ...]) -> str:
    names = [name for name in zip_file.namelist() if not name.endswith("/")]
    lower_extensions = tuple(extension.lower() for extension in extensions)
    suffix_matches = [
        name for name in names
        if Path(name).name.lower().endswith(tuple(f"_color{extension}" for extension in lower_extensions))
    ]
    if suffix_matches:
        return sorted(suffix_matches, key=len)[0]

    color_matches = [
        name for name in names
        if "color" in Path(name).name.lower()
        and Path(name).suffix.lower() in lower_extensions
    ]
    if color_matches:
        return sorted(color_matches, key=len)[0]

    raise RuntimeError(
        "No color map found in ZIP. Members: " +
        ", ".join(Path(name).name for name in names[:20])
    )


def download_bytes(url: str) -> bytes:
    with request_url(url, timeout=240) as response:
        return response.read()


def source_image_from_zip(download: dict, source_kind: str) -> tuple[Image.Image, str]:
    url = download["downloadLink"]
    archive_bytes = download_bytes(url)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        extensions = (".png",) if source_kind == "zip-png" else (".jpg", ".jpeg")
        member = find_color_member(archive, extensions)
        with archive.open(member) as file:
            image = Image.open(file)
            image.load()
    return image, url


def source_image_from_preview(url: str) -> Image.Image:
    image_bytes = download_bytes(url)
    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    return image


def save_tile(image: Image.Image, out_path: Path, size: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tile = image.convert("RGB").resize((size, size), Image.Resampling.NEAREST)
    tile.save(out_path)


def assemble_sheet(tile_paths: list[Path], out_path: Path, columns: int, tile_size: int) -> tuple[int, int]:
    rows = math.ceil(len(tile_paths) / columns)
    sheet = Image.new("RGB", (columns * tile_size, rows * tile_size))
    for index, tile_path in enumerate(tile_paths):
        tile = Image.open(tile_path).convert("RGB")
        x = (index % columns) * tile_size
        y = (index // columns) * tile_size
        sheet.paste(tile, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return columns, rows


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_tileset(path: Path, sheet_path: Path, name: str, columns: int, rows: int, tile_size: int, count: int) -> None:
    tileset = {
        "columns": columns,
        "image": sheet_path.name,
        "imageheight": rows * tile_size,
        "imagewidth": columns * tile_size,
        "margin": 0,
        "name": name,
        "spacing": 0,
        "tilecount": count,
        "tiledversion": "1.12.2-2-geb83ddb9",
        "tileheight": tile_size,
        "tilewidth": tile_size,
        "type": "tileset",
        "version": "1.10",
    }
    write_json(path, tileset)


def create_aseprite(sheet_path: Path, manifest_path: Path, aseprite_path: Path, tile_size: int, script_path: Path) -> None:
    subprocess.run(
        [
            "aseprite",
            "-b",
            str(sheet_path),
            "--script-param",
            f"manifest={manifest_path}",
            "--script-param",
            f"output={aseprite_path}",
            "--script-param",
            f"tile-size={tile_size}",
            "--script",
            str(script_path),
        ],
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build 32x32 AmbientCG wood-floor tiles and an Aseprite spritesheet."
    )
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, default=Path("tiles"))
    parser.add_argument("--name", default="wood_floors")
    parser.add_argument("--category", default=DEFAULT_CATEGORY)
    parser.add_argument("--type", default=DEFAULT_TYPES)
    parser.add_argument("--sort", default=DEFAULT_SORT)
    parser.add_argument("--skip-aseprite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    out_dir = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    tile_dir = out_dir / args.name
    sheet_path = out_dir / f"{args.name}.png"
    manifest_path = out_dir / f"{args.name}_manifest.json"
    tileset_path = out_dir / f"{args.name}.tsj"
    aseprite_path = out_dir / f"{args.name}.aseprite"
    aseprite_script = root / "scripts" / "import_ambientcg_tiles_to_aseprite.lua"

    assets = fetch_assets(args.category, args.type, args.sort)
    tile_paths = []
    tiles = []
    warnings = []

    for index, asset in enumerate(assets):
        asset_id = asset["assetId"]
        display_name = asset.get("displayName") or asset_id
        tile_path = tile_dir / f"{safe_filename(asset_id)}.png"

        download, source_kind = choose_zip_download(asset)
        source_url = None
        try:
            if download:
                image, source_url = source_image_from_zip(download, source_kind)
            else:
                source_url = preview_color_url(asset)
                if not source_url:
                    raise RuntimeError("No ZIP download or preview color map available.")
                source_kind = "preview-color-fallback"
                image = source_image_from_preview(source_url)
                warnings.append(f"{asset_id}: used preview color map because no ZIP download is available.")
        except Exception as exc:
            warnings.append(f"{asset_id}: skipped ({exc})")
            print(f"[{index + 1:02d}/{len(assets):02d}] skip {asset_id}: {exc}", flush=True)
            continue

        save_tile(image, tile_path, args.tile_size)
        tile_paths.append(tile_path)
        tile_index = len(tile_paths) - 1
        x = (tile_index % args.columns) * args.tile_size
        y = (tile_index // args.columns) * args.tile_size
        tiles.append({
            "index": tile_index,
            "asset_id": asset_id,
            "display_name": display_name,
            "tile": str(tile_path.relative_to(root)),
            "x": x,
            "y": y,
            "w": args.tile_size,
            "h": args.tile_size,
            "source_kind": source_kind,
            "source_url": source_url,
            "asset_url": f"https://ambientcg.com/view?id={asset_id}",
        })
        print(f"[{index + 1:02d}/{len(assets):02d}] tile {asset_id} ({source_kind})", flush=True)
        time.sleep(0.05)

    if not tile_paths:
        raise RuntimeError("No tiles were generated.")

    columns, rows = assemble_sheet(tile_paths, sheet_path, args.columns, args.tile_size)
    manifest = {
        "source": LIST_URL,
        "api": API_URL,
        "tile_size": args.tile_size,
        "columns": columns,
        "rows": rows,
        "count": len(tile_paths),
        "tiles": tiles,
        "warnings": warnings,
    }
    write_json(manifest_path, manifest)
    write_tileset(tileset_path, sheet_path, args.name, columns, rows, args.tile_size, len(tile_paths))

    if not args.skip_aseprite:
        create_aseprite(sheet_path, manifest_path, aseprite_path, args.tile_size, aseprite_script)

    print(f"Generated {len(tile_paths)} tiles")
    print(f"Tiles: {tile_dir.relative_to(root)}")
    print(f"Sheet: {sheet_path.relative_to(root)}")
    print(f"Manifest: {manifest_path.relative_to(root)}")
    print(f"Tileset: {tileset_path.relative_to(root)}")
    if not args.skip_aseprite:
        print(f"Aseprite: {aseprite_path.relative_to(root)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
