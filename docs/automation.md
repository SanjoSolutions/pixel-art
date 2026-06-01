# Automation Guide

The repository already contains the important low-level building blocks. The
goal of new automation is to orchestrate those blocks, not copy their logic.

## Automation layers

| Layer | Entry point | Use it for |
|---|---|---|
| Single asset | `scripts/render_pixel_art_asset.sh` | One model to frames and sheets |
| Downstream vehicle pack | external pack script | Calls public render/pixel/sheet scripts |
| Downstream furniture pack | external pack script | Calls public render/export/atlas scripts |

## Single-asset render

Use the flag-based wrapper for new examples and automation:

```bash
scripts/render_pixel_art_asset.sh \
  --model "models/kenney_car_kit/Models/GLB format/sedan-sports.glb" \
  --name sedan-sports \
  --pixel-size 64 \
  --colors 16 \
  --angles 8
```

The wrapper calls, in order:

1. `scripts/render_blender.py`
2. `scripts/pixelize.py`
3. `scripts/make_spritesheet.py`

Outputs are written to the existing `renders/` and `output/` folders:

- `renders/<name>/angle_*.png`
- `output/<name>/angle_*.png`
- `output/<name>_preview/angle_*.png`
- `output/<name>_sheet.png`
- `output/<name>_sheet_preview.png`

## Style presets through flags

The wrapper exposes common style controls while leaving specialized controls in
the underlying Python scripts.

Examples:

```bash
# Geometry-aware Blender outline instead of post-process alpha outline.
scripts/render_pixel_art_asset.sh \
  --model "models/kenney_car_kit/Models/GLB format/taxi.glb" \
  --freestyle-outline \
  --freestyle-thickness 4 \
  --no-post-outline

# Flatter lighting bands.
scripts/render_pixel_art_asset.sh \
  --model "models/kenney_car_kit/Models/GLB format/taxi.glb" \
  --lighting overhead \
  --shader-to-rgb

# Use any palette image you provide.
scripts/render_pixel_art_asset.sh \
  --model "models/kenney_car_kit/Models/GLB format/taxi.glb" \
  --palette-from /path/to/palette.png \
  --palette-distance hsl
```

## Downstream batch builds

Commercial packaging scripts can live outside this public repo and call the
shared files here directly. A vehicle pack script usually does more than the
single-asset wrapper:

- renders every included vehicle model
- caches renders by profile
- creates wheel masks
- freezes non-wheel pixels across wheel animation frames
- writes vehicle metadata for the HTML demo
- builds distributable zip files under `dist/`

The furniture pack script treats an Aseprite source file as the editable source
of truth, while its Blender regeneration path reuses the public render,
pixelize, atlas, and Aseprite import/export helpers.


## Maintenance rule

When adding a new workflow, prefer one of these patterns:

1. Add a flag to an existing script.
2. Add a small orchestration wrapper that calls existing scripts.
3. Document a preset command in Markdown.

Avoid copying rendering, pixelization, or spritesheet logic into a second place.
