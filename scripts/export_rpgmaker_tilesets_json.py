"""Export a single RPG Maker MZ tileset entry as data/Tilesets.json."""

import argparse
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--name", default="Interior")
    parser.add_argument("--id", type=int, default=1)
    parser.add_argument(
        "--available-dir",
        help="When set, blank tileset image names whose PNG is not present here.",
    )
    return parser.parse_args()


def load_tileset_entry(path: Path, name: str) -> dict:
    data = json.loads(path.read_text())
    for entry in data:
        if isinstance(entry, dict) and entry.get("name") == name:
            return dict(entry)
    raise SystemExit(f"No tileset named {name!r} in {path}")


def blank_missing_tileset_names(entry: dict, available_dir: Path) -> None:
    names = list(entry.get("tilesetNames", []))
    for index, name in enumerate(names):
        if not name:
            continue
        if not (available_dir / f"{name}.png").exists():
            names[index] = ""
    entry["tilesetNames"] = names


def main():
    args = parse_args()
    source = Path(args.source)
    out = Path(args.out)

    entry = load_tileset_entry(source, args.name)
    entry["id"] = args.id
    if args.available_dir:
        blank_missing_tileset_names(entry, Path(args.available_dir))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([None, entry], separators=(",", ":")) + "\n")
    print(f"[rpg-maker] wrote {out}")


if __name__ == "__main__":
    main()
