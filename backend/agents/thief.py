"""
Thief agent.

FEATURE FLAG
    Balance-mutating actions (steal_agent / steal_bank / deposit_bank) are
    gated by core.flags.thief_economics_enabled(), which is False unless
    NON_WORKER_ECONOMICS=on. When disabled, the thief still picks an action
    via its policy but any balance-mutating branch is short-circuited to a
    `thief_disabled` audit event — no debit, no credit, no steal event.
    The spatial behavior (movement) is in loop.py and is unaffected.
"""

from core.flags import NANO_ECONOMY_HOOKS, thief_economics_enabled


def handle_thief(thief, state):
    """
    Executes thief behavior.
    """
    import random

    from actions.steal import steal_from_agent, steal_from_bank
    from agents.cop import trigger_cops
    from bank.bank import credit, debit
    from utils.helpers import choose_action, reinforce_action

    personality = thief.setdefault("personality", {})
    aggression = float(personality.get("aggression", 0.6))
    bank_bias = float(personality.get("bank_bias", 0.45))
    stealth = float(personality.get("stealth", 0.4))

    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    theft_success_multiplier = float(multipliers.get("theft_success", 1.0))
    regime = economy.get("regime", "balanced")

    entities = list(state.setdefault("entities", {}).values())
    candidates = [entity for entity in entities if entity.get("id") != thief.get("id")]
    if not candidates:
        return
    balances = state.setdefault("balances", {})
    thief_balance = float(balances.get(thief["id"], 0.0))

    bank_targets = [entity for entity in candidates if entity.get("type") == "bank"]
    non_bank_targets = [entity for entity in candidates if entity.get("type") != "bank"]
    learning = thief.setdefault("learning", {})
    zone_risk = learning.setdefault("zone_risk", {})
    bank_zone_risk = float((zone_risk.get("bank_zone", {}) or {}).get("risk_score", 0.0) or 0.0)
    cops_targeting = sum(
        1 for entity in entities if entity.get("type") == "cop" and entity.get("target") == thief.get("id")
    )
    action_utilities = {
        "steal_bank": (
            0.15 + aggression * 0.45 + bank_bias * 0.35 - stealth * 0.1 - bank_zone_risk * 0.85
            if bank_targets else -0.8
        ),
        "steal_agent": 0.1 + aggression * 0.4 + stealth * 0.2 if non_bank_targets else -0.8,
        # Anti-stall: "lay_low" should be situational (safety when pressured),
        # not the dominant default action for long stretches.
        "lay_low": -0.35 + cops_targeting * 0.22 - aggression * 0.05,
        "deposit_bank": 0.35 + (thief_balance - 8.0) * 0.06 if bank_targets and thief_balance > 8.0 else -0.7,
    }
    # If historical learning pushed lay_low too high, decay it when not under
    # active pressure so movement/exchanges recover.
    policy = thief.setdefault("policy", {})
    weights = policy.setdefault("weights", {})
    if "lay_low" in weights and cops_targeting <= 0:
        try:
            weights["lay_low"] = max(1.0, float(weights.get("lay_low", 1.0)) * 0.94)
        except Exception:
            weights["lay_low"] = 1.0
    action, action_weights = choose_action(thief, action_utilities, state=state, role="thief")

    # ------------------------------------------------------------------
    # FEATURE FLAG: if the thief picks any balance-mutating action while
    # non-worker economics are disabled, short-circuit to a no-op audit
    # event. lay_low is always safe (no money moves), so it falls through.
    # ------------------------------------------------------------------
    balance_mutating = {"steal_agent", "steal_bank", "deposit_bank"}
    if action in balance_mutating and not thief_economics_enabled():
        state.setdefault("events", []).append(
            {
                "type": "thief_disabled",
                "thief_id": thief["id"],
                "suppressed_action": action,
                "action_weights": action_weights,
                "regime": regime,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    if action == "lay_low":
        reinforce_action(
            thief,
            "lay_low",
            0.02 if cops_targeting > 0 else -0.10,
            state=state,
            role="thief",
            context={"regime": regime, "cops_targeting": cops_targeting},
        )
        state.setdefault("events", []).append(
            {
                "type": "thief_idle",
                "thief_id": thief["id"],
                "reason": "policy_lay_low",
                "regime": regime,
                "action": action,
                "action_weights": action_weights,
                "personality": {"aggression": aggression, "bank_bias": bank_bias, "stealth": stealth},
                "learning": {"bank_zone_risk": round(bank_zone_risk, 4)},
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    # Info-driven constraint: when nano hooks are enabled, steals must come
    # through spy intel purchase flow in core.nano_economy (spy_sell_info ->
    # steal_agent). Block direct legacy steal branches here.
    if NANO_ECONOMY_HOOKS and action == "steal_agent":
        reinforce_action(
            thief,
            action,
            -0.12,
            state=state,
            role="thief",
            context={"regime": regime, "reason": "awaiting_spy_intel"},
        )
        state.setdefault("events", []).append(
            {
                "type": "thief_waiting_for_intel",
                "thief_id": thief["id"],
                "blocked_action": action,
                "reason": "nano_intel_required",
                "regime": regime,
                "action_weights": action_weights,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    if action == "deposit_bank" and bank_targets and thief_economics_enabled():
        bank = random.choice(bank_targets)
        bank_id = bank.get("id")
        balances.setdefault(bank_id, 0.0)
        amount = round(min(max(0.2, thief_balance * 0.18), thief_balance * 0.5), 6)
        if amount > 0:
            tx_debit = debit(thief["id"], amount, None, count_lifetime_lost=False)
            tx_credit = credit(bank_id, amount, None)
            reinforce_action(
                thief,
                "deposit_bank",
                0.2,
                state=state,
                role="thief",
                context={"regime": regime, "amount": amount, "bank_id": bank_id},
            )
            state.setdefault("events", []).append(
                {
                    "type": "thief_deposit",
                    "thief_id": thief["id"],
                    "bank_id": bank_id,
                    "amount": amount,
                    "regime": regime,
                    "action": action,
                    "action_weights": action_weights,
                    "tx_hash": tx_credit,
                    "tx_steps": [tx_debit, tx_credit],
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
            return

    # steal_bank / steal_agent. These only run when thief economics are
    # enabled (the master-flag guard near the top of this function
    # already returned otherwise).
    if not thief_economics_enabled():
        return

    choose_bank = action == "steal_bank" and bool(bank_targets)
    target = random.choice(bank_targets if choose_bank else (non_bank_targets or bank_targets or candidates))

    if target.get("type") == "bank":
        bank_amount = random.choice([2, 5]) if aggression < 0.7 else random.choice([5, 5, 2])
        bank_amount = max(0.1, round(bank_amount * theft_success_multiplier, 3))
        fee_cost = round(0.001 + (1.0 - stealth) * 0.003, 6)
        stolen = steal_from_bank(thief, target, state, steal_amount=bank_amount, fee_cost=fee_cost)
        reinforce_action(
            thief,
            "steal_bank",
            (stolen - fee_cost) / max(1.0, stolen),
            state=state,
            role="thief",
            context={"regime": regime, "stolen": stolen, "fee_cost": fee_cost, "target_type": "bank"},
        )
        trigger_cops(thief["id"], state)
    else:
        desired = round((1.0 + aggression * 2.5) * theft_success_multiplier, 3)
        fee_cost = round(0.001 + (1.0 - stealth) * 0.003, 6)
        stolen = steal_from_agent(thief, target, state, steal_amount=desired, fee_cost=fee_cost)
        reinforce_action(
            thief,
            "steal_agent",
            (stolen - fee_cost) / max(1.0, desired),
            state=state,
            role="thief",
            context={"regime": regime, "stolen": stolen, "fee_cost": fee_cost, "target_id": target.get("id")},
        )
        chase_prob = max(0.08, min(0.75, 0.35 + aggression * 0.25 - stealth * 0.28))
        if random.random() < chase_prob:
            trigger_cops(thief["id"], state)
