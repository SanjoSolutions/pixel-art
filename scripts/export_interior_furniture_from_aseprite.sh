#!/usr/bin/env bash
# Export the editable furniture Aseprite file into the runtime PNG,
# sprite manifest, Tiled tileset metadata, and individual trimmed sprites.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${PIXEL_PIPELINE_ROOT:-$DEFAULT_ROOT}"
cd "$ROOT"

ASEPRITE_BIN="${ASEPRITE_BIN:-aseprite}"
ASEPRITE_SOURCE="${ASEPRITE_SOURCE:-interior_furniture.aseprite}"
SHEET="${SHEET:-output/interior_furniture.png}"
MANIFEST="${MANIFEST:-output/furniture_manifest.json}"
TILED_TILESET="${TILED_TILESET:-interior_furniture.tsj}"
TILED_IMAGE_REF="${TILED_IMAGE_REF:-$ASEPRITE_SOURCE}"
SPRITES_DIR="${SPRITES_DIR:-output/sprites}"
TILE_SIZE="${TILE_SIZE:-32}"

if ! command -v "$ASEPRITE_BIN" >/dev/null 2>&1; then
  echo "Aseprite CLI not found: $ASEPRITE_BIN" >&2
  exit 1
fi
if [[ ! -f "$ASEPRITE_SOURCE" ]]; then
  echo "Aseprite source not found: $ASEPRITE_SOURCE" >&2
  exit 1
fi

mkdir -p "$(dirname "$SHEET")" "$(dirname "$MANIFEST")"

echo "== exporting furniture sheet pixels from $ASEPRITE_SOURCE -> $SHEET =="
"$ASEPRITE_BIN" -b "$ASEPRITE_SOURCE" --save-as "$SHEET"

echo "== exporting furniture sheet slices -> $MANIFEST and $TILED_TILESET =="
"$ASEPRITE_BIN" -b \
  --script-param "source=$ASEPRITE_SOURCE" \
  --script-param "sheet=$SHEET" \
  --script-param "manifest=$MANIFEST" \
  --script-param "tileset=$TILED_TILESET" \
  --script-param "image-ref=$TILED_IMAGE_REF" \
  --script-param "tile-size=$TILE_SIZE" \
  --script "$SCRIPT_DIR/export_aseprite_slices.lua"

echo "== exporting trimmed single sprites -> $SPRITES_DIR =="
python3 "$SCRIPT_DIR/export_sprites_from_manifest.py" \
  --sheet "$SHEET" \
  --manifest "$MANIFEST" \
  --out-dir "$SPRITES_DIR"

echo "done -> $SHEET and $SPRITES_DIR"
