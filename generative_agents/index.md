---
title: Generative Agents / Smallville — navigation hub
system: generative-agents
smallville_modes: [native-reverie, django-bridge]
tags:
  - smallville
  - generative-agents
  - navigation
  - phaser
  - django
  - bridge
ai_summary: >-
  Entry map for Stanford Generative Agents code in this repo. Smallville visuals run from
  environment/frontend_server (Django + Phaser). Agent cognition lives under reverie/backend_server.
  AgenticEconomy drives live entities via FastAPI; Django bridge reads /api/bridge/smallville.
---

# Generative Agents workspace

Use this file as a **top-down index** when editing sprites, movement, or the Django bridge.

## Quick paths (most work happens here)

| Goal | Go here |
|------|---------|
| **Live bridge map** (Phaser, `sim_code == bridge_smallville`) | `environment/frontend_server/templates/home/main_script.html` + `translator/views.py` |
| **Compressed replay demo** (all movement preloaded) | `environment/frontend_server/templates/demo/main_script.html` + `translator/views.py` → `demo()` |
| **Django routes** | `environment/frontend_server/frontend_server/urls.py` |
| **Map collision / matrix / tile art** | `environment/frontend_server/static_dirs/assets/the_ville/` |
| **Original reverie simulator** | `reverie/backend_server/` |

## Runtime wiring (AgenticEconomy)

- FastAPI bridge JSON: `backend/api/endpoints.py` → `GET /api/bridge/smallville`
- Repo launcher: `start_smallville.ps1` sets `SMALLVILLE_MODE=bridge`, `SMALLVILLE_BRIDGE_URL`, and starts Django on port **8010** (see script).

## Child indexes

- `environment/index.md` — Django env server subtree
- `environment/frontend_server/index.md` — `manage.py`, static, templates
