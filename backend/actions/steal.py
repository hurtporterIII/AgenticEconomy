import random

from bank.bank import credit, debit
from core.learning import cop_learn_response, thief_learn_bank_penalty

BANK_ROBBERY_BANK_SHARE = 0.4


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

    # Bank-protection rule: if a thief robs the bank, police confiscate ALL
    # thief liquid immediately. This is intentionally strict and visible.
    entities = state.setdefault("entities", {})
    cop = next(
        (ent for ent in entities.values() if isinstance(ent, dict) and ent.get("type") == "cop"),
        None,
    )
    cop_id = cop.get("id") if isinstance(cop, dict) else None
    confiscated = round(float(balances.get(thief["id"], 0.0) or 0.0), 6)
    if cop_id and confiscated > 0:
        bank_target = next(
            (
                ent for ent in entities.values()
                if isinstance(ent, dict) and ent.get("id") != bank.get("id") and ent.get("type") in {"bank", "banker"}
            ),
            None,
        ) or bank
        bank_target_id = bank_target.get("id") if isinstance(bank_target, dict) else bank.get("id")
        bank_share = round(confiscated * BANK_ROBBERY_BANK_SHARE, 6)
        cop_share = round(confiscated - bank_share, 6)
        tx_conf_debit = debit(thief["id"], confiscated, None)
        tx_bank_credit = credit(bank_target_id, bank_share, None) if bank_share > 0 else None
        tx_cop_credit = credit(cop_id, cop_share, None) if cop_share > 0 else None
        thief_learning = thief_learn_bank_penalty(state, thief["id"], confiscated)
        cop_learning = cop_learn_response(state, cop_id, reward=0.8, mode="bank_confiscation")
        state.setdefault("events", []).append(
            {
                "type": "bank_zone_confiscation",
                "thief_id": thief["id"],
                "cop_id": cop_id,
                "bank_id": bank_target_id,
                "amount": confiscated,
                "bank_share": bank_share,
                "cop_share": cop_share,
                "reason": "bank_robbery_immediate_confiscation",
                "payer": thief["id"],
                "payee": cop_id,
                "tx_hash": tx_cop_credit or tx_bank_credit,
                "tx_steps": [step for step in [tx_conf_debit, tx_bank_credit, tx_cop_credit] if step is not None],
                "learning": {
                    "thief": thief_learning,
                    "cop": cop_learning,
                },
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
