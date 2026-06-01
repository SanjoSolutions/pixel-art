# Documentation

This folder is the educational layer for the project. It explains the pipeline
without duplicating the implementation details that already live in the scripts
and root `README.md`.

## Start here

1. [`3d-to-2d-pixel-art.md`](3d-to-2d-pixel-art.md) — how the 3D to pixel-art
   conversion works conceptually.
2. [`automation.md`](automation.md) — which scripts automate each level of the
   workflow.

## Maintainer note

Keep durable concepts here and keep exact command behavior in the scripts'
`--help` output or the root `README.md`. That avoids stale duplicate
documentation when the pipeline changes.
