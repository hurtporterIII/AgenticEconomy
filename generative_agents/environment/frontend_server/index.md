---
title: frontend_server — Django + Phaser Smallville
system: smallville-django
manage_py: generative_agents/environment/frontend_server/manage.py
default_ports:
  django_classic: 8000
  agentic_launcher: 8010
tags:
  - smallville
  - django
  - phaser
  - static-files
ai_summary: >-
  Django app that renders the map. translator/views.py implements bridge vs native data sources.
  URLs in frontend_server/urls.py. Phaser game logic lives in templates/home/main_script.html (simulate/replay/bridge)
  or templates/demo/main_script.html (compressed replay with full movement JSON).
---

# `frontend_server`

## Start

From this directory (see repo `start_smallville.ps1` for exact env vars):

```text
python manage.py runserver 127.0.0.1:8010
```

## High-signal folders

| Path | Purpose |
|------|---------|
| `translator/views.py` | Bridge fetch (`GET` JSON), `update_environment` JSON for Phaser polling, `demo` / `home` / `replay` |
| `frontend_server/urls.py` | Routes: `/simulator_home`, `/demo/...`, `/replay/...`, `/update_environment/` |
| `templates/home/` | **Live map** (`home.html` includes `main_script.html`) — bridge + native simulate |
| `templates/demo/` | **Compressed replay** (`demo.html` + `main_script.html`) |
| `static_dirs/assets/the_ville/` | Matrix + visuals + spritesheets |
| `storage/` | Per-simulation native outputs (when not using bridge-only) |
| `temp_storage/` | Current sim pointer files |

## Downstream indexes

- `translator/index.md`
- `templates/home/index.md`
- `templates/demo/index.md`
- `static_dirs/assets/the_ville/index.md`
