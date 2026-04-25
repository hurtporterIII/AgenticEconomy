"""Economy health, worker ledger, tx diagnostics, settings, logs, minds, and agent summaries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.routes.common import ALLOWED_ENTITY_TYPES, get_events, get_state
from core.nano_economy import INTEL_PRICE_DEFAULT, INTEL_PRICE_MAX, INTEL_PRICE_MIN
from core.state import build_personality, default_behavior_settings, state
from core.state import state_lock
from tx.arc import (
    get_tx_runtime_status,
    inspect_transaction,
    probe_real_transaction,
    reset_tx_runtime_counters,
)
from utils.logger import get_action_log_stats, read_action_logs

economy_tx_router = APIRouter(tags=["demo"])


def _clamp_spy_price(value: float) -> float:
    v = float(value)
    if v < INTEL_PRICE_MIN:
        return INTEL_PRICE_MIN
    if v > INTEL_PRICE_MAX:
        return INTEL_PRICE_MAX
    return round(v, 10)


def _first_spy_entity(shared: dict) -> dict | None:
    entities = shared.get("entities", {}) if isinstance(shared, dict) else {}
    if not isinstance(entities, dict):
        return None
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        if str(entity.get("persona_role", "")).lower() == "spy":
            return entity
    for entity in entities.values():
        if not isinstance(entity, dict):
            continue
        if str(entity.get("id", "")).lower().startswith("spy"):
            return entity
    return None


@economy_tx_router.get("/spy/price")
def get_spy_price_endpoint():
    shared = get_state()
    spy = _first_spy_entity(shared)
    if spy is None:
        raise HTTPException(status_code=404, detail="spy not found")
    raw = spy.get("intel_price", shared.setdefault("economy", {}).get("intel_price", INTEL_PRICE_DEFAULT))
    price = _clamp_spy_price(float(raw))
    spy["intel_price"] = price
    shared.setdefault("economy", {})["intel_price"] = price
    return {
        "spy_id": spy.get("id"),
        "intel_price": price,
        "min_price": INTEL_PRICE_MIN,
        "max_price": INTEL_PRICE_MAX,
        "hackathon_safe": price <= 0.01,
    }


@economy_tx_router.post("/spy/price")
def set_spy_price_endpoint(value: float = Query(..., description="USDC price per intel sale")):
    with state_lock:
        shared = get_state()
        spy = _first_spy_entity(shared)
        if spy is None:
            raise HTTPException(status_code=404, detail="spy not found")
        price = _clamp_spy_price(float(value))
        spy["intel_price"] = price
        shared.setdefault("economy", {})["intel_price"] = price
        shared.setdefault("events", []).append(
            {
                "type": "spy_price_update",
                "spy_id": spy.get("id"),
                "amount": price,
                "min_price": INTEL_PRICE_MIN,
                "max_price": INTEL_PRICE_MAX,
                "network": "Arc",
                "asset": "USDC",
            }
        )
    return {
        "status": "ok",
        "spy_id": spy.get("id"),
        "intel_price": price,
        "min_price": INTEL_PRICE_MIN,
        "max_price": INTEL_PRICE_MAX,
        "hackathon_safe": price <= 0.01,
    }


@economy_tx_router.get("/worker/{worker_id}/ledger")
def get_worker_ledger(worker_id: str, limit: int = 200):
    """Return a per-worker activity log.

    The event stream already tags every economic action with a
    worker_id. This endpoint filters that stream down to a single
    worker so the dashboard (or a curl from a demo) can show "what
    this worker did and how," with amounts and tx hashes, under the
    worker's name.
    """
    from core.state import WORK_TREASURY_ID

    events = get_events() or []
    wid = str(worker_id)
    WORKER_EVENT_TYPES = {
        "worker_earn",
        "worker_earn_skipped",
        "worker_bank_deposit",
        "worker_store_home",
        "bank_fee_nano",
        "bank_fee_skipped",
        "steal_agent",
        "steal_skipped",
        "spy_intel_created",
    }
    rows = []
    for e in events:
        if not isinstance(e, dict):
            continue
        owner = str(e.get("worker_id", "") or e.get("target_worker", ""))
        if owner != wid:
            continue
        et = str(e.get("type", ""))
        if et not in WORKER_EVENT_TYPES:
            continue
        rows.append(
            {
                "type": et,
                "amount": e.get("amount", e.get("reward")),
                "tx_hash": e.get("tx_hash"),
                "tx_steps": e.get("tx_steps"),
                "payer": e.get("payer"),
                "payee": e.get("payee"),
                "bank_id": e.get("bank_id"),
                "home_storage": e.get("home_storage"),
                "carried_cash": e.get("carried_cash"),
                "reason": e.get("reason"),
                "network": e.get("network", "Arc"),
                "asset": e.get("asset", "USDC"),
            }
        )
    capped = max(1, min(int(limit), 5000))
    balances = state.setdefault("balances", {}) if isinstance(state, dict) else {}
    return {
        "worker_id": wid,
        "count": len(rows),
        "ledger": rows[-capped:],
        "summary": {
            "liquid_balance": round(float(balances.get(wid, 0.0)), 8),
            "home_storage": round(
                float((state.get("entities", {}) or {}).get(wid, {}).get("home_storage", 0.0)),
                8,
            ),
            "work_treasury_balance": round(float(balances.get(WORK_TREASURY_ID, 0.0)), 8),
        },
    }


@economy_tx_router.get("/economy/health")
def economy_health_endpoint():
    """Health snapshot of the info-driven nano economy.

    Everything in here is computed from the live event stream + balances,
    not stored counters, so it's always a true reflection of what the
    simulation has actually done."""
    shared = get_state()
    balances = shared.setdefault("balances", {}) if isinstance(shared, dict) else {}
    entities = shared.setdefault("entities", {}) if isinstance(shared, dict) else {}
    events = get_events() or []

    worker_balances = []
    worker_home_storages = []
    for ent in entities.values():
        if not isinstance(ent, dict) or ent.get("type") != "worker":
            continue
        wid = ent.get("id")
        worker_balances.append(float(balances.get(wid, 0.0) or 0.0))
        worker_home_storages.append(float(ent.get("home_storage", 0.0) or 0.0))

    def _first_id_of(etype):
        for eid, ent in entities.items():
            if isinstance(ent, dict) and ent.get("type") == etype:
                return eid
        return None

    def _first_id_by_role(role):
        for eid, ent in entities.items():
            if isinstance(ent, dict) and str(ent.get("persona_role", "")).lower() == role:
                return eid
        return None

    bank_id = _first_id_of("bank")
    thief_id = _first_id_of("thief")
    cop_id = _first_id_of("cop")
    spy_id = _first_id_by_role("spy")

    total_transactions = 0
    theft_count = 0
    recovery_count = 0
    intel_sold_count = 0
    intel_created_count = 0
    spy_sold_to_thief = 0
    spy_sold_to_cop = 0
    redistribution_count = 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = ev.get("type")
        if et in ("debit", "credit"):
            total_transactions += 1
        elif et == "steal_agent":
            theft_count += 1
        elif et == "cop_recover":
            recovery_count += 1
        elif et == "redistribution":
            redistribution_count += 1
        elif et == "spy_intel_created":
            intel_created_count += 1
        elif et == "spy_sell_info":
            intel_sold_count += 1
            if ev.get("buyer_type") == "thief":
                spy_sold_to_thief += 1
            elif ev.get("buyer_type") == "cop":
                spy_sold_to_cop += 1

    worker_count = len(worker_balances)
    worker_avg = round(sum(worker_balances) / max(1, worker_count), 10) if worker_count else 0.0
    worker_min = round(min(worker_balances), 10) if worker_balances else 0.0
    total_home_storage = round(sum(worker_home_storages), 10)

    invariants = {
        "thief_buys_eq_steals": spy_sold_to_thief == theft_count,
        "cop_buys_eq_recoveries": spy_sold_to_cop == recovery_count,
        "recoveries_eq_redistributions": recovery_count == redistribution_count,
        "no_negative_worker_balance": all(b >= 0 for b in worker_balances),
    }

    return {
        "total_transactions": total_transactions,
        "worker_count": worker_count,
        "worker_avg_balance": worker_avg,
        "worker_min_balance": worker_min,
        "bank_balance": round(float(balances.get(bank_id, 0.0) or 0.0), 10) if bank_id else 0.0,
        "spy_balance": round(float(balances.get(spy_id, 0.0) or 0.0), 10) if spy_id else 0.0,
        "thief_balance": round(float(balances.get(thief_id, 0.0) or 0.0), 10) if thief_id else 0.0,
        "cop_balance": round(float(balances.get(cop_id, 0.0) or 0.0), 10) if cop_id else 0.0,
        "total_home_storage": total_home_storage,
        "theft_count": theft_count,
        "recovery_count": recovery_count,
        "intel_count": intel_created_count,
        "intel_sold_count": intel_sold_count,
        "spy_sold_to_thief": spy_sold_to_thief,
        "spy_sold_to_cop": spy_sold_to_cop,
        "redistribution_count": redistribution_count,
        "tick": int(shared.setdefault("economy", {}).get("tick", 0)) if isinstance(shared, dict) else 0,
        "invariants": invariants,
        "healthy": all(invariants.values()),
    }


@economy_tx_router.get("/agents/actions")
def agents_actions_endpoint():
    """Expose each agent's symbolic action queue plus a readable label."""
    from core.action_queue import snapshot_queues

    shared = get_state() if isinstance(get_state(), dict) else {}
    queues = snapshot_queues(shared)
    entities = shared.get("entities", {}) if isinstance(shared, dict) else {}
    summary = {}
    for agent_id, actions in queues.items():
        ent = entities.get(agent_id) if isinstance(entities, dict) else None
        current = None
        if isinstance(ent, dict):
            current = ent.get("current_action")
        summary[agent_id] = {
            "length": len(actions),
            "next": actions[0] if actions else None,
            "kinds": [a.get("type") for a in actions if isinstance(a, dict)],
            "current_action": current or ("idle" if not actions else None),
        }
    return {
        "queues": queues,
        "summary": summary,
        "tick": int(shared.get("economy", {}).get("tick", 0)) if isinstance(shared, dict) else 0,
    }


@economy_tx_router.get("/transactions/count")
def transactions_count_endpoint():
    """Lightweight endpoint: total number of ledger-moving transactions
    (every debit/credit emitted by bank.bank)."""
    events = get_events() or []
    total = sum(
        1
        for ev in events
        if isinstance(ev, dict) and ev.get("type") in ("debit", "credit")
    )
    return {"total_transactions": total}


@economy_tx_router.get("/agents/current")
def agents_current_endpoint():
    """Compact map of each agent's current_action label."""
    shared = get_state() if isinstance(get_state(), dict) else {}
    entities = shared.get("entities", {}) if isinstance(shared, dict) else {}
    out: dict[str, str] = {}
    if isinstance(entities, dict):
        for agent_id, ent in entities.items():
            if not isinstance(ent, dict):
                continue
            label = ent.get("current_action")
            if label:
                out[str(agent_id)] = str(label)
    return out


@economy_tx_router.get("/tx/diagnostics")
def tx_diagnostics_endpoint():
    return get_tx_runtime_status()


@economy_tx_router.post("/tx/session/reset")
def tx_session_reset_endpoint():
    """Reset runtime tx counters for a clean demo session."""
    status = reset_tx_runtime_counters()
    return {"ok": True, "message": "tx session counters reset", "status": status}


@economy_tx_router.get("/tx/recent")
def tx_recent_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    max_records: int = Query(50, ge=10, le=200),
):
    shared = get_state() if isinstance(get_state(), dict) else {}
    settlement = shared.get("settlement", {}) if isinstance(shared, dict) else {}
    history = settlement.get("recent_records", []) if isinstance(settlement, dict) else []

    seen_hashes = set()
    rows = []
    for rec in reversed(history if isinstance(history, list) else []):
        if not isinstance(rec, dict):
            continue
        tx_hash = str(rec.get("tx_hash") or "").strip()
        if not tx_hash.startswith("0x"):
            continue
        if tx_hash in seen_hashes:
            continue
        seen_hashes.add(tx_hash)
        rows.append(
            {
                "tx_hash": tx_hash,
                "type": "settlement",
                "amount": float(rec.get("amount_submitted", 0.0) or 0.0),
                "payer": rec.get("from_wallet"),
                "payee": rec.get("to_wallet"),
                "asset": "USDC",
                "network": "Arc",
                "seq": int(rec.get("tick", 0) or 0),
                "ts": rec.get("ts_epoch"),
            }
        )
        if len(rows) >= int(max_records):
            break

    total = len(rows)
    per_page = int(page_size)
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = min(max(1, int(page)), total_pages)
    start = (current_page - 1) * per_page
    end = start + per_page
    items = rows[start:end]

    return {
        "ok": True,
        "page": current_page,
        "page_size": per_page,
        "total": total,
        "total_pages": total_pages,
        "max_records": int(max_records),
        "items": items,
    }


@economy_tx_router.get("/compliance/status")
def compliance_status_endpoint():
    status = get_tx_runtime_status() or {}
    diagnostics = status.get("diagnostics") if isinstance(status, dict) else {}
    metrics = status.get("metrics") if isinstance(status, dict) else {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    if not isinstance(metrics, dict):
        metrics = {}

    real_tx_count = int(diagnostics.get("real_tx_count", 0) or 0)
    cost_per_action = float(metrics.get("cost_per_action", 0.0) or 0.0)
    cost_ok = cost_per_action <= 0.01
    tx_ok = real_tx_count >= 50
    compliant = tx_ok and cost_ok

    if compliant:
        message = "Ready for judges"
    elif not tx_ok:
        message = "Need more real txs"
    else:
        message = "Cost per action too high"

    return {
        "compliant": compliant,
        "real_tx_count": real_tx_count,
        "cost_per_action": round(cost_per_action, 8),
        "cost_ok": cost_ok,
        "tx_target": 50,
        "message": message,
    }


@economy_tx_router.post("/tx/probe")
def tx_probe_endpoint(amount: float = 0.001):
    try:
        return probe_real_transaction(amount=amount)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"probe failed: {exc}") from exc


@economy_tx_router.get("/tx/inspect")
def tx_inspect_endpoint(id: str):
    try:
        return inspect_transaction(tx_id=id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"inspect failed: {exc}") from exc


@economy_tx_router.get("/settings")
def get_behavior_settings_endpoint():
    return state.setdefault("behavior_settings", default_behavior_settings())


@economy_tx_router.post("/settings")
def update_behavior_settings_endpoint(payload: dict, apply_existing: bool = True):
    behavior_settings = state.setdefault("behavior_settings", default_behavior_settings())
    entities = state.setdefault("entities", {})
    updated_roles = []
    updated_agents = 0
    for role, role_settings in (payload or {}).items():
        if role not in ALLOWED_ENTITY_TYPES:
            continue
        if not isinstance(role_settings, dict):
            continue
        role_target = behavior_settings.setdefault(role, {})
        for key, value in role_settings.items():
            try:
                role_target[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
        updated_roles.append(role)
        if apply_existing:
            for entity in entities.values():
                if entity.get("type") == role:
                    entity["personality"] = build_personality(role, behavior_settings)
                    updated_agents += 1
    return {
        "status": "updated",
        "updated_roles": sorted(set(updated_roles)),
        "updated_agents": updated_agents,
        "settings": behavior_settings,
    }


@economy_tx_router.get("/logs")
def get_logs_endpoint(limit: int = 200, after_seq: int | None = None):
    return read_action_logs(limit=limit, after_seq=after_seq)


@economy_tx_router.get("/logs/stats")
def get_logs_stats_endpoint():
    return get_action_log_stats(memory_events=len(state.setdefault("events", [])))


@economy_tx_router.get("/minds")
def get_minds_endpoint(limit_memory: int = 8, limit_reflections: int = 5):
    entities = state.setdefault("entities", {})
    out = {}
    lm = max(1, min(int(limit_memory), 40))
    lr = max(1, min(int(limit_reflections), 20))
    for entity_id, entity in entities.items():
        mind = entity.get("mind")
        policy = entity.get("policy") if isinstance(entity.get("policy"), dict) else {}
        if not isinstance(mind, dict):
            mind = {}
        out[entity_id] = {
            "intent": mind.get("intent"),
            "reflection": entity.get("reflection") or mind.get("last_reflection"),
            "mood": mind.get("mood"),
            "confidence": mind.get("confidence"),
            "top_action": entity.get("top_action") or policy.get("last_action"),
            "goals": mind.get("goals"),
            "memory": (entity.get("memory") or mind.get("memory") or [])[-lm:],
            "reflections": (mind.get("reflections") or [])[-lr:],
        }
    return out
