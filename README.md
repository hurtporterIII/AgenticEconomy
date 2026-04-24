# AgenticEconomy

AgenticEconomy is a live multi-agent economic simulation where autonomous agents earn, steal, enforce rules, purchase intelligence via API calls, and settle value with USDC on Arc.

## What It Is

- Autonomous agent economy with `worker`, `thief`, `cop`, and `bank` entities.
- Economic loop where every valid value movement is priced and logged.
- AI-powered target selection with provider fallback routing.
- Arc settlement integration that returns verifiable `tx_hash` values for valid on-chain actions.
- User-driven agent spawning with explicit role selection and a single global total-agent cap.

## Hackathon submission (lablab.ai — judges)

This section is written so a judge can decide quickly **what is already evidenced in-repo**, what to **verify live**, and what the **author still attaches** (video, screenshots) after the demo run is stable.

### What you are judging

- **Application of technology:** Circle nanopayments / developer-controlled wallets + Arc testnet USDC settlement, tied to a live multi-agent economy loop.
- **Presentation:** short demo video + clear README path to run and observe.
- **Business value:** many small economic actions per session at **sub-cent effective pricing** (see metrics below).
- **Originality:** hybrid simulation — high-frequency in-sim intents with **sampled or throttled real settlement** so agents keep moving when limits or gas apply.

### Requirements checklist (official themes)

| Requirement | Where to verify | Status in this repo |
|-------------|-----------------|---------------------|
| **Real per-action pricing (≤ $0.01)** | `GET http://127.0.0.1:8000/api/tx/diagnostics` → `metrics.cost_per_action` (also surfaced in the **Bank Panel** in bridge Smallville UI) | **Code + live endpoint.** Judges should capture one JSON response or screenshot during the demo. |
| **50+ on-chain transactions in demo** | Same diagnostics: `diagnostics.real_tx_count` (and explorer hashes from events / `last_tx_hash`) | **Mechanism in code; count is runtime.** Author will attach video + screenshot showing count ≥ 50 for the final submission cut. |
| **Transaction-flow video proof** | Author-hosted link (YouTube / Loom / Drive) | **Placeholder below** — add link when the program is stable. |
| **Margin explanation (why traditional gas fails)** | README subsection below | **Documented below.** |
| **Circle product feedback** | `docs/feedback.md` | **In repo** — expand with concrete API notes after your final run. |

### Demo video (you add this)

- **Demo video:** `ADD_YOUR_DEMO_LINK_HERE` (replace with public URL before submission)

**Suggested 90-second flow for recording:** (1) show `start_smallville.ps1` or running services, (2) open bridge map, (3) point at **Bank Panel** (balances + tx health), (4) hit **Start Scenario** / run until diagnostics show **50+** real txs, (5) paste one `tx_hash` into Arc explorer.

### Margin explanation (gas vs this model)

Traditional L1/L2 retail economics break when **every micro-action** pays a **full transaction fee** (or waits for fee markets). A town simulation may emit **hundreds to thousands** of value movements per minute across workers, intel sales, recoveries, and settlements. If each movement required a separate user-paid gas blob at typical testnet/mainnet **cents-to-dollars** scale, either (a) the simulation stops because agents cannot afford to act, or (b) you **batch/coalesce** and lose per-action pricing fidelity.

This project uses **Circle’s nanopayment-style flows on Arc (USDC)** so many intents can be priced near **sub-cent** levels while the runtime still **samples** or **throttles** how many become full on-chain writes when limits hit — see `SETTLEMENT_STRATEGY` and `/api/tx/diagnostics` for live behavior.

### How To Run

1. Backend dependencies (use the same interpreter as `start_smallville.ps1`):
```bash
C:\Python314\python.exe -m pip install -r backend/requirements.txt
```
On other machines, use your Python 3.11+ binary instead of `C:\Python314\python.exe`.

Do not install `circle-sdk` for this project; backend runtime imports `circle.web3`, which is provided by `circle-developer-controlled-wallets`.
2. Configure environment in repo-root `.env` (create from your secrets; never commit the file):
```env
CIRCLE_API_KEY=...
CIRCLE_ENTITY_SECRET=...
CIRCLE_WALLET_ADDRESS=...
USDC_DESTINATION_ADDRESS=...
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
```
3. Run backend demo loop:
```bash
python backend/main.py
```
4. Optional frontend:
```bash
cd frontend
npm install
npm run dev
```

## Fast Ops Commands (Recommended)

Use these scripts from the repository root to avoid manual startup drift.

1. Start backend + Smallville bridge frontend + open map:
```powershell
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"
```
   By default the backend **loads repo `.env` with override** so keys are not shadowed by empty shell vars. For a **zero-keys motion demo** that forces simulated settlement, use `-SimOnly` (sets `AGENTIC_SIM_ONLY` for the backend process):
```powershell
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1" -SimOnly
```
   The Vite UI shows **SIMULATION / SETUP REQUIRED / LIVE** in the top bar, driven by `/api/tx/diagnostics`.

   **Smooth bridge motion:** `start_smallville.ps1` starts FastAPI with a background **auto-tick** (`AUTO_TICK_MS`, default 100ms in `backend/main.py`) and sets `SMALLVILLE_BRIDGE_STEP_ON_POLL=0` on Django. The browser only **reads** actor positions; it does not advance the sim on every poll. That avoids double-stepping and removes the stop–start jerkiness you get when every HTTP poll also calls `/api/step`. If you use a different backend without auto-tick, set `SMALLVILLE_BRIDGE_STEP_ON_POLL=1` when running `manage.py`.

2. Verify full health (API + bridge + frontend + movement signal):
```powershell
powershell -ExecutionPolicy Bypass -File ".\health_smallville.ps1"
```

3. Stop both services (ports `8000` and `8010`):
```powershell
powershell -ExecutionPolicy Bypass -File ".\stop_smallville.ps1"
```

4. Rebuild all `index.md` and `.meta.json` files:
```powershell
powershell -ExecutionPolicy Bypass -File ".\reindex_structure.ps1"
```

Notes:
- Do not run manual `uvicorn` / `manage.py` commands in parallel shells unless debugging.
- Keep all API keys in repo-root `.env` only (never commit `.env`).

## Legacy Command Compatibility (Phase 1/2)

When moving from old Smallville operator commands to the new API setup, use:

- `POST /api/legacy/command`

Single command example:

```bash
curl -X POST "http://127.0.0.1:8000/api/legacy/command" ^
  -H "Content-Type: application/json" ^
  -d "{\"command\":\"run 10\"}"
```

Batch example:

```bash
curl -X POST "http://127.0.0.1:8000/api/legacy/command" ^
  -H "Content-Type: application/json" ^
  -d "{\"commands\":[\"state\",\"spawn worker balance=5\",\"run 3\"]}"
```

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

Read-only legacy helper endpoints:

- `GET /api/legacy/time`
- `GET /api/legacy/persona/{persona_id}/schedule`
- `GET /api/legacy/persona/schedules`
- `GET /api/legacy/persona/{persona_id}/tile`
- `GET /api/legacy/tile/events?x=<tile_x>&y=<tile_y>&limit=80`

See [`docs/migration-command-map.md`](docs/migration-command-map.md) for the full old->new mapping and planned command coverage.

## Smallville-First Mode (Recommended Build Order)

Run native Generative Agents first, then evolve with the economy bridge.

1. Start Smallville environment server:
```bash
cd generative_agents/environment/frontend_server
set SMALLVILLE_MODE=native
python manage.py runserver 127.0.0.1:8010
```
2. Start Generative Agents simulation server:
```bash
cd generative_agents/reverie/backend_server
set OPENAI_API_KEY=YOUR_OPENAI_KEY
python reverie.py
```
3. In the `reverie.py` prompt:
```text
forked simulation: base_the_ville_n25
new simulation: your_sim_name
option: run 100
```
4. Open:
```text
http://127.0.0.1:8010/simulator_home
```

Bridge mode is optional for later evolution:
```bash
set SMALLVILLE_MODE=bridge
```

## Agent Spawning And Cap

- Players can add agents dynamically through `POST /api/spawn`.
- Player selects the role via `entity_type` (`worker`, `thief`, `cop`, `banker`, `bank`).
- `entity_id` is optional; if omitted, the system auto-generates IDs like `cop_1`, `worker_2`.
- One global cap applies across all roles using `MAX_TOTAL_AGENTS` (default `200`).
- On cap reached, API returns `409` with a clear message.

Example spawn calls:

```bash
curl -X POST "http://127.0.0.1:8000/api/spawn?entity_type=cop&balance=1"
curl -X POST "http://127.0.0.1:8000/api/spawn?entity_type=thief&entity_id=thief_alpha&balance=2"
curl "http://127.0.0.1:8000/api/spawn/types"
```

## Arc + USDC Explanation

- Valid economic actions settle on-chain using USDC on Arc through Circle developer-controlled wallet APIs.
- Non-economic or invalid actions (for example `amount <= 0`) and insufficient-balance paths fall back to simulated hashes to keep the system stable.
- This hybrid approach demonstrates real settlement while preserving high-frequency agent loop continuity.

## Transaction Proof

Example real transaction hashes produced in-system:

- `0x566fade268170010cdb84327441a9feb54c5e304d97b415ded78420d6e320539`
- `0x9dafa13063f9e6f601a8c2adcab2e2f39d75289d07d289e62b5f430b78daca53`
- `0x006727621b1b2772743b9ca0e6a95a0a2660af89c73c362bf57233125827c24d`

Standalone Arc proof transaction:

- `0x22bded4d28dbe09889724214f124b5972b6b51df8ed9f341e5a907011d85c65e`
- Explorer: [Arcscan](https://testnet.arcscan.app/tx/0x22bded4d28dbe09889724214f124b5972b6b51df8ed9f341e5a907011d85c65e)

## Demo Narrative

Use this line during judging:

`Agents operate autonomously, earn and spend value, and settle valid transactions on-chain using USDC on Arc, with fallback handling for invalid states.`

## Judges Summary

AgenticEconomy is a real-time, AI-driven economic simulation where autonomous agents transact using sub-cent micropayments under dynamic policy regimes, with full visual, narrative, and transactional proof.

What judges can verify live:

- Autonomous roles: workers, thieves, cops, banker/bank.
- Trait-based individuality: same-role agents are not clones.
- Policy-to-behavior loop: `decline`, `police_state`, `growth`, `balanced`, `bootstrapping`.
- Economic actions produce transaction attempts; real Arc settlement returns verifiable `tx_hash` where the rail succeeds (see `/api/tx/diagnostics` for live vs simulated counts).
- **Bridge Smallville UI:** per-persona cards, **Bank Panel** (worker/cop ledger + virtual totals + tx health), **Reset Economy**, **Start Scenario** demo helper.
- Optional Vite dashboard (`frontend/`) for richer charts when running `npm run dev`.

Core claim:

`Every decision has a price, that price changes behavior, and that behavior reshapes the economy in real time.`

See [Demo script and slide notes](docs/demo.md) for speaking flow (expand with your final narration).

### Product feedback (Circle / hackathon form)

Structured notes live in [`docs/feedback.md`](docs/feedback.md). Before you submit, add a short section with **what you liked**, **what was confusing**, and **one concrete API or docs improvement** from your integration experience — that is the kind of detail hackathon organizers reuse.
