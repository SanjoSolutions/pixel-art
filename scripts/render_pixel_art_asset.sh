#!/usr/bin/env bash
# Render one 3D model to pixel-art frames, previews, and sprite sheets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="${PIXEL_PIPELINE_ROOT:-$DEFAULT_ROOT}"
cd "$ROOT"

usage() {
  cat <<'USAGE'
Usage:
  scripts/render_pixel_art_asset.sh --model PATH [options]

Options:
  --model PATH                 GLB/GLTF/OBJ/FBX model to render
  --name NAME                  Output name (defaults to model basename)
  --pixel-size PX              Final square frame size (default: 64)
  --colors N                   Palette size when quantizing (default: 16)
  --angles N                   Number of rendered angles (default: 8)
  --render-scale N             Render at N× pixel size (default: 4)
  --render-size PX             Explicit Blender render size
  --elevation DEG              Camera elevation (default: 30)
  --margin N                   Orthographic framing margin (default: 1.25)
  --lighting lpc|overhead      Lighting profile (default: lpc)
  --shader-to-rgb              Use flat Shader-to-RGB light bands
  --freestyle-outline          Use Blender Freestyle outlines
  --freestyle-thickness N      Freestyle line thickness (default: 1)
  --post-outline               Add alpha-silhouette outline after resizing
  --no-post-outline            Disable post-process outline
  --quantize                   Enable color quantization (default)
  --no-quantize                Disable color quantization
  --palette-from PATH          Use colors from a palette image
  --palette-distance MODE      pillow, rgb, or hsl (default: pillow)
  --downscale-filter FILTER    box, bilinear, lanczos, or nearest (default: lanczos)
  --preview-scale N            Preview upscale factor, 0 disables (default: 8)
  -h, --help                   Show this help
USAGE
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required on PATH"
}

MODEL=""
NAME=""
PIXEL_SIZE=64
COLORS=16
ANGLES=8
RENDER_SCALE=4
RENDER_SIZE=""
ELEVATION=30
MARGIN=1.25
LIGHTING="lpc"
SHADER_TO_RGB=0
FREESTYLE_OUTLINE=0
FREESTYLE_THICKNESS=1
POST_OUTLINE=1
QUANTIZE=1
PALETTE_FROM=""
PALETTE_DISTANCE="pillow"
DOWNSCALE_FILTER="lanczos"
PREVIEW_SCALE=8

while [ "$#" -gt 0 ]; do
  case "$1" in
    --model)
      MODEL="${2:?--model requires a path}"
      shift 2
      ;;
    --name)
      NAME="${2:?--name requires a value}"
      shift 2
      ;;
    --pixel-size)
      PIXEL_SIZE="${2:?--pixel-size requires a value}"
      shift 2
      ;;
    --colors)
      COLORS="${2:?--colors requires a value}"
      shift 2
      ;;
    --angles)
      ANGLES="${2:?--angles requires a value}"
      shift 2
      ;;
    --render-scale)
      RENDER_SCALE="${2:?--render-scale requires a value}"
      shift 2
      ;;
    --render-size)
      RENDER_SIZE="${2:?--render-size requires a value}"
      shift 2
      ;;
    --elevation)
      ELEVATION="${2:?--elevation requires a value}"
      shift 2
      ;;
    --margin)
      MARGIN="${2:?--margin requires a value}"
      shift 2
      ;;
    --lighting)
      LIGHTING="${2:?--lighting requires a value}"
      shift 2
      ;;
    --shader-to-rgb)
      SHADER_TO_RGB=1
      shift
      ;;
    --freestyle-outline)
      FREESTYLE_OUTLINE=1
      shift
      ;;
    --freestyle-thickness)
      FREESTYLE_THICKNESS="${2:?--freestyle-thickness requires a value}"
      shift 2
      ;;
    --post-outline)
      POST_OUTLINE=1
      shift
      ;;
    --no-post-outline)
      POST_OUTLINE=0
      shift
      ;;
    --quantize)
      QUANTIZE=1
      shift
      ;;
    --no-quantize)
      QUANTIZE=0
      shift
      ;;
    --palette-from)
      PALETTE_FROM="${2:?--palette-from requires a path}"
      shift 2
      ;;
    --palette-distance)
      PALETTE_DISTANCE="${2:?--palette-distance requires a value}"
      shift 2
      ;;
    --downscale-filter)
      DOWNSCALE_FILTER="${2:?--downscale-filter requires a value}"
      shift 2
      ;;
    --preview-scale)
      PREVIEW_SCALE="${2:?--preview-scale requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -z "$MODEL" ] && [ -f "$1" ]; then
        MODEL="$1"
        shift
      else
        die "unknown argument: $1"
      fi
      ;;
  esac
done

[ -n "$MODEL" ] || die "--model is required"
[ -f "$MODEL" ] || die "model not found: $MODEL"

case "$LIGHTING" in
  lpc|overhead) ;;
  *) die "--lighting must be lpc or overhead" ;;
esac

case "$PALETTE_DISTANCE" in
  pillow|rgb|hsl) ;;
  *) die "--palette-distance must be pillow, rgb, or hsl" ;;
esac

case "$DOWNSCALE_FILTER" in
  box|bilinear|lanczos|nearest) ;;
  *) die "--downscale-filter must be box, bilinear, lanczos, or nearest" ;;
esac

require_command blender
require_command python3

if [ -z "$NAME" ]; then
  model_file="$(basename "$MODEL")"
  NAME="${model_file%.*}"
fi

if [ -z "$RENDER_SIZE" ]; then
  RENDER_SIZE=$((PIXEL_SIZE * RENDER_SCALE))
fi

RENDER_DIR="renders/$NAME"
PIXEL_DIR="output/$NAME"
PREVIEW_DIR="output/${NAME}_preview"
SHEET_PATH="output/${NAME}_sheet.png"
PREVIEW_SHEET_PATH="output/${NAME}_sheet_preview.png"

render_args=(
  --model "$MODEL"
  --out "$RENDER_DIR"
  --angles "$ANGLES"
  --size "$RENDER_SIZE"
  --elevation "$ELEVATION"
  --margin "$MARGIN"
  --lighting "$LIGHTING"
)

if [ "$SHADER_TO_RGB" -eq 1 ]; then
  render_args+=(--shader-to-rgb)
fi

if [ "$FREESTYLE_OUTLINE" -eq 1 ]; then
  render_args+=(--freestyle-outline --freestyle-thickness "$FREESTYLE_THICKNESS")
fi

pixelize_args=(
  --in-dir "$RENDER_DIR"
  --out-dir "$PIXEL_DIR"
  --size "$PIXEL_SIZE"
  --downscale-filter "$DOWNSCALE_FILTER"
  --preview-scale "$PREVIEW_SCALE"
)

if [ "$QUANTIZE" -eq 1 ]; then
  pixelize_args+=(--quantize --colors "$COLORS")
fi

if [ "$POST_OUTLINE" -eq 1 ]; then
  pixelize_args+=(--outline)
fi

if [ -n "$PALETTE_FROM" ]; then
  [ -f "$PALETTE_FROM" ] || die "palette image not found: $PALETTE_FROM"
  pixelize_args+=(--palette-from "$PALETTE_FROM" --palette-distance "$PALETTE_DISTANCE")
fi

echo "== rendering $MODEL -> $RENDER_DIR ($ANGLES angles @ ${RENDER_SIZE}px) =="
blender -b -P "$SCRIPT_DIR/render_blender.py" -- "${render_args[@]}"

echo "== pixelizing -> $PIXEL_DIR (${PIXEL_SIZE}px) =="
python3 "$SCRIPT_DIR/pixelize.py" "${pixelize_args[@]}"

echo "== building sprite sheet =="
python3 "$SCRIPT_DIR/make_spritesheet.py" --in-dir "$PIXEL_DIR" --out "$SHEET_PATH"

if [ "$PREVIEW_SCALE" -gt 1 ] && [ -d "$PREVIEW_DIR" ]; then
  python3 "$SCRIPT_DIR/make_spritesheet.py" --in-dir "$PREVIEW_DIR" --out "$PREVIEW_SHEET_PATH"
fi

echo "done -> $SHEET_PATH"
