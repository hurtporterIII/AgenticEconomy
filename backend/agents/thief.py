def handle_thief(thief, state):
    """
    Executes thief behavior
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
    cops_targeting = sum(
        1 for entity in entities if entity.get("type") == "cop" and entity.get("target") == thief.get("id")
    )
    action_utilities = {
        "steal_bank": 0.15 + aggression * 0.45 + bank_bias * 0.35 - stealth * 0.1 if bank_targets else -0.8,
        "steal_agent": 0.1 + aggression * 0.4 + stealth * 0.2 if non_bank_targets else -0.8,
        "lay_low": 0.25 + cops_targeting * 0.25 - aggression * 0.1,
        "deposit_bank": 0.35 + (thief_balance - 8.0) * 0.06 if bank_targets and thief_balance > 8.0 else -0.7,
    }
    action, action_weights = choose_action(thief, action_utilities, state=state, role="thief")

    if action == "lay_low":
        reinforce_action(
            thief,
            "lay_low",
            0.25 if cops_targeting > 0 else 0.05,
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
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    if action == "deposit_bank" and bank_targets:
        bank = random.choice(bank_targets)
        bank_id = bank.get("id")
        balances.setdefault(bank_id, 0.0)
        amount = round(min(max(0.2, thief_balance * 0.18), thief_balance * 0.5), 6)
        if amount > 0:
            tx_debit = debit(thief["id"], amount, None)
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
