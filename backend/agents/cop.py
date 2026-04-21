from actions.service import call_service
from bank.bank import debit
from utils.helpers import choose_action, reinforce_action


def handle_cop(cop, state):
    """
    Executes cop behavior
    """
    import random

    personality = cop.setdefault("personality", {})
    api_reliance = float(personality.get("api_reliance", 0.65))
    persistence = float(personality.get("persistence", 0.6))
    decisiveness = float(personality.get("decisiveness", 0.55))

    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    cop_effectiveness = float(multipliers.get("cop_effectiveness", 1.0))
    regime = economy.get("regime", "balanced")

    if not cop.get("target"):
        thief_id = None
        action_utilities = {
            "call_service": 0.2 + api_reliance * 0.5,
            "scan_local": 0.15 + (1.0 - api_reliance) * 0.5,
            "patrol": 0.05,
        }
        action, action_weights = choose_action(cop, action_utilities, state=state, role="cop")
        if action == "call_service":
            thief_id = call_service(cop, state)
            reinforce_action(
                cop,
                "call_service",
                0.25 if thief_id else -0.2,
                state=state,
                role="cop",
                context={"regime": regime, "thief_id": thief_id},
            )
        elif action == "scan_local":
            thieves = [
                entity.get("id")
                for entity in state.setdefault("entities", {}).values()
                if entity.get("type") == "thief"
            ]
            if thieves:
                thief_id = random.choice(thieves)
            reinforce_action(
                cop,
                "scan_local",
                0.2 if thief_id else -0.05,
                state=state,
                role="cop",
                context={"regime": regime, "thief_id": thief_id},
            )
            state.setdefault("events", []).append(
                {
                    "type": "cop_scan",
                    "cop_id": cop.get("id"),
                    "mode": "local_reasoning",
                    "action": action,
                    "action_weights": action_weights,
                    "target_candidate": thief_id,
                    "regime": regime,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
        else:
            reinforce_action(
                cop,
                "patrol",
                0.05,
                state=state,
                role="cop",
                context={"regime": regime},
            )
            state.setdefault("events", []).append(
                {
                    "type": "cop_patrol",
                    "cop_id": cop.get("id"),
                    "action": action,
                    "action_weights": action_weights,
                    "regime": regime,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
        if thief_id:
            cop["target"] = thief_id

    target_id = cop.get("target")
    if not target_id:
        return

    target = state.setdefault("entities", {}).get(target_id)
    if target is None:
        cop["target"] = None
        return

    chase_success_prob = max(
        0.05,
        min(0.95, (0.15 + persistence * 0.45 + decisiveness * 0.3) * cop_effectiveness),
    )
    chase_action, chase_weights = choose_action(
        cop,
        {"chase": chase_success_prob, "patrol": 0.12},
        state=state,
        role="cop",
    )
    if chase_action != "chase":
        reinforce_action(
            cop,
            "patrol",
            0.06,
            state=state,
            role="cop",
            context={"regime": regime, "target_id": target_id, "decision": "no_chase"},
        )
        state.setdefault("events", []).append(
            {
                "type": "cop_patrol",
                "cop_id": cop.get("id"),
                "target_id": target_id,
                "reason": "chose_not_to_chase",
                "action": chase_action,
                "action_weights": chase_weights,
                "regime": regime,
                "network": "Arc",
                "asset": "USDC",
            }
        )
        return

    chase_success = random.random() < chase_success_prob
    penalty = round(0.5 + persistence * 1.5, 6)
    penalty_tx = None
    if chase_success:
        penalty_tx = debit(target_id, penalty, None)
        cop["target"] = None
    reinforce_action(
        cop,
        "chase",
        0.4 if chase_success else -0.2,
        state=state,
        role="cop",
        context={"regime": regime, "target_id": target_id, "captured": chase_success, "penalty": penalty},
    )

    state.setdefault("events", []).append(
        {
            "type": "cop_chase",
            "cop_id": cop.get("id"),
            "target_id": target_id,
            "action": "chase",
            "action_weights": chase_weights,
            "captured": chase_success,
            "chase_success_prob": round(chase_success_prob, 4),
            "penalty": penalty if chase_success else 0,
            "penalty_tx_hash": penalty_tx,
            "regime": regime,
            "personality": {
                "api_reliance": api_reliance,
                "persistence": persistence,
                "decisiveness": decisiveness,
                "cop_effectiveness": cop_effectiveness,
            },
            # Chase itself is informational; value movement is represented by penalty_tx_hash.
            "tx_hash": penalty_tx,
            "network": "Arc",
            "asset": "USDC",
        }
    )


def trigger_cops(thief_id, state):
    for entity in state.setdefault("entities", {}).values():
        if entity.get("type") == "cop":
            entity["target"] = thief_id
