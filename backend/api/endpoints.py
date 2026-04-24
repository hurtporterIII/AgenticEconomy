from __future__ import annotations

import os
import random
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from api.legacy_adapter import LegacyHandlers, execute_legacy_command_request
from core.loop import run_loop
from core import navmesh
from core.state import build_personality, default_behavior_settings, default_economy_state, state
from tx.arc import get_tx_runtime_status, inspect_transaction, probe_real_transaction
from utils.logger import get_action_log_stats, read_action_logs

router = APIRouter(prefix="/api", tags=["demo"])
# Bumped when bridge JSON contract changes; `/api/bridge/manifest` and `world.bridge_revision` must match.
BRIDGE_CODE_REVISION = "ae-smallville-lifetime-v2"
MAX_TOTAL_AGENTS = int(os.getenv("MAX_TOTAL_AGENTS", "200"))
DEFAULT_RESET_POPULATION = {
    "workers": 6,
    "cops": 1,
    "bankers": 1,
    "spies": 1,
    "thieves": 1,
    "banks": 0,
}
DEFAULT_RESET_BALANCES = {
    "worker": 1.0,
    "cop": 5.0,
    "banker": 5.0,
    "spy": 5.0,
    "thief": 5.0,
    "bank": 50.0,
}
ALLOWED_ENTITY_TYPES = {"worker", "thief", "cop", "banker", "bank"}
ROLE_TO_SMALLVILLE = {
    "worker": "resident_worker",
    "thief": "resident_thief",
    "cop": "resident_guard",
    "banker": "resident_banker",
    "bank": "landmark_bank",
}
# Single-sourced from core/locations.py. Do not redefine role->building here.
from core import locations as _locations
ROLE_HUB_DEFAULTS = _locations.flat_hub_defaults()
TILE_SIZE = 32.0
MAP_SUMMARY_PATH = Path(__file__).resolve().parents[1] / "store" / "map_summary.json"
BUILDING_CATALOG_PATH = Path(__file__).resolve().parents[1] / "store" / "building_catalog.json"
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
WORKER_MONEY_SECTORS = ["The Willows Market and Pharmacy"]  # B11
WORKER_HOME_SECTORS = ["artist's co-living space"]  # B08
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


def _load_building_catalog() -> dict:
    if not BUILDING_CATALOG_PATH.exists():
        return {}
    try:
        return json.loads(BUILDING_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _building_anchor_point(building_id: str, anchor: str = "center") -> tuple[float, float] | None:
    anchor = str(anchor or "center").strip().lower()
    if anchor not in {"entry", "inside", "center"}:
        anchor = "center"
    catalog = _load_building_catalog()
    for b in catalog.get("buildings", []):
        if str(b.get("id", "")).upper() != str(building_id).upper():
            continue
        if anchor == "inside":
            ep = b.get("inside_px", b.get("center_px", b.get("entry_px", {})))
        elif anchor == "center":
            ep = b.get("center_px", b.get("entry_px", {}))
        else:
            ep = b.get("entry_px", {})
        try:
            return float(ep.get("x")), float(ep.get("y"))
        except Exception:
            return None
    return None


def _stable_offset(seed_key: str, max_abs: int = 16) -> tuple[float, float]:
    seed = sum(ord(ch) for ch in str(seed_key))
    ox = ((seed * 7) % (max_abs * 2 + 1)) - max_abs
    oy = ((seed * 11) % (max_abs * 2 + 1)) - max_abs
    return float(ox), float(oy)


def _spot_target(
    building_id: str,
    anchor: str,
    spot: str,
    entity_id: str,
    ordinal: int,
) -> tuple[float, float] | None:
    spot_name = str(spot or "").strip().lower()
    if spot_name in {"", "anchor"}:
        return _building_anchor_point(building_id, anchor)

    entry = _building_anchor_point(building_id, "entry")
    inside = _building_anchor_point(building_id, "inside")
    center = _building_anchor_point(building_id, "center")
    if not entry and not inside and not center:
        return None

    if spot_name == "entry":
        base = entry or inside or center
        return float(base[0]), float(base[1])
    if spot_name == "inside":
        base = inside or center or entry
        return float(base[0]), float(base[1])
    if spot_name == "center":
        base = center or inside or entry
        return float(base[0]), float(base[1])

    # "meeting" keeps agents close in a small circle.
    if spot_name == "meeting":
        base = inside or center or entry
        radius = 22.0
        angle = (ordinal % 12) * (2.0 * 3.141592653589793 / 12.0)
        return float(base[0] + (radius * math.cos(angle))), float(base[1] + (radius * math.sin(angle)))

    # "desks" spreads agents in a wider ring pattern around an interior point.
    if spot_name == "desks":
        base = inside or center or entry
        ring = (ordinal // 12) + 1
        radius = 28.0 + (ring * 18.0)
        angle = (ordinal % 12) * (2.0 * 3.141592653589793 / 12.0)
        return float(base[0] + (radius * math.cos(angle))), float(base[1] + (radius * math.sin(angle)))

    # "queue" lines agents near the entry (useful for demos).
    if spot_name == "queue":
        base = entry or inside or center
        step = 18.0
        return float(base[0] + (ordinal * step)), float(base[1] + 10.0)

    # Unknown spot: deterministic micro-jitter around requested anchor.
    base = _building_anchor_point(building_id, anchor) or inside or center or entry
    ox, oy = _stable_offset(f"{building_id}:{spot_name}:{entity_id}", max_abs=14)
    return float(base[0] + ox), float(base[1] + oy)


def _nearest_building_id(x: float, y: float, building_entries: dict[str, tuple[float, float]]) -> str | None:
    nearest = None
    nearest_d = None
    for b_id, (bx, by) in building_entries.items():
        d = ((x - bx) ** 2) + ((y - by) ** 2)
        if nearest_d is None or d < nearest_d:
            nearest = b_id
            nearest_d = d
    return nearest


def _hub_destination(
    shared: dict,
    hub_key: str,
    suffix: str,
    anchor: str = "center",
    default: tuple[float, float] = (912.0, 1168.0),
) -> tuple[str, float, float]:
    movement = shared.setdefault("movement", {})
    hubs = movement.setdefault("role_hubs", {})
    for key, value in ROLE_HUB_DEFAULTS.items():
        hubs.setdefault(key, value)
    bid = str(hubs.get(hub_key, ROLE_HUB_DEFAULTS.get(hub_key, ""))).strip().upper()
    if not bid:
        bid = ROLE_HUB_DEFAULTS.get(hub_key, "B08")

    target = (
        _building_anchor_point(bid, anchor)
        or _building_anchor_point(bid, "center")
        or _building_anchor_point(bid, "inside")
        or _building_anchor_point(bid, "entry")
        or default
    )
    catalog = _load_building_catalog()
    b_name = bid
    for b in catalog.get("buildings", []):
        if str(b.get("id", "")).upper() == bid:
            b_name = str(b.get("name", bid))
            break
    label = f"{bid} {b_name} | {suffix}".strip()
    return label, float(target[0]), float(target[1])


def _resolve_destination(
    shared: dict,
    entity: dict,
    latest_event: dict | None,
    entities: dict,
    tick: int,
) -> tuple[str, float, float]:
    role = str(entity.get("persona_role", entity.get("type", "resident"))).lower()
    action = _infer_actor_action(entity, latest_event)
    entity_id = str(entity.get("id", ""))
    _bridge_stuck_retarget(entity, entity_id, action, tick)

    if role == "worker":
        shift = str(entity.get("worker_shift_phase", "to_mine")).strip() or "to_mine"
        if shift == "to_bank" or action in {"commute_bank", "bank"}:
            return _hub_destination(shared, "bank_home", "Bank", anchor="entry")
        if shift == "to_home" or action in {"return_home", "store_home"}:
            return _hub_destination(shared, "worker_home", "Worker Home", anchor="entry")
        return _hub_destination(shared, "worker_work", "Worker Work", anchor="entry")

    if role == "spy":
        return _hub_destination(shared, "spy_home", "Spy Home", anchor="center")

    if role in {"bank", "banker"}:
        return _hub_destination(shared, "bank_home", "Bank Home", anchor="center")

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
            return _hub_destination(shared, "thief_home", "Thief Home", anchor="center")
        if action == "bank":
            return _hub_destination(shared, "bank_home", "Bank Home", anchor="center")
        return _hub_destination(shared, "thief_home", "Thief Home", anchor="center")

    if role == "cop":
        target_id = entity.get("target") or (latest_event or {}).get("target_id")
        target = entities.get(target_id) if target_id else None
        if action == "chase" and target:
            return "target", float(target.get("x", 0.0) or 0.0), float(target.get("y", 0.0) or 0.0)
        return _hub_destination(shared, "cop_home", "Cop Home", anchor="center")

    return _hub_destination(shared, "worker_home", "Worker Home", anchor="center")


def get_state():
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    return state


def get_events():
    return state.setdefault("events", [])


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


def _infer_actor_action(entity: dict, latest_event: dict | None) -> str:
    role = str(entity.get("type", "resident"))
    top_action = str(entity.get("top_action", "")).strip().lower()
    event_type = str((latest_event or {}).get("type", ""))
    if role == "cop" and entity.get("target"):
        return "chase"

    if role == "worker":
        shift = str(entity.get("worker_shift_phase", "to_mine")).strip() or "to_mine"
        if shift == "to_bank":
            return "bank"
        if shift == "to_home":
            return "return_home"
        if top_action in {"commute_mine", "work", "return_home", "store_home", "commute_bank"}:
            return top_action
        if event_type == "worker_store_home":
            return "store_home"
        if event_type == "worker_commute_home":
            return "return_home"
        if event_type == "worker_commute_mine":
            return "commute_mine"
        if event_type == "worker_commute_bank":
            return "commute_bank"
        if event_type == "worker_bank_deposit":
            return "bank"
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


def _flow_n(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _classify_flow_event(entity_id: str, event: dict) -> tuple[str, float] | None:
    """Mirror frontend/src/ui/dashboard.js classifyFlowEvent for bridge/UI parity."""
    et = str(event.get("type") or "")
    n = _flow_n
    eid = str(entity_id).strip()
    if et == "worker_earn" and str(event.get("worker_id", "")).strip() == eid:
        return ("earn", abs(n(event.get("amount"))))
    if et == "bank_fee_nano":
        if str(event.get("worker_id", "")).strip() == eid:
            return ("bank_fee", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("fee_in", abs(n(event.get("amount"))))
    if et == "worker_bank_deposit":
        if str(event.get("worker_id", "")).strip() == eid:
            return ("deposit", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("deposit_in", abs(n(event.get("amount"))))
    if et == "thief_deposit":
        if str(event.get("thief_id", "")).strip() == eid:
            return ("deposit", -abs(n(event.get("amount"))))
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return ("deposit_in", abs(n(event.get("amount"))))
    if et in {"worker_home_store", "worker_stash", "worker_store_home"} and str(
        event.get("worker_id", "")
    ).strip() == eid:
        return ("store", abs(n(event.get("amount"))))
    if et == "steal_agent":
        if str(event.get("thief_id", "")).strip() == eid:
            return ("steal", abs(n(event.get("amount"))))
        if str(event.get("target_id", "")).strip() == eid or str(event.get("worker_id", "")).strip() == eid:
            return ("robbed", -abs(n(event.get("amount"))))
    if et == "cop_recover":
        if str(event.get("cop_id", "")).strip() == eid:
            amt = event.get("amount")
            if amt is None:
                amt = event.get("recovered")
            return ("recover", abs(n(amt)))
        if str(event.get("thief_id", "")).strip() == eid:
            amt = event.get("amount")
            if amt is None:
                amt = event.get("recovered")
            return ("lost", -abs(n(amt)))
    if et == "bank_zone_confiscation":
        amt = event.get("amount")
        if str(event.get("cop_id", "")).strip() == eid:
            return ("confiscate", abs(n(amt)))
        if str(event.get("thief_id", "")).strip() == eid:
            return ("confiscated_loss", -abs(n(amt)))
    if et == "spy_sell_info":
        price = abs(n(event.get("price") or event.get("amount") or 0.000005))
        if str(event.get("buyer_id", "")).strip() == eid:
            return ("intel_payment", -price)
        if str(event.get("spy_id", "")).strip() == eid:
            return ("intel_sale", price)
    if et == "redistribution" and str(event.get("cop_id", "")).strip() == eid:
        kept = abs(n(event.get("cop_amount") or event.get("kept_amount") or event.get("cop_share") or 0.0))
        if kept > 0:
            return ("kept", kept)
    return None


def _format_money_signed(value: float) -> str:
    v = float(value or 0.0)
    sign = "+" if v >= 0 else "-"
    return f"{sign}{abs(v):.6f}"


def _format_money_abs(value: float) -> str:
    return f"{abs(float(value or 0.0)):.6f}"


def _entity_flow_role(entity: dict | None) -> str:
    if not isinstance(entity, dict):
        return "agent"
    pr = str(entity.get("persona_role", "") or "").strip().lower()
    if pr in {"spy"}:
        return "spy"
    t = str(entity.get("type", "") or "").strip().lower()
    if t in {"worker", "thief", "cop", "bank", "banker"}:
        return t
    return pr or t or "agent"


def _flow_segment_final(role: str, key: str, total_signed: float) -> str | None:
    """One clause per bucket; amounts use explicit + / - (STEP 2 verb lock)."""
    v = float(total_signed or 0.0)
    if abs(v) < 1e-21:
        return None
    amt = _format_money_signed(v)
    r = (role or "agent").strip().lower()

    if key == "earn":
        if r != "worker":
            return None
        return f"Earned {amt} at work"

    if key == "bank_fee":
        if r == "worker":
            return f"Lost {amt} to fees"
        return None

    if key == "deposit":
        if r == "worker" or r == "cop":
            return f"Deposited {amt} to bank"
        if r == "thief":
            return f"Paid {amt} to bank"
        return None

    if key == "store" and r == "worker":
        return f"Stored {amt} at home"

    if key == "robbed" and r == "worker":
        return f"Lost {amt} to theft"

    if key == "intel_payment":
        if r in {"thief", "cop"}:
            return f"Paid {amt} for intel"
        if r == "worker":
            return f"Lost {amt} to intel"
        return None

    if key == "intel_sale" and r == "spy":
        return f"Received {amt} for intel"

    if key == "steal" and r == "thief":
        return f"Stole {amt} from worker"

    if key == "recover" and r == "cop":
        return f"Recovered {amt} from thief"

    if key == "lost" and r == "thief":
        return f"Lost {amt} to recovery"

    if key == "kept" and r == "cop":
        return f"Kept {amt} after split"

    if key == "confiscate" and r == "cop":
        return f"Confiscated {amt} from bank robbery"

    if key == "confiscated_loss" and r == "thief":
        return f"Confiscated {amt} after bank robbery"

    if key == "fee_in" and r in {"bank", "banker"}:
        return f"Collected {_format_money_signed(abs(v))} in fees"

    if key == "deposit_in" and r in {"bank", "banker"}:
        return f"Received {_format_money_signed(abs(v))} in deposits"

    return None


def _build_flow_summary_line(entity_id: str, entity: dict | None, recent_events: list) -> str:
    totals = {
        "earn": 0.0,
        "bank_fee": 0.0,
        "deposit": 0.0,
        "store": 0.0,
        "robbed": 0.0,
        "steal": 0.0,
        "recover": 0.0,
        "intel_payment": 0.0,
        "intel_sale": 0.0,
        "lost": 0.0,
        "kept": 0.0,
        "confiscate": 0.0,
        "confiscated_loss": 0.0,
        "fee_in": 0.0,
        "deposit_in": 0.0,
    }
    for ev in recent_events:
        row = _classify_flow_event(entity_id, ev)
        if not row:
            continue
        key, amt = row
        totals[key] = totals.get(key, 0.0) + float(amt or 0.0)
    role = _entity_flow_role(entity)
    order = [
        "earn",
        "bank_fee",
        "deposit",
        "store",
        "robbed",
        "intel_payment",
        "steal",
        "recover",
        "lost",
        "kept",
        "confiscate",
        "confiscated_loss",
        "intel_sale",
        "fee_in",
        "deposit_in",
    ]
    parts: list[str] = []
    for k in order:
        seg = _flow_segment_final(role, k, float(totals.get(k, 0.0) or 0.0))
        if seg:
            parts.append(seg)
    return " · ".join(parts) if parts else "No recent financial flow"


def _event_touches_actor(entity_id: str, event: dict) -> bool:
    eid = str(entity_id).strip()
    if _classify_flow_event(eid, event) is not None:
        return True
    keys = (
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "agent",
        "agent_id",
    )
    return any(str(event.get(k, "")).strip() == eid for k in keys)


def _narrate_recent_line(entity_id: str, role: str, event: dict) -> str:
    """Single-line narrative: Verb signed_amount context (last-5 list; STEP 3)."""
    et = str(event.get("type") or "")
    n = _flow_n
    eid = str(entity_id).strip()
    role = (role or "agent").lower()
    amt = event.get("amount")

    if et == "worker_earn" and str(event.get("worker_id", "")).strip() == eid:
        return f"Earned {_format_money_signed(abs(n(amt)))} at work"
    if et == "bank_fee_nano" and str(event.get("worker_id", "")).strip() == eid:
        return f"Lost {_format_money_signed(-abs(n(amt)))} to fees"
    if et == "bank_fee_nano":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Collected {_format_money_signed(abs(n(amt)))} in fees"
    if et == "worker_bank_deposit" and str(event.get("worker_id", "")).strip() == eid:
        return f"Deposited {_format_money_signed(-abs(n(amt)))} to bank"
    if et == "worker_bank_deposit":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Received {_format_money_signed(abs(n(amt)))} in deposits"
    if et == "thief_deposit" and str(event.get("thief_id", "")).strip() == eid:
        return f"Paid {_format_money_signed(-abs(n(amt)))} to bank"
    if et == "thief_deposit":
        bid = event.get("bank_id")
        if bid is not None and str(bid).strip() == eid:
            return f"Received {_format_money_signed(abs(n(amt)))} in deposits"
    if et in {"worker_home_store", "worker_stash", "worker_store_home"} and str(
        event.get("worker_id", "")
    ).strip() == eid:
        return f"Stored {_format_money_signed(abs(n(amt)))} at home"
    if et == "steal_agent":
        if str(event.get("thief_id", "")).strip() == eid:
            wid = str(event.get("target_id") or event.get("worker_id") or "worker").strip()
            return f"Stole {_format_money_signed(abs(n(amt)))} from {wid}"
        if str(event.get("target_id", "")).strip() == eid or str(event.get("worker_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-abs(n(amt)))} to theft"
    if et == "spy_sell_info":
        price = abs(n(event.get("price") or event.get("amount") or 0.000005))
        if str(event.get("buyer_id", "")).strip() == eid:
            return f"Paid {_format_money_signed(-price)} for intel"
        if str(event.get("spy_id", "")).strip() == eid:
            return f"Received {_format_money_signed(price)} for intel"
    if et == "cop_recover":
        rec = event.get("amount")
        if rec is None:
            rec = event.get("recovered")
        if str(event.get("cop_id", "")).strip() == eid:
            return f"Recovered {_format_money_signed(abs(n(rec)))} from thief"
        if str(event.get("thief_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-abs(n(rec)))} to recovery"
    if et == "bank_zone_confiscation":
        conf = abs(n(event.get("amount")))
        if str(event.get("cop_id", "")).strip() == eid:
            return f"Confiscated {_format_money_signed(conf)} from bank robbery"
        if str(event.get("thief_id", "")).strip() == eid:
            return f"Lost {_format_money_signed(-conf)} to bank confiscation"
    if et == "redistribution" and str(event.get("cop_id", "")).strip() == eid:
        share = event.get("cop_share") or event.get("cop_amount") or event.get("kept_amount")
        return f"Kept {_format_money_signed(abs(n(share)))} after split"
    if et == "spy_intel_created" and str(event.get("spy_id", "")).strip() == eid:
        return "Created intel report for the market"
    if et == "spy_intel_discarded":
        return f"Intel discarded ({event.get('reason', 'unknown')})"
    if et == "spy_sell_info_skipped" and str(event.get("buyer_id", "")).strip() == eid:
        return f"Skipped intel purchase ({event.get('reason', 'unknown')})"
    if et == "worker_earn_skipped" and str(event.get("worker_id", "")).strip() == eid:
        return f"Earn skipped ({event.get('reason', 'unknown')})"
    if et == "bank_fee_skipped" and str(event.get("worker_id", "")).strip() == eid:
        return f"Bank fee skipped ({event.get('reason', 'unknown')})"
    return f"{et.replace('_', ' ').strip() or 'event'}"


def _slim_bridge_event(entity_id: str, role: str, event: dict) -> dict:
    out = {"type": str(event.get("type") or "")}
    for k in (
        "amount",
        "price",
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "recovered",
        "cop_share",
        "bank_share",
        "reason",
    ):
        if k in event and event.get(k) is not None:
            out[k] = event.get(k)
    out["summary"] = _narrate_recent_line(entity_id, role, event)
    return out


def _normalize_bridge_recent(items: list) -> list[dict]:
    """Bridge `recent`: max 5 entries, each dict has type + summary strings (no nulls)."""
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for ev in items:
        if not isinstance(ev, dict):
            continue
        typ = str(ev.get("type") or "")
        summ = str(ev.get("summary") or typ or "event").strip() or "event"
        out.append({"type": typ, "summary": summ})
    return out[-5:]


def _event_actor_ids(event: dict) -> set[str]:
    out: set[str] = set()
    for k in (
        "worker_id",
        "thief_id",
        "cop_id",
        "target_id",
        "buyer_id",
        "spy_id",
        "bank_id",
        "agent",
        "agent_id",
    ):
        v = event.get(k)
        if isinstance(v, str) and v.strip():
            out.add(v.strip())
    return out


def _collect_actor_events_map(actor_ids: list[str], events: list, per_actor_limit: int = 50) -> dict[str, list]:
    """Collect latest linked events per actor in one reverse scan."""
    if per_actor_limit <= 0:
        return {aid: [] for aid in actor_ids}
    actor_set = {str(a).strip() for a in actor_ids if str(a).strip()}
    out: dict[str, list] = {aid: [] for aid in actor_set}
    if not actor_set:
        return out
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        linked = _event_actor_ids(ev)
        if not linked:
            continue
        touched = linked.intersection(actor_set)
        if not touched:
            continue
        for aid in touched:
            rows = out[aid]
            if len(rows) < per_actor_limit:
                rows.append(ev)
        if all(len(out[aid]) >= per_actor_limit for aid in actor_set):
            break
    for aid in actor_set:
        out[aid].reverse()
    return out


def _collect_actor_events(entity_id: str, events: list, limit: int = 40, max_scan: int = 5000) -> list:
    """Collect the latest events that touch one actor.

    This avoids global-tail starvation where noisy roles (e.g. cop patrol/chase)
    can hide worker events from small fixed windows.
    """
    if limit <= 0:
        return []
    picked: list = []
    scanned = 0
    for ev in reversed(events):
        scanned += 1
        if scanned > max_scan:
            break
        if not isinstance(ev, dict):
            continue
        if _event_touches_actor(entity_id, ev):
            picked.append(ev)
            if len(picked) >= limit:
                break
    picked.reverse()
    return picked


def _build_recent_for_actor(entity_id: str, role: str, events: list, limit: int = 5) -> list:
    return [
        _slim_bridge_event(entity_id, role, ev)
        for ev in _collect_actor_events(entity_id, events, limit=limit)
    ]


def _lifetime_from_event_stream(entity_id: str, events) -> tuple[float, float]:
    """Reconcile cumulative collected/lost from the ledger stream (bounded buffer).

    Counts credits/debits for the entity, backs out internal moves mirrored by typed
    events (bank deposit, home stash, thief deposit), and adds **typed fallbacks**
    when matching ledger rows have rolled out of the ring buffer ahead of the
    higher-level economy event (so UI lifetimes stay aligned with balances).
    """
    eid = str(entity_id).strip()
    collected = 0.0
    lost_debits = 0.0
    internal_moves = 0.0
    home_stash_theft = 0.0
    credit_hashes: set[str] = set()
    debit_hashes: set[str] = set()

    def _hash_chains(ev: dict) -> set[str]:
        hs: set[str] = set()
        th = ev.get("tx_hash")
        if th is not None and str(th).strip():
            hs.add(str(th).strip())
        steps = ev.get("tx_steps")
        if isinstance(steps, (list, tuple)):
            for s in steps:
                if s is not None and str(s).strip():
                    hs.add(str(s).strip())
        return hs

    for raw in events:
        if not isinstance(raw, dict):
            continue
        ev = raw
        t = str(ev.get("type") or "")
        aid = str(ev.get("agent_id", "")).strip() if ev.get("agent_id") is not None else ""
        if t == "credit" and aid == eid:
            amt = float(ev.get("amount", 0) or 0.0)
            if amt > 0:
                collected += amt
                credit_hashes.update(_hash_chains(ev))
        if t == "debit" and aid == eid:
            amt = float(ev.get("amount", 0) or 0.0)
            if amt > 0:
                lost_debits += amt
                debit_hashes.update(_hash_chains(ev))
        if t == "worker_bank_deposit" and str(ev.get("worker_id", "")).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t in {"worker_store_home", "worker_stash", "worker_home_store"} and str(
            ev.get("worker_id", "")
        ).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t == "thief_deposit" and str(ev.get("thief_id", "")).strip() == eid:
            internal_moves += float(ev.get("amount", 0) or 0.0)
        if t == "steal_agent" and ev.get("intel_id"):
            wid = str(ev.get("worker_id") or ev.get("target_id") or "").strip()
            if wid == eid:
                home_stash_theft += float(ev.get("amount", 0) or 0.0)

    def _chains_hit_any(ev: dict, pool: set[str]) -> bool:
        return bool(_hash_chains(ev).intersection(pool))

    for raw in events:
        if not isinstance(raw, dict):
            continue
        ev = raw
        t = str(ev.get("type") or "")
        if t == "worker_earn" and str(ev.get("worker_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("amount", 0) or 0.0)
        elif t == "steal_agent" and str(ev.get("thief_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("amount", 0) or 0.0)
        elif t == "cop_recover" and str(ev.get("cop_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                rec = ev.get("amount")
                if rec is None:
                    rec = ev.get("recovered")
                collected += float(rec or 0.0)
        elif t == "spy_sell_info" and str(ev.get("spy_id", "")).strip() == eid:
            if not _chains_hit_any(ev, credit_hashes):
                collected += float(ev.get("price") or ev.get("amount") or 0.0)
        elif t == "bank_fee_nano" and str(ev.get("worker_id", "")).strip() == eid:
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("amount", 0) or 0.0)
        elif t == "spy_sell_info" and str(ev.get("buyer_id", "")).strip() == eid:
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("price") or ev.get("amount") or 0.0)
        elif t == "steal_agent":
            wid = str(ev.get("target_id") or ev.get("worker_id") or "").strip()
            if wid != eid or ev.get("intel_id"):
                continue
            if not _chains_hit_any(ev, debit_hashes):
                lost_debits += float(ev.get("amount", 0) or 0.0)

    lost = max(0.0, lost_debits - internal_moves + home_stash_theft)
    return round(max(0.0, collected), 10), round(lost, 10)


def _sync_lifetime_counters(entity_id: str, entity: dict, events) -> tuple[float, float]:
    """Keep entity counters monotonic vs stream-derived floor (covers missed bumps / old sessions)."""
    c_evt, l_evt = _lifetime_from_event_stream(entity_id, events)
    c_ent = float(entity.get("lifetime_collected", 0.0) or 0.0)
    l_ent = float(entity.get("lifetime_lost", 0.0) or 0.0)
    c = max(c_ent, c_evt)
    l = max(l_ent, l_evt)
    entity["lifetime_collected"] = c
    entity["lifetime_lost"] = l
    return c, l


def _compute_cop_stats(cop_id: str, events: list) -> dict:
    cid = str(cop_id).strip()
    catches = 0
    recovered_total = 0.0
    confiscation_count = 0
    confiscation_total = 0.0
    chase_captures = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("type") or "")
        if et == "cop_chase" and str(ev.get("cop_id", "")).strip() == cid and bool(ev.get("captured")):
            chase_captures += 1
        if et == "cop_recover" and str(ev.get("cop_id", "")).strip() == cid:
            catches += 1
            recovered_total += abs(_flow_n(ev.get("recovered") if ev.get("recovered") is not None else ev.get("amount")))
        if et == "bank_zone_confiscation" and str(ev.get("cop_id", "")).strip() == cid:
            catches += 1
            confiscation_count += 1
            amt = abs(_flow_n(ev.get("amount")))
            confiscation_total += amt
    total_taken = recovered_total + confiscation_total
    return {
        "catches": int(catches),
        "chase_captures": int(chase_captures),
        "recoveries_count": int(max(0, catches - confiscation_count)),
        "recovered_total": round(recovered_total, 6),
        "bank_confiscations_count": int(confiscation_count),
        "bank_confiscations_total": round(confiscation_total, 6),
        "total_taken_from_thief": round(total_taken, 6),
    }


def build_smallville_frame(
    limit_events: int = 250,
    include_debug: bool = False,
    emit_sprite_trace: bool = False,
):
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
    # Larger tail so noisy roles do not evict per-actor flow/recent rows before 50 slots fill.
    actor_event_map = _collect_actor_events_map(list(entities.keys()), events, per_actor_limit=150)

    actors = []
    for entity_id, entity in entities.items():
        latest_event = last_event_by_actor.get(entity_id)
        action = _infer_actor_action(entity, latest_event)
        dest_zone, dest_x, dest_y = _resolve_destination(shared, entity, latest_event, entities, tick)
        lc, ll = _sync_lifetime_counters(entity_id, entity, events)
        lc_r = round(float(lc), 6)
        ll_r = round(float(ll), 6)
        ln_r = round(lc_r - ll_r, 6)
        flow_line = _build_flow_summary_line(
            entity_id, entity, actor_event_map.get(entity_id, [])
        )
        flow_s = (
            flow_line.strip()
            if isinstance(flow_line, str) and flow_line.strip()
            else "No recent financial flow"
        )
        raw_recent = [
            _slim_bridge_event(entity_id, _entity_flow_role(entity), ev)
            for ev in actor_event_map.get(entity_id, [])[-5:]
        ]
        ca_val = str(entity.get("current_action", action) or action).strip() or "idle"
        actor = {
            "id": entity_id,
            "persona_type": ROLE_TO_SMALLVILLE.get(entity.get("type"), "resident"),
            "role": entity.get("persona_role", entity.get("type")),
            "x": float(entity.get("x", 0.0) or 0.0),
            "y": float(entity.get("y", 0.0) or 0.0),
            "target_x": float(entity.get("target_x", entity.get("x", 0.0)) or 0.0),
            "target_y": float(entity.get("target_y", entity.get("y", 0.0)) or 0.0),
            "target_id": entity.get("target"),
            "action": action,
            # PASS 4 queue label (buying_intel / chasing_thief / etc.).
            # Keep alongside legacy `action` so bridge clients can prefer this
            # when available without breaking older renderers.
            "current_action": ca_val,
            "dest_zone": dest_zone,
            "dest_x": float(dest_x),
            "dest_y": float(dest_y),
            "top_action": entity.get("top_action"),
            "reflection": entity.get("reflection", "neutral"),
            "balance": round(float(balances.get(entity_id, 0.0) or 0.0), 6),
            "status_line": (
                f"{action} | {entity.get('reflection', 'neutral')} | {dest_zone}"
            ),
            "home_storage": round(float(entity.get("home_storage", 0.0) or 0.0), 6),
            "carried_cash": round(float(entity.get("carried_cash", 0.0) or 0.0), 6),
            "lifetime_collected": lc_r,
            "lifetime_lost": ll_r,
            "lifetime_net": ln_r,
            "flow": flow_s,
            "recent": _normalize_bridge_recent(raw_recent),
        }
        if entity.get("type") == "worker":
            actor["worker_shift_phase"] = str(entity.get("worker_shift_phase", "to_mine") or "to_mine")
            actor["work_route"] = str(entity.get("work_route", "") or "")
        if entity.get("type") == "cop":
            # Cop ledger should be richer and long-lived; compute against full
            # event stream (not just the trimmed actor tail).
            actor["cop_stats"] = _compute_cop_stats(entity_id, events)
        actors.append(actor)

    payload = {
        "world": {
            "name": "AgenticEconomy-SmallvilleBridge",
            # Sentinel for Django / curl: proves this process is running this repo’s bridge.
            "bridge_revision": BRIDGE_CODE_REVISION,
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
    if emit_sprite_trace:
        rows = []
        for a in actors:
            ax = float(a.get("x", 0.0) or 0.0)
            ay = float(a.get("y", 0.0) or 0.0)
            tx = float(a.get("target_x", ax) or ax)
            ty = float(a.get("target_y", ay) or ay)
            rows.append(
                {
                    "id": a.get("id"),
                    "type": entities.get(str(a.get("id", "")), {}).get("type"),
                    "x": round(ax, 1),
                    "y": round(ay, 1),
                    "target": [round(tx, 1), round(ty, 1)],
                    "dest": [round(float(a.get("dest_x", tx) or tx), 1), round(float(a.get("dest_y", ty) or ty), 1)],
                    "action": a.get("action"),
                    "shift": a.get("worker_shift_phase"),
                    "route": a.get("work_route"),
                    "dist_to_target": round(math.hypot(tx - ax, ty - ay), 1),
                }
            )
        payload["sprite_trace"] = rows
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
        # Spawn workers INSIDE their home (B08 / worker_home_inside).
        # Lay them out on a horizontal line around the inside POI so they
        # DO NOT stack. We try each candidate tile outward from the POI
        # and SKIP any that's already occupied by another worker, so the
        # navmesh never snaps two workers onto the same fallback tile.
        from core import navmesh

        hx, hy = _locations.point("worker", "home", anchor="inside")
        try:
            slot = max(0, int(str(entity_id).split("_")[-1]) - 1)
        except (ValueError, IndexError):
            slot = 0

        base_tx = int(hx // TILE_SIZE)
        base_ty = int(hy // TILE_SIZE)

        # Build (col, row) candidates spiraling outward from the POI so we
        # can fill a region, not just a single row. Covers up to ±4 tiles
        # in each axis (~ 9x9 = 81 slots, plenty for demo).
        candidates = []
        for ring in range(0, 5):
            if ring == 0:
                candidates.append((0, 0))
                continue
            # Walk the square ring at radius `ring`.
            for dx in range(-ring, ring + 1):
                candidates.append((dx, -ring))   # top edge
                candidates.append((dx, +ring))   # bottom edge
            for dy in range(-ring + 1, ring):
                candidates.append((-ring, dy))   # left edge
                candidates.append((+ring, dy))   # right edge

        # Use floor-div to match navmesh.world_to_tile; round() would
        # collapse x=624 (tile 19) and x=656 (tile 20) onto the same key
        # because of Python's banker's rounding on .5.
        taken = {
            (int(e.get("x", 0) // TILE_SIZE), int(e.get("y", 0) // TILE_SIZE))
            for e in entities.values()
            if e.get("type") == "worker"
        }

        sx = sy = None
        # Check each candidate tile DIRECTLY (no snap) — if the tile itself
        # is walkable AND not already taken, use it. This avoids
        # nearest_walkable() collapsing many different unwalkable inputs
        # onto the same 4-5 anchor tiles inside the building.
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
            # Last-resort: accept a stack rather than fail to spawn.
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


@router.post("/demo/force-cop-cycle")
def force_cop_cycle_endpoint(steps: int = 80):
    """
    Demo helper: force a short steal->intel->cop-recovery cycle so cop ledger
    stats visibly update during presentations.
    """
    shared = get_state()
    entities = shared.setdefault("entities", {})
    balances = shared.setdefault("balances", {})

    # Ensure core actors exist for the cycle.
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

    # Seed a stash so spy/thief path has material to work with.
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
    recent = all_events[max(0, after_events - 120):]
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


@router.post("/demo/reset-economy")
def reset_economy_endpoint(start_balance: float = 5.0):
    """
    Reset demo to baseline population and balances for a clean judge run.
    """
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
        # Hard reset per-agent rolling values so all cards return to zeroed progress.
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
    shared["events"] = []
    shared["economy"] = default_economy_state()
    shared.setdefault("metrics", {}).update(
        {
            "total_spent": 0.0,
            "successful_tx": 0,
            "failed_tx": 0,
            "cost_per_action": 0.0,
            "success_rate": 0.0,
        }
    )
    shared.setdefault("tx_diagnostics", {}).clear()
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


@router.get("/legacy/time")
def legacy_time_endpoint():
    return legacy_current_time_payload()


@router.get("/legacy/persona/{persona_id}/tile")
def legacy_persona_tile_endpoint(persona_id: str):
    return legacy_persona_tile_payload(persona_id)


@router.get("/legacy/tile/events")
def legacy_tile_events_endpoint(x: int = Query(...), y: int = Query(...), limit: int = Query(80, ge=1, le=500)):
    return legacy_tile_events_payload(x, y, limit)


@router.get("/legacy/persona/{persona_id}/schedule")
def legacy_persona_schedule_endpoint(persona_id: str):
    return legacy_persona_schedule_payload(persona_id)


@router.get("/legacy/persona/schedules")
def legacy_persona_schedules_endpoint():
    return legacy_all_persona_schedules_payload()


@router.post("/legacy/command")
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


@router.get("/worker/{worker_id}/ledger")
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
    # The event types below are the ones that carry worker-level
    # economic activity. Everything else (commute pings, regime
    # chatter, etc.) is filtered out so the ledger stays readable.
    WORKER_EVENT_TYPES = {
        "worker_earn",
        "worker_earn_skipped",
        "worker_bank_deposit",
        "worker_store_home",
        # Nano-economy events that affect THIS worker:
        "bank_fee_nano",        # banker skims fee from this worker
        "bank_fee_skipped",     # banker tried to fee but worker was too low
        "steal_agent",          # intel-driven theft from this worker's home stash
        "steal_skipped",        # thief had intel but target was empty/missing
        # Observability: spy flagged this worker's stash.
        "spy_intel_created",    # filtered below on target_worker==worker_id
    }
    rows = []
    for e in events:
        if not isinstance(e, dict):
            continue
        # Match on worker_id OR target_worker (spy_intel_created uses
        # target_worker; steal_agent carries both).
        owner = str(e.get("worker_id", "") or e.get("target_worker", ""))
        if owner != wid:
            continue
        et = str(e.get("type", ""))
        if et not in WORKER_EVENT_TYPES:
            continue
        rows.append({
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
        })
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


@router.get("/economy/health")
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

    # Transaction counters — count every money-moving event. The primitive
    # `debit`/`credit` events emitted by bank.bank are the ground truth for
    # total_transactions; every higher-level economic event composes 1-3
    # of them. We also count semantic categories for readability.
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


@router.get("/agents/actions")
def agents_actions_endpoint():
    """Expose each agent's symbolic action queue plus a readable label.

    PASS 1 produced the queues, PASS 2 drives movement off them, PASS 3
    locks targets to real map POIs, and PASS 4 adds the `current_action`
    label consumed here so dashboards can say "buying_intel" / "stealing
    _from_worker" / etc. instead of parsing the raw action dicts."""
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


@router.get("/transactions/count")
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


@router.get("/agents/current")
def agents_current_endpoint():
    """FINAL PASS — compact "what is each agent doing right now" map.

    Shape matches the demo spec exactly:

        { "thief_1": "stealing_from_worker", "cop_1": "chasing_thief" }

    No queue details, no summaries — just the human-readable label the UI
    paints above each sprite. Produced by PASS 4's `_describe_action` in
    `core.action_queue` via `entity.current_action`."""
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


@router.get("/route/status")
def route_status_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route.setdefault("enabled", False)
    route.setdefault("sequence", [{"id": "B11", "anchor": "center"}, {"id": "B08", "anchor": "center"}])
    route.setdefault("phase", 0)
    route.setdefault("stage", "entry")
    route.setdefault("stage_started_tick", int(state.setdefault("economy", {}).get("tick", 0)))
    route.setdefault("hold_ticks", 24)
    route.setdefault("hold_until_tick", 0)
    route.setdefault("max_stage_ticks", 220)
    route.setdefault("allow_stage_timeout", False)
    route.setdefault("inside_stage_enabled", False)
    route.setdefault("arrival_ratio", 1.0)
    route.setdefault("arrival_radius", 36.0)
    return {"status": "ok", "global_route": route}


@router.post("/route/start")
def route_start_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route["enabled"] = True
    return {"status": "started", "global_route": route}


@router.post("/route/stop")
def route_stop_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route["enabled"] = False
    return {"status": "stopped", "global_route": route}


@router.post("/route/set")
def route_set_endpoint(payload: dict):
    """
    Set global synchronized route.
    Example:
    {
      "sequence": [{"id":"B11","anchor":"center"}, {"id":"B08","anchor":"center"}],
      "phase": 0,
      "hold_ticks": 24,
      "max_stage_ticks": 220,
      "allow_stage_timeout": false,
      "inside_stage_enabled": false,
      "arrival_ratio": 1.0,
      "arrival_radius": 36.0,
      "enabled": true
    }
    """
    sequence = payload.get("sequence")
    if not isinstance(sequence, list) or not sequence:
        raise HTTPException(status_code=400, detail="sequence must be a non-empty list")
    seq: list[dict] = []
    for item in sequence:
        if isinstance(item, dict):
            bid = str(item.get("id", "")).strip().upper()
            anchor = str(item.get("anchor", "center")).strip().lower() or "center"
        else:
            bid = str(item).strip().upper()
            anchor = "center"
        if anchor not in {"entry", "inside", "center"}:
            anchor = "center"
        if bid:
            seq.append({"id": bid, "anchor": anchor})
    if not seq:
        raise HTTPException(status_code=400, detail="sequence cannot be empty")

    catalog = _load_building_catalog()
    valid_ids = {str(b.get("id", "")).upper() for b in catalog.get("buildings", [])}
    unknown = [s["id"] for s in seq if s["id"] not in valid_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown building IDs: {unknown}")

    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    now_tick = int(state.setdefault("economy", {}).get("tick", 0))
    route["sequence"] = seq
    route["phase"] = int(payload.get("phase", route.get("phase", 0))) % len(seq)
    route["stage"] = str(payload.get("stage", "entry")).strip().lower() or "entry"
    if route["stage"] not in {"entry", "inside"}:
        route["stage"] = "entry"
    route["stage_started_tick"] = now_tick
    route["hold_ticks"] = max(1, int(payload.get("hold_ticks", route.get("hold_ticks", 24))))
    route["hold_until_tick"] = now_tick + route["hold_ticks"]
    route["max_stage_ticks"] = max(20, int(payload.get("max_stage_ticks", route.get("max_stage_ticks", 220))))
    route["allow_stage_timeout"] = bool(payload.get("allow_stage_timeout", route.get("allow_stage_timeout", False)))
    route["inside_stage_enabled"] = bool(payload.get("inside_stage_enabled", route.get("inside_stage_enabled", False)))
    route["arrival_ratio"] = max(0.1, min(1.0, float(payload.get("arrival_ratio", route.get("arrival_ratio", 1.0)))))
    route["arrival_radius"] = max(4.0, float(payload.get("arrival_radius", route.get("arrival_radius", 36.0))))
    route["enabled"] = bool(payload.get("enabled", True))

    return {"status": "updated", "global_route": route}


@router.post("/spawn")
def spawn_endpoint(entity_type: str, entity_id: str | None = None, balance: float = 0.0):
    try:
        resolved_id = entity_id or _next_entity_id(entity_type)
        entity = spawn_entity(entity_id=resolved_id, entity_type=entity_type, balance=balance)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "spawned", "entity": entity, "balance": state["balances"][resolved_id]}


@router.post("/population/set")
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
        # Re-seed the B11 work treasury after a population reset.
        # Otherwise the treasury is 0 on the first shift and every
        # earn skips with reason="work_treasury_empty".
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
            entity_id = f"{prefix}_{i}"
            entity = spawn_entity(entity_id=entity_id, entity_type=entity_type, balance=start_balance)
            if role_label:
                entity["persona_role"] = role_label
            created.append({"id": entity_id, "type": entity_type, "role": entity.get("persona_role", entity_type)})

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
def get_smallville_bridge_frame(
    limit_events: int = Query(250, ge=1, le=2000),
    include_debug: bool = False,
    trace: bool = Query(False, description="Include sprite_trace[] for tooling / debugging"),
):
    return build_smallville_frame(
        limit_events=limit_events,
        include_debug=include_debug,
        emit_sprite_trace=trace,
    )


@router.get("/bridge/manifest")
def get_bridge_manifest():
    """Lightweight probe: if this 404s or revision mismatches, port 8000 is not this codebase."""
    return {
        "bridge_revision": BRIDGE_CODE_REVISION,
        "endpoints_py": str(Path(__file__).resolve()),
    }


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


@router.get("/map/buildings")
def get_map_buildings_endpoint():
    if not BUILDING_CATALOG_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Building catalog missing. Run "
                "'python backend/utils/build_building_catalog.py' first."
            ),
        )
    try:
        return json.loads(BUILDING_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read building catalog: {exc}") from exc


@router.get("/map/buildings/spots")
def get_map_building_spots_endpoint():
    catalog = _load_building_catalog()
    buildings = catalog.get("buildings", []) if isinstance(catalog, dict) else []
    out = []
    for b in buildings:
        b_id = str(b.get("id", "")).upper()
        if not b_id:
            continue
        entry = _building_anchor_point(b_id, "entry")
        inside = _building_anchor_point(b_id, "inside")
        center = _building_anchor_point(b_id, "center")
        meeting = _spot_target(b_id, "inside", "meeting", f"{b_id}_sample", 0)
        desks = [_spot_target(b_id, "inside", "desks", f"{b_id}_desk_{i}", i) for i in range(6)]
        out.append(
            {
                "id": b_id,
                "name": b.get("name"),
                "entry": {"x": float(entry[0]), "y": float(entry[1])} if entry else None,
                "inside": {"x": float(inside[0]), "y": float(inside[1])} if inside else None,
                "center": {"x": float(center[0]), "y": float(center[1])} if center else None,
                "meeting": {"x": float(meeting[0]), "y": float(meeting[1])} if meeting else None,
                "desks_preview": [{"x": float(p[0]), "y": float(p[1])} for p in desks if p],
            }
        )
    return {
        "supported_spots": ["anchor", "entry", "inside", "center", "meeting", "desks", "queue"],
        "buildings": out,
    }


@router.get("/map/hubs")
def get_role_hubs():
    movement = state.setdefault("movement", {})
    hubs = movement.setdefault("role_hubs", {})
    defaults = {
        "worker_home": "B08",
        "worker_work": "B11",
        "thief_home": "B07",
        "cop_home": "B09",
        "bank_home": "B12",
        "spy_home": "B06",
    }
    for key, value in defaults.items():
        hubs.setdefault(key, value)
    return {"status": "ok", "role_hubs": hubs}


@router.post("/map/hubs")
def set_role_hubs(payload: dict):
    defaults = {
        "worker_home": "B08",
        "worker_work": "B11",
        "thief_home": "B07",
        "cop_home": "B09",
        "bank_home": "B12",
        "spy_home": "B06",
    }
    catalog = _load_building_catalog()
    valid_ids = {str(b.get("id", "")).upper() for b in catalog.get("buildings", [])}
    movement = state.setdefault("movement", {})
    hubs = movement.setdefault("role_hubs", {})
    for key, value in defaults.items():
        hubs.setdefault(key, value)

    unknown = []
    for key in defaults.keys():
        if key not in payload:
            continue
        bid = str(payload.get(key, "")).strip().upper()
        if not bid:
            continue
        if bid not in valid_ids:
            unknown.append({key: bid})
            continue
        hubs[key] = bid

    if unknown:
        raise HTTPException(status_code=400, detail={"unknown_buildings": unknown})

    # Re-enable natural movement around hubs and clear temporary command locks.
    movement.setdefault("global_route", {})["enabled"] = False
    cleared = 0
    for entity in state.setdefault("entities", {}).values():
        if isinstance(entity.get("manual_target"), dict):
            entity.pop("manual_target", None)
            cleared += 1
    return {"status": "ok", "role_hubs": hubs, "cleared_manual_targets": cleared}


@router.post("/move/buildings")
def move_entities_by_building(payload: dict):
    """
    Move entities by building IDs.
    Example payload:
    {
      "from_building_id": "B11",
      "to_building_id": "B03",
      "to_anchor": "center",
      "entity_type": "worker"
    }
    """
    catalog = _load_building_catalog()
    buildings = catalog.get("buildings", [])
    if not buildings:
        raise HTTPException(status_code=404, detail="Building catalog missing or empty.")

    b_map = {str(b.get("id")): b for b in buildings}
    from_id = str(payload.get("from_building_id", "")).strip().upper()
    to_id = str(payload.get("to_building_id", "")).strip().upper()
    to_anchor = str(payload.get("to_anchor", "center")).strip().lower() or "center"
    to_spot = str(payload.get("to_spot", "anchor")).strip().lower() or "anchor"
    if to_anchor not in {"entry", "inside", "center"}:
        raise HTTPException(status_code=400, detail="to_anchor must be one of: entry, inside, center")
    entity_type = payload.get("entity_type")
    if entity_type is not None:
        entity_type = str(entity_type).strip().lower()

    if to_id not in b_map:
        raise HTTPException(status_code=400, detail=f"Unknown to_building_id: {to_id}")
    if from_id and from_id not in b_map:
        raise HTTPException(status_code=400, detail=f"Unknown from_building_id: {from_id}")

    entries = {
        str(b.get("id")): (
            float(b.get("entry_px", {}).get("x", 0.0)),
            float(b.get("entry_px", {}).get("y", 0.0)),
        )
        for b in buildings
    }
    anchor_target = _spot_target(to_id, to_anchor, to_spot, "seed", 0)
    if not anchor_target:
        raise HTTPException(status_code=400, detail=f"Missing anchor for {to_id}/{to_anchor}")
    tx, ty = anchor_target

    entities = state.setdefault("entities", {})
    moved = []
    skipped = []
    matched_entities = []
    for entity_id, entity in entities.items():
        role = str(entity.get("type", "")).lower()
        if entity_type and role != entity_type:
            skipped.append(entity_id)
            continue
        ex = float(entity.get("x", 0.0) or 0.0)
        ey = float(entity.get("y", 0.0) or 0.0)
        if from_id:
            nearest = _nearest_building_id(ex, ey, entries)
            if nearest != from_id:
                skipped.append(entity_id)
                continue
        matched_entities.append((entity_id, entity))

    for ordinal, (entity_id, entity) in enumerate(matched_entities):
        nx, ny = _spot_target(to_id, to_anchor, to_spot, entity_id, ordinal) or (tx, ty)
        entity["x"] = nx
        entity["y"] = ny
        entity["target_x"] = nx
        entity["target_y"] = ny
        entity["manual_target"] = {
            "active": True,
            "building_id": to_id,
            "anchor": to_anchor,
            "spot": to_spot,
            "x": nx,
            "y": ny,
            "persist": False,
            "hold_ticks": 0,
            "arrival_radius": 40.0,
        }
        moved.append(entity_id)

    return {
        "status": "ok",
        "from_building_id": from_id or None,
        "to_building_id": to_id,
        "to_anchor": to_anchor,
        "to_spot": to_spot,
        "entity_type": entity_type,
        "moved_count": len(moved),
        "moved_entities": moved,
        "skipped_count": len(skipped),
    }


@router.post("/command/go")
def command_go_to_building(payload: dict):
    """
    Direct movement command using mapped building anchors.
    Example:
    {
      "building_id": "B08",
      "anchor": "center",
      "spot": "desks",
      "entity_type": "worker",
      "entity_ids": ["worker_1", "worker_2"],
      "persist": true,
      "arrival_radius": 40,
      "disable_global_route": true
    }
    """
    building_id = str(payload.get("building_id", "")).strip().upper()
    if not building_id:
        raise HTTPException(status_code=400, detail="building_id is required")
    anchor = str(payload.get("anchor", "center")).strip().lower() or "center"
    spot = str(payload.get("spot", "anchor")).strip().lower() or "anchor"
    if anchor not in {"entry", "inside", "center"}:
        raise HTTPException(status_code=400, detail="anchor must be one of: entry, inside, center")
    target = _spot_target(building_id, anchor=anchor, spot=spot, entity_id="seed", ordinal=0)
    if not target:
        raise HTTPException(status_code=400, detail=f"Unknown building_id or anchor: {building_id}/{anchor}")

    entity_type = payload.get("entity_type")
    if entity_type is not None:
        entity_type = str(entity_type).strip().lower()
        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid entity_type: {entity_type}")
    raw_ids = payload.get("entity_ids")
    selected_ids = None
    if isinstance(raw_ids, list) and raw_ids:
        selected_ids = {str(x).strip() for x in raw_ids if str(x).strip()}
    persist = bool(payload.get("persist", False))
    hold_ticks = max(0, int(payload.get("hold_ticks", 0) or 0))
    arrival_radius = max(8.0, float(payload.get("arrival_radius", 40.0)))
    disable_global_route = bool(payload.get("disable_global_route", False))

    movement = state.setdefault("movement", {})
    if disable_global_route:
        movement.setdefault("global_route", {})["enabled"] = False

    entities = state.setdefault("entities", {})
    moved = []
    skipped = []
    matched_entities = []
    for entity_id, entity in entities.items():
        role = str(entity.get("type", "")).lower()
        if entity_type and role != entity_type:
            skipped.append(entity_id)
            continue
        if selected_ids is not None and entity_id not in selected_ids:
            skipped.append(entity_id)
            continue
        matched_entities.append((entity_id, entity))

    for ordinal, (entity_id, entity) in enumerate(matched_entities):
        tx, ty = _spot_target(building_id, anchor=anchor, spot=spot, entity_id=entity_id, ordinal=ordinal) or target
        entity["manual_target"] = {
            "active": True,
            "building_id": building_id,
            "anchor": anchor,
            "spot": spot,
            "x": float(tx),
            "y": float(ty),
            "persist": persist,
            "hold_ticks": hold_ticks,
            "arrival_radius": arrival_radius,
        }
        entity["target_x"] = float(tx)
        entity["target_y"] = float(ty)
        moved.append(entity_id)

    return {
        "status": "ok",
        "building_id": building_id,
        "anchor": anchor,
        "spot": spot,
        "persist": persist,
        "hold_ticks": hold_ticks,
        "target_x": float(target[0]),
        "target_y": float(target[1]),
        "moved_count": len(moved),
        "moved_entities": moved,
        "skipped_count": len(skipped),
        "global_route_enabled": bool(movement.get("global_route", {}).get("enabled", False)),
    }


@router.post("/command/clear")
def clear_commands(entity_type: str | None = None):
    entities = state.setdefault("entities", {})
    cleared = []
    for entity_id, entity in entities.items():
        role = str(entity.get("type", "")).lower()
        if entity_type and role != str(entity_type).strip().lower():
            continue
        if isinstance(entity.get("manual_target"), dict):
            entity.pop("manual_target", None)
            cleared.append(entity_id)
    return {"status": "ok", "cleared_count": len(cleared), "cleared_entities": cleared}
