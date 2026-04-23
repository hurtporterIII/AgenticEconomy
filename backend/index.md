---
title: Backend index
system: agentic-economy-backend
tags:
  - backend
  - fastapi
  - simulation
  - action-queue
  - economy
ai_summary: >-
  Backend service for simulation ticks, movement targets, and economy events.
  Most edits route to api/endpoints.py, core/loop.py, core/action_queue.py, and
  core/nano_economy.py.
---

# backend

## Core folders

- `api/` — HTTP routes (`/state`, `/step`, `/economy/health`, `/agents/*`).
- `core/` — loop, state, POIs/navmesh, action queue, nano-economy.
- `agents/` — worker/thief/cop/banker behavior handlers.
- `actions/` — action primitives used by agents.
- `tx/` — transaction submitters and Arc helpers.
- `bank/` — debit/credit engine and balances.
- `store/` — runtime JSON/JSONL artifacts.
- `services/` — model/oracle adapters.
- `utils/` — helper scripts/utilities.

## High-value files

- `main.py` — app creation + startup validation.
- `api/endpoints.py` — primary API and bridge payload assembly.
- `core/loop.py` — tick orchestration + movement target assignment.
- `core/action_queue.py` — event-to-action mapping + queue execution.
- `core/nano_economy.py` — spy/thief/cop economic flow and invariants.
