import random
import math
import json
import os
from pathlib import Path


# Smallville map geometry: 140x100 tiles, 32px per tile.
WORLD_MIN_X = 16.0
WORLD_MAX_X = 4464.0
WORLD_MIN_Y = 16.0
WORLD_MAX_Y = 3184.0
MOVE_LERP = 0.18
FORCE_SINGLE_TARGET = False
SINGLE_TARGET_BUILDING_ID = os.getenv("SINGLE_TARGET_BUILDING_ID", "B08").strip().upper()
SINGLE_TARGET_POINT = "center"
GLOBAL_ROUTE_MODE = os.getenv("GLOBAL_ROUTE_MODE", "0") == "1"
DEFAULT_GLOBAL_ROUTE_IDS = (
    {"id": "B11", "anchor": "center"},
    {"id": "B08", "anchor": "center"},
)
ROLE_HUB_DEFAULTS = {
    "worker_home": "B08",
    "worker_work": "B11",
    "thief_home": "B07",
    "cop_home": "B09",
    "bank_home": "B12",
    "spy_home": "B06",
}
BUILDING_CATALOG_PATH = Path(__file__).resolve().parents[1] / "store" / "building_catalog.json"
_BUILDING_CATALOG_CACHE = None
_BUILDING_POINT_CACHE = {}
_BUILDING_BBOX_CACHE = {}


def _clamp_world(x, y):
    return (
        max(WORLD_MIN_X, min(WORLD_MAX_X, float(x))),
        max(WORLD_MIN_Y, min(WORLD_MAX_Y, float(y))),
    )


def _load_building_catalog():
    global _BUILDING_CATALOG_CACHE
    if _BUILDING_CATALOG_CACHE is not None:
        return _BUILDING_CATALOG_CACHE
    try:
        _BUILDING_CATALOG_CACHE = json.loads(BUILDING_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _BUILDING_CATALOG_CACHE = {}
    return _BUILDING_CATALOG_CACHE


def _get_building_point(building_id, point_type="center", default=(912.0, 1168.0)):
    key = (str(building_id).upper(), str(point_type).lower())
    if key in _BUILDING_POINT_CACHE:
        return _BUILDING_POINT_CACHE[key]

    catalog = _load_building_catalog()
    buildings = catalog.get("buildings", []) if isinstance(catalog, dict) else []
    for b in buildings:
        if str(b.get("id", "")).upper() != key[0]:
            continue
        if key[1] == "center":
            src = b.get("center_px")
        elif key[1] == "inside":
            src = b.get("inside_px")
        else:
            src = b.get("entry_px")
        if not isinstance(src, dict):
            src = b.get("inside_px") or b.get("center_px") or b.get("entry_px") or {}
        px = float(src.get("x", default[0]) or default[0])
        py = float(src.get("y", default[1]) or default[1])
        pt = _clamp_world(px, py)
        _BUILDING_POINT_CACHE[key] = pt
        return pt

    _BUILDING_POINT_CACHE[key] = _clamp_world(default[0], default[1])
    return _BUILDING_POINT_CACHE[key]


def _get_building_bbox(building_id, default_center=(912.0, 1168.0), pad_px=16.0):
    key = (str(building_id).upper(), float(pad_px))
    if key in _BUILDING_BBOX_CACHE:
        return _BUILDING_BBOX_CACHE[key]

    catalog = _load_building_catalog()
    buildings = catalog.get("buildings", []) if isinstance(catalog, dict) else []
    for b in buildings:
        if str(b.get("id", "")).upper() != key[0]:
            continue
        raw = b.get("bbox_px") or {}
        if isinstance(raw, dict):
            min_x = float(raw.get("min_x", default_center[0] - 96) or (default_center[0] - 96))
            min_y = float(raw.get("min_y", default_center[1] - 96) or (default_center[1] - 96))
            max_x = float(raw.get("max_x", default_center[0] + 96) or (default_center[0] + 96))
            max_y = float(raw.get("max_y", default_center[1] + 96) or (default_center[1] + 96))
        else:
            min_x, min_y = default_center[0] - 96, default_center[1] - 96
            max_x, max_y = default_center[0] + 96, default_center[1] + 96

        # Keep targets strictly inside the building footprint.
        min_x += float(pad_px)
        min_y += float(pad_px)
        max_x -= float(pad_px)
        max_y -= float(pad_px)
        if max_x <= min_x:
            max_x = min_x + 8.0
        if max_y <= min_y:
            max_y = min_y + 8.0

        bbox = (
            max(WORLD_MIN_X, min(WORLD_MAX_X, min_x)),
            max(WORLD_MIN_Y, min(WORLD_MAX_Y, min_y)),
            max(WORLD_MIN_X, min(WORLD_MAX_X, max_x)),
            max(WORLD_MIN_Y, min(WORLD_MAX_Y, max_y)),
        )
        _BUILDING_BBOX_CACHE[key] = bbox
        return bbox

    cx, cy = _clamp_world(default_center[0], default_center[1])
    fallback = (
        max(WORLD_MIN_X, cx - 64.0),
        max(WORLD_MIN_Y, cy - 64.0),
        min(WORLD_MAX_X, cx + 64.0),
        min(WORLD_MAX_Y, cy + 64.0),
    )
    _BUILDING_BBOX_CACHE[key] = fallback
    return fallback


def _point_in_bbox(x, y, bbox):
    min_x, min_y, max_x, max_y = bbox
    return min_x <= float(x) <= max_x and min_y <= float(y) <= max_y


def _clamp_to_bbox(x, y, bbox):
    min_x, min_y, max_x, max_y = bbox
    return (
        max(min_x, min(max_x, float(x))),
        max(min_y, min(max_y, float(y))),
    )


def _pick_patrol_point_in_bbox(entity, bbox, tick, hold_ticks=16, anchor=None, anchor_spread=72.0):
    until_tick = int(entity.get("home_patrol_until_tick", -1))
    curr_tx = entity.get("target_x")
    curr_ty = entity.get("target_y")
    has_curr = curr_tx is not None and curr_ty is not None
    curr_inside = bool(has_curr and _point_in_bbox(curr_tx, curr_ty, bbox))

    if tick < until_tick and curr_inside:
        return _clamp_to_bbox(curr_tx, curr_ty, bbox)

    min_x, min_y, max_x, max_y = bbox
    if isinstance(anchor, (tuple, list)) and len(anchor) == 2:
        ax = float(anchor[0])
        ay = float(anchor[1])
        nx = ax + random.uniform(-float(anchor_spread), float(anchor_spread))
        ny = ay + random.uniform(-float(anchor_spread), float(anchor_spread))
        nx, ny = _clamp_to_bbox(nx, ny, bbox)
    else:
        nx = random.uniform(min_x, max_x)
        ny = random.uniform(min_y, max_y)
    entity["home_patrol_until_tick"] = int(tick) + max(8, int(hold_ticks))
    return nx, ny


# Canonical geolocated anchors (all from building catalog, not hardcoded map guesses).
# Center points align with visible building-name anchors.
WORK_ZONE = _get_building_point("B11", "center", default=(2704.0, 1712.0))  # money/work
WORKER_HOME_ZONE = _get_building_point("B08", "center", default=(912.0, 1168.0))  # home/store
THIEF_ZONE = _get_building_point("B07", "center", default=(1840.0, 880.0))
COP_ZONE = _get_building_point("B09", "center", default=(3728.0, 1168.0))
BANKER_ZONE = _get_building_point("B11", "center", default=(2704.0, 1712.0))
BANK_ZONE = _get_building_point("B11", "center", default=(2704.0, 1712.0))


def _stable_lane_offset(entity_id, max_abs=18.0):
    seed = sum(ord(ch) for ch in str(entity_id))
    ox = ((seed * 7) % int(max_abs * 2 + 1)) - max_abs
    oy = ((seed * 11) % int(max_abs * 2 + 1)) - max_abs
    return float(ox), float(oy)


def _get_global_route_stops(route_sequence):
    defaults = {
        "B08": (912.0, 1168.0),
        "B11": (2704.0, 1712.0),
    }
    stops = []
    for raw in route_sequence:
        if isinstance(raw, dict):
            bid = str(raw.get("id", "")).strip().upper()
            anchor = str(raw.get("anchor", "center")).strip().lower() or "center"
        else:
            bid = str(raw).strip().upper()
            anchor = "center"
        if anchor not in {"entry", "inside", "center"}:
            anchor = "center"
        if not bid:
            continue
        default = defaults.get(bid, (912.0, 1168.0))
        stops.append(
            {
                "id": bid,
                "entry": _get_building_point(bid, "entry", default),
                "inside": _get_building_point(bid, "inside", default),
                "anchor": anchor,
                "target": _get_building_point(bid, anchor, default),
            }
        )
    return stops


def _ensure_global_route_state(shared):
    movement = shared.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route.setdefault("enabled", GLOBAL_ROUTE_MODE)
    route.setdefault("phase", 0)
    route.setdefault("stage", "entry")  # entry -> inside -> next phase
    route.setdefault("stage_started_tick", 0)
    route.setdefault("hold_until_tick", 0)
    route.setdefault("max_stage_ticks", 220)
    route.setdefault("allow_stage_timeout", False)
    route.setdefault("inside_stage_enabled", False)
    # Strict synchronized travel: do not advance until the full group arrives.
    route.setdefault("hold_ticks", 24)
    route.setdefault("arrival_ratio", 1.0)
    route.setdefault("arrival_radius", 36.0)
    route.setdefault("sequence", list(DEFAULT_GLOBAL_ROUTE_IDS))
    return movement, route


def _advance_global_route(shared, route, route_points, route_sequence, tick):
    phase = int(route.get("phase", 0))
    next_phase = (phase + 1) % max(1, len(route_points))
    route["phase"] = next_phase
    route["stage"] = "entry"
    route["stage_started_tick"] = int(tick)
    route["hold_until_tick"] = int(tick) + int(route.get("hold_ticks", 18))
    events = shared.setdefault("events", [])
    target_ref = route_sequence[next_phase]
    if isinstance(target_ref, dict):
        target_building = target_ref.get("id")
        target_anchor = target_ref.get("anchor", "entry")
    else:
        target_building = target_ref
        target_anchor = "entry"
    events.append(
        {
            "type": "global_route_phase",
            "phase": next_phase,
            "target_building": target_building,
            "target_anchor": target_anchor,
            "network": "Arc",
            "asset": "USDC",
        }
    )


def _route_slot_target(base_target, entity_id, stage):
    # Keep agents in the same building but avoid one-pixel clumping.
    # Entry stage uses narrower spread near door; inside can spread wider.
    max_abs = 12.0 if stage == "entry" else 36.0
    ox, oy = _stable_lane_offset(f"{entity_id}:{stage}", max_abs=max_abs)
    return _clamp_world(base_target[0] + ox, base_target[1] + oy)


def _apply_global_route_targets(shared):
    entities = shared.setdefault("entities", {})
    if not entities:
        return False
    movement, route = _ensure_global_route_state(shared)
    if not bool(route.get("enabled", GLOBAL_ROUTE_MODE)):
        return False

    raw_sequence = route.get("sequence", list(DEFAULT_GLOBAL_ROUTE_IDS))
    route_sequence = []
    for item in raw_sequence:
        if isinstance(item, dict):
            bid = str(item.get("id", "")).strip().upper()
            anchor = str(item.get("anchor", "center")).strip().lower() or "center"
            if anchor not in {"entry", "inside", "center"}:
                anchor = "center"
            if bid:
                route_sequence.append({"id": bid, "anchor": anchor})
        else:
            bid = str(item).strip().upper()
            if bid:
                route_sequence.append({"id": bid, "anchor": "center"})
    if not route_sequence:
        route_sequence = list(DEFAULT_GLOBAL_ROUTE_IDS)
    route["sequence"] = route_sequence
    route_stops = _get_global_route_stops(route_sequence)
    if not route_stops:
        return False

    tick = int(shared.setdefault("economy", {}).get("tick", 0))
    phase = int(route.get("phase", 0)) % len(route_stops)
    stage = str(route.get("stage", "entry")).lower()
    inside_stage_enabled = bool(route.get("inside_stage_enabled", False))
    if not inside_stage_enabled:
        stage = "entry"
        route["stage"] = "entry"
    stop = route_stops[phase]
    if stage not in {"entry", "inside"}:
        stage = "entry"
    if inside_stage_enabled:
        base_target = stop["entry"] if stage == "entry" else stop["inside"]
    else:
        base_target = stop["target"]
    base_radius = float(route.get("arrival_radius", 36.0))
    radius = base_radius if stage == "entry" else max(base_radius, 64.0)

    total = 0
    arrived = 0
    for entity_id, entity in entities.items():
        manual_target = entity.get("manual_target")
        if isinstance(manual_target, dict) and bool(manual_target.get("active", True)):
            tx = float(manual_target.get("x", entity.get("x", 0.0)) or 0.0)
            ty = float(manual_target.get("y", entity.get("y", 0.0)) or 0.0)
            entity["target_x"], entity["target_y"] = _clamp_world(tx, ty)
            radius = float(manual_target.get("arrival_radius", 40.0) or 40.0)
            persist = bool(manual_target.get("persist", False))
            hold_ticks = max(0, int(manual_target.get("hold_ticks", 0) or 0))
            if _near(entity, (tx, ty), radius):
                arrived_tick = int(manual_target.get("arrived_tick", tick))
                manual_target["arrived_tick"] = arrived_tick
                should_release = (not persist) or (hold_ticks > 0 and (int(tick) - arrived_tick) >= hold_ticks)
                if should_release:
                    manual_target["active"] = False
                    entity["manual_target"] = manual_target
            else:
                manual_target.pop("arrived_tick", None)
                entity["manual_target"] = manual_target
            continue
        total += 1
        slot_target = _route_slot_target(base_target, entity_id, stage)
        entity["target_x"], entity["target_y"] = slot_target
        if _near(entity, slot_target, radius):
            arrived += 1

    arrival_ratio = (arrived / max(1, total))
    required_ratio = float(route.get("arrival_ratio", 1.0))
    hold_until = int(route.get("hold_until_tick", 0))
    stage_started_tick = int(route.get("stage_started_tick", tick))
    stage_elapsed = max(0, int(tick) - stage_started_tick)
    max_stage_ticks = max(20, int(route.get("max_stage_ticks", 220)))
    stage_timed_out = stage_elapsed >= max_stage_ticks
    allow_stage_timeout = bool(route.get("allow_stage_timeout", False))
    can_advance_on_timeout = allow_stage_timeout and stage_timed_out

    if tick >= hold_until and (arrival_ratio >= required_ratio or can_advance_on_timeout):
        if stage == "entry" and inside_stage_enabled:
            route["stage"] = "inside"
            route["stage_started_tick"] = int(tick)
            route["hold_until_tick"] = int(tick) + max(8, int(route.get("hold_ticks", 24)) // 2)
            shared.setdefault("events", []).append(
                {
                    "type": "global_route_stage",
                    "phase": phase,
                    "target_building": stop["id"],
                    "stage": "inside",
                    "arrival_ratio": round(arrival_ratio, 3),
                    "timed_out": bool(can_advance_on_timeout),
                    "network": "Arc",
                    "asset": "USDC",
                }
            )
        else:
            _advance_global_route(shared, route, route_stops, route_sequence, tick)
    movement["global_route"] = route
    return True


def _ensure_spatial_fields(entity):
    if "x" not in entity or "y" not in entity:
        x = random.uniform(WORLD_MIN_X, WORLD_MAX_X)
        y = random.uniform(WORLD_MIN_Y, WORLD_MAX_Y)
        entity["x"], entity["y"] = _clamp_world(x, y)
    if "target_x" not in entity or "target_y" not in entity:
        entity["target_x"], entity["target_y"] = _clamp_world(entity["x"], entity["y"])


def _ensure_role_hubs(shared):
    movement = shared.setdefault("movement", {})
    hubs = movement.setdefault("role_hubs", {})
    for key, bid in ROLE_HUB_DEFAULTS.items():
        hubs.setdefault(key, bid)
    return hubs


def _hub_point(shared, hub_key, anchor="inside", default=(912.0, 1168.0)):
    hubs = _ensure_role_hubs(shared)
    bid = str(hubs.get(hub_key, ROLE_HUB_DEFAULTS.get(hub_key, ""))).strip().upper()
    if not bid:
        return _clamp_world(default[0], default[1])
    return _get_building_point(bid, anchor, default)


def _home_zone(shared, entity):
    entity_type = str(entity.get("type", "")).lower()
    role = str(entity.get("persona_role", entity_type)).lower()

    if entity_type == "worker":
        return _hub_point(shared, "worker_home", "inside", default=WORKER_HOME_ZONE)
    if entity_type == "thief":
        return _hub_point(shared, "thief_home", "inside", default=THIEF_ZONE)
    if entity_type == "cop":
        return _hub_point(shared, "cop_home", "inside", default=COP_ZONE)
    if role == "spy":
        return _hub_point(shared, "spy_home", "inside", default=BANKER_ZONE)
    if entity_type == "banker":
        return _hub_point(shared, "bank_home", "inside", default=BANKER_ZONE)
    if entity_type == "bank":
        return _hub_point(shared, "bank_home", "inside", default=BANK_ZONE)
    return _clamp_world(WORKER_HOME_ZONE[0], WORKER_HOME_ZONE[1])


def _near(entity, target, radius):
    ex = float(entity.get("x", 0.0) or 0.0)
    ey = float(entity.get("y", 0.0) or 0.0)
    tx, ty = float(target[0]), float(target[1])
    return math.hypot(ex - tx, ey - ty) <= float(radius)


def _find_target_entity(entities, target_id):
    if not target_id:
        return None
    return entities.get(target_id)


def _choose_entity_by_type(entities, entity_type):
    matches = [e for e in entities.values() if e.get("type") == entity_type]
    if not matches:
        return None
    return random.choice(matches)


def _set_behavior_target(entity, entities, shared):
    entity_type = entity.get("type")
    entity_role = str(entity.get("persona_role", entity_type)).lower()
    top_action = str(entity.get("top_action") or "").lower()
    target_id = entity.get("target")

    # Demo override: force all agents to meet at one shared target point.
    if FORCE_SINGLE_TARGET:
        center = _get_building_point(SINGLE_TARGET_BUILDING_ID, SINGLE_TARGET_POINT, default=(912.0, 1168.0))
        jitter = 8.0
        entity["target_x"], entity["target_y"] = _clamp_world(
            center[0] + random.uniform(-jitter, jitter),
            center[1] + random.uniform(-jitter, jitter),
        )
        return

    if entity_type == "worker":
        route = str(entity.get("work_route", "to_mine"))
        haul_mode = str(entity.get("haul_mode", ""))

        # After mining, workers must physically return home before next run.
        if haul_mode == "return_home":
            route = "to_home"
        elif route not in {"to_mine", "to_home"}:
            route = "to_mine"

        worker_work_zone = _hub_point(shared, "worker_work", "inside", default=WORK_ZONE)
        worker_home_zone = _home_zone(shared, entity)

        if route == "to_mine":
            entity["target_x"], entity["target_y"] = _clamp_world(
                worker_work_zone[0] + random.uniform(-65, 65),
                worker_work_zone[1] + random.uniform(-45, 45),
            )
            entity["work_route"] = "to_mine"
            if _near(entity, worker_work_zone, 90):
                entity["at_mine"] = True
            else:
                entity["at_mine"] = False
            return

        entity["target_x"], entity["target_y"] = _clamp_world(
            worker_home_zone[0] + random.uniform(-70, 70),
            worker_home_zone[1] + random.uniform(-50, 50),
        )
        entity["work_route"] = "to_home"
        entity["at_mine"] = False
        if _near(entity, worker_home_zone, 95):
            entity["haul_mode"] = ""
            entity["work_route"] = "to_mine"
            return

    if entity_type == "thief":
        thief_zone = _home_zone(shared, entity)
        entity["target_x"], entity["target_y"] = _clamp_world(
            thief_zone[0] + random.uniform(-80, 80),
            thief_zone[1] + random.uniform(-55, 55),
        )
        return

    if entity_type == "cop":
        cop_zone = _home_zone(shared, entity)
        entity["target_x"], entity["target_y"] = _clamp_world(
            cop_zone[0] + random.uniform(-90, 90),
            cop_zone[1] + random.uniform(-60, 60),
        )
        return

    if entity_type in {"bank", "banker"}:
        if entity_type == "bank":
            zone = _hub_point(shared, "bank_home", "entry", default=BANK_ZONE)
            jitter = 10
            entity["target_x"], entity["target_y"] = _clamp_world(
                zone[0] + random.uniform(-jitter, jitter),
                zone[1] + random.uniform(-jitter, jitter),
            )
            return

        tick = int(shared.setdefault("economy", {}).get("tick", 0))
        hubs = _ensure_role_hubs(shared)
        if entity_role == "spy":
            home_hub_key = "spy_home"
            default_home = _hub_point(shared, "spy_home", "center", default=BANKER_ZONE)
            patrol_hold = 14
        else:
            home_hub_key = "bank_home"
            default_home = _hub_point(shared, "bank_home", "center", default=BANKER_ZONE)
            patrol_hold = 18

        home_bid = str(hubs.get(home_hub_key, ROLE_HUB_DEFAULTS.get(home_hub_key, ""))).strip().upper()
        home_bbox = _get_building_bbox(home_bid, default_center=default_home, pad_px=18.0)
        ex = float(entity.get("x", default_home[0]) or default_home[0])
        ey = float(entity.get("y", default_home[1]) or default_home[1])
        if not _point_in_bbox(ex, ey, home_bbox):
            # If nudged out, immediately recover back inside home bounds.
            entity["target_x"], entity["target_y"] = _clamp_to_bbox(default_home[0], default_home[1], home_bbox)
            return

        intruders = []
        self_id = str(entity.get("id", ""))
        for other_id, other in entities.items():
            if str(other_id) == self_id:
                continue
            ox = float(other.get("x", 0.0) or 0.0)
            oy = float(other.get("y", 0.0) or 0.0)
            if _point_in_bbox(ox, oy, home_bbox):
                intruders.append(other)

        if intruders:
            # Track nearest intruder while still constrained to home interior.
            intruders.sort(
                key=lambda o: math.hypot(
                    float(o.get("x", ex) or ex) - ex,
                    float(o.get("y", ey) or ey) - ey,
                )
            )
            target = intruders[0]
            tx = float(target.get("x", ex) or ex)
            ty = float(target.get("y", ey) or ey)
            entity["target_x"], entity["target_y"] = _clamp_to_bbox(tx, ty, home_bbox)
            entity["home_patrol_until_tick"] = int(tick) + 6
            entity["tracking_intruder"] = str(target.get("id", ""))
            return

        entity["tracking_intruder"] = ""
        px, py = _pick_patrol_point_in_bbox(
            entity,
            home_bbox,
            tick,
            hold_ticks=patrol_hold,
            anchor=default_home,
            anchor_spread=86.0,
        )
        entity["target_x"], entity["target_y"] = _clamp_to_bbox(px, py, home_bbox)
        return

    zone = _home_zone(shared, entity)
    entity["target_x"], entity["target_y"] = _clamp_world(
        zone[0] + random.uniform(-120, 120),
        zone[1] + random.uniform(-90, 90),
    )


def _move_entity(entity):
    _ensure_spatial_fields(entity)
    x = float(entity["x"])
    y = float(entity["y"])
    tx = float(entity["target_x"])
    ty = float(entity["target_y"])
    nx = x + (tx - x) * MOVE_LERP
    ny = y + (ty - y) * MOVE_LERP
    entity["x"], entity["y"] = _clamp_world(nx, ny)


def update_spatial_world(shared):
    entities = shared.setdefault("entities", {})
    for entity in entities.values():
        _ensure_spatial_fields(entity)
    if _apply_global_route_targets(shared):
        for entity in entities.values():
            _move_entity(entity)
        return
    for entity in entities.values():
        manual_target = entity.get("manual_target")
        if isinstance(manual_target, dict) and bool(manual_target.get("active", True)):
            tx = float(manual_target.get("x", entity.get("x", 0.0)) or 0.0)
            ty = float(manual_target.get("y", entity.get("y", 0.0)) or 0.0)
            entity["target_x"], entity["target_y"] = _clamp_world(tx, ty)
            radius = float(manual_target.get("arrival_radius", 40.0) or 40.0)
            persist = bool(manual_target.get("persist", False))
            hold_ticks = max(0, int(manual_target.get("hold_ticks", 0) or 0))
            if _near(entity, (tx, ty), radius):
                arrived_tick = int(manual_target.get("arrived_tick", shared.setdefault("economy", {}).get("tick", 0)))
                manual_target["arrived_tick"] = arrived_tick
                curr_tick = int(shared.setdefault("economy", {}).get("tick", 0))
                should_release = (not persist) or (hold_ticks > 0 and (curr_tick - arrived_tick) >= hold_ticks)
                if should_release:
                    manual_target["active"] = False
            else:
                manual_target.pop("arrived_tick", None)
            entity["manual_target"] = manual_target
            continue
        _set_behavior_target(entity, entities, shared)
    for entity in entities.values():
        _move_entity(entity)


def _count_population(entities):
    counts = {"worker": 0, "thief": 0, "cop": 0, "banker": 0, "bank": 0}
    for entity in entities.values():
        entity_type = entity.get("type")
        if entity_type in counts:
            counts[entity_type] += 1
    counts["total"] = sum(counts.values())
    return counts


def _ratios(counts):
    total = max(1, counts.get("total", 0))
    return {
        "worker": counts.get("worker", 0) / total,
        "thief": counts.get("thief", 0) / total,
        "cop": counts.get("cop", 0) / total,
        "banker": counts.get("banker", 0) / total,
        "bank": counts.get("bank", 0) / total,
    }


def _regime_from_counts(counts, ratios):
    workers = counts.get("worker", 0)
    thieves = counts.get("thief", 0)
    cops = counts.get("cop", 0)
    total = counts.get("total", 0)

    if total < 4:
        return "bootstrapping"
    if ratios["cop"] >= 0.45 and cops >= max(3, thieves + workers // 2):
        return "police_state"
    if ratios["thief"] >= 0.34 and thieves >= max(2, workers):
        return "decline"
    if ratios["worker"] >= 0.5 and workers > (thieves + cops):
        return "growth"
    return "balanced"


def _regime_profile(regime):
    if regime == "bootstrapping":
        return {
            "narration": "A frontier market is forming; every role still has outsized influence.",
            "multipliers": {
                "worker_income": 1.0,
                "worker_tax": 0.0,
                "theft_success": 1.0,
                "cop_effectiveness": 1.0,
                "api_cost": 1.0,
                "bank_fee": 1.0,
            },
            "ui_phase": "boot",
        }
    if regime == "decline":
        return {
            "narration": "Thief dominance drives decline: workers lose income and theft pressure surges.",
            "multipliers": {
                "worker_income": 0.7,
                "worker_tax": 0.0,
                "theft_success": 1.35,
                "cop_effectiveness": 0.85,
                "api_cost": 1.2,
                "bank_fee": 1.15,
            },
            "ui_phase": "crime",
        }
    if regime == "police_state":
        return {
            "narration": "Police state active: surveillance rises, theft drops, and workers lose 10% to compliance drag.",
            "multipliers": {
                "worker_income": 1.0,
                "worker_tax": 0.10,
                "theft_success": 0.65,
                "cop_effectiveness": 1.4,
                "api_cost": 0.85,
                "bank_fee": 1.2,
            },
            "ui_phase": "stress",
        }
    if regime == "growth":
        return {
            "narration": "Worker-led expansion: production rises, theft edge weakens, and liquidity improves.",
            "multipliers": {
                "worker_income": 1.22,
                "worker_tax": 0.0,
                "theft_success": 0.8,
                "cop_effectiveness": 1.05,
                "api_cost": 0.9,
                "bank_fee": 0.9,
            },
            "ui_phase": "stable",
        }
    return {
        "narration": "Balanced city: production, enforcement, and risk remain in tension.",
        "multipliers": {
            "worker_income": 1.0,
            "worker_tax": 0.0,
            "theft_success": 1.0,
            "cop_effectiveness": 1.0,
            "api_cost": 1.0,
            "bank_fee": 1.0,
        },
        "ui_phase": "flux",
    }


def _compute_stability(ratios):
    target = {"worker": 0.55, "cop": 0.25, "thief": 0.15, "banker": 0.05}
    error = sum(abs(ratios[key] - target[key]) for key in target.keys())
    score = max(0.0, min(100.0, 100.0 - (error * 125.0)))
    return round(score, 2)


def _guidance(counts):
    active_total = max(1, counts["worker"] + counts["cop"] + counts["thief"] + counts["banker"])
    target_mix = {"worker": 0.55, "cop": 0.25, "thief": 0.15, "banker": 0.05}
    recommended = {}
    for role, share in target_mix.items():
        value = int(round(active_total * share))
        recommended[role] = max(1 if active_total > 0 else 0, value)
    adjustments = {role: recommended[role] - counts.get(role, 0) for role in recommended.keys()}
    notes = []
    for role, delta in adjustments.items():
        if delta > 0:
            notes.append(f"Add {delta} {role}(s) for stability.")
        elif delta < 0:
            notes.append(f"Reduce {-delta} {role}(s) to rebalance.")
    if not notes:
        notes.append("Population is near the stable mix.")
    return {
        "target_mix": target_mix,
        "recommended_counts": recommended,
        "adjustments": adjustments,
        "notes": notes[:4],
    }


def update_macro_economy(shared):
    economy = shared.setdefault("economy", {})
    entities = shared.setdefault("entities", {})
    events = shared.setdefault("events", [])

    counts = _count_population(entities)
    ratios = _ratios(counts)
    regime = _regime_from_counts(counts, ratios)
    profile = _regime_profile(regime)
    old_regime = economy.get("regime")

    economy["tick"] = int(economy.get("tick", 0)) + 1
    economy["regime"] = regime
    economy["narration"] = profile["narration"]
    economy["population"] = counts
    economy["ratios"] = ratios
    economy["multipliers"] = profile["multipliers"]
    economy["stability_score"] = _compute_stability(ratios)
    economy["guidance"] = _guidance(counts)
    economy["ui_phase"] = profile["ui_phase"]

    if old_regime != regime:
        events.append(
            {
                "type": "regime_shift",
                "regime": regime,
                "narration": profile["narration"],
                "population": counts,
                "multipliers": profile["multipliers"],
                "stability_score": economy["stability_score"],
                "guidance": economy["guidance"],
                "network": "Arc",
                "asset": "USDC",
            }
        )
    elif economy["tick"] % 10 == 0:
        events.append(
            {
                "type": "economic_guidance",
                "regime": regime,
                "stability_score": economy["stability_score"],
                "guidance": economy["guidance"],
                "network": "Arc",
                "asset": "USDC",
            }
        )


def run_loop(state):
    """
    Main engine loop
    """
    import core.state as state_module
    from agents.banker import handle_bank
    from agents.cop import handle_cop
    from agents.thief import handle_thief
    from agents.worker import handle_worker
    from tx.arc import execute_settlement_cycle
    from utils.helpers import compute_policy_bias, compute_reflection, maybe_reflect

    shared = state_module.state
    if state is not shared:
        shared.clear()
        shared.update(state)

    update_macro_economy(shared)
    tick = int(shared.setdefault("economy", {}).get("tick", 0))
    entities = shared.setdefault("entities", {})
    events = shared.setdefault("events", [])
    pre_event_count = len(events)
    events.append(
        {
            "type": "loop_tick_start",
            "tick": tick,
            "entity_count": len(entities),
            "network": "Arc",
            "asset": "USDC",
        }
    )

    for entity in list(entities.values()):
        entity_type = entity.get("type")
        if entity_type == "worker":
            handle_worker(entity, shared)
        elif entity_type == "thief":
            handle_thief(entity, shared)
        elif entity_type == "cop":
            handle_cop(entity, shared)
        elif entity_type in {"banker", "bank"}:
            handle_bank(entity, shared)

    update_spatial_world(shared)

    economy = shared.setdefault("economy", {})
    settlement_summary = execute_settlement_cycle(shared, economy.get("tick", 0))
    if settlement_summary is not None:
        events.append(
            {
                "type": "settlement_cycle",
                "summary": settlement_summary,
                "network": "Arc",
                "asset": "USDC",
            }
        )

    IMPORTANT_EVENTS = {
        "worker_earn",
        "steal_agent",
        "steal_bank",
        "cop_chase",
        "bank_fee_cycle",
        "credit",
        "debit",
    }

    # Memory ingestion: attach economic deltas to per-agent rolling memory buffers.
    def add_memory(agent_id, event, delta):
        if not agent_id:
            return
        agent = entities.get(agent_id)
        if not isinstance(agent, dict):
            return
        memory = agent.setdefault("memory", [])
        memory.append(
            {
                "type": event.get("type"),
                "delta": float(delta),
                "tick": tick,
            }
        )
        if len(memory) > 15:
            del memory[: len(memory) - 15]

    new_events = list(events[pre_event_count:])
    for event in new_events:
        event_type = str(event.get("type"))
        if event_type not in IMPORTANT_EVENTS:
            continue
        if event_type == "debit":
            add_memory(event.get("agent_id"), event, -float(event.get("amount", 0.0) or 0.0))
        elif event_type == "credit":
            add_memory(event.get("agent_id"), event, float(event.get("amount", 0.0) or 0.0))
        elif event_type == "worker_earn":
            reward = float(event.get("reward", 0.0) or 0.0)
            cost = float(event.get("cost", 0.0) or 0.0)
            tax = float(event.get("worker_tax", 0.0) or 0.0)
            add_memory(event.get("worker_id"), event, reward - cost - tax)
        elif event_type == "worker_support_received":
            add_memory(event.get("worker_id"), event, float(event.get("amount", 0.0) or 0.0))
            add_memory(event.get("bank_id"), event, -float(event.get("amount", 0.0) or 0.0))
        elif event_type == "steal_agent":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, amount)
            add_memory(event.get("target_id"), event, -amount)
        elif event_type == "steal_bank":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, amount)
            add_memory(event.get("bank_id"), event, -amount)
        elif event_type == "thief_deposit":
            amount = float(event.get("amount", 0.0) or 0.0)
            add_memory(event.get("thief_id"), event, -amount)
            add_memory(event.get("bank_id"), event, amount)
        elif event_type == "cop_chase":
            penalty = float(event.get("penalty", 0.0) or 0.0)
            add_memory(event.get("cop_id"), event, 0.3 if event.get("captured") else -0.2)
            if event.get("captured") and penalty > 0:
                add_memory(event.get("target_id"), event, -penalty)
        elif event_type == "api_call":
            add_memory(event.get("agent"), event, -float(event.get("cost", 0.0) or 0.0))
        elif event_type == "bank_fee_cycle":
            add_memory(event.get("bank_id"), event, float(event.get("fee_collected", 0.0) or 0.0))
        elif event_type == "bank_redistribution":
            add_memory(event.get("bank_id"), event, -float(event.get("total_amount", 0.0) or 0.0))
        elif event_type == "bank_anti_hoard_levy":
            add_memory(event.get("bank_id"), event, float(event.get("levy_total", 0.0) or 0.0))

    if tick % 10 == 0:
        for entity in entities.values():
            reflection = compute_reflection(entity)
            entity["reflection"] = reflection
            entity["policy_bias"] = compute_policy_bias(entity)
            maybe_reflect(entity, state=shared, role=entity.get("type"))
            events.append(
                {
                    "type": "agent_reflection",
                    "agent": entity.get("id"),
                    "state": reflection,
                    "network": "Arc",
                    "asset": "USDC",
                }
            )

    metrics = shared.setdefault("metrics", {})
    total_spent = float(metrics.get("total_spent", 0.0))
    successful_tx = int(metrics.get("successful_tx", 0))
    failed_tx = int(metrics.get("failed_tx", 0))
    metrics["cost_per_action"] = total_spent / max(successful_tx, 1)
    metrics["success_rate"] = successful_tx / max(successful_tx + failed_tx, 1)

    if state is not shared:
        state.clear()
        state.update(shared)

    events.append(
        {
            "type": "loop_tick_end",
            "tick": tick,
            "event_count": len(events),
            "successful_tx": int(metrics.get("successful_tx", 0)),
            "failed_tx": int(metrics.get("failed_tx", 0)),
            "network": "Arc",
            "asset": "USDC",
        }
    )
