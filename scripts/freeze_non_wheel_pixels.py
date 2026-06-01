"""Freeze non-wheel pixels across wheel animation frames.

The vehicle demo sheets animate only wheel rotation. Freestyle and banded
lighting can still introduce tiny per-frame changes on body pixels when hidden
or partially occluded wheels rotate. This script uses per-angle visible-wheel
masks from render_blender.py and copies pixels outside those masks from the
first wheel frame, keeping body pixels stable while preserving wheel animation.
"""

import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageFilter


ANGLE_WHEEL = re.compile(r"angle_(\d+)_w(\d+)\.png$")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--mask-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--threshold", type=int, default=64,
                        help="Minimum source RGB value for wheel-mask pixels.")
    parser.add_argument("--coverage-threshold", type=int, default=96,
                        help="Minimum resized mask coverage to keep. Low "
                             "values preserve thin/partially visible wheels.")
    parser.add_argument("--dilate", type=int, default=0,
                        help="Dilate final-size wheel mask by this many pixels.")
    return parser.parse_args()


def grouped_frame_paths(frames_dir: Path) -> dict[int, list[tuple[int, Path]]]:
    groups: dict[int, list[tuple[int, Path]]] = defaultdict(list)
    for path in sorted(frames_dir.glob("*.png")):
        match = ANGLE_WHEEL.fullmatch(path.name)
        if not match:
            continue
        angle = int(match.group(1))
        wheel = int(match.group(2))
        groups[angle].append((wheel, path))
    return {
        angle: sorted(paths)
        for angle, paths in groups.items()
    }


def wheel_mask(
    mask_path: Path,
    size: tuple[int, int],
    threshold: int,
    coverage_threshold: int,
    dilate: int,
):
    source = Image.open(mask_path).convert("RGBA")
    mask = Image.new("L", source.size, 0)
    pixels = source.load()
    mask_pixels = mask.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 0 and max(red, green, blue) >= threshold:
                mask_pixels[x, y] = 255

    mask = mask.resize(size, Image.Resampling.BOX)
    mask = mask.point(lambda value: 255 if value >= coverage_threshold else 0)
    if dilate > 0:
        mask = mask.filter(ImageFilter.MaxFilter(dilate * 2 + 1))
    return mask


def freeze_group(
    frames: list[tuple[int, Path]],
    mask: Image.Image,
    out_dir: Path,
):
    base_path = dict(frames).get(0, frames[0][1])
    base = Image.open(base_path).convert("RGBA")
    for _wheel, path in frames:
        frame = Image.open(path).convert("RGBA")
        frozen = Image.composite(frame, base, mask)
        frozen.save(out_dir / path.name)


def main():
    args = parse_args()
    frames_dir = Path(args.frames_dir)
    mask_dir = Path(args.mask_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    grouped = grouped_frame_paths(frames_dir)
    handled = set()
    for angle, frames in grouped.items():
        sample = Image.open(frames[0][1]).convert("RGBA")
        mask_path = mask_dir / f"angle_{angle:03d}.png"
        if not mask_path.exists():
            for _wheel, path in frames:
                shutil.copy2(path, out_dir / path.name)
                handled.add(path.name)
            continue
        mask = wheel_mask(
            mask_path,
            sample.size,
            args.threshold,
            args.coverage_threshold,
            args.dilate,
        )
        freeze_group(frames, mask, out_dir)
        handled.update(path.name for _wheel, path in frames)

    for path in sorted(frames_dir.glob("*.png")):
        if path.name not in handled:
            shutil.copy2(path, out_dir / path.name)

    print(f"[freeze] {frames_dir} -> {out_dir}")


if __name__ == "__main__":
    main()
