"""
Minimal POI loader.

Reads the object layer named "POIs" from the Tiled map and exposes a single
dict: POI_POINTS[name] = (x, y). Nothing else.

If the map does not have a "POIs" layer yet (e.g. you haven't added it in
Tiled), POI_POINTS will be empty. No crashes, no fallbacks, no overrides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


POI_POINTS: dict[str, tuple[float, float]] = {}


def _default_map_path() -> Path:
    here = Path(__file__).resolve()
    root = here.parents[2]
    return (
        root
        / "generative_agents"
        / "environment"
        / "frontend_server"
        / "static_dirs"
        / "assets"
        / "the_ville"
        / "visuals"
        / "the_ville_jan7.json"
    )


def load_pois(force: bool = False) -> dict[str, tuple[float, float]]:
    """Populate POI_POINTS from the map's 'POIs' object layer.

    Returns the dict. Idempotent unless force=True.
    """
    global POI_POINTS
    if POI_POINTS and not force:
        return POI_POINTS

    map_path = Path(os.environ.get("NAV_MAP_PATH", "")) or _default_map_path()
    if not map_path.is_file():
        map_path = _default_map_path()
    if not map_path.is_file():
        POI_POINTS = {}
        return POI_POINTS

    try:
        with map_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:
        POI_POINTS = {}
        return POI_POINTS

    points: dict[str, tuple[float, float]] = {}
    for layer in data.get("layers", []) or []:
        if str(layer.get("name", "")).strip() != "POIs":
            continue
        for obj in layer.get("objects", []) or []:
            name = str(obj.get("name", "")).strip()
            if not name:
                continue
            try:
                x = float(obj.get("x"))
                y = float(obj.get("y"))
            except (TypeError, ValueError):
                continue
            points[name] = (x, y)
        break

    POI_POINTS = points
    return POI_POINTS


load_pois()


def goto_poi(name: str) -> tuple[float, float]:
    """Return (x, y) world-pixel coordinates of the POI named `name`.

    Raises KeyError if the POI is not in the map's POIs layer — on purpose.
    A missing POI should fail loudly, not silently fall back to a wrong spot.
    """
    x, y = POI_POINTS[name]
    return x, y


def try_poi(name: str) -> tuple[float, float] | None:
    """Soft lookup: return (x, y) if the POI exists, else None.

    Use this in call sites that want a graceful fallback (e.g. map author
    hasn't placed the POI yet) instead of a KeyError. goto_poi() is still
    the right choice for POIs we treat as required.
    """
    pt = POI_POINTS.get(name)
    if pt is None:
        return None
    return (float(pt[0]), float(pt[1]))
