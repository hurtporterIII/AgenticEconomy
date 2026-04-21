# Demo

## 60-Second Spoken Pitch

`AgenticEconomy is a live system where autonomous agents work, steal, enforce, and pay for intelligence under real economic pressure.`

`Workers, thieves, cops, and banks each have independent behavior profiles, and even same-role agents are not clones.`

`At the macro level, population composition drives policy regimes: thief-heavy systems fall into decline, cop-heavy systems become a police state, and worker-heavy systems move toward growth.`

`Those regimes directly modify income, theft pressure, enforcement effectiveness, API cost, and fee behavior.`

`Every meaningful action emits a transaction-linked event with tx proof, and we track cost per action, success rate, and total spend in real time.`

`So this is not a toy demo; it is a controllable laboratory where priced decisions change behavior and behavior reshapes the economy, visibly and measurably.`

## One-Slide Opener (Talk Track)

Slide title:

`AgenticEconomy: Autonomous Agents Under Real Economic Pressure`

Slide bullets:

- `Autonomous roles with unique traits: worker / thief / cop / bank`
- `Population-driven regimes: decline, police_state, growth`
- `Priced actions with tx-linked event proof`
- `Live observability: metrics, narrative, replay`
- `Interactive control: spawn, tune doctrine, force scenarios`

Closing line for slide:

`AI decisions cost money, money changes behavior, and behavior reshapes the system.`

## Live Flow

1. Run backend:
```bash
python backend/main.py
```
2. Spawn custom mix of agents by role:
```bash
curl -X POST "http://127.0.0.1:8000/api/spawn?entity_type=cop&balance=1"
curl -X POST "http://127.0.0.1:8000/api/spawn?entity_type=worker&balance=5"
curl -X POST "http://127.0.0.1:8000/api/spawn?entity_type=thief&balance=2"
```
3. Show cap/status endpoint:
```bash
curl "http://127.0.0.1:8000/api/spawn/types"
```
4. Show event stream with:
- worker earning
- thief stealing (agent and bank)
- cop enforcement and paid intelligence calls
5. Point out `tx_hash` values per event.
6. Show transaction count from output.
7. Call out at least one real `0x...` Arc hash.

## Proof Script

Use this statement during demo:

`Each valid economic action settles using USDC on Arc. Invalid states are safely simulated to preserve engine continuity.`

## Demo Sequence For Judges

1. Baseline:
- Spawn balanced population and run normal flow.
2. Break:
- Increase thieves to force `decline`; show theft pressure and narrative shift.
3. Enforce:
- Increase cops to force `police_state`; show lower theft and worker compliance drag.
4. Optimize:
- Increase workers and tune doctrine to move toward `growth`.
5. Prove:
- Show `tx_hash`, `cost_per_action`, `success_rate`, and replay export.

## Example Proof Hashes

- `0x22bded4d28dbe09889724214f124b5972b6b51df8ed9f341e5a907011d85c65e`
- `0x566fade268170010cdb84327441a9feb54c5e304d97b415ded78420d6e320539`
