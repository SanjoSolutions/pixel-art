"""Copy generated sprites, then overlay manual per-sprite overrides."""
import argparse
import shutil
from pathlib import Path

from PIL import Image


def reset_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_pngs(source: Path, target: Path):
    if not source.exists():
        return
    for path in sorted(source.glob("*.png")):
        shutil.copy2(path, target / path.name)


def validate_tile_size(path: Path, image: Image.Image, tile_size: int):
    if image.width % tile_size or image.height % tile_size:
        raise SystemExit(
            f"{path} is {image.width}×{image.height}; expected multiples of "
            f"{tile_size}px"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-dir", required=True)
    parser.add_argument("--override-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--tile-size", type=int, default=32)
    parser.add_argument("--preview-scale", type=int, default=0)
    args = parser.parse_args()

    generated_dir = Path(args.generated_dir)
    override_dir = Path(args.override_dir)
    out_dir = Path(args.out_dir)
    generated_preview_dir = generated_dir.parent / f"{generated_dir.name}_preview"
    out_preview_dir = out_dir.parent / f"{out_dir.name}_preview"

    reset_dir(out_dir)
    copy_pngs(generated_dir, out_dir)

    if args.preview_scale > 1:
        reset_dir(out_preview_dir)
        copy_pngs(generated_preview_dir, out_preview_dir)

    if not override_dir.exists():
        print(f"[overrides] no override dir at {override_dir}")
        return

    applied = 0
    for override_path in sorted(override_dir.glob("*.png")):
        override = Image.open(override_path).convert("RGBA")
        validate_tile_size(override_path, override, args.tile_size)

        generated_path = generated_dir / override_path.name
        if generated_path.exists():
            generated = Image.open(generated_path)
            if generated.size != override.size:
                print(
                    f"[overrides] warning: {override_path.name} is "
                    f"{override.size}, generated is {generated.size}"
                )

        override.save(out_dir / override_path.name)
        if args.preview_scale > 1:
            preview = override.resize(
                (
                    override.width * args.preview_scale,
                    override.height * args.preview_scale,
                ),
                Image.Resampling.NEAREST,
            )
            preview.save(out_preview_dir / override_path.name)
        applied += 1
        print(f"[overrides] applied {override_path.name}")

    print(f"[overrides] applied {applied} override(s)")


if __name__ == "__main__":
    main()
