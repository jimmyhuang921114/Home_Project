from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import yaml
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from .models import (
    ChatRequest,
    ExportWaypointsRequest,
    GenerateWaypointsRequest,
    LoadWaypointsRequest,
    NavToPointRequest,
    SaveWaypointsRequest,
    Waypoint,
)
from .waypoint_generator import generate_waypoints_from_polygon
from .waypoint_io import (
    RUNTIME_WAYPOINT_YAML,
    export_waypoints,
    load_default_waypoints,
    load_waypoints,
    save_waypoints,
    waypoint_search_paths,
)
from .static_map import RUNTIME_MAP_DIR, RUNTIME_MAP_YAML, StaticMapProvider


def create_app(ros_node) -> FastAPI:
    app = FastAPI(title='web_nav_control API')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    static_map = StaticMapProvider()

    state = {
        'waypoints': None,
        'waypoint_source': None,
        'waypoint_path': None,
    }

    @app.get('/api/health')
    def health():
        return {'ok': True, 'node': 'web_nav_api'}

    @app.post('/api/chat')
    def chat(req: ChatRequest):
        message = req.message.strip()
        lower = message.lower()
        if any(token in lower for token in ('導航', '去', '移動', 'waypoint')):
            actions = []
            if '去' in message:
                target = message.split('去', 1)[1].strip() or None
                if target:
                    actions.append({'type': 'suggest_navigation', 'target': target})
            return {
                'ok': True,
                'reply': '我收到導航相關指令，目前可以在 Navigation Points 頁面選點導航。下一版可以把文字命令轉成 nav_to_point。',
                'intent': 'navigation',
                'actions': actions,
            }
        if any(token in lower for token in ('地圖', 'map')):
            return {
                'ok': True,
                'reply': '你可以在 Main Map 或 Navigation Points 頁面查看地圖，也可以上傳 map.png 和 map.yaml。',
                'intent': 'map',
                'actions': [],
            }
        if any(token in lower for token in ('房間', 'room', 'polygon')):
            return {
                'ok': True,
                'reply': '你可以在 Polygon Tool 頁面框選房間區域，命名後匯出 room JSON/YAML。',
                'intent': 'room_polygon',
                'actions': [],
            }
        return {
            'ok': True,
            'reply': f'我收到：{message}',
            'intent': 'echo',
            'actions': [],
        }

    @app.get('/api/map')
    def get_map():
        # Prefer fixed map.yaml + image for web display. This avoids sending very large
        # OccupancyGrid JSON payloads to the browser. If the fixed map is not available,
        # fall back to the live /map topic.
        if static_map.available:
            return static_map.display_payload()
        return ros_node.get_map()

    @app.post('/api/upload_map')
    async def upload_map(map_image: UploadFile = File(...), map_yaml: UploadFile = File(...)):
        RUNTIME_MAP_DIR.mkdir(parents=True, exist_ok=True)
        image_path = RUNTIME_MAP_DIR / 'map.png'
        yaml_path = RUNTIME_MAP_YAML

        image_bytes = await map_image.read()
        yaml_bytes = await map_yaml.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail='map image is empty')
        if not yaml_bytes:
            raise HTTPException(status_code=400, detail='map yaml is empty')

        try:
            cfg = yaml.safe_load(yaml_bytes.decode('utf-8')) or {}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f'invalid map yaml: {exc}')
        cfg['image'] = 'map.png'

        image_path.write_bytes(image_bytes)
        yaml_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')
        static_map.reload()
        if not static_map.available:
            raise HTTPException(status_code=400, detail='uploaded map could not be loaded')
        return static_map.display_payload()

    @app.get('/api/static_map_image')
    def get_static_map_image():
        if not static_map.available or static_map.image_path is None:
            raise HTTPException(status_code=404, detail='static map image is not available')
        return FileResponse(static_map.image_path)

    @app.get('/api/robot_pose')
    def get_robot_pose():
        return ros_node.get_pose()

    @app.get('/api/plan')
    def get_plan():
        return ros_node.get_plan()

    @app.get('/api/waypoints')
    def get_waypoints():
        if state['waypoints'] is None:
            path, waypoints, searched = load_default_waypoints()
            if path is None:
                return {
                    'available': False,
                    'error': 'waypoint yaml not found',
                    'searched_paths': searched,
                    'waypoints': [],
                    'count': 0,
                }
            state['waypoints'] = waypoints
            state['waypoint_source'] = 'runtime_upload' if path == str(RUNTIME_WAYPOINT_YAML) else 'yaml_file'
            state['waypoint_path'] = path

        return {
            'available': True,
            'source': state['waypoint_source'] or 'memory',
            'path': state['waypoint_path'],
            'count': len(state['waypoints']),
            'waypoints': [w.model_dump(exclude_none=True) for w in state['waypoints']],
        }

    @app.post('/api/waypoints/load')
    def load_waypoints_api(req: LoadWaypointsRequest):
        try:
            waypoints = load_waypoints(req.path)
            state['waypoints'] = waypoints
            state['waypoint_source'] = 'yaml_file'
            state['waypoint_path'] = req.path
            return {
                'success': True,
                'available': True,
                'source': 'yaml_file',
                'path': req.path,
                'count': len(waypoints),
                'waypoints': [w.model_dump(exclude_none=True) for w in waypoints],
            }
        except Exception as exc:
            return {
                'success': False,
                'available': False,
                'error': str(exc),
                'searched_paths': waypoint_search_paths(),
                'waypoints': [],
                'count': 0,
            }

    @app.post('/api/upload_waypoints')
    async def upload_waypoints(file: UploadFile = File(...)):
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail='waypoint yaml is empty')
        RUNTIME_WAYPOINT_YAML.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_WAYPOINT_YAML.write_bytes(data)
        try:
            waypoints = load_waypoints(str(RUNTIME_WAYPOINT_YAML))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f'invalid waypoint yaml: {exc}')
        state['waypoints'] = waypoints
        state['waypoint_source'] = 'runtime_upload'
        state['waypoint_path'] = str(RUNTIME_WAYPOINT_YAML)
        return {
            'available': True,
            'source': 'runtime_upload',
            'path': str(RUNTIME_WAYPOINT_YAML),
            'count': len(waypoints),
            'waypoints': [w.model_dump(exclude_none=True) for w in waypoints],
        }

    @app.post('/api/waypoints')
    def save_waypoints_api(req: SaveWaypointsRequest):
        path = save_waypoints(str(RUNTIME_WAYPOINT_YAML), req.waypoints)
        state['waypoints'] = req.waypoints
        state['waypoint_source'] = 'runtime_upload'
        state['waypoint_path'] = path
        return {
            'success': True,
            'available': True,
            'source': 'runtime_upload',
            'path': path,
            'count': len(req.waypoints),
            'waypoints': [w.model_dump(exclude_none=True) for w in req.waypoints],
        }

    @app.post('/api/nav_to_point')
    def nav_to_point(req: NavToPointRequest):
        return ros_node.call_nav_to_point(req.x, req.y, req.yaw, req.use_yaw)

    @app.post('/api/generate_waypoints')
    def generate_waypoints(req: GenerateWaypointsRequest):
        waypoints = generate_waypoints_from_polygon(
            polygon_raw=req.polygon,
            map_payload=(static_map.planning_payload() if static_map.available else ros_node.get_map()),
            spacing=req.spacing,
            margin=req.margin,
            snake_order=req.snake_order,
        )
        state['waypoints'] = waypoints
        state['waypoint_source'] = 'generated'
        state['waypoint_path'] = None
        return {
            'success': True,
            'count': len(waypoints),
            'waypoints': [w.model_dump(exclude_none=True) for w in waypoints],
        }

    @app.post('/api/export_waypoints', response_class=PlainTextResponse)
    def export_waypoints_api(req: ExportWaypointsRequest):
        return export_waypoints(req.waypoints, frame_id=req.frame_id, fmt=req.format)

    return app
