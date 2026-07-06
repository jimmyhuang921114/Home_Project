#!/usr/bin/env python3
"""
Map Builder Node
================
多視角語意地圖建置節點。

流程：
  1. 機器人移動至觀測位置並停穩
  2. 呼叫 /semantic_map/confirm  → 收集 N 幀，存為一個視角快照
  3. 重複步驟 1-2（建議 3-4 個視角）
  4. 呼叫 /semantic_map/finalize → 跨視角融合，寫入持久化地圖

融合邏輯：
  - 同類別物件在空間上叢集
  - 出現於 >= min_viewpoints 個視角 → 加權平均位置後寫入（高信心）
  - 僅出現於 1 個視角           → 捨棄（可能是誤偵測或遮擋誤判）

Services：
  /semantic_map/confirm         (std_srvs/Trigger) → 收集一個視角快照
  /semantic_map/finalize        (std_srvs/Trigger) → 跨視角融合並寫入地圖
  /semantic_map/clear_viewpoints(std_srvs/Trigger) → 清除所有視角快照（不動地圖）
  /semantic_map/clear_map       (std_srvs/Trigger) → 清空持久化地圖

發布：
  /semantic_objects              (std_msgs/String, JSON)
  /semantic_map                  (visualization_msgs/MarkerArray)
  /map_builder/status            (std_msgs/String)
  /map_builder/viewpoints_info   (std_msgs/String, JSON)  ← 已收集的視角快照摘要
"""

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Dict, List, Optional, Tuple

import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from geometry_msgs.msg import Point, Vector3
from std_msgs.msg import ColorRGBA, String
from std_srvs.srv import Trigger
from visualization_msgs.msg import Marker, MarkerArray


def get_project_root() -> Path:
    env = os.environ.get('HOME_PROJECT_ROOT')
    if env:
        return Path(env).expanduser().resolve()

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / 'src').exists():
            return parent
    return p.parents[4]


def _parse_detections(data: dict) -> list:
    """
    兩種輸入格式都轉成統一的 detections list，每筆含 class / score / position{x,y,z}。

    vision_package (bbox_all_3d_marker_node) 格式：
      {"objects": [{"class": "...", "score": 0.9, "base_point": {x,y,z}}]}

    semantic_map_node / 舊格式：
      {"detections": [{"class": "...", "score": 0.9, "position": {x,y,z}}]}
    """
    # vision_package 格式
    if 'objects' in data:
        result = []
        for obj in data['objects']:
            bp = obj.get('base_point', {})
            result.append({
                'class': obj.get('class', 'unknown'),
                'score': obj.get('score', 0.0),
                'position': {
                    'x': bp.get('x', 0.0),
                    'y': bp.get('y', 0.0),
                    'z': bp.get('z', 0.0),
                },
            })
        return result

    # 舊格式（semantic_map_node）
    return data.get('detections', [])


@dataclass
class ViewpointCluster:
    """一個視角內某類別的一個空間叢集（觀測結果）。"""
    class_name: str
    x: float
    y: float
    z: float
    score: float
    n_obs: int      # 這個視角收集到的幀數（加權依據）


@dataclass
class ViewpointSnapshot:
    """一次 confirm 收集到的所有叢集。"""
    viewpoint_id: int
    clusters: List[ViewpointCluster] = field(default_factory=list)


@dataclass
class SemanticObject:
    obj_id: str
    class_name: str
    x: float
    y: float
    z: float
    confidence: float = 1.0
    observe_count: int = 0
    viewpoint_count: int = 0    # 幾個視角都看到過

    def to_dict(self) -> dict:
        return {
            'id': self.obj_id,
            'class': self.class_name,
            'position': {'x': round(self.x, 4), 'y': round(self.y, 4), 'z': round(self.z, 4)},
            'confidence': round(self.confidence, 4),
            'observe_count': self.observe_count,
            'viewpoint_count': self.viewpoint_count,
        }


class MapBuilderNode(Node):

    def __init__(self) -> None:
        super().__init__('map_builder_node')
        project_root = get_project_root()

        self.declare_parameter('raw_detections_topic', '/grounding_dino/objects_3d_json')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('collect_frames', 10)
        self.declare_parameter('collect_timeout', 5.0)
        self.declare_parameter('min_obs_per_viewpoint', 3)
        self.declare_parameter('max_std_dev', 0.15)
        self.declare_parameter('merge_distance', 0.50)
        self.declare_parameter('min_viewpoints', 2)
        self.declare_parameter('map_save_path', 'data/semantic_map.json')
        self.declare_parameter('auto_save_interval', 60.0)
        self.declare_parameter('publish_rate', 2.0)

        p = self.get_parameter
        self._raw_topic        = str(p('raw_detections_topic').value)
        self._map_frame        = str(p('map_frame').value)
        self._collect_frames   = int(p('collect_frames').value)
        self._collect_timeout  = float(p('collect_timeout').value)
        self._min_obs          = int(p('min_obs_per_viewpoint').value)
        self._max_std_dev      = float(p('max_std_dev').value)
        self._merge_dist       = float(p('merge_distance').value)
        self._min_viewpoints   = int(p('min_viewpoints').value)
        save_path = Path(str(p('map_save_path').value)).expanduser()
        if not save_path.is_absolute():
            save_path = project_root / save_path
        self._save_path        = str(save_path)
        self._publish_rate     = float(p('publish_rate').value)

        # 視角快照（confirm 累積，finalize 消費）
        self._viewpoints: List[ViewpointSnapshot] = []
        self._vp_next_id: int = 0
        self._vp_lock = Lock()

        # 持久化地圖
        self._objects: Dict[str, SemanticObject] = {}
        self._next_id: int = 0
        self._map_lock = Lock()

        # 定點收集狀態
        self._collecting = False
        self._buffer: List[dict] = []
        self._frame_count: int = 0
        self._collect_event: Event = Event()
        self._collect_lock = Lock()

        self._busy = False
        self._busy_lock = Lock()

        self._cbg = ReentrantCallbackGroup()

        self.create_subscription(
            String, self._raw_topic, self._raw_cb, 10,
            callback_group=self._cbg,
        )

        self.create_service(Trigger, '/semantic_map/confirm',
                            self._confirm_cb, callback_group=self._cbg)
        self.create_service(Trigger, '/semantic_map/finalize',
                            self._finalize_cb, callback_group=self._cbg)
        self.create_service(Trigger, '/semantic_map/clear_viewpoints',
                            self._clear_vp_cb, callback_group=self._cbg)
        self.create_service(Trigger, '/semantic_map/clear_map',
                            self._clear_map_cb, callback_group=self._cbg)

        self._objects_pub  = self.create_publisher(String, '/semantic_objects', 10)
        self._marker_pub   = self.create_publisher(MarkerArray, '/semantic_map', 10)
        self._status_pub   = self.create_publisher(String, '/map_builder/status', 10)
        self._vp_info_pub  = self.create_publisher(String, '/map_builder/viewpoints_info', 10)

        self.create_timer(1.0 / self._publish_rate, self._publish, callback_group=self._cbg)
        self.create_timer(float(p('auto_save_interval').value), self._save_map,
                          callback_group=self._cbg)

        self._load_map()

        self.get_logger().info(
            f'MapBuilderNode started\n'
            f'  collect_frames      : {self._collect_frames}\n'
            f'  min_obs_per_viewpoint: {self._min_obs}\n'
            f'  max_std_dev         : {self._max_std_dev} m\n'
            f'  merge_distance      : {self._merge_dist} m\n'
            f'  min_viewpoints      : {self._min_viewpoints}\n'
            f'  save_path           : {self._save_path}'
        )

    # ── Raw detections ────────────────────────────────────────────────────────
    def _raw_cb(self, msg: String) -> None:
        if not self._collecting:
            return
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        with self._collect_lock:
            if not self._collecting:
                return
            self._buffer.extend(_parse_detections(data))
            self._frame_count += 1
            self._publish_status(
                f'collecting {self._frame_count}/{self._collect_frames}'
            )
            if self._frame_count >= self._collect_frames:
                self._collect_event.set()

    # ── Service: confirm（收集一個視角快照）──────────────────────────────────
    def _confirm_cb(
        self, request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        with self._busy_lock:
            if self._busy:
                response.success = False
                response.message = 'Busy — try again later'
                return response
            self._busy = True
        try:
            return self._do_confirm(response)
        finally:
            with self._busy_lock:
                self._busy = False

    def _do_confirm(self, response: Trigger.Response) -> Trigger.Response:
        with self._vp_lock:
            vp_id = self._vp_next_id

        self.get_logger().info(f'Confirm: collecting viewpoint #{vp_id}')

        with self._collect_lock:
            self._buffer = []
            self._frame_count = 0
            self._collect_event.clear()
            self._collecting = True

        self._publish_status(f'collecting viewpoint #{vp_id}  0/{self._collect_frames}')
        got_enough = self._collect_event.wait(timeout=self._collect_timeout)

        with self._collect_lock:
            self._collecting = False
            dets = list(self._buffer)
            n_frames = self._frame_count

        if not dets:
            msg = f'No detections ({n_frames} frames) — viewpoint #{vp_id} skipped'
            self.get_logger().warn(msg)
            response.success = False
            response.message = msg
            self._publish_status_vp()
            return response

        if not got_enough:
            self.get_logger().warn(
                f'Timeout with {n_frames} frames — proceeding with partial data'
            )

        # 對本視角觀測叢集化
        clusters = self._cluster_detections(dets)

        if not clusters:
            msg = f'Viewpoint #{vp_id}: no valid clusters after filtering'
            self.get_logger().warn(msg)
            response.success = False
            response.message = msg
            self._publish_status_vp()
            return response

        snapshot = ViewpointSnapshot(viewpoint_id=vp_id, clusters=clusters)
        with self._vp_lock:
            self._viewpoints.append(snapshot)
            self._vp_next_id += 1
            n_vp = len(self._viewpoints)

        msg = (f'Viewpoint #{vp_id} saved: {len(clusters)} clusters  '
               f'(total viewpoints={n_vp})')
        self.get_logger().info(msg)
        response.success = True
        response.message = msg
        self._publish_status(
            f'idle — {n_vp} viewpoint(s) collected, call finalize to commit'
        )
        self._publish_vp_info()
        return response

    def _cluster_detections(self, dets: List[dict]) -> List[ViewpointCluster]:
        """對一組偵測結果分組並叢集化，回傳品質通過的叢集。"""
        by_class: Dict[str, list] = defaultdict(list)
        for det in dets:
            cls = det.get('class', 'unknown')
            pos = det.get('position', {})
            try:
                x = float(pos.get('x', 0.0))
                y = float(pos.get('y', 0.0))
                z = float(pos.get('z', 0.0))
                score = float(det.get('score', 0.0))
            except (TypeError, ValueError):
                continue
            by_class[cls].append((x, y, z, score))

        result: List[ViewpointCluster] = []
        for cls, obs in by_class.items():
            for cluster in self._cluster(obs):
                n = len(cluster)
                if n < self._min_obs:
                    continue
                xs = np.array([o[0] for o in cluster])
                ys = np.array([o[1] for o in cluster])
                zs = np.array([o[2] for o in cluster])
                std_xy = float(max(np.std(xs), np.std(ys)))
                if std_xy > self._max_std_dev:
                    self.get_logger().debug(
                        f'Skip {cls}: std_xy={std_xy:.3f}m'
                    )
                    continue
                result.append(ViewpointCluster(
                    class_name=cls,
                    x=float(np.median(xs)),
                    y=float(np.median(ys)),
                    z=float(np.median(zs)),
                    score=float(np.mean([o[3] for o in cluster])),
                    n_obs=n,
                ))
        return result

    # ── Service: finalize（跨視角融合並寫入地圖）────────────────────────────
    def _finalize_cb(
        self, request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        with self._busy_lock:
            if self._busy:
                response.success = False
                response.message = 'Busy — try again later'
                return response
            self._busy = True
        try:
            return self._do_finalize(response)
        finally:
            with self._busy_lock:
                self._busy = False

    def _do_finalize(self, response: Trigger.Response) -> Trigger.Response:
        with self._vp_lock:
            snapshots = list(self._viewpoints)

        n_vp = len(snapshots)
        if n_vp == 0:
            response.success = False
            response.message = 'No viewpoints collected — call confirm first'
            return response

        if n_vp < self._min_viewpoints:
            self.get_logger().warn(
                f'Only {n_vp} viewpoint(s), min_viewpoints={self._min_viewpoints} — '
                f'proceeding anyway'
            )

        self.get_logger().info(f'Finalize: fusing {n_vp} viewpoints')
        self._publish_status(f'finalizing {n_vp} viewpoints...')

        committed, discarded = self._fuse_and_commit(snapshots)

        # 清除視角快照（已消費）
        with self._vp_lock:
            self._viewpoints.clear()
            self._vp_next_id = 0

        msg = (f'Committed {committed}, discarded {discarded}  '
               f'(from {n_vp} viewpoints, min_viewpoints={self._min_viewpoints})')
        self.get_logger().info(f'Finalize done: {msg}')
        response.success = True
        response.message = msg
        self._publish_status(f'idle ({msg})')
        self._publish_vp_info()
        self._save_map()
        return response

    def _fuse_and_commit(
        self, snapshots: List[ViewpointSnapshot]
    ) -> Tuple[int, int]:
        """
        跨視角融合：
          1. 收集所有視角的叢集
          2. 空間叢集化（跨視角）
          3. 統計每個叢集出現在幾個視角
          4. >= min_viewpoints → 加權平均位置，寫入地圖
          5. < min_viewpoints  → 捨棄
        """
        # 把所有叢集扁平化，帶上視角 ID
        all_obs: List[Tuple[str, float, float, float, float, int, int]] = []
        # (class, x, y, z, score, n_obs, viewpoint_id)
        for snap in snapshots:
            for c in snap.clusters:
                all_obs.append((
                    c.class_name, c.x, c.y, c.z, c.score, c.n_obs, snap.viewpoint_id
                ))

        # 依 class 分組
        by_class: Dict[str, list] = defaultdict(list)
        for obs in all_obs:
            by_class[obs[0]].append(obs)

        committed = discarded = 0

        with self._map_lock:
            for cls, obs_list in by_class.items():
                # 空間叢集化（以 x,y,z 做 greedy merge）
                points = [(o[1], o[2], o[3], o[4], o[5], o[6]) for o in obs_list]
                # (x, y, z, score, n_obs, vp_id)

                used = [False] * len(points)
                for i, p in enumerate(points):
                    if used[i]:
                        continue
                    cluster = [p]
                    used[i] = True
                    for j, q in enumerate(points):
                        if used[j]:
                            continue
                        d = math.sqrt(
                            (p[0]-q[0])**2 + (p[1]-q[1])**2 + (p[2]-q[2])**2
                        )
                        if d <= self._merge_dist:
                            cluster.append(q)
                            used[j] = True

                    # 統計視角數
                    vp_ids = set(c[5] for c in cluster)
                    n_viewpoints = len(vp_ids)

                    if n_viewpoints < self._min_viewpoints:
                        discarded += 1
                        self.get_logger().info(
                            f'Discard {cls}: only seen in {n_viewpoints}/'
                            f'{self._min_viewpoints} viewpoint(s)'
                        )
                        continue

                    # 以各視角的 n_obs 加權平均位置
                    total_w = sum(c[4] for c in cluster)
                    fx = sum(c[0] * c[4] for c in cluster) / total_w
                    fy = sum(c[1] * c[4] for c in cluster) / total_w
                    fz = sum(c[2] * c[4] for c in cluster) / total_w
                    conf = float(np.mean([c[3] for c in cluster]))
                    total_n = sum(c[4] for c in cluster)

                    self.get_logger().info(
                        f'Commit {cls} @ ({fx:.3f},{fy:.3f},{fz:.3f})  '
                        f'viewpoints={n_viewpoints}  total_obs={total_n}'
                    )
                    self._upsert(cls, fx, fy, fz, conf, total_n, n_viewpoints)
                    committed += 1

        return committed, discarded

    # ── Greedy spatial clustering（單視角用）────────────────────────────────
    def _cluster(
        self, obs: List[Tuple[float, float, float, float]]
    ) -> List[List[Tuple[float, float, float, float]]]:
        used = [False] * len(obs)
        clusters = []
        for i, o in enumerate(obs):
            if used[i]:
                continue
            cluster = [o]
            used[i] = True
            for j, other in enumerate(obs):
                if used[j]:
                    continue
                if math.sqrt(
                    (o[0]-other[0])**2 + (o[1]-other[1])**2 + (o[2]-other[2])**2
                ) <= self._merge_dist:
                    cluster.append(other)
                    used[j] = True
            clusters.append(cluster)
        return clusters

    # ── Map upsert（呼叫時需持有 _map_lock）──────────────────────────────────
    def _upsert(self, cls: str, x: float, y: float, z: float,
                confidence: float, n: int, n_viewpoints: int) -> None:
        best: Optional[SemanticObject] = None
        best_dist = self._merge_dist
        for obj in self._objects.values():
            if obj.class_name != cls:
                continue
            d = math.sqrt((obj.x-x)**2 + (obj.y-y)**2 + (obj.z-z)**2)
            if d < best_dist:
                best_dist = d
                best = obj

        if best is not None:
            total = best.observe_count + n
            w = n / total
            best.x = (1.0 - w) * best.x + w * x
            best.y = (1.0 - w) * best.y + w * y
            best.z = (1.0 - w) * best.z + w * z
            best.confidence = max(best.confidence, confidence)
            best.observe_count = total
            best.viewpoint_count = max(best.viewpoint_count, n_viewpoints)
        else:
            new_id = f'{cls}_{self._next_id}'
            self._next_id += 1
            self._objects[new_id] = SemanticObject(
                obj_id=new_id, class_name=cls,
                x=x, y=y, z=z,
                confidence=confidence, observe_count=n,
                viewpoint_count=n_viewpoints,
            )

    # ── Services: clear ───────────────────────────────────────────────────────
    def _clear_vp_cb(
        self, request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        with self._vp_lock:
            n = len(self._viewpoints)
            self._viewpoints.clear()
            self._vp_next_id = 0
        self.get_logger().info(f'Viewpoints cleared ({n} snapshots)')
        response.success = True
        response.message = f'Cleared {n} viewpoint snapshots'
        self._publish_status('idle (viewpoints cleared)')
        self._publish_vp_info()
        return response

    def _clear_map_cb(
        self, request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        with self._map_lock:
            n = len(self._objects)
            self._objects.clear()
            self._next_id = 0
        self.get_logger().info(f'Map cleared ({n} objects)')
        response.success = True
        response.message = f'Cleared {n} objects'
        self._publish_status('idle (map cleared)')
        return response

    # ── Publishing ────────────────────────────────────────────────────────────
    def _publish(self) -> None:
        with self._map_lock:
            objs = list(self._objects.values())

        out = String()
        out.data = json.dumps(
            {'frame_id': self._map_frame, 'count': len(objs),
             'objects': [o.to_dict() for o in objs]},
            ensure_ascii=False,
        )
        self._objects_pub.publish(out)

        ma = MarkerArray()
        clear = Marker()
        clear.action = Marker.DELETEALL
        clear.header.frame_id = self._map_frame
        ma.markers.append(clear)

        now = self.get_clock().now().to_msg()
        for idx, obj in enumerate(objs):
            m = Marker()
            m.header.frame_id = self._map_frame
            m.header.stamp = now
            m.ns = 'map_builder_objects'
            m.id = idx * 2
            m.type = Marker.SPHERE
            m.action = Marker.ADD
            m.pose.position = Point(x=obj.x, y=obj.y, z=obj.z)
            m.pose.orientation.w = 1.0
            m.scale = Vector3(x=0.3, y=0.3, z=0.3)
            c = self._class_color(obj.class_name)
            # 視角數越多透明度越高（視覺上越確定）
            alpha = min(0.4 + obj.viewpoint_count * 0.15, 0.95)
            m.color = ColorRGBA(r=c.r, g=c.g, b=c.b, a=alpha)
            ma.markers.append(m)

            t = Marker()
            t.header.frame_id = self._map_frame
            t.header.stamp = now
            t.ns = 'map_builder_labels'
            t.id = idx * 2 + 1
            t.type = Marker.TEXT_VIEW_FACING
            t.action = Marker.ADD
            t.pose.position = Point(x=obj.x, y=obj.y, z=obj.z + 0.4)
            t.pose.orientation.w = 1.0
            t.scale.z = 0.25
            t.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
            t.text = f'{obj.class_name} (vp={obj.viewpoint_count} n={obj.observe_count})'
            ma.markers.append(t)

        self._marker_pub.publish(ma)
        self._publish_vp_info()

    def _publish_status(self, status: str) -> None:
        msg = String()
        msg.data = status
        self._status_pub.publish(msg)

    def _publish_status_vp(self) -> None:
        with self._vp_lock:
            n = len(self._viewpoints)
        self._publish_status(
            f'idle — {n} viewpoint(s) collected'
            + (', call finalize to commit' if n > 0 else '')
        )

    def _publish_vp_info(self) -> None:
        with self._vp_lock:
            info = [
                {'viewpoint_id': s.viewpoint_id,
                 'clusters': [
                     {'class': c.class_name, 'n_obs': c.n_obs,
                      'position': {'x': round(c.x, 3), 'y': round(c.y, 3), 'z': round(c.z, 3)}}
                     for c in s.clusters
                 ]}
                for s in self._viewpoints
            ]
        msg = String()
        msg.data = json.dumps(
            {'total_viewpoints': len(info),
             'min_viewpoints_to_commit': self._min_viewpoints,
             'viewpoints': info},
            ensure_ascii=False,
        )
        self._vp_info_pub.publish(msg)

    @staticmethod
    def _class_color(class_name: str) -> ColorRGBA:
        h = hash(class_name)
        return ColorRGBA(
            r=((h >> 16) & 0xFF) / 255.0,
            g=((h >> 8) & 0xFF) / 255.0,
            b=(h & 0xFF) / 255.0,
            a=0.9,
        )

    # ── Persistence ───────────────────────────────────────────────────────────
    def _save_map(self) -> None:
        with self._map_lock:
            data = {'frame_id': self._map_frame, 'next_id': self._next_id,
                    'objects': [o.to_dict() for o in self._objects.values()]}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._save_path)), exist_ok=True)
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.get_logger().debug(f'Map saved → {self._save_path}')
        except OSError as e:
            self.get_logger().warn(f'Save failed: {e}')

    def _load_map(self) -> None:
        if not os.path.exists(self._save_path):
            return
        try:
            with open(self._save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._next_id = data.get('next_id', 0)
            for o in data.get('objects', []):
                obj = SemanticObject(
                    obj_id=o['id'], class_name=o['class'],
                    x=o['position']['x'], y=o['position']['y'], z=o['position']['z'],
                    confidence=o.get('confidence', 1.0),
                    observe_count=o.get('observe_count', 1),
                    viewpoint_count=o.get('viewpoint_count', 1),
                )
                self._objects[obj.obj_id] = obj
            self.get_logger().info(
                f'Map loaded: {len(self._objects)} objects ← {self._save_path}'
            )
        except (OSError, json.JSONDecodeError, KeyError) as e:
            self.get_logger().warn(f'Load failed: {e}')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MapBuilderNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node._save_map()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
