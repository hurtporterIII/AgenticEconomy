from bank.bank import debit
from services.oracle import locate_thief


def call_service(agent, state):
    """
    Paid API call
    """
    cost = 0.001
    tx_hash = debit(agent["id"], cost, None)
    result = locate_thief(state)

    state.setdefault("events", []).append(
        {
            "type": "api_call",
            "agent": agent["id"],
            "cost": cost,
            "result": result,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return result
