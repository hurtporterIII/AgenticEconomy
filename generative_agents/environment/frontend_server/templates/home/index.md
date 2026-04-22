---
title: templates/home — live Phaser map (simulate, replay, bridge)
system: smallville-phaser
entry_template: home.html
script: main_script.html
bridge_sim_code: bridge_smallville
tags:
  - smallville
  - phaser
  - sprites
  - movement
  - bridge
ai_summary: >-
  home.html loads Phaser and includes main_script.html. bridge_mode is when sim_code === bridge_smallville.
  Persona spawn positions come from Django context (bridge uses pixel coords). Polling hits /update_environment/.
---

# `templates/home`

## Files

| File | Role |
|------|------|
| **`home.html`** | Layout, time UI, includes **`home/main_script.html`** |
| **`main_script.html`** | **Phaser 3** game: preload/create/update, persona movement, polling |
| `error_start_backend.html` | Shown when native mode lacks temp step pointer |

## Bridge vs native (same script)

- `let bridge_mode = (sim_code === "bridge_smallville");` near top of `main_script.html`.
- Bridge: positions are **pixels** from FastAPI JSON (see `translator/views.py::_bridge_persona_lists`).
- Native: positions come from reverie environment JSON steps under `storage/<sim>/environment/`.

## Debugging “sprites do not stay put / oscillate”

1. Inspect `/update_environment/` JSON: check `persona[ id ].movement` vs `dest_x` / `dest_y`.
2. In bridge mode, **`dest_*` must track backend `target_x` / `target_y`** — logic is documented in `translator/views.py`.
3. Verify `tile_width` % `movement_speed` == 0 (comment in `main_script.html`).

## Sibling index

- `../demo/index.md` — **different** Phaser path used for **compressed** replays with full `all_movement` JSON
