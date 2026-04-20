import random

from bank.bank import credit, debit


def steal_from_bank(thief, bank, state):
    balances = state.setdefault("balances", {})
    balances.setdefault(thief["id"], 0.0)
    balances.setdefault(bank["id"], 0.0)

    amount = random.choice([2, 5])
    amount = min(amount, balances[bank["id"]])

    tx_fee = debit(thief["id"], 0.002, None)
    tx_bank = debit(bank["id"], amount, None)
    tx_credit = credit(thief["id"], amount, None)

    state.setdefault("events", []).append(
        {
            "type": "steal_bank",
            "thief_id": thief["id"],
            "bank_id": bank["id"],
            "amount": amount,
            "tx_hash": tx_credit,
            "tx_steps": [tx_fee, tx_bank, tx_credit],
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return amount


def steal_from_agent(thief, target, state):
    balances = state.setdefault("balances", {})
    balances.setdefault(thief["id"], 0.0)
    balances.setdefault(target["id"], 0.0)

    amount = min(2, balances[target["id"]])
    tx_fee = debit(thief["id"], 0.002, None)
    tx_target = debit(target["id"], amount, None)
    tx_credit = credit(thief["id"], amount, None)

    state.setdefault("events", []).append(
        {
            "type": "steal_agent",
            "thief_id": thief["id"],
            "target_id": target["id"],
            "amount": amount,
            "tx_hash": tx_credit,
            "tx_steps": [tx_fee, tx_target, tx_credit],
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return amount
