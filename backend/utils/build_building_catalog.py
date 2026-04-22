from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAP_SUMMARY_PATH = ROOT / "backend" / "store" / "map_summary.json"
MAP_JSON_PATH = (
    ROOT
    / "generative_agents"
    / "environment"
    / "frontend_server"
    / "static_dirs"
    / "assets"
    / "the_ville"
    / "visuals"
    / "the_ville_jan7.json"
)
CATALOG_PATH = ROOT / "backend" / "store" / "building_catalog.json"
DOC_PATH = ROOT / "docs" / "building_catalog.md"


def _layer_map(map_json: dict) -> dict[str, dict]:
    out = {}
    for layer in map_json.get("layers", []):
        name = str(layer.get("name", "")).strip().lower()
        out[name] = layer
    return out


def _get_layer_data(layer_lookup: dict[str, dict], name: str, width: int, height: int) -> list[int]:
    layer = layer_lookup.get(name.strip().lower())
    if not layer:
        return [0] * (width * height)
    data = layer.get("data", [])
    if len(data) != width * height:
        return [0] * (width * height)
    return data


def _to_idx(x: int, y: int, width: int) -> int:
    return y * width + x


def _in_bounds(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def _door_tile(
    x: int,
    y: int,
    width: int,
    height: int,
    wall_data: list[int],
    interior_data: list[int],
    exterior_data: list[int],
) -> bool:
    if wall_data[_to_idx(x, y, width)] <= 0:
        return False
    has_interior = False
    has_exterior = False
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if not _in_bounds(nx, ny, width, height):
            continue
        nidx = _to_idx(nx, ny, width)
        if interior_data[nidx] > 0:
            has_interior = True
        if exterior_data[nidx] > 0:
            has_exterior = True
    return has_interior and has_exterior


def _build_walkability_grid(
    width: int,
    height: int,
    collision_data: list[int],
    wall_data: list[int],
    interior_data: list[int],
    exterior_data: list[int],
) -> list[bool]:
    walkable = [True] * (width * height)
    for y in range(height):
        for x in range(width):
            idx = _to_idx(x, y, width)
            blocked = False
            if collision_data[idx] > 0:
                blocked = True
            elif wall_data[idx] > 0 and not _door_tile(x, y, width, height, wall_data, interior_data, exterior_data):
                blocked = True
            walkable[idx] = not blocked
    return walkable


def _nearest_walkable(start_x: int, start_y: int, width: int, height: int, walkable: list[bool]) -> tuple[int, int]:
    if _in_bounds(start_x, start_y, width, height) and walkable[_to_idx(start_x, start_y, width)]:
        return start_x, start_y
    q = deque([(start_x, start_y)])
    seen = {(start_x, start_y)}
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not _in_bounds(nx, ny, width, height):
                continue
            if (nx, ny) in seen:
                continue
            idx = _to_idx(nx, ny, width)
            if walkable[idx]:
                return nx, ny
            seen.add((nx, ny))
            q.append((nx, ny))
    return max(0, min(width - 1, start_x)), max(0, min(height - 1, start_y))


def _bfs_distances(src: tuple[int, int], width: int, height: int, walkable: list[bool]) -> list[int]:
    dist = [-1] * (width * height)
    sx, sy = src
    sidx = _to_idx(sx, sy, width)
    if not walkable[sidx]:
        return dist
    q = deque([sidx])
    dist[sidx] = 0
    while q:
        idx = q.popleft()
        x = idx % width
        y = idx // width
        base = dist[idx]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not _in_bounds(nx, ny, width, height):
                continue
            nidx = _to_idx(nx, ny, width)
            if dist[nidx] != -1 or not walkable[nidx]:
                continue
            dist[nidx] = base + 1
            q.append(nidx)
    return dist


def _scanline_buildings(sectors: dict[str, dict]) -> list[tuple[str, dict]]:
    return sorted(
        sectors.items(),
        key=lambda kv: (float(kv[1].get("cy", 0.0)), float(kv[1].get("cx", 0.0))),
    )


def build_catalog() -> dict:
    summary = json.loads(MAP_SUMMARY_PATH.read_text(encoding="utf-8"))
    map_json = json.loads(MAP_JSON_PATH.read_text(encoding="utf-8"))

    meta = summary.get("meta", {})
    width = int(meta.get("w", map_json.get("width", 140)))
    height = int(meta.get("h", map_json.get("height", 100)))
    tile = int(meta.get("tile", 32))
    sectors = summary.get("sector_centers", {})

    layers = _layer_map(map_json)
    collision_data = _get_layer_data(layers, "Collisions", width, height)
    wall_data = _get_layer_data(layers, "Wall", width, height)
    interior_data = _get_layer_data(layers, "Interior Ground", width, height)
    exterior_data = _get_layer_data(layers, "Exterior Ground", width, height)
    walkable = _build_walkability_grid(width, height, collision_data, wall_data, interior_data, exterior_data)

    ordered = _scanline_buildings(sectors)
    buildings = []
    entry_points: dict[str, tuple[int, int]] = {}
    center_points: dict[str, tuple[float, float]] = {}

    for i, (name, info) in enumerate(ordered, start=1):
        b_id = f"B{i:02d}"
        bbox = info.get("bbox", [0, 0, 0, 0])
        min_x, min_y, max_x, max_y = [int(v) for v in bbox]
        cx = float(info.get("cx", (min_x + max_x) / 2))
        cy = float(info.get("cy", (min_y + max_y) / 2))
        w_tiles = max(0, max_x - min_x + 1)
        h_tiles = max(0, max_y - min_y + 1)
        area_tiles = w_tiles * h_tiles

        center_points[b_id] = (cx, cy)

        entry_x = int(round(cx))
        entry_y = max_y + 1
        entry_x = max(0, min(width - 1, entry_x))
        entry_y = max(0, min(height - 1, entry_y))
        entry_x, entry_y = _nearest_walkable(entry_x, entry_y, width, height, walkable)
        entry_points[b_id] = (entry_x, entry_y)

        # Find a reliable interior anchor tile (walkable + interior ground) inside bbox.
        # This is used for deterministic "go inside building" commands.
        inside_candidates: list[tuple[int, int, float]] = []
        for ty in range(min_y, max_y + 1):
            for tx in range(min_x, max_x + 1):
                if not _in_bounds(tx, ty, width, height):
                    continue
                idx = _to_idx(tx, ty, width)
                if not walkable[idx]:
                    continue
                if interior_data[idx] <= 0:
                    continue
                dist_center = math.hypot(float(tx) - cx, float(ty) - cy)
                inside_candidates.append((tx, ty, dist_center))

        inside_x: int
        inside_y: int
        inside_source = "inside_walkable"
        if inside_candidates:
            # Prefer tiles close to center while still close to entry route.
            dist_from_entry = _bfs_distances((entry_x, entry_y), width, height, walkable)
            best = None
            best_score = None
            for tx, ty, dcenter in inside_candidates:
                path_d = dist_from_entry[_to_idx(tx, ty, width)]
                if path_d < 0:
                    continue
                score = (path_d * 1.0) + (dcenter * 0.55)
                if best_score is None or score < best_score:
                    best = (tx, ty)
                    best_score = score
            if best is None:
                # Interior candidates exist but are not path-connected from entry.
                inside_source = "inside_fallback_nearest_center"
                inside_x, inside_y = _nearest_walkable(int(round(cx)), int(round(cy)), width, height, walkable)
            else:
                inside_x, inside_y = best
        else:
            inside_source = "inside_fallback_nearest_center"
            inside_x, inside_y = _nearest_walkable(int(round(cx)), int(round(cy)), width, height, walkable)

        buildings.append(
            {
                "id": b_id,
                "name": name,
                "center_tile": {"x": round(cx, 2), "y": round(cy, 2)},
                "center_px": {"x": round(cx * tile, 2), "y": round(cy * tile, 2)},
                "entry_tile": {"x": entry_x, "y": entry_y},
                "entry_px": {"x": entry_x * tile + tile // 2, "y": entry_y * tile + tile // 2},
                "inside_tile": {"x": inside_x, "y": inside_y},
                "inside_px": {"x": inside_x * tile + tile // 2, "y": inside_y * tile + tile // 2},
                "inside_source": inside_source,
                "bbox_tile": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
                "bbox_px": {
                    "min_x": min_x * tile,
                    "min_y": min_y * tile,
                    "max_x": (max_x + 1) * tile,
                    "max_y": (max_y + 1) * tile,
                },
                "size_tiles": {"w": w_tiles, "h": h_tiles},
                "size_px": {"w": w_tiles * tile, "h": h_tiles * tile},
                "area_tiles": area_tiles,
                "area_px2": area_tiles * (tile * tile),
                "sector_tile_count": int(info.get("count", 0)),
            }
        )

    pairwise: dict[str, dict[str, dict]] = {}
    building_ids = [b["id"] for b in buildings]

    for src_id in building_ids:
        src_entry = entry_points[src_id]
        dist_grid = _bfs_distances(src_entry, width, height, walkable)
        src_cx, src_cy = center_points[src_id]
        pairwise[src_id] = {}
        for dst_id in building_ids:
            dst_entry = entry_points[dst_id]
            dst_cx, dst_cy = center_points[dst_id]
            euclid = math.hypot(dst_cx - src_cx, dst_cy - src_cy)
            manhattan = abs(dst_cx - src_cx) + abs(dst_cy - src_cy)
            path = dist_grid[_to_idx(dst_entry[0], dst_entry[1], width)]
            pairwise[src_id][dst_id] = {
                "center_euclidean_tiles": round(euclid, 2),
                "center_manhattan_tiles": round(manhattan, 2),
                "entry_path_steps": int(path if path >= 0 else round(manhattan)),
            }

    return {
        "map": {"width_tiles": width, "height_tiles": height, "tile_px": tile},
        "building_count": len(buildings),
        "buildings": buildings,
        "pairwise_steps": pairwise,
    }


def write_docs(catalog: dict) -> None:
    lines = []
    lines.append("# Building Catalog")
    lines.append("")
    lines.append(
        f"Map size: {catalog['map']['width_tiles']}x{catalog['map']['height_tiles']} tiles "
        f"({catalog['map']['tile_px']} px per tile)"
    )
    lines.append("")
    lines.append("## Buildings")
    for b in catalog["buildings"]:
        lines.append(
            f"- {b['id']} | {b['name']} | center(tile)=({b['center_tile']['x']}, {b['center_tile']['y']}) "
            f"| entry(tile)=({b['entry_tile']['x']}, {b['entry_tile']['y']}) "
            f"| inside(tile)=({b['inside_tile']['x']}, {b['inside_tile']['y']}) "
            f"| size={b['size_tiles']['w']}x{b['size_tiles']['h']} tiles"
        )
    lines.append("")
    lines.append("## Step Distance Notes")
    lines.append("- `entry_path_steps` is shortest path steps between building entry points using walkable tiles.")
    lines.append("- `center_euclidean_tiles` and `center_manhattan_tiles` are geometric center distances.")
    lines.append("")
    lines.append("Pairwise data is stored in `backend/store/building_catalog.json` under `pairwise_steps`.")
    lines.append("")
    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    catalog = build_catalog()
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    write_docs(catalog)
    print(f"Wrote catalog: {CATALOG_PATH}")
    print(f"Wrote docs:    {DOC_PATH}")


if __name__ == "__main__":
    main()
