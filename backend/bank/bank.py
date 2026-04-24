from core.state import state
from tx.arc import record_payment_intent


def _bump_lifetime(agent_id, *, collected: float = 0.0, lost: float = 0.0) -> None:
    """Cumulative per-sprite totals (never reset). Only entities in state['entities']."""
    aid = str(agent_id).strip() if agent_id is not None else ""
    if not aid:
        return
    ent = state.setdefault("entities", {}).get(aid)
    if not isinstance(ent, dict):
        return
    if collected and collected > 0:
        ent["lifetime_collected"] = round(
            float(ent.get("lifetime_collected", 0.0) or 0.0) + float(collected), 10
        )
    if lost and lost > 0:
        ent["lifetime_lost"] = round(float(ent.get("lifetime_lost", 0.0) or 0.0) + float(lost), 10)


def record_lifetime_lost(agent_id: str, amount: float) -> None:
    """Non-liquid losses (e.g. home stash stolen) that do not pass debit()."""
    if float(amount or 0.0) > 0:
        _bump_lifetime(str(agent_id).strip(), lost=float(amount))


def debit(agent_id, amount, event_id, *, count_lifetime_lost: bool = True):
    aid = str(agent_id).strip() if agent_id is not None else ""
    balances = state.setdefault("balances", {})
    balances.setdefault(aid, 0.0)
    balances[aid] -= amount
    if count_lifetime_lost and float(amount or 0.0) > 0:
        _bump_lifetime(aid, lost=float(amount))
    tx_hash = record_payment_intent(aid, "FEE_POOL", amount, metadata={"event_id": event_id, "kind": "debit"})
    state.setdefault("events", []).append(
        {
            "type": "debit",
            "agent_id": aid,
            "amount": amount,
            "event_id": event_id,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
            "exclude_from_lifetime": not count_lifetime_lost,
        }
    )
    return tx_hash


def credit(agent_id, amount, event_id, *, count_lifetime_collected: bool = True):
    aid = str(agent_id).strip() if agent_id is not None else ""
    balances = state.setdefault("balances", {})
    balances.setdefault(aid, 0.0)
    balances[aid] += amount
    if count_lifetime_collected and float(amount or 0.0) > 0:
        _bump_lifetime(aid, collected=float(amount))
    tx_hash = record_payment_intent("BANK_TREASURY", aid, amount, metadata={"event_id": event_id, "kind": "credit"})
    state.setdefault("events", []).append(
        {
            "type": "credit",
            "agent_id": aid,
            "amount": amount,
            "event_id": event_id,
            "tx_hash": tx_hash,
            "network": "Arc",
            "asset": "USDC",
        }
    )
    return tx_hash
