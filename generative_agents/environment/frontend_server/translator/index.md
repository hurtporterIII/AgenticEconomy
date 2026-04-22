---
title: translator app — bridge + HTTP APIs for Phaser
system: smallville-django
django_app: translator
key_modules:
  - views.py
tags:
  - smallville
  - django-views
  - bridge
  - json
  - movement
ai_summary: >-
  Django views glue the Phaser client to either reverie storage files or the FastAPI bridge.
  Bridge mode uses sim_code bridge_smallville, fetches GET SMALLVILLE_BRIDGE_URL, optionally POSTs /api/step,
  and serves persona positions as pixel coordinates. update_environment returns JsonResponse for Phaser polling.
---

# `translator` (Django app)

## Read first

- **`views.py`** — all bridge constants, `_bridge_fetch`, `_bridge_update_payload`, `update_environment`, `demo`, `home`, `replay`.

## Environment variables (bridge)

| Variable | Effect |
|----------|--------|
| `SMALLVILLE_MODE` | `bridge` enables bridge paths; otherwise native reverie file mode |
| `SMALLVILLE_BRIDGE_URL` | Primary JSON source (`/api/bridge/smallville` on FastAPI) |
| `SMALLVILLE_BRIDGE_FALLBACK_URL` | Secondary JSON source |
| `SMALLVILLE_BRIDGE_STEP_ON_POLL` | When `1`, POST `/api/step` on each poll (see `_bridge_step_once`) |

## HTTP surface (see `frontend_server/urls.py`)

| Route | View | Notes |
|-------|------|-------|
| `/simulator_home` | `home` | Native: needs temp step files; Bridge: redirects to `/demo/bridge_smallville/0/2/` when enabled |
| `/demo/<sim>/<step>/<speed>/` | `demo` | **`bridge_smallville` uses `templates/home/home.html`** (not `demo/demo.html`) |
| `/replay/<sim>/<step>/` | `replay` | Same bridge exception as demo |
| `/update_environment/` | `update_environment` | **Phaser polling** — returns `_bridge_update_payload` JSON in bridge mode |

## Bridge actor JSON → Phaser persona dict

`_bridge_update_payload` maps each actor to:

- `movement`: current pixel `[x, y]`
- `dest_x` / `dest_y`: **must align with backend target** (see comments in `views.py`; avoids “walk past” fighting)

Downstream Phaser: `templates/home/main_script.html` (`bridge_mode` branch).
