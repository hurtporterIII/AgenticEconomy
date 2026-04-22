from __future__ import annotations

import os
import random
import json
import math
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
ROLE_HUB_DEFAULTS = {
    "worker_home": "B08",
    "worker_work": "B11",
    "thief_home": "B07",
    "cop_home": "B09",
    "bank_home": "B12",
    "spy_home": "B06",
}
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
        route = str(entity.get("work_route", "to_mine"))
        haul_mode = str(entity.get("haul_mode", ""))
        if action in {"return_home", "store_home"} or route == "to_home" or haul_mode == "return_home":
            return _hub_destination(shared, "worker_home", "Worker Home", anchor="center")
        if action in {"work", "commute_mine"} or route == "to_mine":
            return _hub_destination(shared, "worker_work", "Worker Work", anchor="center")
        if action == "bank":
            return _hub_destination(shared, "bank_home", "Bank Home", anchor="center")
        return _hub_destination(shared, "worker_home", "Worker Home", anchor="center")

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


def _infer_actor_action(entity: dict, latest_event: dict | None) -> str:
    role = str(entity.get("type", "resident"))
    top_action = str(entity.get("top_action", "")).strip().lower()
    event_type = str((latest_event or {}).get("type", ""))
    if role == "cop" and entity.get("target"):
        return "chase"

    if role == "worker":
        if top_action in {"commute_mine", "work", "return_home", "store_home"}:
            return top_action
        if event_type == "worker_store_home":
            return "store_home"
        if event_type == "worker_commute_home":
            return "return_home"
        if event_type == "worker_commute_mine":
            return "commute_mine"
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
        dest_zone, dest_x, dest_y = _resolve_destination(shared, entity, latest_event, entities, tick)
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
            "dest_zone": dest_zone,
            "dest_x": float(dest_x),
            "dest_y": float(dest_y),
            "top_action": entity.get("top_action"),
            "reflection": entity.get("reflection", "neutral"),
            "balance": float(balances.get(entity_id, 0.0) or 0.0),
            "status_line": (
                f"{action} | {entity.get('reflection', 'neutral')} | {dest_zone}"
            ),
            "home_storage": float(entity.get("home_storage", 0.0) or 0.0),
            "carried_cash": float(entity.get("carried_cash", 0.0) or 0.0),
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
        sx, sy = _sector_nav_point("artist's co-living space", entity_id)
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


@router.get("/route/status")
def route_status_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route.setdefault("enabled", True)
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
        state.setdefault("events", []).append(
            {
                "type": "population_reset",
                "requested_total": target_total,
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
