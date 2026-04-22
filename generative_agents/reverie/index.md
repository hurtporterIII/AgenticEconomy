---
title: reverie — classic generative-agents simulation server
system: reverie
entrypoint: backend_server/reverie.py
tags:
  - reverie
  - smallville
  - simulation-server
  - python
ai_summary: >-
  Original Stanford stack: run reverie.py to step personas and write movement JSON consumed by Django
  templates/home in native mode. AgenticEconomy bridge mode bypasses most of this for live actors but
  the folder remains for prompts, persona modules, and compression utilities.
---

# `generative_agents/reverie`

## When you still need this

- **Native Smallville loop** — `reverie.py` + `environment/frontend_server/storage/<sim>/movement/*.json`
- **Prompt templates / persona cognition** — `backend_server/persona/`
- **Compress simulations for demo** — `compress_sim_storage.py`

## Bridge note

If you only run **`SMALLVILLE_MODE=bridge`**, day-to-day sprite work is usually in **`environment/frontend_server/`** + FastAPI `GET /api/bridge/smallville`, not here.

Child index: `backend_server/index.md`
