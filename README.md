# AgenticEconomy (Arc + USDC Hackathon Build)

AgenticEconomy is a live multi-agent economy where agents earn, steal, buy intel, and settle value on Arc testnet in USDC.

## For Judges (Start Here)

This section is intentionally short so you can verify requirements quickly.

### 1) Start the system

```powershell
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"
```

### 2) Open the live demo

- Bridge UI: `http://127.0.0.1:8010/demo/bridge_smallville/0/2/`

### 3) Verify compliance in under 30 seconds

- Compliance endpoint: `http://127.0.0.1:8000/api/compliance/status`
  - Must show: `compliant: true`
  - Must show: `real_tx_count >= 50`
  - Must show: `cost_per_action <= 0.01`

- Diagnostics endpoint: `http://127.0.0.1:8000/api/tx/diagnostics`
  - Must show: `diagnostics.last_mode: "real"`
  - Must show real tx hash values

### 4) Verify on Arc explorer

- Copy any hash from diagnostics and open:
  - `https://testnet.arcscan.app/tx/<tx_hash>`

---

## Hackathon Fit

Primary track alignment:
- Agent-to-Agent Payment Loop

Also matches:
- Per-API Monetization Engine
- Usage-Based Compute Billing

Why:
- Thief and cop both pay spy for intel (priced per action).
- Every valid settlement intent is priced in USDC and pushed through Arc settlement flow.
- Cost/action is measured live and kept sub-cent.

---

## Requirements Mapping

| Hackathon requirement | Where to verify | Status |
|---|---|---|
| Real per-action pricing (`<= $0.01`) | `GET /api/compliance/status` (`cost_per_action`) | Implemented + live |
| 50+ onchain transactions in demo | `GET /api/compliance/status` (`real_tx_count`) | Implemented + live |
| Show transaction frequency data | `GET /api/tx/diagnostics` + Bank Panel in UI | Implemented + live |
| Explain why gas-heavy model fails | See "Margin explanation" below | Implemented |
| Arc + USDC settlement | `GET /api/tx/diagnostics` (`last_mode`, `last_tx_hash`) | Implemented + live |

---

## What The Software Does

There are 6 core roles in the demo baseline:
- `worker` earns and stores value
- `thief` buys intel and steals
- `cop` buys intel and recovers funds
- `spy` sells information (intel market)
- `banker` policy/economic pressure role
- `bank` settlement sink/treasury role

Core economic loop:
1. Worker generates activity and value.
2. Spy creates intel.
3. Thief pays spy for intel, then executes theft.
4. Spy emits theft intel.
5. Cop pays spy for intel, then executes recovery/redistribution.
6. Settlement pipeline submits real Arc USDC transactions.

---

## Margin Explanation (Why This Model)

If every micro-action paid normal gas-heavy costs directly, high-frequency agent actions become uneconomical fast. This system keeps per-action pricing viable by:
- pricing every action in very small USDC amounts,
- keeping the simulation continuous,
- and settling through Arc/Circle flow with live cost/action tracking.

Result: economically meaningful per-action behavior with sub-cent measured action cost.

---

## Quick Runbook

### Start

```powershell
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"
```

### Stop

```powershell
powershell -ExecutionPolicy Bypass -File ".\stop_smallville.ps1"
```

### Health check

```powershell
powershell -ExecutionPolicy Bypass -File ".\health_smallville.ps1"
```

---

## Key API Endpoints

- `GET /api/compliance/status`
- `GET /api/tx/diagnostics`
- `GET /api/tx/recent?page=1&page_size=10&max_records=50`
- `GET /api/economy/health`
- `POST /api/demo/reset-economy`
- `POST /api/demo/force-cop-cycle`
- `GET /api/bridge/smallville`

Spy pricing (hackathon-safe runtime control):
- `GET /api/spy/price`
- `POST /api/spy/price?value=<number>`
  - clamped to `0.000001` ... `0.01`

---

## Judge-Friendly Demo Script (90 Seconds)

1. Open Bridge UI.
2. Show agents moving and bank panel updating.
3. Open `/api/compliance/status` and point to:
   - `compliant: true`
   - `real_tx_count >= 50`
   - `cost_per_action <= 0.01`
4. Open `/api/tx/diagnostics` and show real mode + tx hash.
5. Open one tx hash in Arcscan.

---

## Notes

- If `/api/spy/price` returns 404, restart backend (old process still running).
- Use the tagged checkpoint for this demo state:
  - `demo-ready-2026-04-24`
