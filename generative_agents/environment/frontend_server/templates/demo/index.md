---
title: templates/demo — compressed replay Phaser (not bridge_smallville)
system: smallville-phaser
entry_template: demo.html
script: main_script.html
tags:
  - smallville
  - phaser
  - replay
  - compressed-storage
ai_summary: >-
  Used when translator.views.demo loads a real compressed simulation from compressed_storage/.
  For sim_code bridge_smallville, views.py renders home/home.html instead — do not confuse the two code paths.
---

# `templates/demo`

## When this folder is used

`translator.views.demo()` selects:

- **`demo/demo.html` + `demo/main_script.html`** — classic compressed replay (`master_movement.json` + `meta.json`).
- **`home/home.html` + `home/main_script.html`** — when `sim_code == bridge_smallville` (live bridge).

## Files

| File | Role |
|------|------|
| `demo.html` | Host page for compressed replay |
| `main_script.html` | Phaser scene with **`all_movement`** preloaded JSON |

## Gotcha

If you edit **`demo/main_script.html`** expecting bridge behavior to change, you may be editing the **wrong** script — bridge live map uses **`home/main_script.html`**.
