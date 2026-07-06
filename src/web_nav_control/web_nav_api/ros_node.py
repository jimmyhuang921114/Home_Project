from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy

from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Path

try:
    from tf2_ros import Buffer, TransformException, TransformListener
except Exception:  # tf2 may be unavailable in minimal environments
    Buffer = None
    TransformException = Exception
    TransformListener = None

try:
    from semantic_nav_interfaces.srv import NavToPoint
except Exception:  # package may not be built yet
    NavToPoint = None


def quat_to_yaw(q) -> float:
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class WebNavRosNode(Node):
    def __init__(self) -> None:
        super().__init__('web_nav_api_node')
        self._lock = threading.Lock()
        self._map: Optional[Dict[str, Any]] = None
        self._pose: Optional[Dict[str, Any]] = None
        self._plan: Optional[Dict[str, Any]] = None
        self._tf_buffer = None
        self._tf_listener = None

        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        normal_qos = QoSProfile(depth=10)

        self.create_subscription(OccupancyGrid, '/map', self._on_map, map_qos)
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self._on_pose, normal_qos)
        self.create_subscription(Path, '/plan', self._on_plan, normal_qos)

        if Buffer is not None and TransformListener is not None:
            self._tf_buffer = Buffer()
            self._tf_listener = TransformListener(self._tf_buffer, self)

        self._nav_client = None
        if NavToPoint is not None:
            self._nav_client = self.create_client(NavToPoint, '/nav_to_point')

    def _on_map(self, msg: OccupancyGrid) -> None:
        payload = {
            'available': True,
            'frame_id': msg.header.frame_id,
            'info': {
                'width': msg.info.width,
                'height': msg.info.height,
                'resolution': msg.info.resolution,
                'origin': {
                    'x': msg.info.origin.position.x,
                    'y': msg.info.origin.position.y,
                    'z': msg.info.origin.position.z,
                },
            },
            # int8[] may be array-like; convert for JSON.
            'data': list(msg.data),
        }
        with self._lock:
            self._map = payload

    def _on_pose(self, msg: PoseWithCovarianceStamped) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        payload = {
            'available': True,
            'source_topic': '/amcl_pose',
            'last_update_time': time.time(),
            'frame_id': msg.header.frame_id,
            'x': p.x,
            'y': p.y,
            'z': p.z,
            'yaw': quat_to_yaw(q),
            'yaw_degree': math.degrees(quat_to_yaw(q)),
        }
        with self._lock:
            self._pose = payload

    def _on_plan(self, msg: Path) -> None:
        points: List[Dict[str, float]] = []
        for pose in msg.poses:
            points.append({
                'x': pose.pose.position.x,
                'y': pose.pose.position.y,
            })
        payload = {
            'available': True,
            'frame_id': msg.header.frame_id,
            'points': points,
        }
        with self._lock:
            self._plan = payload

    def get_map(self) -> Dict[str, Any]:
        with self._lock:
            return self._map or {'available': False}

    def get_pose(self) -> Dict[str, Any]:
        with self._lock:
            pose = self._pose
        if pose is not None:
            return pose
        tf_pose = self._lookup_tf_pose()
        return tf_pose or {'available': False, 'error': 'robot pose unavailable'}

    def _lookup_tf_pose(self) -> Optional[Dict[str, Any]]:
        if self._tf_buffer is None:
            return None
        for child_frame in ('base_link', 'base_footprint'):
            try:
                transform = self._tf_buffer.lookup_transform(
                    'map',
                    child_frame,
                    rclpy.time.Time(),
                    timeout=Duration(seconds=0.05),
                )
            except TransformException:
                continue
            except Exception:
                continue
            t = transform.transform.translation
            q = transform.transform.rotation
            yaw = quat_to_yaw(q)
            return {
                'available': True,
                'source_topic': f'tf: map->{child_frame}',
                'last_update_time': time.time(),
                'frame_id': 'map',
                'x': t.x,
                'y': t.y,
                'z': t.z,
                'yaw': yaw,
                'yaw_degree': math.degrees(yaw),
            }
        return None

    def get_plan(self) -> Dict[str, Any]:
        with self._lock:
            return self._plan or {'available': False, 'points': []}

    def call_nav_to_point(self, x: float, y: float, yaw: float = 0.0, use_yaw: bool = False, timeout_sec: float = 5.0) -> Dict[str, Any]:
        if NavToPoint is None or self._nav_client is None:
            return {'success': False, 'message': 'semantic_nav_interfaces/NavToPoint is not available'}

        if not self._nav_client.wait_for_service(timeout_sec=timeout_sec):
            return {'success': False, 'message': '/nav_to_point service not available'}

        req = NavToPoint.Request()
        req.x = float(x)
        req.y = float(y)
        req.yaw = float(yaw)
        req.use_yaw = bool(use_yaw)

        future = self._nav_client.call_async(req)
        deadline = self.get_clock().now().nanoseconds + int(timeout_sec * 1e9)
        while rclpy.ok() and not future.done():
            rclpy.spin_once(self, timeout_sec=0.05)
            if self.get_clock().now().nanoseconds > deadline:
                return {'success': False, 'message': '/nav_to_point service timeout'}

        res = future.result()
        return {
            'success': bool(getattr(res, 'success', False)),
            'message': str(getattr(res, 'message', '')),
        }
