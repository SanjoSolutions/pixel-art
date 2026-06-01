"""Snapshot the current atlas and manifest for future edit detection."""
import argparse
import shutil
from pathlib import Path


def copy_file(source: Path, target: Path):
    if not source.exists():
        raise SystemExit(f"Missing required file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--baseline-manifest", required=True)
    args = parser.parse_args()

    copy_file(Path(args.sheet), Path(args.baseline))
    copy_file(Path(args.manifest), Path(args.baseline_manifest))
    print(f"[sheet-edits] baseline updated at {args.baseline}")


if __name__ == "__main__":
    main()
