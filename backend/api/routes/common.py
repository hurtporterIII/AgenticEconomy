"""Shared API constants and helpers used across multiple route modules."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from core import locations as _locations
from core.state import default_behavior_settings, default_economy_state, state

# Bumped when bridge JSON contract changes; `/api/bridge/manifest` and `world.bridge_revision` must match.
BRIDGE_CODE_REVISION = "ae-smallville-lifetime-v2"
MAX_TOTAL_AGENTS = int(os.getenv("MAX_TOTAL_AGENTS", "200"))
DEFAULT_RESET_POPULATION = {
    "workers": 6,
    "cops": 1,
    "bankers": 1,
    "spies": 1,
    "thieves": 1,
    "banks": 1,
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
ROLE_HUB_DEFAULTS = _locations.flat_hub_defaults()
TILE_SIZE = 32.0
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
MAP_SUMMARY_PATH = _BACKEND_ROOT / "store" / "map_summary.json"
BUILDING_CATALOG_PATH = _BACKEND_ROOT / "store" / "building_catalog.json"
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


def _flow_n(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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


def get_state():
    state.setdefault("behavior_settings", default_behavior_settings())
    state.setdefault("economy", default_economy_state())
    return state


def get_events():
    return state.setdefault("events", [])
