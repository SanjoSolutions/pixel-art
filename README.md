# 3D to 2D Pixel Art Pipeline

## Requirements

- Blender (tested with 5.1)
  - `blender` on `PATH`
- Python 3 with Pillow (`python3 -m pip install -r requirements.txt`)

## Example

To render an example vehicle:

```bash
scripts/render_pixel_art_asset.sh \
  --model "models/kenney_car_kit/Models/GLB format/sedan-sports.glb"
```

Outputs are written to:

- `renders/sedan-sports/angle_*.png`
- `output/sedan-sports/angle_*.png`
- `output/sedan-sports_sheet.png`

## Blender Template

`pixel_render_template.blend` is a ready-made interactive Blender scene with
the same camera, lighting, color-management, and outline settings used by the
automation scripts.

1. Open it
2. Allow the embedded script if Blender asks
3. Import a GLB/GLTF/OBJ/FBX model
4. Render with `F12`

Settings live under Render Properties > `Pixel Render Template`.

## Learn the Process

- `docs/3d-to-2d-pixel-art.md` explains the 3D-to-sprite process.
- `docs/automation.md` explains the automation layers and script entry points.

## Key Scripts

- `scripts/render_pixel_art_asset.sh` orchestrates the single-model workflow.
- `scripts/render_blender.py` imports a model and renders angle frames in
  Blender.
- `scripts/pixelize.py` resizes, quantizes, outlines, trims, and previews PNGs.
- `scripts/make_spritesheet.py` composes frames into a sprite sheet.

Additional utility scripts support palette conversion, grid sheets, Aseprite
slice export/import, RPG Maker/Tiled metadata, and reusable Blender templates.
Downstream pack packaging scripts can call the shared scripts here directly.
