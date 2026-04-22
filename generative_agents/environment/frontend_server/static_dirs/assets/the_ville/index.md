---
title: the_ville — map matrix, visuals, collision
system: smallville-assets
tile_size_px: 32
tags:
  - smallville
  - map
  - collision
  - spritesheet
  - tileset
ai_summary: >-
  Static assets for the Smallville map. matrix/ defines walkability; visuals/ holds tile layers and character sheets.
  Phaser loads paths from Django static; reverie utils.py also references these locations for the Python side.
related_repo_files:
  - generative_agents/environment/frontend_server/templates/home/main_script.html
---

# `static_dirs/assets/the_ville`

## Typical layout

- **`matrix/`** — CSV / matrix data used for pathing and collision IDs (see `collision_block_id` in reverie `utils.py` template).
- **`visuals/`** — Rendered map layers, tilesets, and character sprite atlases used by Phaser `preload()`.

## When debugging “sprites slide / clip / wrong tile”

1. Confirm Phaser `tile_width` matches **`TILE_SIZE` in `translator/views.py` (32)** and movement math in `main_script.html`.
2. Check which **map version** subdirectory under `visuals/map_assets/` is active in the Phaser preload paths.
3. Verify static URL resolution (Django `{% static %}`) is not 404ing assets in the browser network tab.
