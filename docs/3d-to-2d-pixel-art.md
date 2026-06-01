# From 3D Models to 2D Pixel Art

This project turns low-poly 3D assets into 2D sprites by combining deterministic
Blender renders with small, explicit image-processing steps.

The short version:

```text
3D model → orthographic render → pixel-sized PNGs → optional palette/outline → sprite sheet
```

## Why render from 3D?

Rendering from 3D is useful when a project needs many consistent sprites:

- the same object from many angles
- animation frames that stay aligned
- repeated style choices across an entire asset pack
- quick regeneration after changing lighting, scale, camera angle, or materials

The tradeoff is that the first setup takes more care than drawing one sprite by
hand. The payoff comes when the same setup can process dozens or hundreds of
assets.

## Step 1: prepare the model

The best source models for this pipeline are simple, readable, and mostly
flat-colored. Low-poly assets work especially well because their shapes survive
aggressive downscaling.

Before rendering, check:

- **Scale** — related assets should use similar real-world proportions.
- **Forward direction** — vehicles or directional objects should face a known
  axis so generated angle indices are predictable.
- **Materials** — flat base colors are easier to pixelize than noisy textures.
- **Origin and bounds** — the object should be centered enough that camera
  framing remains stable.

The current vehicle renderer imports GLB, GLTF, OBJ, and FBX files in
`scripts/render_blender.py`.

## Step 2: render orthographic views

Blender renders the model with an orthographic camera instead of a perspective
camera. Orthographic projection keeps the sprite game-friendly: parallel lines
remain parallel, and the object does not distort as it rotates.

The renderer rotates the model under a fixed camera and fixed light. Keeping the
camera and light fixed gives each angle consistent screen-space lighting, which
usually reads better in a sprite sheet than a light that rotates with the model.

Important render choices:

- **Transparent background** keeps the sprite ready for game engines.
- **Fixed render size** makes all frames align.
- **Low render filter size** keeps edges crisp before downscaling.
- **Standard color management** avoids filmic color shifts.
- **Optional Shader-to-RGB bands** create flatter, more pixel-art-friendly
  lighting.
- **Optional Freestyle outlines** create geometry-aware line art before
  pixelization.

## Step 3: reduce to the target pixel size

The renderer can output larger images than the final sprite size. The pixelizer
then downsamples to the target size, for example 256 px renders down to 64 px
sprites.

This two-stage approach gives Blender enough resolution for clean silhouettes
while still producing tiny final frames. The default single-asset path renders
at 4× final size, then downscales with Pillow.

## Step 4: simplify color and alpha

After resizing, `scripts/pixelize.py` makes the PNG more sprite-like:

- alpha is binarized so semi-transparent fringes disappear
- colors can be quantized to a smaller palette
- frames can share palettes to avoid flicker across animation frames
- an alpha-silhouette outline can be added after downscaling
- transparent borders can be trimmed for tile-aligned assets

There are two outline approaches:

- **Freestyle outline** happens in Blender and follows 3D geometry.
- **Post-process outline** happens after resizing and follows the alpha
  silhouette.

Freestyle is usually cleaner for vehicles and objects with visible internal
edges. Post-process outlines are simpler and useful for quick experiments.

## Step 5: compose sheets

Individual frames are easier to inspect and debug, but games usually want sprite
sheets. `scripts/make_spritesheet.py` reads the generated PNG names and composes
either:

- a horizontal strip for angle-only frames
- a 2D grid for angle plus wheel-animation frames

The filename convention is intentionally simple:

```text
angle_000.png
angle_001.png
angle_000_w00.png
angle_000_w01.png
```

## Step 6: iterate deliberately

Most quality improvements come from changing one variable at a time:

- camera elevation
- orthographic margin
- final pixel size
- material colors
- palette size or palette image
- outline type and thickness
- lighting profile

Save presets as scripts or documented commands instead of hand-tuning in a GUI.
That keeps the pipeline reproducible and makes regenerated assets comparable.

## Where to look in this repo

- `scripts/render_pixel_art_asset.sh` is the single-asset automation wrapper.
- `scripts/render_blender.py` handles Blender import, camera, lighting, and
  rendering.
- `scripts/pixelize.py` handles resizing, palette reduction, alpha cleanup,
  outlines, trimming, and previews.
- `scripts/make_spritesheet.py` turns frames into sheets.
- Downstream vehicle and furniture pack scripts can call these public scripts
  directly, avoiding duplicated render or pixelization logic.
