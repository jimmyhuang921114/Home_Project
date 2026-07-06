from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .models import Waypoint


RUNTIME_WAYPOINT_DIR = Path('/home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints')
RUNTIME_WAYPOINT_YAML = RUNTIME_WAYPOINT_DIR / 'nav2_waypoints.yaml'

DEFAULT_WAYPOINT_PATHS = [
    '/home/jimmy/work_ws/home_project_ws/src/Semanti_Map/config/nav2_waypoints_margin_060.yaml',
    '/home/jimmy/work_ws/home_project_ws/src/Home_Project/config/nav2_waypoints_margin_060.yaml',
    '/home/jimmy/work_ws/home_project_ws/config/nav2_waypoints.yaml',
    '/home/jimmy/work_ws/home_project_ws/src/web_nav_control/config/nav2_waypoints.yaml',
]


class IndentedDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def waypoint_search_paths() -> List[str]:
    paths = [str(RUNTIME_WAYPOINT_YAML)]
    env_path = os.environ.get('WEB_NAV_WAYPOINT_YAML')
    if env_path:
        paths.append(env_path)
    paths.extend(DEFAULT_WAYPOINT_PATHS)
    return paths


def _yaw_from_quaternion(raw: Dict[str, Any]) -> float:
    x = float(raw.get('x', 0.0))
    y = float(raw.get('y', 0.0))
    z = float(raw.get('z', 0.0))
    w = float(raw.get('w', 1.0))
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _normalize_waypoint(raw: Dict[str, Any], index: int) -> Waypoint:
    pose = raw.get('pose') if isinstance(raw.get('pose'), dict) else {}
    position = pose.get('position') if isinstance(pose.get('position'), dict) else {}
    orientation = pose.get('orientation') if isinstance(pose.get('orientation'), dict) else {}
    x = raw.get('x', pose.get('x', position.get('x')))
    y = raw.get('y', pose.get('y', position.get('y')))
    yaw = raw.get('yaw', pose.get('yaw', _yaw_from_quaternion(orientation) if orientation else 0.0))
    use_yaw = raw.get('use_yaw', pose.get('use_yaw', False))
    return Waypoint(
        id=str(raw.get('id', raw.get('name', f'wp_{index:03d}'))),
        source_node_id=raw.get('source_node_id', raw.get('source_id', None)),
        x=float(x),
        y=float(y),
        yaw=float(yaw),
        use_yaw=bool(use_yaw),
    )


def load_waypoints(path: str) -> List[Waypoint]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f'Waypoint file not found: {p}')

    text = p.read_text(encoding='utf-8')
    if p.suffix.lower() == '.json':
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)

    if data is None:
        return []

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get('waypoints', [])
    else:
        raise ValueError('Unsupported waypoint file format')

    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        pose = row.get('pose') if isinstance(row.get('pose'), dict) else {}
        position = pose.get('position') if isinstance(pose.get('position'), dict) else {}
        has_flat_xy = 'x' in row and 'y' in row
        has_pose_xy = 'x' in pose and 'y' in pose
        has_nav2_xy = 'x' in position and 'y' in position
        if not (has_flat_xy or has_pose_xy or has_nav2_xy):
            continue
        out.append(_normalize_waypoint(row, i))
    return out


def load_default_waypoints() -> Tuple[Optional[str], List[Waypoint], List[str]]:
    searched = waypoint_search_paths()
    for raw_path in searched:
        path = Path(raw_path).expanduser()
        if path.exists():
            return str(path), load_waypoints(str(path)), searched
    return None, [], searched


def export_waypoints(waypoints: List[Waypoint], frame_id: str = 'map', fmt: str = 'yaml') -> str:
    payload = {
        'waypoints': [w.model_dump(exclude_none=True) for w in waypoints],
    }
    if fmt == 'json':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return yaml.dump(payload, Dumper=IndentedDumper, allow_unicode=True, sort_keys=False)


def save_waypoints(path: str, waypoints: List[Waypoint]) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(export_waypoints(waypoints, fmt='yaml'), encoding='utf-8')
    return str(p)
