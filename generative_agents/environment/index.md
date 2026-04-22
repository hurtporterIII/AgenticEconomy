---
title: Environment server (Django) — Smallville map host
system: smallville-django
parent: generative_agents/index.md
tags:
  - smallville
  - django
  - environment-server
  - phaser
ai_summary: >-
  Hosts the Phaser map and templates. Bridge mode polls FastAPI for actor positions.
  Native mode reads reverie step files under frontend_server/storage/.
---

# `generative_agents/environment`

## Primary subtree

- **`frontend_server/`** — Django project with `manage.py`, Phaser templates, static map assets, and `translator` app (views, bridge).

## Related (not under environment/)

- **`../reverie/`** — classic `reverie.py` simulation server and persona code paths.
