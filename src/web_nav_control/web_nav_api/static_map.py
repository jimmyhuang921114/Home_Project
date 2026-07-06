from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def get_project_root() -> Path:
    env = os.environ.get('HOME_PROJECT_ROOT')
    if env:
        return Path(env).expanduser().resolve()

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / 'src').exists():
            return parent
    return p.parents[3]


def _read_png_size(path: Path) -> Tuple[int, int]:
    with path.open('rb') as f:
        sig = f.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            raise ValueError('not a PNG image')
        f.read(8)  # length + IHDR
        width, height = struct.unpack('>II', f.read(8))
        return int(width), int(height)


def _read_pnm_header(path: Path) -> Tuple[str, int, int, int, int]:
    """Return magic, width, height, maxval, data_offset for PBM/PGM/PPM."""
    data = path.read_bytes()
    i = 0
    tokens = []
    while i < len(data) and len(tokens) < 4:
        while i < len(data) and chr(data[i]).isspace():
            i += 1
        if i < len(data) and data[i:i + 1] == b'#':
            while i < len(data) and data[i:i + 1] not in (b'\n', b'\r'):
                i += 1
            continue
        start = i
        while i < len(data) and not chr(data[i]).isspace():
            i += 1
        if start != i:
            tokens.append(data[start:i].decode('ascii'))
    while i < len(data) and chr(data[i]).isspace():
        i += 1
    if len(tokens) < 4:
        raise ValueError('invalid PNM/PGM header')
    return tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3]), i


def _read_image_size(path: Path) -> Tuple[int, int]:
    suffix = path.suffix.lower()
    if suffix == '.png':
        return _read_png_size(path)
    if suffix in ('.pgm', '.ppm', '.pnm'):
        _, width, height, _, _ = _read_pnm_header(path)
        return width, height
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception as exc:
        raise ValueError(f'cannot read image size for {path}: {exc}')


def _load_gray_image_optional(path: Path):
    """Load grayscale image as numpy array when optional deps exist, else None."""
    try:
        import cv2
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            return img
    except Exception:
        pass
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            return np.array(im.convert('L'))
    except Exception:
        pass
    if path.suffix.lower() == '.pgm':
        try:
            import numpy as np
            magic, width, height, maxval, offset = _read_pnm_header(path)
            raw = path.read_bytes()[offset:]
            if magic == 'P5' and maxval <= 255:
                return np.frombuffer(raw, dtype=np.uint8, count=width * height).reshape((height, width))
        except Exception:
            pass
    return None


PROJECT_ROOT = get_project_root()
RUNTIME_MAP_DIR = PROJECT_ROOT / 'src' / 'web_nav_control' / 'runtime' / 'map'
RUNTIME_MAP_YAML = RUNTIME_MAP_DIR / 'map.yaml'


class StaticMapProvider:
    """Serve a fixed Nav2 map.yaml + map image for Web display.

    The display payload intentionally does not include millions of occupancy cells.
    The planning payload may include occupancy data when cv2/Pillow/PGM parsing is available.
    """

    def __init__(self, yaml_path: Optional[str] = None) -> None:
        self._explicit_yaml_path = Path(yaml_path).expanduser() if yaml_path else None
        self.yaml_path = self._select_yaml_path()
        self._display_payload: Optional[Dict[str, Any]] = None
        self._planning_payload: Optional[Dict[str, Any]] = None
        self._image_path: Optional[Path] = None
        self._map_cfg: Dict[str, Any] = {}
        self._mtime: float = 0.0
        self._load()

    @property
    def available(self) -> bool:
        return self._display_payload is not None

    @property
    def image_path(self) -> Optional[Path]:
        return self._image_path

    def _select_yaml_path(self) -> Path:
        if self._explicit_yaml_path is not None:
            return self._explicit_yaml_path
        if RUNTIME_MAP_YAML.exists():
            return RUNTIME_MAP_YAML
        env_path = os.environ.get('WEB_NAV_STATIC_MAP_YAML')
        if env_path:
            return Path(env_path).expanduser()
        return PROJECT_ROOT / 'config' / 'map.yaml'

    def reload(self) -> None:
        self.yaml_path = self._select_yaml_path()
        self._display_payload = None
        self._planning_payload = None
        self._image_path = None
        self._map_cfg = {}
        self._mtime = 0.0
        self._load()

    def _load(self) -> None:
        if yaml is None:
            return
        if not self.yaml_path.exists():
            return

        cfg = yaml.safe_load(self.yaml_path.read_text()) or {}
        self._map_cfg = cfg
        image_ref = cfg.get('image')
        if not image_ref:
            return
        image_path = Path(image_ref)
        if not image_path.is_absolute():
            image_path = self.yaml_path.parent / image_path
        if not image_path.exists():
            return

        width, height = _read_image_size(image_path)
        resolution = float(cfg.get('resolution', 1.0))
        origin_raw = cfg.get('origin', [0.0, 0.0, 0.0])
        origin_x = float(origin_raw[0]) if len(origin_raw) > 0 else 0.0
        origin_y = float(origin_raw[1]) if len(origin_raw) > 1 else 0.0
        origin_z = float(origin_raw[2]) if len(origin_raw) > 2 else 0.0

        self._image_path = image_path
        self._mtime = max(self.yaml_path.stat().st_mtime, image_path.stat().st_mtime)
        info = {
            'width': width,
            'height': height,
            'resolution': resolution,
            'origin': {'x': origin_x, 'y': origin_y, 'z': origin_z},
        }
        self._display_payload = {
            'available': True,
            'source': 'runtime_upload' if self.yaml_path == RUNTIME_MAP_YAML else 'static_file',
            'frame_id': 'map',
            'yaml_path': str(self.yaml_path),
            'image_path': str(image_path),
            'image_url': f'/api/static_map_image?v={int(self._mtime)}',
            'info': info,
        }

    def _build_planning_payload(self) -> Dict[str, Any]:
        if self._planning_payload is not None:
            return self._planning_payload
        if self._display_payload is None or self._image_path is None:
            return {'available': False}

        planning_payload = dict(self._display_payload)
        gray = _load_gray_image_optional(self._image_path)
        if gray is not None:
            negate = int(self._map_cfg.get('negate', 0))
            occupied_thresh = float(self._map_cfg.get('occupied_thresh', 0.65))
            free_thresh = float(self._map_cfg.get('free_thresh', 0.196))
            occ_data = []
            # Nav2 map images have image row 0 as top. OccupancyGrid row 0 is map bottom.
            # Flip vertically so index my*width+mx matches world y increasing upward.
            for row in gray[::-1]:
                for pixel in row:
                    v = int(pixel)
                    occ = v / 255.0 if negate else (255 - v) / 255.0
                    if occ > occupied_thresh:
                        occ_data.append(100)
                    elif occ < free_thresh:
                        occ_data.append(0)
                    else:
                        occ_data.append(-1)
            planning_payload['data'] = occ_data
        self._planning_payload = planning_payload
        return planning_payload

    def display_payload(self) -> Dict[str, Any]:
        return self._display_payload or {'available': False, 'message': f'static map not found: {self.yaml_path}'}

    def planning_payload(self) -> Dict[str, Any]:
        return self._build_planning_payload()
