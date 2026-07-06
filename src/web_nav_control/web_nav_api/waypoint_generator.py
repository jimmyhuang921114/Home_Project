from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Waypoint

Point = Tuple[float, float]


@dataclass
class MapInfo:
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    data: List[int]


def point_inside_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def world_to_cell(x: float, y: float, map_info: MapInfo) -> Tuple[int, int]:
    mx = int((x - map_info.origin_x) / map_info.resolution)
    my = int((y - map_info.origin_y) / map_info.resolution)
    return mx, my


def is_cell_in_bounds(mx: int, my: int, map_info: MapInfo) -> bool:
    return 0 <= mx < map_info.width and 0 <= my < map_info.height


def cell_value(mx: int, my: int, map_info: MapInfo) -> int:
    if not is_cell_in_bounds(mx, my, map_info):
        return 100
    return map_info.data[my * map_info.width + mx]


def is_free_space(x: float, y: float, map_info: Optional[MapInfo], margin: float) -> bool:
    if map_info is None:
        return True

    mx, my = world_to_cell(x, y, map_info)
    if not is_cell_in_bounds(mx, my, map_info):
        return False

    radius_cells = max(0, int(margin / map_info.resolution))

    for dy in range(-radius_cells, radius_cells + 1):
        for dx in range(-radius_cells, radius_cells + 1):
            nx, ny = mx + dx, my + dy
            v = cell_value(nx, ny, map_info)
            # ROS OccupancyGrid: -1 unknown, 0 free, 100 occupied.
            # 導航點不放 unknown / occupied。
            if v < 0 or v >= 50:
                return False
    return True


def generate_waypoints_from_polygon(
    polygon_raw: Sequence[Sequence[float]],
    map_payload: Optional[Dict] = None,
    spacing: float = 0.75,
    margin: float = 0.60,
    snake_order: bool = True,
) -> List[Waypoint]:
    polygon: List[Point] = [(float(p[0]), float(p[1])) for p in polygon_raw]
    if len(polygon) < 3:
        return []

    map_info: Optional[MapInfo] = None
    if map_payload and map_payload.get('available'):
        info = map_payload['info']
        map_info = MapInfo(
            width=int(info['width']),
            height=int(info['height']),
            resolution=float(info['resolution']),
            origin_x=float(info['origin']['x']),
            origin_y=float(info['origin']['y']),
            data=list(map_payload['data']),
        )

    min_x = min(p[0] for p in polygon)
    max_x = max(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_y = max(p[1] for p in polygon)

    rows: List[List[Point]] = []
    y = min_y
    while y <= max_y + 1e-9:
        row: List[Point] = []
        x = min_x
        while x <= max_x + 1e-9:
            if point_inside_polygon((x, y), polygon):
                if is_free_space(x, y, map_info, margin):
                    row.append((x, y))
            x += spacing
        if row:
            rows.append(row)
        y += spacing

    ordered: List[Point] = []
    for row_idx, row in enumerate(rows):
        if snake_order and row_idx % 2 == 1:
            row = list(reversed(row))
        ordered.extend(row)

    return [
        Waypoint(
            id=f'wp_{i:03d}',
            x=round(x, 3),
            y=round(y, 3),
            yaw=0.0,
            use_yaw=False,
        )
        for i, (x, y) in enumerate(ordered)
    ]
