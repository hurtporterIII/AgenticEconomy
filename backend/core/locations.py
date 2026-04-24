"""
Single authoritative registry of role -> place -> building -> world point.

WHY THIS EXISTS
    Before this module, "home" for a worker was defined in five different
    files with two different coordinate values:

        - backend/core/loop.py        WORKER_HOME_ZONE   (B08 center)
        - backend/core/loop.py        _home_zone()       (B08 inside)
        - backend/core/loop.py        _set_behavior_target (B08 entry)
        - backend/agents/worker.py    HOME_ZONE           (hardcoded to B08 entry)
        - backend/api/endpoints.py    ROLE_HUB_DEFAULTS   (just the B-ID)

    Whichever function ran first decided where "home" was. That's what
    caused sprites to look like they had a mind of their own: the commute
    target, the arrival detector, and the spawn point all read different
    coordinates for the same building.

    From now on every location answer comes from here. No hardcoded pixel
    coordinates anywhere else in the backend. No fallback defaults that
    quietly disagree with the catalog. One registry, one command.

HOW TO CHANGE A PLACE
    - To move a role's home/work/bank to a different building: edit ROLE_PLACES
      below. Nothing else needs to change.
    - To change the pixel coordinates of an existing building: edit the map,
      rerun `python backend/utils/build_building_catalog.py`.
    - To change the arrival radius for a place: edit ARRIVAL_RADIUS below.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# THE REGISTRY (edit this, nothing else)
# ---------------------------------------------------------------------------

# role -> place_name -> building_id
# place_name is the ONLY string that game logic should use ("home", "work",
# "bank"). B-IDs are an implementation detail.
ROLE_PLACES: dict[str, dict[str, str]] = {
    "worker": {"home": "B08", "work": "B11", "bank": "B12"},
    "cop":    {"home": "B09"},
    "thief":  {"home": "B07"},
    "banker": {"home": "B12"},
    "spy":    {"home": "B06"},
    "bank":   {"home": "B12"},
}

# Which anchor of the building we mean by default for each place. An
# anchor is one of "entry" (the door), "inside" (a walkable interior tile),
# or "center" (bbox centroid, sometimes not walkable).
#
# Rules of thumb:
#   - "home" / "work" / "bank" as navigation targets ⇒ "entry" (door).
#   - "home" as a spawn point ⇒ call point(..., anchor="inside") explicitly.
DEFAULT_ANCHOR: dict[str, str] = {
    # "home" means INSIDE the house, not at the door. `entry` is the doorway
    # tile, which is on the outside edge of the building — agents targeting
    # `entry` arrive at the door and stop there. Using `inside` makes A*
    # route them through the door into an interior walkable tile.
    "home": "inside",
    "work": "entry",
    "bank": "entry",
}

# Arrival radius (pixels) for each place. An entity "has arrived at <place>"
# when within this distance of the place's point.
#
# "home" is intentionally tight (40 px) because the home anchor (inside_px)
# sits deep in the building footprint, and a loose radius causes agents to
# register "arrived" from the doorway area — then the shift flips and they
# immediately walk back out, looking like "they won't go inside." 40 px
# forces them to actually step into the room.
ARRIVAL_RADIUS: dict[str, float] = {
    # Deterministic FSM: every worker target is an exact pixel, hit within
    # 10 px. Same radius for all three legs so there is no special casing.
    # agents/worker.py hardcodes the same 10.0 — keep them aligned.
    "home": 10.0,
    "work": 10.0,
    "bank": 10.0,
}


# ---------------------------------------------------------------------------
# POINT OVERRIDES
# ---------------------------------------------------------------------------
# `building_catalog.json` computes `inside_px` by flood-filling walkable tiles
# from the door. For B08 that flood includes tiles across an internal wall
# the A* layer *does* respect, so the catalog's inside_px=(1296,1104) sits in
# a sub-room the door cannot reach. We override here with a tile that is
# verified reachable from the door on the backend navmesh (tile (20, 34),
# 8 tiles deep inside the building along the main corridor). If you edit
# the map, re-verify this coordinate; the BFS-from-door diagnostic is in
# backend/core/navmesh.py.
POINT_OVERRIDE: dict[tuple[str, str, str], tuple[float, float]] = {
    ("worker", "home", "inside"): (656.0, 1104.0),
}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def building_id(role: str, place: str) -> str:
    """Return the B-ID registered for this role's place. Raises KeyError on
    bad input so misuse surfaces loudly instead of silently defaulting."""
    r = str(role).lower()
    p = str(place).lower()
    try:
        return ROLE_PLACES[r][p]
    except KeyError as e:
        raise KeyError(
            f"no building registered for role={r!r} place={p!r}. "
            f"Edit ROLE_PLACES in backend/core/locations.py."
        ) from e


def point(role: str, place: str, anchor: Optional[str] = None) -> tuple[float, float]:
    """Return (x, y) world pixels for <role>'s <place>.

    <anchor> is "entry" | "inside" | "center". If omitted, uses the default
    anchor for the place (usually "entry" for home/work/bank so agents walk
    to the door).
    """
    # Local import breaks the loop.py -> locations.py -> loop.py cycle.
    from core.loop import _get_building_point

    r = str(role).lower()
    p = str(place).lower()
    a = (anchor or DEFAULT_ANCHOR.get(p, "entry")).lower()
    override = POINT_OVERRIDE.get((r, p, a))
    if override is not None:
        return (float(override[0]), float(override[1]))
    bid = building_id(role, place)
    return _get_building_point(bid, a)


def radius(place: str) -> float:
    """Arrival radius in pixels for a place name."""
    return float(ARRIVAL_RADIUS.get(str(place).lower(), 150.0))


def flat_hub_defaults() -> dict[str, str]:
    """Legacy view: {"worker_home": "B08", "worker_work": "B11", ...}.

    Emitted from ROLE_PLACES so there's still ONE place to edit. Call sites
    that haven't been migrated to point(role, place) yet can read this dict.
    """
    out: dict[str, str] = {}
    for role, places in ROLE_PLACES.items():
        for place, bid in places.items():
            out[f"{role}_{place}"] = bid
    return out


def describe() -> dict:
    """Resolve every registered (role, place) to its B-ID and coordinates.
    Useful for startup diagnostics or a `/api/locations` endpoint. Any
    mismatch between files shows up as a contradiction here."""
    from core.loop import _get_building_point

    out: dict[str, dict[str, dict]] = {}
    for role, places in ROLE_PLACES.items():
        out[role] = {}
        for place, bid in places.items():
            anchor = DEFAULT_ANCHOR.get(place, "entry")
            x, y = _get_building_point(bid, anchor)
            out[role][place] = {
                "building_id": bid,
                "anchor": anchor,
                "x": float(x),
                "y": float(y),
                "arrival_radius": float(ARRIVAL_RADIUS.get(place, 150.0)),
            }
    return out
