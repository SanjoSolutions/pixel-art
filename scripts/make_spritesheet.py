"""Compose frames into a sprite sheet.

Filename conventions:
  angle_NNN.png            -> horizontal strip (1 row × N cols)
  angle_NNN_wMM.png        -> 2D grid (rows = angles N, cols = wheel frames M)
                              standard "character sheet" layout
"""
import argparse
import re
from pathlib import Path
from PIL import Image


ANGLE_ONLY = re.compile(r"angle_(\d+)\.png$")
ANGLE_WHEEL = re.compile(r"angle_(\d+)_w(\d+)\.png$")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    in_dir = Path(args.in_dir)
    files = sorted(in_dir.glob("*.png"))
    if not files:
        raise SystemExit(f"No PNGs in {in_dir}")

    # Detect layout by the first filename that matches a known pattern.
    wheel_match = [ANGLE_WHEEL.search(f.name) for f in files]
    if any(wheel_match):
        frames = {}
        max_a = max_w = 0
        for f, m in zip(files, wheel_match):
            if not m:
                continue
            a, w = int(m.group(1)), int(m.group(2))
            frames[(a, w)] = f
            max_a = max(max_a, a)
            max_w = max(max_w, w)
        rows = max_a + 1
        cols = max_w + 1
        sample = Image.open(files[0]).convert("RGBA")
        fw, fh = sample.size
        sheet = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
        for (a, w), path in frames.items():
            img = Image.open(path).convert("RGBA")
            sheet.paste(img, (w * fw, a * fh), img)
        sheet.save(args.out)
        print(f"[sheet] 2D grid {cols}×{rows} ({cols * fw}×{rows * fh}) -> {args.out}")
        return

    frames = [Image.open(f).convert("RGBA") for f in files]
    w, h = frames[0].size
    sheet = Image.new("RGBA", (w * len(frames), h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * w, 0), frame)
    sheet.save(args.out)
    print(f"[sheet] strip {len(frames)}×1 ({w * len(frames)}×{h}) -> {args.out}")


if __name__ == "__main__":
    main()
