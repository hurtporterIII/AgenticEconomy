import math


MINE_ZONE = (2032.0, 1524.0)
MINE_WORK_RADIUS = 180.0


def handle_worker(worker, state):
    """
    Executes worker behavior
    """
    from bank.bank import credit, debit
    from utils.helpers import choose_action, reinforce_action

    balances = state.setdefault("balances", {})
    balances.setdefault(worker["id"], 0.0)

    personality = worker.setdefault("personality", {})
    effort = float(personality.get("effort", 0.6))
    efficiency = float(personality.get("efficiency", 0.55))
    reliability = float(personality.get("reliability", 0.7))

    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    worker_income_multiplier = float(multipliers.get("worker_income", 1.0))
    worker_tax_rate = float(multipliers.get("worker_tax", 0.0))
    regime = economy.get("regime", "balanced")

    cost = round(0.0015 + effort * 0.0025, 6)
    base_reward = round(3.0 + effort * 2.5 + efficiency * 2.5, 6)
    reward = round(base_reward * worker_income_multiplier, 6)
    tax_amount = round(reward * worker_tax_rate, 6)
    balance = float(balances.get(worker["id"], 0.0))
    banks = [entity for entity in state.setdefault("entities", {}).values() if entity.get("type") == "bank"]
    support_possible = bool(banks)

    action_utilities = {
        "work": ((reward - cost - tax_amount) / max(1.0, base_reward)) + (reliability - 0.5) * 0.2,
        "idle": 0.08 if balance > 2.0 else -0.35,
        "request_support": 0.55 if (balance < 1.0 and support_possible) else -0.45,
    }
    action, action_weights = choose_action(worker, action_utilities, state=state, role="worker")

    if action == "work":
        wx = float(worker.get("x", 0.0) or 0.0)
        wy = float(worker.get("y", 0.0) or 0.0)
        mine_distance = math.hypot(wx - MINE_ZONE[0], wy - MINE_ZONE[1])
        if mine_distance > MINE_WORK_RADIUS:
            # Workers only earn while physically at the mine/work zone.
            worker["top_action"] = "commute_mine"
            worker["work_route"] = "to_mine"
            reinforce_action(
                worker,
                "idle",
                -0.05,
                state=state,
                role="worker",
                context={"regime": regime, "reason": "not_at_mine", "distance": round(mine_distance, 2)},
            )
            state.setdefault("events", []).append(
                {
                    "type": "worker_commute_mine",
                    "worker_id": worker["id"],
                    "distance_to_mine": round(mine_distance, 2),
                    "regime": regime,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return

        fee_tx = debit(worker["id"], cost, None)
        reward_tx = credit(worker["id"], reward, None)
        tax_tx = None
        if tax_amount > 0:
            tax_tx = debit(worker["id"], tax_amount, None)
        worker["haul_mode"] = "return_home"
        worker["work_route"] = "to_home"
        worker["top_action"] = "return_home"
        net_gain = reward - cost - tax_amount
        reinforce_action(
            worker,
            "work",
            net_gain / max(1.0, reward),
            state=state,
            role="worker",
            context={"regime": regime, "cost": cost, "reward": reward, "tax": tax_amount},
        )
        state.setdefault("events", []).append(
            {
                "type": "worker_earn",
                "worker_id": worker["id"],
                "cost": cost,
                "base_reward": base_reward,
                "reward": reward,
                "worker_tax": tax_amount,
                "regime": regime,
                "action": action,
                "action_weights": action_weights,
                "regime_multipliers": {"worker_income": worker_income_multiplier, "worker_tax": worker_tax_rate},
                "personality": {
                    "effort": effort,
                    "efficiency": efficiency,
                    "reliability": reliability,
                },
                "tx_hash": reward_tx,
                "tx_steps": [fee_tx, reward_tx] + ([tax_tx] if tax_tx else []),
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    if action == "request_support" and support_possible:
        bank = max(banks, key=lambda entity: float(balances.get(entity.get("id"), 0.0)))
        bank_id = bank.get("id")
        balances.setdefault(bank_id, 0.0)
        needed = max(0.0, 1.0 - balance)
        support_amount = round(min(needed, max(0.0, balances[bank_id] * 0.08)), 6)
        if support_amount > 0:
            tx_debit = debit(bank_id, support_amount, None)
            tx_credit = credit(worker["id"], support_amount, None)
            reinforce_action(
                worker,
                "request_support",
                0.35,
                state=state,
                role="worker",
                context={"regime": regime, "support_amount": support_amount, "bank_id": bank_id},
            )
            state.setdefault("events", []).append(
                {
                    "type": "worker_support_received",
                    "worker_id": worker["id"],
                    "bank_id": bank_id,
                    "amount": support_amount,
                    "action": action,
                    "action_weights": action_weights,
                    "regime": regime,
                    "tx_hash": tx_credit,
                    "tx_steps": [tx_debit, tx_credit],
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return
        reinforce_action(
            worker,
            "request_support",
            -0.2,
            state=state,
            role="worker",
            context={"regime": regime, "support_amount": 0},
        )

    reinforce_action(
        worker,
        "idle",
        0.05 if balance > 1.0 else -0.1,
        state=state,
        role="worker",
        context={"regime": regime, "balance": balance},
    )
    state.setdefault("events", []).append(
        {
            "type": "worker_idle",
            "worker_id": worker["id"],
            "reason": "policy_choice",
            "action": action,
            "action_weights": action_weights,
            "regime": regime,
            "network": "Arc",
            "asset": "USDC",
        }
    )
