---
title: AgenticEconomy — project index
system: agentic-economy
tags:
  - navigation
  - backend
  - frontend
  - smallville
  - economy
ai_summary: >-
  Root navigation for the AgenticEconomy hackathon project. Backend simulation,
  movement, and economy logic live in backend/. Phaser UI lives in frontend/.
  Smallville bridge and legacy assets live in generative_agents/. Use this file
  to quickly route edits to the right folder.
---

# AgenticEconomy

## Quick map

- `backend/` — FastAPI endpoints, simulation loop, action queue, nano-economy.
- `frontend/` — Phaser/Vite app, dashboard cards, labels, counters.
- `generative_agents/` — Smallville Django bridge + map/static assets.
- `docs/` — architecture, demo notes, catalog docs.
- `config/` — constants and pricing/config rules.
- `wallet_setup/` — wallet scripts and provisioning helpers.

## High-value entry points

- API bootstrap: `backend/main.py`
- Main API routes: `backend/api/endpoints.py`
- Simulation loop: `backend/core/loop.py`
- Action queue engine: `backend/core/action_queue.py`
- Frontend runtime: `frontend/src/game.js`
- Card/UI renderer: `frontend/src/ui/dashboard.js`

## Operations scripts

- Start services: `start_smallville.ps1`
- Stop services: `stop_smallville.ps1`
- Health check: `health_smallville.ps1`
- Regenerate index/meta: `reindex_structure.ps1` (runs `generate_structure.py`)
