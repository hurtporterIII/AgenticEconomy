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
# Server is now the single movement authority. Entities walk along an A*
# path computed against the same Collisions layer the Phaser tilemap uses,
# one fixed step per tick. The client is expected to render the sprite at
# the server's x/y (no client-side pathfinding).
MOVE_STEP_PX = 18.0  # per-tick pixel advance along the walkable path
MOVE_ARRIVAL_EPS = 2.0  # consider a waypoint reached within this many pixels
PATH_REPLAN_EVERY_TICKS = 45  # periodically refresh A* even if target unchanged
UNSTICK_EMPTY_PATH_TICKS = 12  # deterministic recovery window before snap
FORCE_SINGLE_TARGET = False
SINGLE_TARGET_BUILDING_ID = os.getenv("SINGLE_TARGET_BUILDING_ID", "B08").strip().upper()
SINGLE_TARGET_POINT = "center"
DEFAULT_GLOBAL_ROUTE_IDS = (
    {"id": "B11", "anchor": "center"},
    {"id": "B08", "anchor": "center"},
)
# Derived from the single registry — see core/locations.py ROLE_PLACES.
# Do NOT hardcode role->building mappings anywhere else.
from core import locations as _locations
ROLE_HUB_DEFAULTS = _locations.flat_hub_defaults()
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


def _next_patrol_point_in_bbox(entity, bbox):
    """Deterministic patrol waypoint sequence (no randomness).

    Used for cop fallback movement so the sprite visibly walks a route instead
    of jittering in place."""
    min_x, min_y, max_x, max_y = bbox
    pad = 24.0
    points = [
        (min_x + pad, min_y + pad),
        (max_x - pad, min_y + pad),
        (max_x - pad, max_y - pad),
        (min_x + pad, max_y - pad),
        ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0),
    ]
    idx = int(entity.get("_patrol_idx", 0) or 0)
    entity["_patrol_idx"] = idx + 1
    px, py = points[idx % len(points)]
    return _clamp_to_bbox(px, py, bbox)


# Canonical geolocated anchors (all from building catalog, not hardcoded map guesses).
# Center points align with visible building-name anchors.
# All place coordinates come from core/locations.py (the single registry).
# These module-level constants always resolve to the "entry" anchor (the
# door), which is what agents should actually navigate to. If you need
# center/inside, call locations.point(..., anchor="...") explicitly instead
# of adding new constants.
WORK_ZONE        = _locations.point("worker", "work")   # B11 entry
WORKER_HOME_ZONE = _locations.point("worker", "home")   # B08 entry
THIEF_ZONE       = _locations.point("thief",  "home")   # B07 entry
COP_ZONE         = _locations.point("cop",    "home")   # B09 entry
BANKER_ZONE      = _locations.point("banker", "home")   # B12 entry
BANK_ZONE        = _locations.point("bank",   "home")   # B12 entry


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
    # Off unless explicitly enabled (API or saved state); avoids parade mode hijacking workers.
    route.setdefault("enabled", False)
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
    if not bool(route.get("enabled", False)):
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
        # Workers follow shift / role hubs — never the global parade target.
        if str(entity.get("type", "") or "").lower() == "worker":
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
    """Return the 'home' point for an entity. One lookup, no fallbacks: the
    role -> place mapping lives in core/locations.py."""
    entity_type = str(entity.get("type", "")).lower()
    role = str(entity.get("persona_role", entity_type)).lower()
    lookup_role = "spy" if role == "spy" else entity_type
    if lookup_role not in _locations.ROLE_PLACES:
        lookup_role = "worker"  # last-resort fallback; see locations.ROLE_PLACES
    x, y = _locations.point(lookup_role, "home")
    return _clamp_world(x, y)


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
    tick = int(shared.setdefault("economy", {}).get("tick", 0) or 0)

    # Demo override: force all agents to meet at one shared target point.
    if FORCE_SINGLE_TARGET:
        center = _get_building_point(SINGLE_TARGET_BUILDING_ID, SINGLE_TARGET_POINT, default=(912.0, 1168.0))
        jitter = 8.0
        entity["target_x"], entity["target_y"] = _clamp_world(
            center[0] + random.uniform(-jitter, jitter),
            center[1] + random.uniform(-jitter, jitter),
        )
        return

    # PASS 2: if the entity has queued actions, the queue wins over the
    # default FSM / roaming logic. Workers are deliberately excluded so
    # the nano-economy worker FSM remains the sole authority for
    # worker movement (per the hard rule set by the user).
    if entity_type != "worker":
        from core.action_queue import consume_action_queue
        tick = int(shared.setdefault("economy", {}).get("tick", 0) or 0)
        if consume_action_queue(entity, shared, tick):
            return

    if entity_type == "worker":
        shift = str(entity.get("worker_shift_phase", "to_mine")).strip() or "to_mine"
        # One registry decides anchors (see core/locations.py DEFAULT_ANCHOR).
        # Home defaults to "inside" so workers actually walk into the house,
        # not stop at the doorway tile. Work and bank default to "entry".
        work_pt = _locations.point("worker", "work")
        home_pt = _locations.point("worker", "home")
        bank_pt = _locations.point("worker", "bank")

        # Lock the jittered target for the duration of each phase. Re-rolling
        # the random jitter every tick was causing target_x/target_y to jump
        # up to ~64px/tick, which forced A* to repath constantly and
        # produced the visible "pacing back and forth" behavior.
        last_shift = str(entity.get("_shift_locked") or "")
        need_new = (last_shift != shift) or ("target_x" not in entity) or ("target_y" not in entity)
        if need_new:
            # Deterministic FSM: target MUST match the arrival check in
            # agents/worker.py exactly. No jitter, no randomness — the
            # worker has to land on the same pixel the FSM is testing.
            from core.pois import try_poi

            if shift == "to_bank":
                poi = try_poi("bank_customer_spot")
                anchor = poi if poi is not None else bank_pt
            elif shift == "to_home":
                poi = try_poi("worker_home_inside")
                anchor = poi if poi is not None else home_pt
            else:
                anchor = work_pt

            tx, ty = _clamp_world(anchor[0], anchor[1])
            entity["target_x"] = tx
            entity["target_y"] = ty
            entity["_shift_locked"] = shift

        if shift == "to_bank":
            entity["work_route"] = "to_bank"
            entity["at_mine"] = False
            return
        if shift == "to_home":
            entity["work_route"] = "to_home"
            entity["at_mine"] = False
            return
        entity["work_route"] = "to_mine"
        entity["at_mine"] = bool(_near(entity, work_pt, 96))
        return

    if entity_type == "thief":
        thief_zone = _home_zone(shared, entity)
        entity["target_x"], entity["target_y"] = _clamp_world(
            thief_zone[0] + random.uniform(-80, 80),
            thief_zone[1] + random.uniform(-55, 55),
        )
        return

    if entity_type == "cop":
        # Deterministic city patrol fallback when queue is empty:
        # spy home -> thief home -> bank -> police station.
        # This keeps cop movement readable and avoids "circling one spot".
        patrol_points = [
            _locations.point("spy", "home"),
            _locations.point("thief", "home"),
            _locations.point("bank", "home"),
            _locations.point("cop", "home"),
        ]
        idx = int(entity.get("_cop_city_patrol_idx", 0) or 0)
        hold_until = int(entity.get("_cop_patrol_hold_until_tick", -1) or -1)
        px, py = patrol_points[idx % len(patrol_points)]
        px, py = _clamp_world(px, py)

        if tick < hold_until:
            entity["target_x"], entity["target_y"] = px, py
            return

        if _near(entity, (px, py), 36.0):
            entity["_cop_city_patrol_idx"] = idx + 1
            entity["_cop_patrol_hold_until_tick"] = int(tick) + 16
            npx, npy = patrol_points[(idx + 1) % len(patrol_points)]
            entity["target_x"], entity["target_y"] = _clamp_world(npx, npy)
            return

        entity["target_x"], entity["target_y"] = px, py
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

        # --- Banker: roam the bank until a customer walks in, then go
        # to the desk and stay there until they leave. ---
        # - No one in the bank bbox  → patrol (same wandering logic the
        #   spy uses, confined to the bank's interior).
        # - Someone else in the bbox → snap to the 'banker_desk' POI
        #   (or bank center as a fallback) and hold there until the
        #   customer leaves. Deliberately does NOT track the customer,
        #   so it doesn't look like the banker is chasing them out.
        if entity_role != "spy":
            home_hub_key = "bank_home"
            default_home = _hub_point(shared, "bank_home", "center", default=BANKER_ZONE)
            home_bid = str(hubs.get(home_hub_key, ROLE_HUB_DEFAULTS.get(home_hub_key, ""))).strip().upper()
            home_bbox = _get_building_bbox(home_bid, default_center=default_home, pad_px=18.0)

            ex = float(entity.get("x", default_home[0]) or default_home[0])
            ey = float(entity.get("y", default_home[1]) or default_home[1])
            if not _point_in_bbox(ex, ey, home_bbox):
                # Nudged out of the bank — recover back inside first.
                entity["target_x"], entity["target_y"] = _clamp_to_bbox(
                    default_home[0], default_home[1], home_bbox
                )
                return

            # Is any non-banker currently inside the bank?
            self_id = str(entity.get("id", ""))
            customer_present = False
            for other_id, other in entities.items():
                if str(other_id) == self_id:
                    continue
                if str(other.get("type", "")).lower() in {"banker", "bank"}:
                    continue
                ox = float(other.get("x", 0.0) or 0.0)
                oy = float(other.get("y", 0.0) or 0.0)
                if _point_in_bbox(ox, oy, home_bbox):
                    customer_present = True
                    break

            if customer_present:
                # Prefer the 'banker_desk' POI when it's placed inside
                # the bank. Otherwise fall back to the bank center so
                # the banker still has a well-defined spot to stand.
                desk_pt = default_home
                try:
                    from core.pois import try_poi
                    poi = try_poi("banker_desk")
                    if poi is not None and _point_in_bbox(poi[0], poi[1], home_bbox):
                        desk_pt = (float(poi[0]), float(poi[1]))
                except Exception:
                    pass

                entity["tracking_intruder"] = ""
                entity["at_desk"] = True
                entity["target_x"], entity["target_y"] = _clamp_to_bbox(
                    desk_pt[0], desk_pt[1], home_bbox
                )
                return

            # Empty bank -> roam.
            entity["tracking_intruder"] = ""
            entity["at_desk"] = False
            px, py = _pick_patrol_point_in_bbox(
                entity,
                home_bbox,
                tick,
                hold_ticks=18,
                anchor=default_home,
                anchor_spread=86.0,
            )
            entity["target_x"], entity["target_y"] = _clamp_to_bbox(
                px, py, home_bbox
            )
            return

        # --- Spy: keep patrol + intruder tracking inside home bbox ---
        home_hub_key = "spy_home"
        default_home = _hub_point(shared, "spy_home", "center", default=BANKER_ZONE)
        patrol_hold = 14

        home_bid = str(hubs.get(home_hub_key, ROLE_HUB_DEFAULTS.get(home_hub_key, ""))).strip().upper()
        home_bbox = _get_building_bbox(home_bid, default_center=default_home, pad_px=18.0)
        ex = float(entity.get("x", default_home[0]) or default_home[0])
        ey = float(entity.get("y", default_home[1]) or default_home[1])
        if not _point_in_bbox(ex, ey, home_bbox):
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


def _path_needs_replan(entity: dict) -> bool:
    """True if the entity's cached A* path is stale relative to its current
    position or target. Cheap checks only — no pathfinding here."""
    tx = float(entity.get("target_x", entity.get("x", 0.0)) or 0.0)
    ty = float(entity.get("target_y", entity.get("y", 0.0)) or 0.0)
    last_target = entity.get("_path_target")
    waypoints = entity.get("_path") or []
    if not last_target or not waypoints:
        return True
    if abs(float(last_target[0]) - tx) > 1.0 or abs(float(last_target[1]) - ty) > 1.0:
        return True
    age = int(entity.get("_path_age_ticks", 0) or 0)
    return age >= PATH_REPLAN_EVERY_TICKS


def _recompute_path(entity: dict) -> None:
    """Run A* on the Collisions grid from the entity's current pixel to its
    (target_x, target_y), caching the waypoint list on the entity."""
    from core import navmesh

    x = float(entity.get("x", 0.0) or 0.0)
    y = float(entity.get("y", 0.0) or 0.0)
    tx = float(entity.get("target_x", x) or x)
    ty = float(entity.get("target_y", y) or y)
    waypoints = navmesh.find_path_world(x, y, tx, ty)
    entity["_path"] = waypoints
    entity["_path_target"] = (tx, ty)
    entity["_path_age_ticks"] = 0


def _move_entity(entity):
    """Advance the entity one fixed step along its cached walkable path.
    Pathfinding itself is deferred to `_recompute_path` so the hot per-tick
    loop is O(1). Corner-cutting is already prevented inside A* (see navmesh).
    """
    _ensure_spatial_fields(entity)
    x = float(entity["x"])
    y = float(entity["y"])
    tx = float(entity["target_x"])
    ty = float(entity["target_y"])
    if math.hypot(tx - x, ty - y) <= MOVE_ARRIVAL_EPS:
        entity["_path"] = []
        entity["_path_target"] = (tx, ty)
        entity["_stuck_empty_path_ticks"] = 0
        return

    if _path_needs_replan(entity):
        _recompute_path(entity)

    waypoints = list(entity.get("_path") or [])
    # If the solver can't produce waypoints for several ticks in a row, the
    # entity is usually standing on (or immediately boxed by) a blocked tile.
    # Recover deterministically by snapping to nearest walkable tile center.
    if not waypoints:
        stuck_ticks = int(entity.get("_stuck_empty_path_ticks", 0) or 0) + 1
        entity["_stuck_empty_path_ticks"] = stuck_ticks
        if stuck_ticks >= UNSTICK_EMPTY_PATH_TICKS:
            from core import navmesh
            sx, sy = navmesh.world_to_tile(x, y)
            gx, gy = navmesh.world_to_tile(tx, ty)

            def _escape_tile_with_path(start_tx: int, start_ty: int, goal_tx: int, goal_ty: int, max_r: int = 24):
                # Deterministic ring scan around current tile; pick first tile
                # that is walkable AND has a non-empty path to goal.
                if navmesh.is_walkable(start_tx, start_ty):
                    p0 = navmesh.find_path_tiles(start_tx, start_ty, goal_tx, goal_ty)
                    if p0:
                        return start_tx, start_ty
                for r in range(1, max_r + 1):
                    for dx in range(-r, r + 1):
                        for dy in range(-r, r + 1):
                            if abs(dx) != r and abs(dy) != r:
                                continue
                            cx, cy = start_tx + dx, start_ty + dy
                            if not navmesh.is_walkable(cx, cy):
                                continue
                            path = navmesh.find_path_tiles(cx, cy, goal_tx, goal_ty)
                            if path:
                                return cx, cy
                return None

            chosen = _escape_tile_with_path(sx, sy, gx, gy, max_r=24)
            if chosen is None:
                # Last-resort fallback: nearest walkable, even if we can't
                # prove path connectivity this tick.
                chosen = navmesh.nearest_walkable(sx, sy, max_radius=24)
            nx_t, ny_t = int(chosen[0]), int(chosen[1])
            nx_w, ny_w = navmesh.tile_to_world(nx_t, ny_t)
            entity["x"], entity["y"] = _clamp_world(nx_w, ny_w)
            entity["_path"] = []
            entity["_path_target"] = None
            entity["_path_age_ticks"] = 0
            # Even if current tile is technically walkable, force a clean replan
            # cycle after the stuck window so workers don't remain frozen.
            entity["_stuck_empty_path_ticks"] = 0
        return
    else:
        entity["_stuck_empty_path_ticks"] = 0

    remaining_step = MOVE_STEP_PX
    nx, ny = x, y
    while waypoints and remaining_step > 0.0001:
        wx, wy = waypoints[0]
        dx = wx - nx
        dy = wy - ny
        dist = math.hypot(dx, dy)
        if dist <= MOVE_ARRIVAL_EPS:
            waypoints.pop(0)
            continue
        if dist <= remaining_step:
            nx, ny = wx, wy
            remaining_step -= dist
            waypoints.pop(0)
        else:
            nx += (dx / dist) * remaining_step
            ny += (dy / dist) * remaining_step
            remaining_step = 0.0
    entity["_path"] = waypoints
    entity["_path_age_ticks"] = int(entity.get("_path_age_ticks", 0) or 0) + 1
    entity["x"], entity["y"] = _clamp_world(nx, ny)


def update_spatial_world(shared):
    entities = shared.setdefault("entities", {})
    for entity in entities.values():
        _ensure_spatial_fields(entity)
    global_parade = _apply_global_route_targets(shared)
    if global_parade:
        for entity in entities.values():
            if str(entity.get("type", "") or "").lower() == "worker":
                continue
            _move_entity(entity)
    for entity in entities.values():
        if global_parade and str(entity.get("type", "") or "").lower() != "worker":
            continue
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
        if global_parade and str(entity.get("type", "") or "").lower() != "worker":
            continue
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

    # Nano-economy hooks: banker fees (reactive to worker_earn), thief steals
    # (reactive to home_storage), cop recovery (reactive to steal events).
    # Runs AFTER agent handlers so it can see this tick's emitted events.
    # No-op when core.flags.NANO_ECONOMY_HOOKS is off.
    from core.nano_economy import apply_nano_economy
    apply_nano_economy(shared)

    # PASS 1: translate fresh economy events into per-agent symbolic action
    # queues. Pure data (no movement is performed here; movement stays with
    # the spatial subsystem below and is untouched by PASS 1).
    from core.action_queue import apply_event_actions
    apply_event_actions(shared)

    update_spatial_world(shared)

    economy = shared.setdefault("economy", {})
    demo_fast = os.getenv("AGENTIC_SIM_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
    if not demo_fast:
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
            # New FSM emits a flat `amount`; legacy events carried
            # reward/cost/worker_tax. Accept both so replayed logs still
            # produce the right memory delta.
            if "amount" in event:
                delta = float(event.get("amount", 0.0) or 0.0)
            else:
                reward = float(event.get("reward", 0.0) or 0.0)
                cost = float(event.get("cost", 0.0) or 0.0)
                tax = float(event.get("worker_tax", 0.0) or 0.0)
                delta = reward - cost - tax
            add_memory(event.get("worker_id"), event, delta)
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
