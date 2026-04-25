# AgenticEconomy

**Real-Time Agent-to-Agent Micro-Economy on Arc Testnet**

A live simulation where autonomous AI agents earn, steal, trade intelligence, recover assets, and settle every action **on-chain** using real USDC on Arc testnet.

### Hackathon Compliance

| Requirement                        | Status     | Details |
|------------------------------------|------------|-------|
| Real per-action pricing <= $0.01   | ✅ Passed   | Current: ~$0.00009 per action |
| 50+ real on-chain transactions     | ✅ Live    | Actively generating during demo |
| Arc + USDC settlement              | ✅ Passed   | Fully implemented |
| Agent-to-Agent economic loop       | ✅ Passed   | Workers, Thieves, Cops, Spies, Bankers |

### Live Demo Links

**Main Simulation (Watch Agents Move)**  
-> **http://127.0.0.1:8010/demo/bridge_smallville/0/2/**

**Compliance & Proof**  
-> **http://127.0.0.1:8000/api/compliance/status** (must show `compliant: true`)

**Recent On-Chain Transactions**  
-> **http://127.0.0.1:8000/api/tx/recent**

**Arc Testnet Explorer**  
-> **https://testnet.arcscan.app/**

### Quick Start

```powershell
# Start full stack
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"

# Stop
powershell -ExecutionPolicy Bypass -File ".\stop_smallville.ps1"
```

### Core Concept

Traditional blockchain gas fees make high-frequency micro-transactions uneconomical.  
**AgenticEconomy** proves that **real agent-driven commerce at sub-cent pricing** is possible using Arc + USDC.

Agents continuously:
- Generate value (Workers)
- Buy intel and steal (Thieves)
- Buy intel and recover (Cops)
- Sell intelligence (Spies)
- Settle everything on-chain

Every meaningful action has a transparent, priced, and on-chain financial consequence.

### Key Features

- Dynamic spy intel marketplace (price adjustable in real time)
- Real economic incentives and learning behaviors
- Full on-chain settlement visibility
- Live bank panel with both simulation + on-chain data
