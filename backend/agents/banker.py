"""
Banker agent.

Spatial behavior (roam / snap-to-desk when a customer is in B12) is driven
from backend/core/loop.py and is NOT affected by the feature flag below.
This file implements the banker's *economic* policy actions.

FEATURE FLAGS
    Balance-mutating actions (collect_fees / anti_hoard_levy /
    redistribute) are gated by core.flags.banker_economics_enabled(),
    which itself is False unless BOTH:
        - NON_WORKER_ECONOMICS=on  (master flag)
        - BANKER_ECONOMIC_ACTIONS=on  (per-agent override)

    When disabled, the banker still tracks its policy state and emits
    a `banker_economy_disabled` audit event on the skipped tick. No
    balances move, no bank_fee_cycle / bank_anti_hoard_levy /
    bank_redistribution events are produced.

    This exists because the nano-purchasing worker loop
    (EARN == DEPOSIT + HOME, 0.0001 == 0.00001 + 0.00009) requires the
    worker's liquid balance to survive between bank and home. Any
    autonomous skim breaks the invariant and the stash never fires.
"""

from core.flags import banker_economics_enabled


def handle_bank(bank, state):
    """
    Bank management logic.
    """
    from bank.bank import credit, debit
    from utils.helpers import choose_action, reinforce_action

    personality = bank.setdefault("personality", {})
    strictness = float(personality.get("strictness", 0.5))
    liquidity_bias = float(personality.get("liquidity_bias", 0.6))
    generosity = float(personality.get("generosity", 0.35))
    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    bank_fee_multiplier = float(multipliers.get("bank_fee", 1.0))
    regime = economy.get("regime", "balanced")

    entities = state.setdefault("entities", {})
    balances = state.setdefault("balances", {})
    balances.setdefault(bank["id"], 0.0)
    bank_balance = float(balances.get(bank["id"], 0.0))

    participant_ids = [
        entity.get("id")
        for entity in entities.values()
        if entity.get("id") and entity.get("id") != bank["id"] and entity.get("type") != "bank"
    ]
    participant_balances = [float(balances.get(entity_id, 0.0)) for entity_id in participant_ids]
    low_balance_ids = [entity_id for entity_id in participant_ids if float(balances.get(entity_id, 0.0)) < 1.0]
    wealthy_ids = [entity_id for entity_id in participant_ids if float(balances.get(entity_id, 0.0)) > 15.0]

    action_utilities = {
        "redistribute": 0.2 + len(low_balance_ids) * 0.08 + max(0.0, bank_balance - 5.0) * 0.01,
        "collect_fees": 0.15 + strictness * 0.35 + max(0.0, sum(participant_balances)) * 0.0005,
        "anti_hoard_levy": 0.18 + len(wealthy_ids) * 0.09,
        "hold_reserve": 0.12 + (3.0 - min(bank_balance, 3.0)) * 0.2,
    }
    action, action_weights = choose_action(bank, action_utilities, state=state, role="banker")

    # ------------------------------------------------------------------
    # FEATURE FLAG: when banker economic actions are disabled, short-circuit
    # any action that would mutate balances. The banker still gets a
    # single informational event per tick so downstream systems see it
    # "doing something" — but nothing moves.
    # ------------------------------------------------------------------
    economic_action_selected = action in {"collect_fees", "anti_hoard_levy", "redistribute"}
    if economic_action_selected and not banker_economics_enabled():
        state.setdefault("events", []).append(
            {
                "type": "banker_economy_disabled",
                "bank_id": bank["id"],
                "suppressed_action": action,
                "action_weights": action_weights,
                "regime": regime,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    # Bankers tune systemic behavior by selecting one dominant policy action per tick.
    if action == "collect_fees" and banker_economics_enabled():
        fee_rate = round((0.0003 + strictness * 0.0012) * bank_fee_multiplier, 6)
        fee_collected = 0.0
        fee_steps = []
        for entity in entities.values():
            entity_id = entity.get("id")
            if entity_id == bank["id"] or entity.get("type") == "bank":
                continue
            balances.setdefault(entity_id, 0.0)
            fee = min(fee_rate, max(0.0, balances[entity_id] * 0.02))
            if fee <= 0:
                continue
            fee_steps.append(debit(entity_id, fee, None))
            fee_steps.append(credit(bank["id"], fee, None))
            fee_collected += fee
        if fee_collected > 0:
            reinforce_action(
                bank,
                "collect_fees",
                min(0.5, fee_collected),
                state=state,
                role="banker",
                context={"regime": regime, "fee_collected": fee_collected, "fee_rate": fee_rate},
            )
            state.setdefault("events", []).append(
                {
                    "type": "bank_fee_cycle",
                    "bank_id": bank["id"],
                    "fee_collected": round(fee_collected, 6),
                    "fee_rate": fee_rate,
                    "action": action,
                    "action_weights": action_weights,
                    "regime": regime,
                    "tx_steps": fee_steps,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return
        reinforce_action(bank, "collect_fees", -0.1, state=state, role="banker", context={"regime": regime})

    if action == "anti_hoard_levy" and wealthy_ids and banker_economics_enabled():
        levy_steps = []
        levy_total = 0.0
        for entity_id in wealthy_ids:
            bal = float(balances.get(entity_id, 0.0))
            levy_rate = 0.01 if bal < 30 else (0.025 if bal < 60 else 0.05)
            levy = round(max(0.0, bal - 10.0) * levy_rate, 6)
            levy = min(levy, max(0.0, bal * 0.3))
            if levy <= 0:
                continue
            levy_steps.append(debit(entity_id, levy, None))
            levy_steps.append(credit(bank["id"], levy, None))
            levy_total += levy
        if levy_total > 0:
            reinforce_action(
                bank,
                "anti_hoard_levy",
                min(0.6, levy_total * 0.5),
                state=state,
                role="banker",
                context={"regime": regime, "levy_total": levy_total, "targets": len(wealthy_ids)},
            )
            state.setdefault("events", []).append(
                {
                    "type": "bank_anti_hoard_levy",
                    "bank_id": bank["id"],
                    "levy_total": round(levy_total, 6),
                    "targets": len(wealthy_ids),
                    "action": action,
                    "action_weights": action_weights,
                    "regime": regime,
                    "tx_steps": levy_steps,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return
        reinforce_action(bank, "anti_hoard_levy", -0.1, state=state, role="banker", context={"regime": regime})

    if (
        action == "redistribute"
        and low_balance_ids
        and balances[bank["id"]] > 0
        and banker_economics_enabled()
    ):
        support_steps = []
        support_total = 0.0
        max_per_agent = round(0.2 + generosity * 0.9, 6)
        reserve_fraction = max(0.05, min(0.35, liquidity_bias * 0.35))
        budget = round(max(0.0, balances[bank["id"]] * reserve_fraction), 6)
        for entity_id in sorted(low_balance_ids, key=lambda item: balances.get(item, 0.0)):
            current = float(balances.get(entity_id, 0.0))
            needed = max(0.0, 1.1 - current)
            stipend = round(min(max_per_agent, needed, budget - support_total), 6)
            if stipend <= 0:
                break
            support_steps.append(debit(bank["id"], stipend, None))
            support_steps.append(credit(entity_id, stipend, None))
            support_total += stipend
            if support_total >= budget:
                break

        if support_total > 0:
            reinforce_action(
                bank,
                "redistribute",
                min(0.7, support_total),
                state=state,
                role="banker",
                context={"regime": regime, "support_total": support_total, "recipient_count": len(low_balance_ids)},
            )
            state.setdefault("events", []).append(
                {
                    "type": "bank_redistribution",
                    "bank_id": bank["id"],
                    "recipient_count": len(low_balance_ids),
                    "total_amount": round(support_total, 6),
                    "action": action,
                    "action_weights": action_weights,
                    "regime": regime,
                    "tx_steps": support_steps,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return
        reinforce_action(bank, "redistribute", -0.1, state=state, role="banker", context={"regime": regime})

    # hold_reserve is the always-safe fallback. It never mutates balances,
    # so it stays unconditional whether the feature flag is on or off.
    reinforce_action(
        bank,
        "hold_reserve",
        0.08 if bank_balance < 2.0 else 0.02,
        state=state,
        role="banker",
        context={"regime": regime, "bank_balance": bank_balance},
    )
    state.setdefault("events", []).append(
        {
            "type": "bank_hold_reserve",
            "bank_id": bank["id"],
            "bank_balance": float(balances.get(bank["id"], 0.0)),
            "action": action,
            "action_weights": action_weights,
            "regime": regime,
            "network": "Arc",
            "asset": "USDC",
        }
    )
