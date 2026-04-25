"""Global route sync, map metadata, building moves, and manual movement commands."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from api.routes.common import (
    ALLOWED_ENTITY_TYPES,
    BANK_SECTORS,
    BUILDING_CATALOG_PATH,
    COP_PATROL_SECTORS,
    HOME_SECTORS,
    MAP_ROAM_SECTORS,
    TILE_SIZE,
    WORK_SECTORS,
    _MAP_LAYOUT_CACHE,
    _SECTOR_CENTERS,
    _building_anchor_point,
    _load_building_catalog,
    _load_map_layout,
    _nearest_building_id,
    _spot_target,
)
from core.state import state

routes_map_router = APIRouter(tags=["demo"])


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


@routes_map_router.get("/route/status")
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


@routes_map_router.post("/route/start")
def route_start_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route["enabled"] = True
    return {"status": "started", "global_route": route}


@routes_map_router.post("/route/stop")
def route_stop_endpoint():
    movement = state.setdefault("movement", {})
    route = movement.setdefault("global_route", {})
    route["enabled"] = False
    return {"status": "stopped", "global_route": route}


@routes_map_router.post("/route/set")
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


@routes_map_router.get("/map/areas")
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


@routes_map_router.get("/map/buildings")
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


@routes_map_router.get("/map/buildings/spots")
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


@routes_map_router.get("/map/hubs")
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


@routes_map_router.post("/map/hubs")
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

    movement.setdefault("global_route", {})["enabled"] = False
    cleared = 0
    for entity in state.setdefault("entities", {}).values():
        if isinstance(entity.get("manual_target"), dict):
            entity.pop("manual_target", None)
            cleared += 1
    return {"status": "ok", "role_hubs": hubs, "cleared_manual_targets": cleared}


@routes_map_router.post("/move/buildings")
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


@routes_map_router.post("/command/go")
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


@routes_map_router.post("/command/clear")
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
