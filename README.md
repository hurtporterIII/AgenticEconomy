# AgenticEconomy

**Real Agent-to-Agent Micro-Economy on Arc Testnet**

Live simulation where autonomous AI agents earn, steal, buy/sell intelligence, recover value, and settle every action **on-chain** using real USDC on Arc testnet.

### Hackathon Compliance

| Requirement                        | Status   | Details |
|------------------------------------|----------|---------|
| Real per-action pricing <= $0.01   | ✅ Passed | Sub-cent in live runtime (`/api/compliance/status`) |
| 50+ real on-chain transactions     | ✅ Live   | Actively generating during demo (`real_tx_count`) |
| Arc + USDC settlement              | ✅ Passed | Fully implemented |
| Agent-to-agent economic loop       | ✅ Passed | Workers, thieves, cops, spies, bankers |

**Public Demo URL**  
-> [PASTE YOUR PUBLIC UI URL HERE]

### Quick Start

```powershell
# 1. Clone the repo
git clone https://github.com/hurtporterIII/AgenticEconomy.git
cd AgenticEconomy

# 2. Start the full system
powershell -ExecutionPolicy Bypass -File ".\start_smallville.ps1"
```

Open the simulation after startup:
- Use the Public Demo URL above.

### Stop the System

```powershell
powershell -ExecutionPolicy Bypass -File ".\stop_smallville.ps1"
```

### Key Features

- Dynamic spy intel marketplace (runtime-adjustable intel pricing)
- Real economic incentives and adaptive agent behavior
- On-chain settlement with Arc + USDC
- Live bank panel showing simulation state + on-chain transaction stream

### Margin Explanation

Traditional gas fees make high-frequency micro-transactions uneconomical because fee overhead can exceed the value being moved per action.

AgenticEconomy uses Arc + USDC settlement with sub-cent action pricing so each action can remain economically meaningful while still being verifiable on-chain.

### On-Chain Proof

- Explorer: [Arc Testnet Explorer](https://testnet.arcscan.app/)
