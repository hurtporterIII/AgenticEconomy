"""
PASS 1 — Event → Action Queue.

Scans economy events produced during a tick and appends symbolic
"actions" to each agent's `entity.action_queue`. This is pure data:

    NO movement logic here. NO pathing. NO dest_x/dest_y writes.

An action is a plain dict:

    {"type": "move", "target": "<symbolic_target>"}
    {"type": "wait", "duration": <seconds>}

Symbolic targets are resolved later (PASS 2) to real world coordinates:

    spy_location        -> spy's current position / POI
    worker_home_inside  -> worker's home POI
    bank_customer_spot  -> bank customer POI
    police_station      -> cop's home / police POI
    thief_location      -> the named thief's current entity position

Idempotency: each source event is stamped with `_action_enqueued = True`
so a second scan over the same event is a no-op. This makes the mapper
safe to call multiple times per logical tick.
"""

from __future__ import annotations

import sys
from typing import Any


# PASS 4: tighter cap so agents always respond to RECENT events, not stale
# backlog. Anything over this gets FIFO-trimmed in `_push`.
_MAX_QUEUE_LEN = 24

# PASS 4 timing knobs. Durations are in ticks (default auto-tick is 250 ms, so
# 1.0 tick ≈ 250 ms). Keep these at module scope so they are tunable in one
# place without touching enqueue or execution logic.
#
# _PAUSE_DURATION     base pause that follows an event-driven move (the
#                     "breather" between discrete legs of a chase).
# _ARRIVAL_HOLD_TICKS after `distance <= 10`, hold in place for this many
#                     ticks before popping the move — prevents the visible
#                     "teleport to next target" snap.
# _MICRO_PAUSE_TICKS  injected between two back-to-back moves if the enqueue
#                     didn't already leave a wait between them.
_PAUSE_DURATION = 0.1
_ARRIVAL_HOLD_TICKS = 0
_MICRO_PAUSE_TICKS = 0.0
# Visual interaction holds (ticks). Auto-tick default is ~250ms, so:
# 8 ticks ≈ 2 seconds, enough to read "interaction" on screen.
_INTERACTION_HOLD_TICKS = 0.5
# Soft caps to avoid long stale behavior chains (especially thief/cops).
# When an entity is already busy with several queued actions, newer events are
# still marked consumed but we skip enqueue to keep movement responsive.
_THIEF_QUEUE_SOFT_CAP = 8
_COP_QUEUE_SOFT_CAP = 8


def _entity(state: dict, entity_id: str | None) -> dict | None:
    if not entity_id:
        return None
    ent = state.setdefault("entities", {}).get(entity_id)
    return ent if isinstance(ent, dict) else None


def _push(entity: dict, *actions: dict) -> None:
    """Append actions to the entity's queue, trimming the oldest entries
    if it would exceed _MAX_QUEUE_LEN (FIFO overflow)."""
    queue = entity.setdefault("action_queue", [])
    for act in actions:
        queue.append(act)
    if len(queue) > _MAX_QUEUE_LEN:
        # Drop the oldest entries so we keep the most recently planned
        # behavior. PASS 4 tightens this.
        del queue[: len(queue) - _MAX_QUEUE_LEN]


def _queue_len(entity: dict | None) -> int:
    if not isinstance(entity, dict):
        return 0
    q = entity.get("action_queue")
    if not isinstance(q, list):
        return 0
    return len(q)


def _thief_home_anchor(entity: dict) -> tuple[float, float]:
    """Persist a deterministic 'home anchor' per thief.

    We cannot rely on a map POI for thief home (none exists in required POIs),
    so we pin the first known position and reuse it forever."""
    hx = entity.get("_home_x")
    hy = entity.get("_home_y")
    if hx is None or hy is None:
        hx = float(entity.get("x", 0.0) or 0.0)
        hy = float(entity.get("y", 0.0) or 0.0)
        entity["_home_x"] = hx
        entity["_home_y"] = hy
    return float(hx), float(hy)


def _worker_position(state: dict, target_entity_id: str | None) -> tuple[float, float] | None:
    if not target_entity_id:
        return None
    ent = state.setdefault("entities", {}).get(target_entity_id)
    if not isinstance(ent, dict):
        return None
    return float(ent.get("x", 0.0) or 0.0), float(ent.get("y", 0.0) or 0.0)


def _is_b11_worker_workplace(pt: tuple[float, float] | None) -> bool:
    """Hard guard: thieves must never target B11 (Willows Market / worker work).

    We treat "at workplace" as being within a small radius of the worker work
    anchor from the shared location registry."""
    if pt is None:
        return False
    try:
        from core import locations as _locations
    except Exception:
        return False
    work_pt = _locations.point("worker", "work")
    if not work_pt:
        return False
    import math

    # Primary guard: broader radius around B11 work anchor so thieves do not
    # chase workers while they are circulating through the work area tiles.
    if math.hypot(float(pt[0]) - float(work_pt[0]), float(pt[1]) - float(work_pt[1])) <= 260.0:
        return True

    # Secondary guard: explicit B11 building bbox from catalog when available.
    try:
        from core.locations import _load_building_catalog

        catalog = _load_building_catalog()
        buildings = catalog.get("buildings", []) if isinstance(catalog, dict) else []
        b11 = next((b for b in buildings if str(b.get("id", "")).upper() == "B11"), None)
        if isinstance(b11, dict):
            bbox = b11.get("bbox_px")
            if isinstance(bbox, dict):
                x = float(pt[0])
                y = float(pt[1])
                min_x = float(bbox.get("min_x", 0.0))
                min_y = float(bbox.get("min_y", 0.0))
                max_x = float(bbox.get("max_x", 0.0))
                max_y = float(bbox.get("max_y", 0.0))
                pad = 36.0
                if (min_x - pad) <= x <= (max_x + pad) and (min_y - pad) <= y <= (max_y + pad):
                    return True
    except Exception:
        pass

    return False


def apply_event_actions(state: dict) -> None:
    """Translate fresh economy events into per-agent action queues.

    Called once per tick, AFTER the nano-economy hooks. Idempotent via
    the `_action_enqueued` flag on each source event."""
    events = state.setdefault("events", [])
    if not events:
        return

    # Snapshot length so any events we happen to append here (none today,
    # but future-proof) don't get re-scanned in the same pass.
    scan_end = len(events)
    for idx in range(scan_end):
        ev = events[idx]
        if not isinstance(ev, dict):
            continue
        if ev.get("_action_enqueued"):
            continue
        et = ev.get("type")

        if et == "spy_sell_info":
            buyer_id = ev.get("buyer_id")
            buyer_type = ev.get("buyer_type")
            buyer = _entity(state, buyer_id)
            if buyer is not None and buyer_type in ("thief", "cop"):
                cap = _THIEF_QUEUE_SOFT_CAP if buyer_type == "thief" else _COP_QUEUE_SOFT_CAP
                if _queue_len(buyer) >= cap:
                    ev["_action_enqueued"] = True
                    continue
                _push(
                    buyer,
                    {"type": "move", "target": "spy_location", "source_event": et},
                    {"type": "wait", "duration": _PAUSE_DURATION},
                )
            ev["_action_enqueued"] = True

        elif et == "steal_agent":
            thief = _entity(state, ev.get("thief_id"))
            if thief is not None:
                if _queue_len(thief) >= _THIEF_QUEUE_SOFT_CAP:
                    ev["_action_enqueued"] = True
                    continue
                # Deterministic branch lock (NO randomness):
                # alternate worker-home raid and worker-direct raid each incident.
                branch = str(thief.get("_next_raid_branch", "worker_home"))
                target_worker = ev.get("target_id") or ev.get("worker_id")
                _thief_home_anchor(thief)
                if branch == "worker_direct":
                    move_target = {
                        "type": "move",
                        "target": "worker_location",
                        "target_entity": target_worker,
                        "source_event": et,
                    }
                    thief["_next_raid_branch"] = "worker_home"
                else:
                    move_target = {
                        "type": "move",
                        "target": "worker_home_inside",
                        "target_entity": target_worker,
                        "source_event": et,
                    }
                    thief["_next_raid_branch"] = "worker_direct"
                _push(
                    thief,
                    move_target,
                    {"type": "wait", "duration": _INTERACTION_HOLD_TICKS},
                    {"type": "move", "target": "bank_customer_spot", "source_event": et},
                    {"type": "wait", "duration": _PAUSE_DURATION},
                    {"type": "move", "target": "thief_home_anchor", "source_event": et},
                )
            ev["_action_enqueued"] = True

        elif et == "cop_recover":
            cop = _entity(state, ev.get("cop_id"))
            if cop is not None:
                if _queue_len(cop) >= _COP_QUEUE_SOFT_CAP:
                    ev["_action_enqueued"] = True
                    continue
                # Deterministic branch lock (NO randomness):
                # choose ONE of {thief live position, thief home anchor} per cycle,
                # then alternate next cycle.
                branch = str(cop.get("_next_hunt_branch", "thief_direct"))
                thief_id = ev.get("thief_id")
                hunt_move: dict[str, Any]
                if branch == "thief_home":
                    hunt_move = {
                        "type": "move",
                        "target": "thief_home_anchor",
                        "target_entity": thief_id,
                        "source_event": et,
                    }
                    cop["_next_hunt_branch"] = "thief_direct"
                else:
                    hunt_move = {
                        "type": "move",
                        "target": "thief_location",
                        "target_entity": thief_id,
                        "source_event": et,
                    }
                    cop["_next_hunt_branch"] = "thief_home"
                _push(
                    cop,
                    hunt_move,
                    {"type": "wait", "duration": _INTERACTION_HOLD_TICKS},
                    {"type": "move", "target": "bank_customer_spot", "source_event": et},
                    {"type": "wait", "duration": _PAUSE_DURATION},
                    {"type": "move", "target": "police_station", "source_event": et},
                )
            ev["_action_enqueued"] = True

        else:
            # Mark everything else seen so we don't waste cycles rescanning.
            # Unknown events are cheap enough that a `_action_enqueued` stamp
            # on them is worth the idempotency guarantee.
            ev["_action_enqueued"] = True


def snapshot_queues(state: dict) -> dict[str, list[dict]]:
    """Return a shallow copy of every entity's action_queue keyed by id.
    Entities without queues are omitted."""
    out: dict[str, list[dict]] = {}
    for entity_id, ent in state.setdefault("entities", {}).items():
        if not isinstance(ent, dict):
            continue
        q = ent.get("action_queue")
        if not q:
            continue
        # shallow-copy so callers can't mutate the real queue
        out[str(entity_id)] = [dict(a) if isinstance(a, dict) else a for a in q]
    return out


# ---------------------------------------------------------------------------
# PASS 2 — Execute the action queue against the existing movement system.
# ---------------------------------------------------------------------------

# Movement arrival tolerance for queue actions, in world pixels.
# Per spec: "IF arrived (distance <= 10): pop action".
_ACTION_ARRIVE_EPS_PX = 16.0

# Fail-safe: if a single action sits at the head of the queue for more than
# this many ticks without completing, pop it so the agent doesn't lock up
# (e.g. the target moved into an unreachable tile). Generous enough that
# normal cross-map walks never trip it.
_ACTION_MAX_TICKS = 90


def _action_arrive_eps(action: dict) -> float:
    target = str((action or {}).get("target") or "").lower()
    if target in {"worker_location", "thief_location"}:
        # Dynamic targets can keep moving; treat near-proximity as "arrived"
        # to prevent long chase-jiggle stalls.
        return 36.0
    return _ACTION_ARRIVE_EPS_PX


def _action_max_ticks(action: dict) -> int:
    target = str((action or {}).get("target") or "").lower()
    if target in {"worker_location", "thief_location"}:
        # Fail faster on moving targets so queue stays responsive.
        return 36
    return _ACTION_MAX_TICKS


def _find_first_by(state: dict, predicate) -> dict | None:
    for ent in state.setdefault("entities", {}).values():
        if isinstance(ent, dict) and predicate(ent):
            return ent
    return None


# PASS 3: the symbolic move targets that MUST resolve to a real POI in the
# Tiled map. `thief_location` is intentionally excluded — a thief is mobile,
# so that target is resolved against the live entity each tick. Every other
# movement anchor lives on the map and is validated at startup.
REQUIRED_POIS: tuple[str, ...] = (
    "spy_location",
    "worker_home_inside",
    "bank_customer_spot",
    "police_station",
)


def validate_required_pois() -> None:
    """Loud startup check: abort if any PASS 3 POI is missing from the map.
    Movement execution depends on these; a silent fallback would make the
    demo drift off real locations."""
    from core.pois import load_pois

    pts = load_pois()
    missing = [name for name in REQUIRED_POIS if name not in pts]
    if missing:
        raise RuntimeError(
            "Missing required POIs in Tiled map "
            "(add them to the 'POIs' object layer, then restart): "
            + ", ".join(missing)
        )


def _thief_position(state: dict, target_entity_id: str | None) -> tuple[float, float] | None:
    """`thief_location` is dynamic by design: it tracks the named thief's
    live pixel position. Returns None if no thief can be found so the
    caller pops the action instead of walking to (0, 0)."""
    entities = state.setdefault("entities", {})
    thief = None
    if target_entity_id:
        t = entities.get(target_entity_id)
        if isinstance(t, dict):
            thief = t
    if thief is None:
        thief = _find_first_by(state, lambda e: e.get("type") == "thief")
    if thief is None:
        return None
    return float(thief.get("x", 0.0) or 0.0), float(thief.get("y", 0.0) or 0.0)


_MISSING_POI_WARNED: set[str] = set()


def _poi_strict(name: str) -> tuple[float, float] | None:
    """Return the POI, or None + one-shot stderr warning if it isn't in the
    map. Fail-loud on first miss; silent on subsequent misses so we don't
    spam the log if a POI gets deleted mid-run."""
    from core.pois import try_poi

    pt = try_poi(name)
    if pt is not None:
        return float(pt[0]), float(pt[1])
    if name not in _MISSING_POI_WARNED:
        _MISSING_POI_WARNED.add(name)
        sys.stderr.write(
            f"[action_queue] required POI missing from Tiled map: {name!r}. "
            f"Action popped. Add it to the 'POIs' object layer.\n"
        )
    return None


def resolve_action_target(action: dict, state: dict) -> tuple[float, float] | None:
    """Translate a symbolic target name into concrete world pixels.

    Returns None if the symbolic name cannot be resolved; callers treat
    None as "pop this action" — there's nothing meaningful to walk toward.

    PASS 3: the static anchors (`spy_location`, `worker_home_inside`,
    `bank_customer_spot`, `police_station`) come from the Tiled map's POIs
    layer ONLY. No fallback to live entity position or role-registry
    anchors — if the POI is missing the action is dropped and a warning
    is emitted. `thief_location` stays dynamic because the thief moves."""
    if not isinstance(action, dict):
        return None
    target = str(action.get("target") or "").lower()
    if target == "spy_location":
        return _poi_strict("spy_location")
    if target == "worker_home_inside":
        # All worker homes share one POI (B08) in the current world. The
        # enqueued `target_entity` stays on the action for downstream
        # analytics (which worker triggered this chase) but does NOT
        # change the movement anchor — PASS 3 locks that to the map POI.
        return _poi_strict("worker_home_inside")
    if target == "bank_customer_spot":
        return _poi_strict("bank_customer_spot")
    if target == "police_station":
        return _poi_strict("police_station")
    if target == "thief_location":
        return _thief_position(state, action.get("target_entity"))
    if target == "worker_location":
        worker_pt = _worker_position(state, action.get("target_entity"))
        # User rule: thief can go anywhere EXCEPT B11 worker workplace.
        # If the worker is currently at/near B11, route the thief to worker home.
        if _is_b11_worker_workplace(worker_pt):
            return _poi_strict("worker_home_inside")
        return worker_pt
    if target == "thief_home_anchor":
        thief_id = action.get("target_entity")
        thief = None
        if thief_id:
            t = state.setdefault("entities", {}).get(thief_id)
            if isinstance(t, dict):
                thief = t
        if thief is None:
            thief = _find_first_by(state, lambda e: e.get("type") == "thief")
        if thief is None:
            return None
        return _thief_home_anchor(thief)
    return None


def _distance(entity: dict, pt: tuple[float, float]) -> float:
    import math
    ex = float(entity.get("x", 0.0) or 0.0)
    ey = float(entity.get("y", 0.0) or 0.0)
    return math.hypot(ex - float(pt[0]), ey - float(pt[1]))


def _describe_action(action: dict | None, entity_type: str) -> str:
    """Turn the head action into a short, readable label for UI / judges.
    Deliberately terse — this string shows up in dashboards and hovers."""
    if not isinstance(action, dict):
        return "idle"
    act_type = str(action.get("type") or "").lower()
    if act_type == "wait":
        return "waiting"
    if act_type != "move":
        return act_type or "idle"
    target = str(action.get("target") or "").lower()
    if target == "spy_location":
        # Both thief and cop visit the spy to buy intel — same verb.
        return "buying_intel"
    if target == "worker_home_inside":
        return "stealing_from_worker" if entity_type == "thief" else "moving_to_worker_home"
    if target == "worker_location":
        return "stealing_from_worker"
    if target == "thief_location":
        return "chasing_thief"
    if target == "thief_home_anchor":
        return "moving_to_thief_home"
    if target == "bank_customer_spot":
        return "depositing_at_bank"
    if target == "police_station":
        return "returning_to_station"
    return f"moving_to_{target}" if target else "moving"


def _inject_micro_pause_if_needed(queue: list) -> None:
    """PASS 4: after a completed move, make sure the very next tick is not
    ANOTHER move. If the enqueue logic already left a wait in place, do
    nothing. Otherwise insert a short breather so agents don't snap from
    one target to the next in a single tick."""
    if not queue:
        return
    nxt = queue[0]
    if isinstance(nxt, dict) and str(nxt.get("type", "")).lower() == "wait":
        return
    queue.insert(
        0,
        {"type": "wait", "duration": _MICRO_PAUSE_TICKS, "source": "pass4_micro_pause"},
    )


def consume_action_queue(entity: dict, state: dict, tick: int) -> bool:
    """PASS 2+4: drive the head-of-queue action for this entity.

    Returns True if an action was in flight this tick (and therefore the
    caller must NOT run its default FSM / roaming logic). Returns False
    if the queue is empty — caller falls through to normal behavior.

    Movement itself is still performed by the existing spatial subsystem
    (`_move_entity` in loop.py). This function ONLY assigns `target_x /
    target_y`, exactly like the default behavior paths do.

    Wait semantics: `duration = N` means "hold in place for N ticks".
    We hold the current tick FIRST, then decrement, so a `duration = 1.0`
    action produces exactly one tick of visible standing still.

    Arrival hold (PASS 4): once the entity is within _ACTION_ARRIVE_EPS_PX
    of the resolved target, we stamp `_action_arrived_tick` and keep the
    sprite parked there for `_ARRIVAL_HOLD_TICKS` before popping — so the
    judge SEES the agent arrive and pause instead of snapping to the next
    destination in the same frame. A micro-pause is injected between
    back-to-back moves."""
    queue = entity.get("action_queue")
    if not queue:
        entity["current_action"] = "idle"
        return False

    entity_type = str(entity.get("type", "") or "").lower()

    # Loop guard: if the head action is a fully resolved no-op (unknown
    # type, unresolvable target), pop it and try the next one. Bounded
    # so we can't busy-spin.
    for _ in range(4):
        if not queue:
            entity["current_action"] = "idle"
            return False
        action = queue[0]
        if not isinstance(action, dict):
            queue.pop(0)
            entity.pop("_action_started_tick", None)
            entity.pop("_action_arrived_tick", None)
            continue

        if "_action_started_tick" not in entity:
            entity["_action_started_tick"] = tick
        started = int(entity.get("_action_started_tick", tick) or tick)
        elapsed = max(0, int(tick) - started)

        act_type = str(action.get("type") or "").lower()

        if act_type == "wait":
            remaining = float(action.get("duration", 0.0) or 0.0)
            if remaining <= 0:
                queue.pop(0)
                entity.pop("_action_started_tick", None)
                continue  # already consumed; try next head on same tick
            # Hold position THIS tick, then decrement. This makes
            # `duration=1.0` worth exactly one visible tick of pause,
            # instead of zero (the pre-PASS-4 off-by-one).
            entity["target_x"] = float(entity.get("x", 0.0) or 0.0)
            entity["target_y"] = float(entity.get("y", 0.0) or 0.0)
            action["duration"] = remaining - 1.0
            entity["current_action"] = _describe_action(action, entity_type)
            return True

        if act_type == "move":
            pt = resolve_action_target(action, state)
            if pt is None:
                queue.pop(0)
                entity.pop("_action_started_tick", None)
                entity.pop("_action_arrived_tick", None)
                continue

            arrive_eps = _action_arrive_eps(action)
            if _distance(entity, pt) <= arrive_eps:
                # Arrived. Park the sprite on the target pixel and hold
                # for a couple of ticks so the arrival is readable.
                entity["target_x"] = float(pt[0])
                entity["target_y"] = float(pt[1])
                arrived_tick = entity.get("_action_arrived_tick")
                if arrived_tick is None:
                    entity["_action_arrived_tick"] = tick
                    arrived_tick = tick
                if (int(tick) - int(arrived_tick)) < _ARRIVAL_HOLD_TICKS:
                    entity["current_action"] = _describe_action(action, entity_type)
                    return True
                # Hold window elapsed — pop and optionally breathe.
                queue.pop(0)
                entity.pop("_action_started_tick", None)
                entity.pop("_action_arrived_tick", None)
                _inject_micro_pause_if_needed(queue)
                continue

            max_ticks = _action_max_ticks(action)
            if elapsed > max_ticks:
                # Fail-safe: something is keeping us from arriving. Pop
                # and move on so the queue keeps flowing.
                queue.pop(0)
                entity.pop("_action_started_tick", None)
                entity.pop("_action_arrived_tick", None)
                continue

            entity["target_x"] = float(pt[0])
            entity["target_y"] = float(pt[1])
            entity["current_action"] = _describe_action(action, entity_type)
            return True

        # Unknown action type — drop it.
        queue.pop(0)
        entity.pop("_action_started_tick", None)
        entity.pop("_action_arrived_tick", None)

    return bool(queue)
