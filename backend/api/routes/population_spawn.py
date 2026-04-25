"""Population, spawn, core sim step, and demo reset/force-cycle routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.routes.common import (
    ALLOWED_ENTITY_TYPES,
    BANK_SECTORS,
    DEFAULT_RESET_BALANCES,
    DEFAULT_RESET_POPULATION,
    MAX_TOTAL_AGENTS,
    TILE_SIZE,
    _compute_cop_stats,
    _home_coords,
    _pick_sector,
    _sector_point,
    get_events,
    get_state,
)
from core import locations as _locations
from core import navmesh
from core.nano_economy import INTEL_PRICE_DEFAULT, INTEL_PRICE_MAX, INTEL_PRICE_MIN
from core.loop import run_loop
from core.state import build_personality, default_behavior_settings, default_economy_state, state, state_lock
from utils.logger import create_event_buffer

population_router = APIRouter(tags=["demo"])


def step():
    with state_lock:
        run_loop(state)
        event_count = len(state.setdefault("events", []))
    return {"status": "step complete", "event_count": event_count}


def _next_entity_id(entity_type: str) -> str:
    entities = state.setdefault("entities", {})
    prefix = f"{entity_type}_"
    highest = 0
    for entity_id in entities.keys():
        if not entity_id.startswith(prefix):
            continue
        suffix = entity_id[len(prefix) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{entity_type}_{highest + 1}"


def spawn_entity(entity_id, entity_type, balance=0.0):
    with state_lock:
        entities = state.setdefault("entities", {})
        balances = state.setdefault("balances", {})
        behavior_settings = state.setdefault("behavior_settings", default_behavior_settings())

        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(
                f"invalid entity_type '{entity_type}'. "
                f"Allowed: {sorted(ALLOWED_ENTITY_TYPES)}"
            )

        is_new_entity = entity_id not in entities
        if is_new_entity and len(entities) >= MAX_TOTAL_AGENTS:
            raise ValueError(
                f"agent cap reached ({MAX_TOTAL_AGENTS}). "
                "Delete existing agents or increase MAX_TOTAL_AGENTS."
            )

        if entity_type in {"bank", "banker"}:
            sx, sy = _sector_point(_pick_sector(BANK_SECTORS, entity_id), entity_id, spread=0.2)
        elif entity_type == "worker":
            hx, hy = _locations.point("worker", "home", anchor="inside")
            try:
                slot = max(0, int(str(entity_id).split("_")[-1]) - 1)
            except (ValueError, IndexError):
                slot = 0

            base_tx = int(hx // TILE_SIZE)
            base_ty = int(hy // TILE_SIZE)

            candidates = []
            for ring in range(0, 5):
                if ring == 0:
                    candidates.append((0, 0))
                    continue
                for dx in range(-ring, ring + 1):
                    candidates.append((dx, -ring))
                    candidates.append((dx, +ring))
                for dy in range(-ring + 1, ring):
                    candidates.append((-ring, dy))
                    candidates.append((+ring, dy))

            taken = {
                (int(e.get("x", 0) // TILE_SIZE), int(e.get("y", 0) // TILE_SIZE))
                for e in entities.values()
                if e.get("type") == "worker"
            }

            sx = sy = None
            for dx, dy in candidates:
                wx = base_tx + dx
                wy = base_ty + dy
                if not navmesh.is_walkable(wx, wy):
                    continue
                if (wx, wy) in taken:
                    continue
                sx, sy = navmesh.tile_to_world(wx, wy)
                break
            if sx is None:
                wx, wy = navmesh.nearest_walkable(base_tx, base_ty, max_radius=10)
                sx, sy = navmesh.tile_to_world(wx, wy)
        elif entity_type == "thief":
            sx, sy = _sector_point("The Rose and Crown Pub", entity_id, spread=0.45)
        elif entity_type == "cop":
            sx, sy = _sector_point("Oak Hill College", entity_id, spread=0.4)
        else:
            sx, sy = _home_coords(entity_id)
        entity = {
            "id": entity_id,
            "type": entity_type,
            "x": float(sx),
            "y": float(sy),
            "target_x": float(sx),
            "target_y": float(sy),
        }
        if entity_type == "cop":
            entity["target"] = None
        entity["memory"] = []
        entity["reflection"] = "neutral"
        entity["policy_bias"] = {}
        entity["personality"] = build_personality(entity_type, behavior_settings)
        entity["lifetime_collected"] = 0.0
        entity["lifetime_lost"] = 0.0

        entities[entity_id] = entity
        balances.setdefault(entity_id, float(balance))
        return entity


@population_router.get("/state")
def get_state_endpoint():
    return get_state()


@population_router.get("/events")
def get_events_endpoint(limit: int | None = None):
    events = get_events()
    if limit is None:
        return events
    capped = max(1, min(int(limit), 5000))
    return events[-capped:]


@population_router.post("/step")
def step_endpoint():
    return step()


@population_router.post("/demo/force-cop-cycle")
def force_cop_cycle_endpoint(steps: int = 80):
    """
    Demo helper: force a short steal->intel->cop-recovery cycle so cop ledger
    stats visibly update during presentations.
    """
    with state_lock:
        shared = get_state()
        entities = shared.setdefault("entities", {})
        balances = shared.setdefault("balances", {})

        required = [
            ("worker_1", "worker", 5.0),
            ("thief_1", "thief", 2.0),
            ("cop_1", "cop", 2.0),
            ("spy_1", "banker", 1.0),
            ("bank_1", "bank", 50.0),
        ]
        for entity_id, entity_type, bal in required:
            if entity_id not in entities:
                spawn_entity(entity_id=entity_id, entity_type=entity_type, balance=bal)
            balances[entity_id] = max(float(balances.get(entity_id, 0.0) or 0.0), float(bal))
        entities["spy_1"]["persona_role"] = "spy"
        entities["spy_1"]["intel_price"] = max(INTEL_PRICE_MIN, min(INTEL_PRICE_DEFAULT, INTEL_PRICE_MAX))

        worker = entities.get("worker_1", {})
        worker["home_storage"] = max(float(worker.get("home_storage", 0.0) or 0.0), 0.06)

        before_events = len(get_events())
        before_stats = _compute_cop_stats("cop_1", get_events())
        run_steps = max(1, min(int(steps), 300))
        for _ in range(run_steps):
            run_loop(shared)

        all_events = get_events()
        after_events = len(all_events)
        after_stats = _compute_cop_stats("cop_1", all_events)
        recent = all_events[max(0, after_events - 120) :]
        counts = {}
        for ev in recent:
            if not isinstance(ev, dict):
                continue
            et = str(ev.get("type") or "")
            counts[et] = int(counts.get(et, 0)) + 1

        return {
            "status": "ok",
            "steps_run": run_steps,
            "events_added": max(0, after_events - before_events),
            "cop_stats_before": before_stats,
            "cop_stats_after": after_stats,
            "recent_event_counts": {
                "spy_sell_info": counts.get("spy_sell_info", 0),
                "steal_agent": counts.get("steal_agent", 0),
                "cop_waiting_threshold": counts.get("cop_waiting_threshold", 0),
                "cop_recover": counts.get("cop_recover", 0),
                "bank_zone_confiscation": counts.get("bank_zone_confiscation", 0),
            },
        }


@population_router.post("/demo/reset-economy")
def reset_economy_endpoint(start_balance: float = 5.0):
    """
    Reset demo to baseline population and balances for a clean judge run.
    """
    with state_lock:
        shared = get_state()
        payload = dict(DEFAULT_RESET_POPULATION)
        payload["clear_existing"] = True
        payload["start_balance"] = float(start_balance)
        population_result = set_population_endpoint(payload)
        entities = shared.setdefault("entities", {})
        balances = shared.setdefault("balances", {})
        for entity_id, entity in entities.items():
            role = str(entity.get("persona_role", entity.get("type", ""))).strip().lower()
            if not role:
                role = str(entity.get("type", "")).strip().lower()
            base_balance = DEFAULT_RESET_BALANCES.get(role)
            if base_balance is not None:
                balances[entity_id] = float(base_balance)
            if role == "spy":
                entity["intel_price"] = max(INTEL_PRICE_MIN, min(INTEL_PRICE_DEFAULT, INTEL_PRICE_MAX))
            entity["home_storage"] = 0.0
            entity["carried_cash"] = 0.0
            entity["lifetime_collected"] = 0.0
            entity["lifetime_lost"] = 0.0
            entity["current_action"] = "idle"
            entity["memory"] = []
            if isinstance(entity.get("mind"), dict):
                entity["mind"]["memory"] = []
                entity["mind"]["reflections"] = []
                entity["mind"]["intent"] = None
                entity["mind"]["last_reflection"] = "reset"
            if isinstance(entity.get("policy"), dict):
                entity["policy"]["last_action"] = None
                entity["policy"]["last_outcome"] = None
        shared["events"] = create_event_buffer(initial=[])
        shared["economy"] = default_economy_state()
        # Keep global tx proof counters/history intact across simulation resets.
        # Arc ledger is immutable; reset should only normalize simulation actors/state.
        shared.setdefault("settlement", {}).update(
            {"pending_intents": [], "last_cycle_tick": 0, "last_cycle_summary": {}}
        )
        return {
            "status": "reset",
            "start_balance": float(start_balance),
            "role_balances": DEFAULT_RESET_BALANCES,
            "population": population_result,
            "message": "Economy reset to baseline demo population.",
        }


@population_router.post("/spawn")
def spawn_endpoint(entity_type: str, entity_id: str | None = None, balance: float = 0.0):
    try:
        resolved_id = entity_id or _next_entity_id(entity_type)
        entity = spawn_entity(entity_id=resolved_id, entity_type=entity_type, balance=balance)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "spawned", "entity": entity, "balance": state["balances"][resolved_id]}


@population_router.post("/population/set")
def set_population_endpoint(payload: dict):
    """
    Set full population in one call.
    Example:
    {
      "workers": 2,
      "cops": 1,
      "bankers": 1,
      "spies": 1,
      "thieves": 0,
      "banks": 0,
      "clear_existing": true,
      "start_balance": 5
    }
    """
    with state_lock:
        workers = max(0, int(payload.get("workers", 0)))
        cops = max(0, int(payload.get("cops", 0)))
        bankers = max(0, int(payload.get("bankers", 0)))
        spies = max(0, int(payload.get("spies", 0)))
        thieves = max(0, int(payload.get("thieves", 0)))
        banks = max(0, int(payload.get("banks", 0)))
        clear_existing = bool(payload.get("clear_existing", True))
        start_balance = float(payload.get("start_balance", 5.0))

        target_total = workers + cops + bankers + spies + thieves + banks
        if target_total > MAX_TOTAL_AGENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Requested total {target_total} exceeds MAX_TOTAL_AGENTS={MAX_TOTAL_AGENTS}",
            )

        entities = state.setdefault("entities", {})
        balances = state.setdefault("balances", {})
        if clear_existing:
            entities.clear()
            balances.clear()
            from core.state import WORK_TREASURY_ID, WORK_TREASURY_START

            balances[WORK_TREASURY_ID] = float(WORK_TREASURY_START)
            state.setdefault("events", []).append(
                {
                    "type": "population_reset",
                    "requested_total": target_total,
                    "work_treasury_balance": balances[WORK_TREASURY_ID],
                    "network": "Arc",
                    "asset": "USDC",
                }
            )

        created = []

        def _spawn_many(prefix: str, count: int, entity_type: str, role_label: str | None = None):
            for i in range(1, count + 1):
                eid = f"{prefix}_{i}"
                entity = spawn_entity(entity_id=eid, entity_type=entity_type, balance=start_balance)
                if role_label:
                    entity["persona_role"] = role_label
                    if role_label == "spy":
                        entity["intel_price"] = max(INTEL_PRICE_MIN, min(INTEL_PRICE_DEFAULT, INTEL_PRICE_MAX))
                created.append({"id": eid, "type": entity_type, "role": entity.get("persona_role", entity_type)})

        _spawn_many("worker", workers, "worker")
        _spawn_many("cop", cops, "cop")
        _spawn_many("banker", bankers, "banker")
        _spawn_many("spy", spies, "banker", role_label="spy")
        _spawn_many("thief", thieves, "thief")
        _spawn_many("bank", banks, "bank")

        return {
            "status": "ok",
            "created_count": len(created),
            "created": created,
            "total_agents": len(state.setdefault("entities", {})),
        }


@population_router.get("/spawn/types")
def spawn_types_endpoint():
    return {
        "allowed_entity_types": sorted(ALLOWED_ENTITY_TYPES),
        "max_total_agents": MAX_TOTAL_AGENTS,
        "current_total_agents": len(state.setdefault("entities", {})),
    }
