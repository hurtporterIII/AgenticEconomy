from core.state import state
from tx.arc import record_payment_intent


def debit(agent_id, amount, event_id):
    balances = state.setdefault("balances", {})
    balances.setdefault(agent_id, 0.0)
    balances[agent_id] -= amount
    tx_hash = record_payment_intent(agent_id, "FEE_POOL", amount, metadata={"event_id": event_id, "kind": "debit"})
    state.setdefault("events", []).append(
        {
            "type": "debit",
            "agent_id": agent_id,
            "amount": amount,
            "event_id": event_id,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return tx_hash


def credit(agent_id, amount, event_id):
    balances = state.setdefault("balances", {})
    balances.setdefault(agent_id, 0.0)
    balances[agent_id] += amount
    tx_hash = record_payment_intent("BANK_TREASURY", agent_id, amount, metadata={"event_id": event_id, "kind": "credit"})
    state.setdefault("events", []).append(
        {
            "type": "credit",
            "agent_id": agent_id,
            "amount": amount,
            "event_id": event_id,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return tx_hash
