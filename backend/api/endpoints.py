import os
import random

from fastapi import APIRouter, HTTPException

from core.loop import run_loop
from core.state import build_personality, default_behavior_settings, default_economy_state, state
from tx.arc import get_tx_runtime_status, inspect_transaction, probe_real_transaction
from utils.logger import get_action_log_stats, read_action_logs

router = APIRouter(prefix="/api", tags=["demo"])
MAX_TOTAL_AGENTS = int(os.getenv("MAX_TOTAL_AGENTS", "200"))
ALLOWED_ENTITY_TYPES = {"worker", "thief", "cop", "banker", "bank"}
ROLE_TO_SMALLVILLE = {
    "worker": "resident_worker",
    "thief": "resident_thief",
    "cop": "resident_guard",
    "banker": "resident_banker",
    "bank": "landmark_bank",
}


def get_state():
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    return state


def get_events():
    return state.setdefault("events", [])


def _infer_actor_action(entity: dict, latest_event: dict | None) -> str:
    event_type = str((latest_event or {}).get("type", ""))
    if entity.get("type") == "cop" and entity.get("target"):
        return "chase"
    if event_type in {"steal_agent", "steal_bank"}:
        return "steal"
    if event_type == "worker_earn":
        return "work"
    if event_type.startswith("bank_") or event_type in {"debit", "credit"}:
        return "bank"
    if event_type == "cop_chase":
        return "chase"
    return "idle"


def build_smallville_frame(limit_events: int = 250):
    shared = get_state()
    entities = shared.setdefault("entities", {})
    balances = shared.setdefault("balances", {})
    events = get_events()
    metrics = shared.setdefault("metrics", {})

    last_event_by_actor = {}
    for event in reversed(events):
        for key in ("worker_id", "thief_id", "cop_id", "bank_id", "target_id", "agent"):
            actor_id = event.get(key)
            if actor_id and actor_id not in last_event_by_actor:
                last_event_by_actor[actor_id] = event

    actors = []
    for entity_id, entity in entities.items():
        latest_event = last_event_by_actor.get(entity_id)
        action = _infer_actor_action(entity, latest_event)
        actor = {
            "id": entity_id,
            "persona_type": ROLE_TO_SMALLVILLE.get(entity.get("type"), "resident"),
            "role": entity.get("type"),
            "x": float(entity.get("x", 0.0) or 0.0),
            "y": float(entity.get("y", 0.0) or 0.0),
            "target_x": float(entity.get("target_x", entity.get("x", 0.0)) or 0.0),
            "target_y": float(entity.get("target_y", entity.get("y", 0.0)) or 0.0),
            "target_id": entity.get("target"),
            "action": action,
            "top_action": entity.get("top_action"),
            "reflection": entity.get("reflection", "neutral"),
            "balance": float(balances.get(entity_id, 0.0) or 0.0),
            "status_line": (
                f"{action} | {entity.get('reflection', 'neutral')}"
            ),
        }
        actors.append(actor)

    event_limit = max(1, min(int(limit_events), 1000))
    return {
        "world": {
            "name": "AgenticEconomy-SmallvilleBridge",
            "tick": int(shared.setdefault("economy", {}).get("tick", 0)),
            "regime": shared.setdefault("economy", {}).get("regime", "balanced"),
            "narration": shared.setdefault("economy", {}).get("narration", ""),
        },
        "actors": actors,
        "metrics": {
            "total_spent": float(metrics.get("total_spent", 0.0) or 0.0),
            "successful_tx": int(metrics.get("successful_tx", 0) or 0),
            "failed_tx": int(metrics.get("failed_tx", 0) or 0),
            "cost_per_action": float(metrics.get("cost_per_action", 0.0) or 0.0),
            "success_rate": float(metrics.get("success_rate", 0.0) or 0.0),
        },
        "events": events[-event_limit:],
        # Compatibility mirror for the current Phaser scene.
        "state": {
            "entities": entities,
            "balances": balances,
            "metrics": metrics,
            "economy": shared.setdefault("economy", default_economy_state()),
        },
    }


def step():
    run_loop(state)
    return {"status": "step complete", "event_count": len(state.setdefault("events", []))}


def _next_entity_id(entity_type: str) -> str:
    entities = state.setdefault("entities", {})
    prefix = f"{entity_type}_"
    highest = 0
    for entity_id in entities.keys():
        if not entity_id.startswith(prefix):
            continue
        suffix = entity_id[len(prefix):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{entity_type}_{highest + 1}"


def spawn_entity(entity_id, entity_type, balance=0.0):
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

    x = random.randint(50, 950)
    y = random.randint(50, 550)
    entity = {
        "id": entity_id,
        "type": entity_type,
        "x": float(x),
        "y": float(y),
        "target_x": float(x),
        "target_y": float(y),
    }
    if entity_type == "cop":
        entity["target"] = None
    entity["memory"] = []
    entity["reflection"] = "neutral"
    entity["policy_bias"] = {}
    entity["personality"] = build_personality(entity_type, behavior_settings)

    entities[entity_id] = entity
    balances.setdefault(entity_id, float(balance))
    return entity


@router.get("/state")
def get_state_endpoint():
    return get_state()


@router.get("/events")
def get_events_endpoint(limit: int | None = None):
    events = get_events()
    if limit is None:
        return events
    capped = max(1, min(int(limit), 5000))
    return events[-capped:]


@router.post("/step")
def step_endpoint():
    return step()


@router.post("/spawn")
def spawn_endpoint(entity_type: str, entity_id: str | None = None, balance: float = 0.0):
    try:
        resolved_id = entity_id or _next_entity_id(entity_type)
        entity = spawn_entity(entity_id=resolved_id, entity_type=entity_type, balance=balance)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "spawned", "entity": entity, "balance": state["balances"][resolved_id]}


@router.get("/spawn/types")
def spawn_types_endpoint():
    return {
        "allowed_entity_types": sorted(ALLOWED_ENTITY_TYPES),
        "max_total_agents": MAX_TOTAL_AGENTS,
        "current_total_agents": len(state.setdefault("entities", {})),
    }


@router.get("/tx/diagnostics")
def tx_diagnostics_endpoint():
    return get_tx_runtime_status()


@router.post("/tx/probe")
def tx_probe_endpoint(amount: float = 0.001):
    try:
        return probe_real_transaction(amount=amount)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"probe failed: {exc}") from exc


@router.get("/tx/inspect")
def tx_inspect_endpoint(id: str):
    try:
        return inspect_transaction(tx_id=id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"inspect failed: {exc}") from exc


@router.get("/settings")
def get_behavior_settings_endpoint():
    return state.setdefault("behavior_settings", default_behavior_settings())


@router.post("/settings")
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


@router.get("/logs")
def get_logs_endpoint(limit: int = 200, after_seq: int | None = None):
    return read_action_logs(limit=limit, after_seq=after_seq)


@router.get("/logs/stats")
def get_logs_stats_endpoint():
    return get_action_log_stats(memory_events=len(state.setdefault("events", [])))


@router.get("/minds")
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


@router.get("/bridge/smallville")
def get_smallville_bridge_frame(limit_events: int = 250):
    return build_smallville_frame(limit_events=limit_events)
