"""Legacy compatibility API routes and payload helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from api.legacy_adapter import LegacyHandlers, execute_legacy_command_request
from api.routes.common import get_events, get_state
from api.routes.population_spawn import (
    _next_entity_id,
    spawn_entity,
    spawn_types_endpoint,
    step,
)
from core import navmesh
from core.state import state

legacy_router = APIRouter(tags=["demo"])

def _legacy_find_persona(persona_id: str) -> tuple[str, dict]:
    entities = state.setdefault("entities", {})
    key = str(persona_id).strip()
    entity = entities.get(key)
    if isinstance(entity, dict):
        return key, entity
    key_lower = key.lower()
    for entity_id, candidate in entities.items():
        if str(entity_id).lower() == key_lower and isinstance(candidate, dict):
            return str(entity_id), candidate
    raise HTTPException(status_code=404, detail=f"Unknown persona: {persona_id}")


def _legacy_schedule_for_entity(entity_id: str, entity: dict) -> dict:
    now_tick = int(state.setdefault("economy", {}).get("tick", 0))
    current_action = str(entity.get("current_action") or entity.get("top_action") or "idle")
    phase = str(entity.get("worker_shift_phase", "n/a"))
    target_x = float(entity.get("target_x", entity.get("x", 0.0)) or 0.0)
    target_y = float(entity.get("target_y", entity.get("y", 0.0)) or 0.0)
    tx, ty = navmesh.world_to_tile(target_x, target_y)
    return {
        "persona_id": entity_id,
        "role": str(entity.get("type", "resident")),
        "current_action": current_action,
        "worker_shift_phase": phase,
        "target_tile": [int(tx), int(ty)],
        "schedule": [
            {"slot": "now", "label": current_action},
            {"slot": "next", "label": f"move_to_tile_{tx}_{ty}"},
        ],
        "tick": now_tick,
    }


def legacy_current_time_payload() -> dict:
    tick = int(state.setdefault("economy", {}).get("tick", 0))
    return {
        "tick": tick,
        "utc_iso": datetime.now(timezone.utc).isoformat(),
    }


def legacy_persona_tile_payload(persona_id: str) -> dict:
    resolved_id, entity = _legacy_find_persona(persona_id)
    x = float(entity.get("x", 0.0) or 0.0)
    y = float(entity.get("y", 0.0) or 0.0)
    tile_x, tile_y = navmesh.world_to_tile(x, y)
    return {
        "persona_id": resolved_id,
        "tile": [int(tile_x), int(tile_y)],
        "world": [round(x, 2), round(y, 2)],
    }


def _event_tile_coords(event: dict) -> tuple[int, int] | None:
    if "tile_x" in event and "tile_y" in event:
        try:
            return int(event["tile_x"]), int(event["tile_y"])
        except Exception:
            return None
    if "x" in event and "y" in event:
        try:
            return navmesh.world_to_tile(float(event["x"]), float(event["y"]))
        except Exception:
            return None
    return None


def _event_persona_ids(event: dict) -> list[str]:
    ids: list[str] = []
    for key, value in event.items():
        if value is None:
            continue
        k = str(key).lower()
        if k == "entity_id" or k.endswith("_id") or k in {"actor", "agent", "worker", "thief", "cop", "bank"}:
            sid = str(value).strip()
            if sid:
                ids.append(sid)
    deduped: list[str] = []
    seen = set()
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def legacy_tile_events_payload(tile_x: int, tile_y: int, limit: int = 80) -> dict:
    events = get_events() or []
    entities = state.setdefault("entities", {})
    hits = []
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        matched = False
        coords = _event_tile_coords(event)
        if coords is not None and coords == (tile_x, tile_y):
            matched = True
        if not matched:
            for persona_id in _event_persona_ids(event):
                persona = entities.get(persona_id)
                if not isinstance(persona, dict):
                    continue
                px = float(persona.get("x", 0.0) or 0.0)
                py = float(persona.get("y", 0.0) or 0.0)
                if navmesh.world_to_tile(px, py) == (tile_x, tile_y):
                    matched = True
                    break
        if matched:
            hits.append(event)
        if len(hits) >= max(1, min(int(limit), 500)):
            break
    hits.reverse()
    return {"tile": [int(tile_x), int(tile_y)], "event_count": len(hits), "events": hits}


def legacy_persona_schedule_payload(persona_id: str) -> dict:
    resolved_id, entity = _legacy_find_persona(persona_id)
    return _legacy_schedule_for_entity(resolved_id, entity)


def legacy_all_persona_schedules_payload() -> dict:
    entities = state.setdefault("entities", {})
    schedules = []
    for entity_id, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        schedules.append(_legacy_schedule_for_entity(str(entity_id), entity))
    return {"count": len(schedules), "schedules": schedules}


@legacy_router.get("/legacy/time")
def legacy_time_endpoint():
    return legacy_current_time_payload()


@legacy_router.get("/legacy/persona/{persona_id}/tile")
def legacy_persona_tile_endpoint(persona_id: str):
    return legacy_persona_tile_payload(persona_id)


@legacy_router.get("/legacy/tile/events")
def legacy_tile_events_endpoint(x: int = Query(...), y: int = Query(...), limit: int = Query(80, ge=1, le=500)):
    return legacy_tile_events_payload(x, y, limit)


@legacy_router.get("/legacy/persona/{persona_id}/schedule")
def legacy_persona_schedule_endpoint(persona_id: str):
    return legacy_persona_schedule_payload(persona_id)


@legacy_router.get("/legacy/persona/schedules")
def legacy_persona_schedules_endpoint():
    return legacy_all_persona_schedules_payload()


@legacy_router.post("/legacy/command")
def legacy_command_endpoint(payload: dict):
    """
    Compatibility shim for old text-based operator commands.

    Supports single or batch command payloads:
      {"command": "run 10"}
      {"commands": ["state", "spawn worker balance=5", "run 3"]}
    """
    def _legacy_spawn(entity_type: str, entity_id: str | None, balance: float) -> dict:
        resolved_id = entity_id or _next_entity_id(entity_type)
        entity = spawn_entity(entity_id=resolved_id, entity_type=entity_type, balance=balance)
        return {"status": "spawned", "entity": entity, "balance": state["balances"][resolved_id]}

    handlers = LegacyHandlers(
        step=step,
        state=get_state,
        spawn=_legacy_spawn,
        spawn_types=spawn_types_endpoint,
        current_time=legacy_current_time_payload,
        persona_tile=legacy_persona_tile_payload,
        tile_events=legacy_tile_events_payload,
        persona_schedule=legacy_persona_schedule_payload,
        all_persona_schedules=legacy_all_persona_schedules_payload,
    )
    try:
        return execute_legacy_command_request(payload, handlers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


