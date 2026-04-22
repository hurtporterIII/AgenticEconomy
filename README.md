# AgenticEconomy

AgenticEconomy is a live multi-agent economic simulation where autonomous agents earn, steal, enforce rules, purchase intelligence via API calls, and settle value with USDC on Arc.

## What It Is

- Autonomous agent economy with `worker`, `thief`, `cop`, and `bank` entities.
- Economic loop where every valid value movement is priced and logged.
- AI-powered target selection with provider fallback routing.
- Arc settlement integration that returns verifiable `tx_hash` values for valid on-chain actions.
- User-driven agent spawning with explicit role selection and a single global total-agent cap.

## Demo Link

- Demo video: `ADD_YOUR_DEMO_LINK_HERE`

## How To Run

1. Backend dependencies (use the same interpreter as `start_smallville.ps1`):
```bash
C:\Python314\python.exe -m pip install -r backend/requirements.txt
```
Do not install `circle-sdk` for this project; backend runtime imports `circle.web3`, which is provided by `circle-developer-controlled-wallets`.
2. Configure environment in [`.env`](C:\Users\Admin\Desktop\HACKATHON\COmpatetion Folder\AgenticEconomy\.env):
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
- Keep all API keys in [`.env`](C:\Users\Admin\Desktop\HACKATHON\COmpatetion Folder\AgenticEconomy\.env) only.

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
- Every meaningful action produces a transaction attempt and event record with `tx_hash`.
- Full observability stack: event feed, metrics, story ticker, per-agent intent bars, regime narration, replay export.
- Interactive controls: spawn population, tune doctrine, force scenarios, change speed, export replay.

Core claim:

`Every decision has a price, that price changes behavior, and that behavior reshapes the economy in real time.`

See [Demo Script And Slide Notes](C:\Users\Admin\Desktop\HACKATHON\COmpatetion Folder\AgenticEconomy\docs\demo.md) for speaking flow.
