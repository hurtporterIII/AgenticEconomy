from actions.service import call_service
from tx.arc import submit_transaction


def handle_cop(cop, state):
    """
    Executes cop behavior
    """
    if not cop.get("target"):
        thief_id = call_service(cop, state)
        if thief_id:
            cop["target"] = thief_id

    target_id = cop.get("target")
    if not target_id:
        return

    target = state.setdefault("entities", {}).get(target_id)
    if target is None:
        cop["target"] = None
        return

    # Simple chase placeholder: mark chase attempt in events.
    chase_tx = submit_transaction("MASTER", cop.get("id"), 0)
    state.setdefault("events", []).append(
        {
            "type": "cop_chase",
            "cop_id": cop.get("id"),
            "target_id": target_id,
            "tx_hash": chase_tx,
            "network": "Arc",
            "asset": "USDC",
        }
    )


def trigger_cops(thief_id, state):
    for entity in state.setdefault("entities", {}).values():
        if entity.get("type") == "cop":
            entity["target"] = thief_id
