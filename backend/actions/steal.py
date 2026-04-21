import random

from bank.bank import credit, debit


def steal_from_bank(thief, bank, state, steal_amount=None, fee_cost=0.002):
    balances = state.setdefault("balances", {})
    balances.setdefault(thief["id"], 0.0)
    balances.setdefault(bank["id"], 0.0)
    regime = state.setdefault("economy", {}).get("regime", "balanced")

    amount = random.choice([2, 5]) if steal_amount is None else float(steal_amount)
    amount = min(amount, balances[bank["id"]])
    amount = round(max(0.0, amount), 6)

    tx_fee = debit(thief["id"], fee_cost, None)
    tx_bank = None
    tx_credit = None
    if amount > 0:
        tx_bank = debit(bank["id"], amount, None)
        tx_credit = credit(thief["id"], amount, None)

    state.setdefault("events", []).append(
        {
            "type": "steal_bank",
            "thief_id": thief["id"],
            "bank_id": bank["id"],
            "amount": amount,
            "fee_cost": fee_cost,
            "regime": regime,
            "tx_hash": tx_credit,
            "tx_steps": [step for step in [tx_fee, tx_bank, tx_credit] if step is not None],
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return amount


def steal_from_agent(thief, target, state, steal_amount=None, fee_cost=0.002):
    balances = state.setdefault("balances", {})
    balances.setdefault(thief["id"], 0.0)
    balances.setdefault(target["id"], 0.0)
    regime = state.setdefault("economy", {}).get("regime", "balanced")

    desired_amount = 2 if steal_amount is None else float(steal_amount)
    amount = min(desired_amount, balances[target["id"]])
    amount = round(max(0.0, amount), 6)
    tx_fee = debit(thief["id"], fee_cost, None)
    tx_target = None
    tx_credit = None
    if amount > 0:
        tx_target = debit(target["id"], amount, None)
        tx_credit = credit(thief["id"], amount, None)

    state.setdefault("events", []).append(
        {
            "type": "steal_agent",
            "thief_id": thief["id"],
            "target_id": target["id"],
            "amount": amount,
            "fee_cost": fee_cost,
            "regime": regime,
            "tx_hash": tx_credit,
            "tx_steps": [step for step in [tx_fee, tx_target, tx_credit] if step is not None],
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return amount
