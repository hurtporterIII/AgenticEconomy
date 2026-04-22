from __future__ import annotations

import os
import random
import json
from pathlib import Path

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
TILE_SIZE = 32.0
MAP_SUMMARY_PATH = Path(__file__).resolve().parents[1] / "store" / "map_summary.json"
_MAP_LAYOUT_CACHE = None
_SECTOR_CENTERS: dict[str, dict] = {}

HOME_SECTORS = [
    "Adam Smith's house",
    "Yuriko Yamamoto's house",
    "Moore family's house",
    "Tamara Taylor and Carmen Ortiz's house",
    "Moreno family's house",
    "Lin family's house",
    "Arthur Burton's apartment",
    "Ryan Park's apartment",
    "Isabella Rodriguez's apartment",
    "Giorgio Rossi's apartment",
    "Carlos Gomez's apartment",
    "artist's co-living space",
    "Dorm for Oak Hill College",
]
WORK_SECTORS = [
    "Harvey Oak Supply Store",
    "The Willows Market and Pharmacy",
    "Hobbs Cafe",
    "Oak Hill College",
]
BANK_SECTORS = [
    "The Willows Market and Pharmacy",
    "Harvey Oak Supply Store",
]
COP_PATROL_SECTORS = [
    "Oak Hill College",
    "The Willows Market and Pharmacy",
    "Johnson Park",
    "The Rose and Crown Pub",
]
MAP_ROAM_SECTORS = [
    "Giorgio Rossi's apartment",
    "Carlos Gomez's apartment",
    "Arthur Burton's apartment",
    "Ryan Park's apartment",
    "Isabella Rodriguez's apartment",
    "artist's co-living space",
    "Hobbs Cafe",
    "The Rose and Crown Pub",
    "Oak Hill College",
    "Dorm for Oak Hill College",
    "Johnson Park",
    "Harvey Oak Supply Store",
    "The Willows Market and Pharmacy",
    "Adam Smith's house",
    "Yuriko Yamamoto's house",
    "Moore family's house",
    "Tamara Taylor and Carmen Ortiz's house",
    "Moreno family's house",
    "Lin family's house",
]
ENTRY_NAV_SECTORS = {
    "Giorgio Rossi's apartment",
    "Carlos Gomez's apartment",
    "Arthur Burton's apartment",
    "Ryan Park's apartment",
    "Isabella Rodriguez's apartment",
    "artist's co-living space",
    "Hobbs Cafe",
    "The Rose and Crown Pub",
    "Oak Hill College",
    "Dorm for Oak Hill College",
    "Harvey Oak Supply Store",
    "The Willows Market and Pharmacy",
    "Adam Smith's house",
    "Yuriko Yamamoto's house",
    "Moore family's house",
    "Tamara Taylor and Carmen Ortiz's house",
    "Moreno family's house",
    "Lin family's house",
}


def _load_map_layout() -> None:
    global _MAP_LAYOUT_CACHE, _SECTOR_CENTERS
    if _MAP_LAYOUT_CACHE is not None:
        return
    try:
        data = json.loads(MAP_SUMMARY_PATH.read_text(encoding="utf-8"))
        _MAP_LAYOUT_CACHE = data
        _SECTOR_CENTERS = data.get("sector_centers", {})
    except Exception:
        _MAP_LAYOUT_CACHE = {}
        _SECTOR_CENTERS = {}


def _stable_lane_offset(actor_id: str, max_abs: int = 36) -> tuple[float, float]:
    seed = sum(ord(ch) for ch in str(actor_id))
    x = ((seed * 7) % (max_abs * 2 + 1)) - max_abs
    y = ((seed * 11) % (max_abs * 2 + 1)) - max_abs
    return float(x), float(y)


def _home_coords(actor_id: str) -> tuple[float, float]:
    _load_map_layout()
    if not _SECTOR_CENTERS:
        dx, dy = _stable_lane_offset(f"home:{actor_id}", max_abs=40)
        return 640.0 + dx, 720.0 + dy
    seed = sum(ord(ch) for ch in str(actor_id))
    sector = HOME_SECTORS[seed % len(HOME_SECTORS)]
    return _sector_nav_point(sector, actor_id)


def _sector_point(sector_name: str, actor_id: str, spread: float = 0.35) -> tuple[float, float]:
    _load_map_layout()
    info = _SECTOR_CENTERS.get(sector_name)
    if not info:
        cx, cy = 80.0, 50.0
        return (cx * TILE_SIZE, cy * TILE_SIZE)

    bbox = info.get("bbox", [0, 0, int(info.get("cx", 80)), int(info.get("cy", 50))])
    min_x, min_y, max_x, max_y = [float(v) for v in bbox]
    center_x = float(info.get("cx", (min_x + max_x) / 2))
    center_y = float(info.get("cy", (min_y + max_y) / 2))

    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    dx, dy = _stable_lane_offset(f"{sector_name}:{actor_id}", max_abs=100)
    nx = dx / 100.0
    ny = dy / 100.0

    tx = center_x + (nx * width * spread)
    ty = center_y + (ny * height * spread)

    tx = max(min_x + 0.25, min(max_x - 0.25, tx))
    ty = max(min_y + 0.25, min(max_y - 0.25, ty))
    return tx * TILE_SIZE, ty * TILE_SIZE


def _sector_entry_point(sector_name: str, actor_id: str) -> tuple[float, float]:
    """Return a walkable approach point near a sector's likely entrance."""
    _load_map_layout()
    info = _SECTOR_CENTERS.get(sector_name)
    if not info:
        return _sector_point(sector_name, actor_id, spread=0.25)

    bbox = info.get("bbox", [0, 0, int(info.get("cx", 80)), int(info.get("cy", 50))])
    min_x, min_y, max_x, max_y = [float(v) for v in bbox]
    center_x = float(info.get("cx", (min_x + max_x) / 2))
    width = max(1.0, max_x - min_x)
    dx, _ = _stable_lane_offset(f"entry:{sector_name}:{actor_id}", max_abs=100)
    x_jitter = (dx / 100.0) * width * 0.18

    # Most building doors in this tileset are on the south edge.
    tx = max(min_x + 0.6, min(max_x - 0.6, center_x + x_jitter))
    ty = max_y + 1.25

    map_meta = (_MAP_LAYOUT_CACHE or {}).get("meta", {})
    map_w = float(map_meta.get("w", 140) or 140)
    map_h = float(map_meta.get("h", 100) or 100)
    tx = max(0.5, min(map_w - 0.5, tx))
    ty = max(0.5, min(map_h - 0.5, ty))
    return tx * TILE_SIZE, ty * TILE_SIZE


def _sector_nav_point(sector_name: str, actor_id: str) -> tuple[float, float]:
    if sector_name in ENTRY_NAV_SECTORS:
        return _sector_entry_point(sector_name, actor_id)
    return _sector_point(sector_name, actor_id, spread=0.35)


def _pick_sector(sectors: list[str], actor_id: str) -> str:
    seed = sum(ord(ch) for ch in str(actor_id))
    return sectors[seed % len(sectors)]


def _pick_sector_cycle(sectors: list[str], actor_id: str, tick: int, cadence: int = 8) -> str:
    if not sectors:
        return "Johnson Park"
    seed = sum(ord(ch) for ch in str(actor_id)) % len(sectors)
    step_idx = max(0, tick // max(1, cadence))
    return sectors[(seed + step_idx) % len(sectors)]


def _bridge_roam_goal(
    entity: dict,
    actor_id: str,
    tick: int,
    sectors: list[str],
    label: str,
    hold_ticks: int = 18,
    force_retarget: bool = False,
) -> tuple[str, float, float]:
    """
    Sticky map-wide roaming target for bridge visualization.
    Prevents rapid per-tick retargeting that causes circular jitter.
    """
    if not sectors:
        sx, sy = _sector_nav_point("Johnson Park", actor_id)
        return "Johnson Park", sx, sy

    key_prefix = f"bridge_goal_{label}"
    idx_key = f"{key_prefix}_idx"
    until_key = f"{key_prefix}_until"
    zone_key = f"{key_prefix}_zone"
    x_key = f"{key_prefix}_x"
    y_key = f"{key_prefix}_y"

    idx = int(entity.get(idx_key, sum(ord(ch) for ch in actor_id) % len(sectors)))
    until_tick = int(entity.get(until_key, -1))

    if force_retarget or tick >= until_tick or zone_key not in entity:
        idx = (idx + 1) % len(sectors)
        zone = sectors[idx]
        x, y = _sector_nav_point(zone, actor_id)
        entity[idx_key] = idx
        entity[until_key] = tick + max(6, int(hold_ticks))
        entity[zone_key] = zone
        entity[x_key] = float(x)
        entity[y_key] = float(y)

    return (
        str(entity.get(zone_key)),
        float(entity.get(x_key, 0.0) or 0.0),
        float(entity.get(y_key, 0.0) or 0.0),
    )


def _bridge_stuck_retarget(entity: dict, actor_id: str, action: str, tick: int) -> bool:
    """
    Detect agents that are effectively parked and request a new roam goal.
    Exempts active interaction states to avoid interrupting real actions.
    """
    active_actions = {"chase", "steal", "bank", "scan", "work"}
    if action in active_actions:
        entity["bridge_stuck_count"] = 0
        entity["bridge_stuck_last_tick"] = tick
        entity["bridge_stuck_last_x"] = float(entity.get("x", 0.0) or 0.0)
        entity["bridge_stuck_last_y"] = float(entity.get("y", 0.0) or 0.0)
        return False

    x = float(entity.get("x", 0.0) or 0.0)
    y = float(entity.get("y", 0.0) or 0.0)
    prev_tick = int(entity.get("bridge_stuck_last_tick", tick))
    prev_x = float(entity.get("bridge_stuck_last_x", x) or x)
    prev_y = float(entity.get("bridge_stuck_last_y", y) or y)

    # Ignore duplicate checks inside the same tick.
    if tick == prev_tick:
        return False

    delta = abs(x - prev_x) + abs(y - prev_y)
    stuck_count = int(entity.get("bridge_stuck_count", 0))
    if delta <= 3.0:
        stuck_count += 1
    else:
        stuck_count = 0

    entity["bridge_stuck_count"] = stuck_count
    entity["bridge_stuck_last_tick"] = tick
    entity["bridge_stuck_last_x"] = x
    entity["bridge_stuck_last_y"] = y

    if stuck_count >= 4:
        entity["bridge_stuck_count"] = 0
        return True
    return False


def _sector_footprint(sector_name: str) -> dict:
    _load_map_layout()
    info = _SECTOR_CENTERS.get(sector_name, {})
    bbox = info.get("bbox", [0, 0, 0, 0])
    min_tx, min_ty, max_tx, max_ty = [float(v) for v in bbox]
    w_tiles = max(0.0, (max_tx - min_tx + 1.0))
    h_tiles = max(0.0, (max_ty - min_ty + 1.0))
    return {
        "name": sector_name,
        "tiles_bbox": {"min_x": min_tx, "min_y": min_ty, "max_x": max_tx, "max_y": max_ty},
        "pixel_bbox": {
            "min_x": min_tx * TILE_SIZE,
            "min_y": min_ty * TILE_SIZE,
            "max_x": (max_tx + 1.0) * TILE_SIZE,
            "max_y": (max_ty + 1.0) * TILE_SIZE,
        },
        "center_tile": {"x": float(info.get("cx", 0.0) or 0.0), "y": float(info.get("cy", 0.0) or 0.0)},
        "center_pixel": {
            "x": float(info.get("cx", 0.0) or 0.0) * TILE_SIZE,
            "y": float(info.get("cy", 0.0) or 0.0) * TILE_SIZE,
        },
        "tile_count": int(info.get("count", 0) or 0),
        "approx_area_px2": w_tiles * h_tiles * (TILE_SIZE * TILE_SIZE),
    }


def _resolve_destination(entity: dict, latest_event: dict | None, entities: dict, tick: int) -> tuple[str, float, float]:
    role = str(entity.get("type", "resident"))
    action = _infer_actor_action(entity, latest_event)
    entity_id = str(entity.get("id", ""))
    force_retarget = _bridge_stuck_retarget(entity, entity_id, action, tick)

    if role == "worker":
        if action == "work":
            return _bridge_roam_goal(entity, entity_id, tick, WORK_SECTORS, "work", hold_ticks=16)
        if action == "bank":
            return _bridge_roam_goal(entity, entity_id, tick, BANK_SECTORS, "bank", hold_ticks=14)
        return _bridge_roam_goal(
            entity, entity_id, tick, MAP_ROAM_SECTORS, "roam", hold_ticks=14, force_retarget=force_retarget
        )

    if role in {"bank", "banker"}:
        banker_sectors = BANK_SECTORS + WORK_SECTORS + ["Johnson Park", "Hobbs Cafe"]
        return _bridge_roam_goal(
            entity, entity_id, tick, banker_sectors, "banker", hold_ticks=20, force_retarget=force_retarget
        )

    if role == "thief":
        target_id = entity.get("target") or (latest_event or {}).get("target_id")
        target = entities.get(target_id) if target_id else None
        if action == "chase" and target:
            return "target", float(target.get("x", 0.0) or 0.0), float(target.get("y", 0.0) or 0.0)
        if action == "steal":
            target = entities.get((latest_event or {}).get("target_id"))
            if target:
                tx = float(target.get("x", 0.0) or 0.0)
                ty = float(target.get("y", 0.0) or 0.0)
                return "target", tx, ty
            return _bridge_roam_goal(entity, entity_id, tick, BANK_SECTORS + ["The Rose and Crown Pub"], "steal", hold_ticks=10)
        if action == "bank":
            return _bridge_roam_goal(entity, entity_id, tick, BANK_SECTORS, "bank", hold_ticks=12)
        return _bridge_roam_goal(
            entity, entity_id, tick, MAP_ROAM_SECTORS, "roam", hold_ticks=10, force_retarget=force_retarget
        )

    if role == "cop":
        target_id = entity.get("target") or (latest_event or {}).get("target_id")
        target = entities.get(target_id) if target_id else None
        if action == "chase" and target:
            return "target", float(target.get("x", 0.0) or 0.0), float(target.get("y", 0.0) or 0.0)
        patrol_sectors = COP_PATROL_SECTORS + MAP_ROAM_SECTORS
        return _bridge_roam_goal(
            entity, entity_id, tick, patrol_sectors, "patrol", hold_ticks=10, force_retarget=force_retarget
        )

    return _bridge_roam_goal(
        entity, entity_id, tick, MAP_ROAM_SECTORS, "default", hold_ticks=14, force_retarget=force_retarget
    )


def get_state():
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    return state


def get_events():
    return state.setdefault("events", [])


def _infer_actor_action(entity: dict, latest_event: dict | None) -> str:
    role = str(entity.get("type", "resident"))
    event_type = str((latest_event or {}).get("type", ""))
    if role == "cop" and entity.get("target"):
        return "chase"

    if role == "worker":
        if event_type == "worker_earn":
            return "work"
        if event_type.startswith("bank_"):
            return "bank"
        return "idle"

    if role == "thief":
        if event_type in {"steal_agent", "steal_bank"}:
            return "steal"
        if event_type == "thief_deposit":
            return "bank"
        if entity.get("target"):
            return "chase"
        return "idle"

    if role == "cop":
        if event_type in {"cop_chase"}:
            return "chase"
        if event_type in {"api_call", "cop_scan"}:
            return "scan"
        return "patrol"

    if role in {"bank", "banker"}:
        if event_type.startswith("bank_") or event_type in {"debit", "credit"}:
            return "bank"
        return "idle"

    if event_type.startswith("bank_") or event_type in {"debit", "credit"}:
        return "bank"
    return "idle"


def build_smallville_frame(limit_events: int = 250, include_debug: bool = False):
    shared = get_state()
    entities = shared.setdefault("entities", {})
    balances = shared.setdefault("balances", {})
    events = get_events()
    metrics = shared.setdefault("metrics", {})
    tick = int(shared.setdefault("economy", {}).get("tick", 0))

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
        dest_zone, dest_x, dest_y = _resolve_destination(entity, latest_event, entities, tick)
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
            "dest_zone": dest_zone,
            "dest_x": float(dest_x),
            "dest_y": float(dest_y),
            "top_action": entity.get("top_action"),
            "reflection": entity.get("reflection", "neutral"),
            "balance": float(balances.get(entity_id, 0.0) or 0.0),
            "status_line": (
                f"{action} | {entity.get('reflection', 'neutral')} | {dest_zone}"
            ),
        }
        actors.append(actor)

    payload = {
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
    }
    if include_debug:
        event_limit = max(1, min(int(limit_events), 1000))
        payload["events"] = events[-event_limit:]
        payload["state"] = {
            "entities": entities,
            "balances": balances,
            "metrics": metrics,
            "economy": shared.setdefault("economy", default_economy_state()),
        }
    return payload


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

    if entity_type in {"bank", "banker"}:
        sx, sy = _sector_point(_pick_sector(BANK_SECTORS, entity_id), entity_id, spread=0.2)
    elif entity_type == "worker":
        sx, sy = _home_coords(entity_id)
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
def get_smallville_bridge_frame(limit_events: int = 250, include_debug: bool = False):
    return build_smallville_frame(limit_events=limit_events, include_debug=include_debug)


@router.get("/map/areas")
def get_map_areas_endpoint():
    _load_map_layout()
    sectors = {
        "home_sectors": HOME_SECTORS,
        "work_sectors": WORK_SECTORS,
        "bank_sectors": BANK_SECTORS,
        "cop_patrol_sectors": COP_PATROL_SECTORS,
        "map_roam_sectors": MAP_ROAM_SECTORS,
    }
    return {
        "map": (_MAP_LAYOUT_CACHE or {}).get("meta", {"w": 140, "h": 100, "tile": 32}),
        "areas": {group: [_sector_footprint(name) for name in names] for group, names in sectors.items()},
    }
