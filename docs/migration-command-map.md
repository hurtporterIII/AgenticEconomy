# Smallville Command Migration Map

This document tracks the old Smallville operator commands against the new AgenticEconomy API surface.

Status labels:
- `ported`: implemented in the new API already
- `shimmed`: available via compatibility endpoint
- `planned`: intentionally deferred
- `not_supported`: no mapped behavior yet

## Compatibility Endpoint

- Endpoint: `POST /api/legacy/command`
- Accepts either:
  - single: `{"command":"run 10"}`
  - batch: `{"commands":["state","spawn worker balance=5","run 3"]}`

Current shimmed commands:
- `state`
- `step`
- `run <n>` (clamped to 500)
- `spawn <type> [entity_id=...] [balance=...]`
- `spawn types`
- `print current time`
- `print persona schedule <persona_id>`
- `print all persona schedule`
- `print persona current tile <persona_id>`
- `print tile event <x>, <y>`

Direct read endpoints added for tooling:
- `GET /api/legacy/time`
- `GET /api/legacy/persona/{persona_id}/schedule`
- `GET /api/legacy/persona/schedules`
- `GET /api/legacy/persona/{persona_id}/tile`
- `GET /api/legacy/tile/events?x=<tile_x>&y=<tile_y>&limit=80`

## Old -> New Command Mapping

| Old command / route | New command / endpoint | Status | Notes |
|---|---|---|---|
| `run <n>` | `POST /api/legacy/command` with `{"command":"run <n>"}` | `shimmed` | Executes `step` repeatedly. |
| `step` (operator intent) | `POST /api/step` | `ported` | Also available via legacy shim. |
| `state` / `get state` | `GET /api/state` | `ported` | Also available via legacy shim. |
| `spawn ...` (operator intent) | `POST /api/spawn` | `ported` | Legacy shim parses simplified text form. |
| `spawn types` | `GET /api/spawn/types` | `ported` | Also available via legacy shim. |
| `print persona schedule <name>` | `POST /api/legacy/command` or `GET /api/legacy/persona/{persona_id}/schedule` | `shimmed` | Uses current action + target-derived schedule summary. |
| `print all persona schedule` | `POST /api/legacy/command` or `GET /api/legacy/persona/schedules` | `shimmed` | Returns schedule summaries for all entities. |
| `print persona current tile <name>` | `POST /api/legacy/command` or `GET /api/legacy/persona/{persona_id}/tile` | `shimmed` | Tile is computed via backend navmesh world->tile conversion. |
| `print tile event x, y` | `POST /api/legacy/command` or `GET /api/legacy/tile/events` | `shimmed` | Filters recent events using event coords and associated entity tile matches. |
| `print current time` | `POST /api/legacy/command` or `GET /api/legacy/time` | `shimmed` | Returns simulation tick + UTC timestamp. |
| `save` / `finish` | TBD save/export endpoint | `planned` | Phase 3 target. |
| `/path_tester/` flows | TBD compatibility strategy | `planned` | May be retained in Django stack first. |

## Non-goals (this phase)

- No rewrites of existing FastAPI command endpoints.
- No removal of Django bridge routes.
- No behavior changes to the running simulation loop.
