from bank.bank import debit
from services.oracle import locate_thief


def call_service(agent, state):
    """
    Paid API call
    """
    economy = state.setdefault("economy", {})
    multipliers = economy.get("multipliers", {})
    api_cost_multiplier = float(multipliers.get("api_cost", 1.0))
    regime = economy.get("regime", "balanced")

    cost = round(0.001 * api_cost_multiplier, 6)
    tx_hash = debit(agent["id"], cost, None)
    result = locate_thief(state)

    state.setdefault("events", []).append(
        {
            "type": "api_call",
            "agent": agent["id"],
            "cost": cost,
            "result": result,
            "regime": regime,
            "api_cost_multiplier": api_cost_multiplier,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return result
