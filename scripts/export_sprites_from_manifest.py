"""Export one trimmed PNG per manifest sprite."""

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def safe_output_path(out_dir: Path, file_name: str) -> Path:
    path = out_dir / Path(file_name).name
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    return path


def trimmed_sprite(crop: Image.Image) -> Image.Image:
    bbox = crop.getchannel("A").getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return crop.crop(bbox)


def main():
    args = parse_args()
    sheet_path = Path(args.sheet)
    manifest_path = Path(args.manifest)
    out_dir = Path(args.out_dir)

    manifest = json.loads(manifest_path.read_text())
    sprites = manifest.get("sprites", [])
    if not sprites:
        raise SystemExit(f"No sprites in {manifest_path}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    sheet = Image.open(sheet_path).convert("RGBA")
    used_paths: set[Path] = set()
    for sprite in sprites:
        file_name = f"{sprite['name']}.png"
        out_path = safe_output_path(out_dir, str(file_name))
        if out_path in used_paths:
            raise SystemExit(f"Duplicate sprite output filename: {out_path.name}")
        used_paths.add(out_path)

        x = int(sprite["x"])
        y = int(sprite["y"])
        width = int(sprite["w"])
        height = int(sprite["h"])
        crop = sheet.crop((x, y, x + width, y + height))
        trimmed_sprite(crop).save(out_path)

    print(f"[sprites] exported {len(sprites)} trimmed sprites -> {out_dir}")


if __name__ == "__main__":
    main()
