# AgenticEconomy

AgenticEconomy is a live multi-agent economic simulation on Arc testnet using USDC settlement.  
Agents earn, steal, buy information, enforce recovery, and settle value per action.

## Overview

This project models a high-frequency, agent-driven economy where every meaningful action has a price and a financial consequence.

Core roles:
- `worker`: earns and stores value.
- `thief`: buys intel and executes theft.
- `cop`: buys intel and executes recovery.
- `spy`: sells intel to other agents.
- `banker` and `bank`: provide system-level settlement and liquidity behavior.

Core loop:
1. Workers generate value.
2. Spy creates actionable intel.
3. Thief pays spy for intel, then steals.
4. Spy creates theft intel.
5. Cop pays spy for intel, then recovers and redistributes.
6. Settlement pipeline pushes valid intents on-chain on Arc in USDC.

---

## Quick Start

Start the full stack:

```powershell
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"
```

Open demo UI:

- `http://127.0.0.1:8010/demo/bridge_smallville/0/2/`

Stop services:

```powershell
powershell -ExecutionPolicy Bypass -File ".\stop_smallville.ps1"
```

Optional health check:

```powershell
powershell -ExecutionPolicy Bypass -File ".\health_smallville.ps1"
```

---

## Live Verification

Compliance and transaction metrics:
- `GET http://127.0.0.1:8000/api/compliance/status`
- `GET http://127.0.0.1:8000/api/tx/diagnostics`
- `GET http://127.0.0.1:8000/api/economy/health`
- `GET http://127.0.0.1:8000/api/tx/recent?page=1&page_size=10&max_records=50`

Arc explorer:
- Copy any tx hash from diagnostics and open:
- `https://testnet.arcscan.app/tx/<tx_hash>`

---

## Why This Works

The architecture is built for high-frequency micro-economics:
- Information-gated actions: thief and cop actions are paid and data-driven through the spy market.
- Per-action accounting: each economic action produces priced intents and measurable cost/action.
- Real settlement rail: valid intents settle on Arc testnet in USDC with verifiable hashes.
- Stability under load: simulation loop remains continuous while settlement is managed by strategy controls.

This gives both behavioral realism (agents react to incentives) and measurable economic proof (live transaction and pricing data).

---

## Why Normal Gas Economics Break This

This system emits many small, frequent value movements.  
With a traditional gas-heavy model, per-action fees can exceed or distort the action value itself.

What breaks in a normal gas environment:
- Micro-actions become uneconomic when fixed fee overhead dominates tiny transfers.
- High-frequency behavior must be batched to reduce fees, which destroys true per-action pricing fidelity.
- If not batched, agent strategies collapse because cost noise overwhelms signal.

Why this implementation remains viable:
- Actions are priced at sub-cent levels.
- Cost per action is tracked directly and enforced operationally through runtime checks.
- Arc + USDC settlement provides verifiable on-chain execution while preserving usable micro-transaction economics.

---

## API Surface

Core demo endpoints:
- `GET /api/bridge/smallville`
- `POST /api/demo/reset-economy`
- `POST /api/demo/force-cop-cycle`
- `GET /api/compliance/status`
- `GET /api/tx/diagnostics`
- `GET /api/tx/recent`
- `GET /api/economy/health`

Spy pricing control (runtime, clamped for safety):
- `GET /api/spy/price`
- `POST /api/spy/price?value=<number>`
- Allowed range: `0.000001` to `0.01`

---

## Current Demo Checkpoint

Tagged checkpoint for stable demo state:
- `demo-ready-2026-04-24`
