#!/usr/bin/env bash
# Update the editable Aseprite furniture source from the generated PNG+manifest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${PIXEL_PIPELINE_ROOT:-$DEFAULT_ROOT}"
cd "$ROOT"

ASEPRITE_BIN="${ASEPRITE_BIN:-aseprite}"
ASEPRITE_SOURCE="${ASEPRITE_SOURCE:-interior_furniture.aseprite}"
SHEET="${SHEET:-output/interior_furniture.png}"
MANIFEST="${MANIFEST:-output/furniture_manifest.json}"
REPLACEMENT_SHEET="${REPLACEMENT_SHEET:-}"
REPLACEMENT_MANIFEST="${REPLACEMENT_MANIFEST:-}"
PRESERVE_ASEPRITE_LAYOUT="${PRESERVE_ASEPRITE_LAYOUT:-1}"
TILE_SIZE="${TILE_SIZE:-32}"

if ! command -v "$ASEPRITE_BIN" >/dev/null 2>&1; then
  echo "Aseprite CLI not found: $ASEPRITE_BIN" >&2
  exit 1
fi
if [[ ! -f "$ASEPRITE_SOURCE" ]]; then
  echo "Aseprite source not found: $ASEPRITE_SOURCE" >&2
  exit 1
fi
if [[ ! -f "$SHEET" ]]; then
  echo "Furniture sheet not found: $SHEET" >&2
  exit 1
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "Furniture manifest not found: $MANIFEST" >&2
  exit 1
fi
if [[ -n "$REPLACEMENT_SHEET" && ! -f "$REPLACEMENT_SHEET" ]]; then
  echo "Replacement sheet not found: $REPLACEMENT_SHEET" >&2
  exit 1
fi
if [[ -n "$REPLACEMENT_MANIFEST" && ! -f "$REPLACEMENT_MANIFEST" ]]; then
  echo "Replacement manifest not found: $REPLACEMENT_MANIFEST" >&2
  exit 1
fi

echo "== importing furniture sheet pixels and slices -> $ASEPRITE_SOURCE =="
"$ASEPRITE_BIN" -b \
  --script-param "source=$ASEPRITE_SOURCE" \
  --script-param "sheet=$SHEET" \
  --script-param "manifest=$MANIFEST" \
  --script-param "replacement-sheet=$REPLACEMENT_SHEET" \
  --script-param "replacement-manifest=$REPLACEMENT_MANIFEST" \
  --script-param "preserve-layout=$PRESERVE_ASEPRITE_LAYOUT" \
  --script-param "tile-size=$TILE_SIZE" \
  --script "$SCRIPT_DIR/import_interior_furniture_to_aseprite.lua"
