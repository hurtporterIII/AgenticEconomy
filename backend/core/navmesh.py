"""
Server-side walkable-tile navigation (single authority for sprite movement).

The Phaser client previously ran its own A* from the sprite's position toward
`dest_x/dest_y`, independently of the backend's lerped `x/y`. That produced two
competing movement authorities that diverged over time (the "err 800" problem
and "wandering around in the bank"). This module makes the backend the sole
authority: it reads the same Collisions layer the client uses, builds a
walkable grid, runs A* from the entity's current tile to the target tile, and
exposes helpers so `_move_entity` can step along the returned path one tile at
a time at a fixed speed.

All pixel<->tile math matches the Phaser client (32 px/tile, tile centers at
tx*32+16, ty*32+16).
"""

from __future__ import annotations

import heapq
import json
import math
import os
from pathlib import Path
from typing import Iterable, Optional

TILE_SIZE = 32


def _default_map_path() -> Path:
    # backend/core/navmesh.py -> workspace root -> generative_agents/.../the_ville_jan7.json
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


_grid: list[list[bool]] | None = None  # _grid[y][x] == True means blocked
_grid_w: int = 0
_grid_h: int = 0


def _load_grid(force: bool = False) -> tuple[list[list[bool]], int, int]:
    """Load the Collisions layer once and cache it as a 2D blocked-grid."""
    global _grid, _grid_w, _grid_h
    if _grid is not None and not force:
        return _grid, _grid_w, _grid_h

    map_path = Path(os.environ.get("NAV_MAP_PATH", "")) or _default_map_path()
    if not map_path.is_file():
        map_path = _default_map_path()
    with map_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    width = int(data.get("width", 140))
    height = int(data.get("height", 100))
    coll = None
    for layer in data.get("layers", []):
        if str(layer.get("name", "")).strip().lower() == "collisions":
            coll = layer
            break
    if coll is None:
        raise RuntimeError("Tiled map missing 'Collisions' layer")
    flat = list(coll.get("data", []) or [])
    if len(flat) != width * height:
        raise RuntimeError(
            f"Collisions layer size mismatch: {len(flat)} vs {width}x{height}"
        )

    grid = [[False] * width for _ in range(height)]
    for idx, gid in enumerate(flat):
        if gid:
            y = idx // width
            x = idx % width
            grid[y][x] = True

    # --- Building wall overlay --------------------------------------------
    # The stock Tiled "Collisions" layer does NOT mark individual building
    # walls as blocked, so A* cheerfully routed workers straight through the
    # east wall of B08 to the interior anchor ("phasing through walls"). Here
    # we read the building catalog and mark the perimeter tiles of every
    # building's bbox as blocked, EXCEPT the one tile at `entry_tile` (the
    # door), forcing A* to route through the door to reach any interior
    # target. Interior tiles are left untouched (still walkable).
    _apply_building_wall_overlay(grid, width, height)

    _grid = grid
    _grid_w = width
    _grid_h = height
    return _grid, _grid_w, _grid_h


def _apply_building_wall_overlay(
    grid: list[list[bool]], width: int, height: int
) -> None:
    # Scope: only building IDs in WALL_OVERLAY_IDS get their perimeter
    # walls enforced. Every other building keeps whatever routing the
    # original Tiled "Collisions" layer provided, because several
    # buildings (notably B11/B12) were authored with their door on a row
    # where the tiles immediately outside are also blocked — the original
    # map depended on agents "phasing through walls" to enter/exit. We
    # intentionally do NOT block those so the existing work/bank flow
    # stays unchanged. B08 is enforced because that is the worker home
    # where the user wants sprites to visibly walk through the door.
    WALL_OVERLAY_IDS = {"B08"}

    catalog_path = Path(__file__).resolve().parents[1] / "store" / "building_catalog.json"
    if not catalog_path.is_file():
        return
    try:
        with catalog_path.open("r", encoding="utf-8") as fp:
            catalog = json.load(fp)
    except Exception:
        return
    buildings = catalog.get("buildings") if isinstance(catalog, dict) else None
    if not isinstance(buildings, list):
        return

    for b in buildings:
        if not isinstance(b, dict):
            continue
        if str(b.get("id", "")).upper() not in WALL_OVERLAY_IDS:
            continue
        bbox = b.get("bbox_tile")
        if not isinstance(bbox, dict):
            continue
        try:
            min_x = int(bbox.get("min_x"))
            min_y = int(bbox.get("min_y"))
            max_x = int(bbox.get("max_x"))
            max_y = int(bbox.get("max_y"))
        except (TypeError, ValueError):
            continue

        entry_tile = b.get("entry_tile") or {}
        try:
            ex = int(entry_tile.get("x"))
            ey = int(entry_tile.get("y"))
        except (TypeError, ValueError):
            ex, ey = -1, -1

        # Entry tiles typically sit one tile OUTSIDE the bbox (the doormat
        # in front of the building). The tile on the wall edge that lines up
        # with the door must stay open, otherwise the door leads to a
        # blocked wall. Compute that adjacent wall tile:
        door_passages: set[tuple[int, int]] = {(ex, ey)}
        if ex >= 0 and ey >= 0:
            if ey == max_y + 1:  # door is one south of the building
                door_passages.add((ex, max_y))
            elif ey == min_y - 1:  # one north
                door_passages.add((ex, min_y))
            elif ex == max_x + 1:  # one east
                door_passages.add((max_x, ey))
            elif ex == min_x - 1:  # one west
                door_passages.add((min_x, ey))

        def _block(tx: int, ty: int) -> None:
            if 0 <= tx < width and 0 <= ty < height:
                if (tx, ty) in door_passages:
                    return
                grid[ty][tx] = True

        for tx in range(min_x, max_x + 1):
            _block(tx, min_y)
            _block(tx, max_y)
        for ty in range(min_y, max_y + 1):
            _block(min_x, ty)
            _block(max_x, ty)


def world_to_tile(x: float, y: float) -> tuple[int, int]:
    return int(x // TILE_SIZE), int(y // TILE_SIZE)


def tile_to_world(tx: int, ty: int) -> tuple[float, float]:
    return float(tx * TILE_SIZE + TILE_SIZE / 2), float(ty * TILE_SIZE + TILE_SIZE / 2)


def is_walkable(tx: int, ty: int) -> bool:
    grid, w, h = _load_grid()
    if tx < 0 or ty < 0 or tx >= w or ty >= h:
        return False
    return not grid[ty][tx]


def nearest_walkable(tx: int, ty: int, max_radius: int = 12) -> tuple[int, int]:
    """Snap a tile to the closest walkable neighbor. Useful when a building's
    catalog anchor happens to sit on a blocked tile."""
    if is_walkable(tx, ty):
        return tx, ty
    for r in range(1, max_radius + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) != r and abs(dy) != r:
                    continue
                nx, ny = tx + dx, ty + dy
                if is_walkable(nx, ny):
                    return nx, ny
    return tx, ty


def _heuristic(ax: int, ay: int, bx: int, by: int) -> float:
    dx = abs(ax - bx)
    dy = abs(ay - by)
    # octile distance (we allow 8-way moves)
    return (dx + dy) + (math.sqrt(2) - 2) * min(dx, dy)


_NEIGHBOR_OFFSETS = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)),
    (-1, -1, math.sqrt(2)),
)


def find_path_tiles(
    sx: int,
    sy: int,
    gx: int,
    gy: int,
    max_nodes: int = 20000,
) -> list[tuple[int, int]]:
    """A* on the walkable grid. Returns a list of tiles from start to goal
    inclusive, or [] if unreachable. Allows diagonal moves but not corner
    cutting through walls."""
    grid, w, h = _load_grid()
    if sx == gx and sy == gy:
        return [(sx, sy)] if is_walkable(sx, sy) else []
    if not is_walkable(sx, sy):
        sx, sy = nearest_walkable(sx, sy)
    if not is_walkable(gx, gy):
        gx, gy = nearest_walkable(gx, gy)

    open_heap: list[tuple[float, int, int, int]] = []
    counter = 0
    heapq.heappush(open_heap, (0.0, counter, sx, sy))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
    visited = 0

    while open_heap:
        _, _, cx, cy = heapq.heappop(open_heap)
        if cx == gx and cy == gy:
            # reconstruct
            path: list[tuple[int, int]] = [(cx, cy)]
            cur = (cx, cy)
            while cur in came_from:
                cur = came_from[cur]
                path.append(cur)
            path.reverse()
            return path
        visited += 1
        if visited > max_nodes:
            return []
        cg = g_score[(cx, cy)]
        for dx, dy, cost in _NEIGHBOR_OFFSETS:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            if grid[ny][nx]:  # blocked
                continue
            # prevent diagonal corner-cutting through walls
            if dx != 0 and dy != 0:
                if grid[cy][nx] or grid[ny][cx]:
                    continue
            tentative = cg + cost
            key = (nx, ny)
            if tentative < g_score.get(key, float("inf")):
                g_score[key] = tentative
                came_from[key] = (cx, cy)
                counter += 1
                f = tentative + _heuristic(nx, ny, gx, gy)
                heapq.heappush(open_heap, (f, counter, nx, ny))
    return []


def find_path_world(
    x: float, y: float, target_x: float, target_y: float
) -> list[tuple[float, float]]:
    """A* from one world pixel to another. Returns a list of waypoints (world
    pixel centers of each tile on the path), already pruned of the starting
    tile."""
    sx, sy = world_to_tile(x, y)
    gx, gy = world_to_tile(target_x, target_y)
    tiles = find_path_tiles(sx, sy, gx, gy)
    if not tiles:
        return []
    waypoints = [tile_to_world(tx, ty) for tx, ty in tiles]
    # drop the starting tile's center so the first waypoint is an actual move
    if waypoints and _distance(waypoints[0], (x, y)) < TILE_SIZE * 0.5:
        waypoints = waypoints[1:]
    # the final waypoint is the destination tile center; replace with the
    # exact target pixel so the entity lands on the requested spot.
    if waypoints:
        waypoints[-1] = (float(target_x), float(target_y))
    else:
        waypoints = [(float(target_x), float(target_y))]
    return waypoints


def _distance(a: Iterable[float], b: Iterable[float]) -> float:
    ax, ay = a
    bx, by = b
    return math.hypot(ax - bx, ay - by)


def debug_dimensions() -> tuple[int, int, int]:
    _, w, h = _load_grid()
    return w, h, TILE_SIZE
