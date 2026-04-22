---
title: Django templates — Phaser pages for Smallville
system: smallville-django
subfolders:
  - home
  - demo
  - landing
  - path_tester
  - persona_state
tags:
  - smallville
  - django-templates
  - phaser
ai_summary: >-
  home/ = live map (includes main_script for bridge + native). demo/ = compressed replay path.
  Other folders are utilities or persona introspection UIs.
---

# `templates`

| Folder | Purpose |
|--------|---------|
| **`home/`** | **Primary** Phaser map for `/simulator_home`, `/demo/bridge_smallville/...`, `/replay/bridge_smallville/...` |
| **`demo/`** | Phaser **compressed replay** (`demo.html` + `demo/main_script.html`) |
| `landing/` | Marketing / entry landing |
| `path_tester/` | Map path debugging tool |
| `persona_state/` | Persona introspection UI |
| `base.html` | Django base layout |

See **`home/index.md`** first for sprite movement issues.
