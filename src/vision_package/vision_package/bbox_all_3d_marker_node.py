#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
bbox_all_3d_cube_marker_node.py

bbox -> 3D -> RViz2 MarkerArray node。

修改重點：
1. RViz 顯示改成「立體小方塊」Marker.CUBE
2. cube 的 x/y/z 尺寸一致，不再是扁平 2D 方塊
3. 文字只顯示 class name
4. 不顯示 confidence / score
5. 不顯示 position
6. 不顯示 id
7. 保留原本 depth 反投影、TF 轉換、objects_3d_json 除錯輸出

建議 RViz 加：
- MarkerArray
- Topic: /visualization_marker_array
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time

from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray

import tf2_ros
from tf2_geometry_msgs import do_transform_point


class BBoxAll3DCubeMarkerNode(Node):
    def __init__(self):
        super().__init__("bbox_all_2d_marker_node")

        # ============================================================
        # Topics
        # ============================================================
        self.declare_parameter("bboxes_topic", "/grounding_dino/bboxes")
        self.declare_parameter("depth_topic", "/realsense/depth")
        self.declare_parameter("camera_info_topic", "/realsense/camera_info")
        self.declare_parameter("objects_3d_json_topic", "/grounding_dino/objects_3d_json")
        self.declare_parameter("marker_topic", "/visualization_marker_array")

        # ============================================================
        # Frames
        # ============================================================
        self.declare_parameter("target_frame", "map")
        self.declare_parameter("camera_frame_override", "")

        # ============================================================
        # Depth / projection
        # ============================================================
        self.declare_parameter("depth_scale", 0.001)
        self.declare_parameter("min_depth_m", 0.05)
        self.declare_parameter("max_depth_m", 10.0)

        self.declare_parameter("depth_window_radius", 15)
        self.declare_parameter("use_bbox_depth_fallback", True)
        self.declare_parameter("bbox_depth_inner_ratio", 0.60)
        self.declare_parameter("bbox_depth_percentile", 35.0)
        self.declare_parameter("bbox_depth_max_samples", 2500)

        self.declare_parameter("auto_scale_bbox_to_depth", True)

        # ============================================================
        # Marker display
        # ============================================================
        # False = 使用真實 3D z 位置
        # True  = 全部壓到固定 marker_z 平面
        self.declare_parameter("flatten_to_2d", False)
        self.declare_parameter("marker_z", 0.08)

        # 立體小方塊尺寸，單位 m
        # 0.10 = 10 cm
        self.declare_parameter("cube_size", 0.10)

        # 保留舊參數名稱，避免 launch file 還有 square_size / square_height 時報錯
        self.declare_parameter("square_size", 0.10)
        self.declare_parameter("square_height", 0.10)

        self.declare_parameter("cube_alpha", 0.85)
        self.declare_parameter("marker_lifetime_s", 0.0)

        # 文字只顯示名稱
        self.declare_parameter("text_scale", 0.12)
        self.declare_parameter("text_z_offset", 0.13)

        # 這三個預設都關掉
        self.declare_parameter("show_score", False)
        self.declare_parameter("show_position", False)
        self.declare_parameter("show_id", False)

        # ============================================================
        # Filtering
        # ============================================================
        self.declare_parameter("min_score", 0.0)
        self.declare_parameter("max_objects", 100)
        self.declare_parameter("delete_when_empty", True)

        # ============================================================
        # Read params
        # ============================================================
        self.bboxes_topic = str(self.get_parameter("bboxes_topic").value)
        self.depth_topic = str(self.get_parameter("depth_topic").value)
        self.camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        self.objects_3d_json_topic = str(self.get_parameter("objects_3d_json_topic").value)
        self.marker_topic = str(self.get_parameter("marker_topic").value)

        self.target_frame = str(self.get_parameter("target_frame").value)
        self.camera_frame_override = str(self.get_parameter("camera_frame_override").value)

        self.depth_scale = float(self.get_parameter("depth_scale").value)
        self.min_depth_m = float(self.get_parameter("min_depth_m").value)
        self.max_depth_m = float(self.get_parameter("max_depth_m").value)

        self.depth_window_radius = int(self.get_parameter("depth_window_radius").value)
        self.use_bbox_depth_fallback = bool(self.get_parameter("use_bbox_depth_fallback").value)
        self.bbox_depth_inner_ratio = float(self.get_parameter("bbox_depth_inner_ratio").value)
        self.bbox_depth_percentile = float(self.get_parameter("bbox_depth_percentile").value)
        self.bbox_depth_max_samples = int(self.get_parameter("bbox_depth_max_samples").value)

        self.auto_scale_bbox_to_depth = bool(self.get_parameter("auto_scale_bbox_to_depth").value)

        self.flatten_to_2d = bool(self.get_parameter("flatten_to_2d").value)
        self.marker_z = float(self.get_parameter("marker_z").value)

        self.cube_size = float(self.get_parameter("cube_size").value)
        self.square_size = float(self.get_parameter("square_size").value)
        self.square_height = float(self.get_parameter("square_height").value)

        self.cube_alpha = float(self.get_parameter("cube_alpha").value)
        self.marker_lifetime_s = float(self.get_parameter("marker_lifetime_s").value)

        self.text_scale = float(self.get_parameter("text_scale").value)
        self.text_z_offset = float(self.get_parameter("text_z_offset").value)

        self.show_score = bool(self.get_parameter("show_score").value)
        self.show_position = bool(self.get_parameter("show_position").value)
        self.show_id = bool(self.get_parameter("show_id").value)

        self.min_score = float(self.get_parameter("min_score").value)
        self.max_objects = int(self.get_parameter("max_objects").value)
        self.delete_when_empty = bool(self.get_parameter("delete_when_empty").value)

        # ============================================================
        # State
        # ============================================================
        self.last_depth_msg: Optional[Image] = None
        self.last_camera_info: Optional[CameraInfo] = None
        self.last_marker_count = 0
        self.last_skip_reasons: Dict[str, int] = {}

        # ============================================================
        # TF
        # ============================================================
        self.tf_buffer = tf2_ros.Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # ============================================================
        # QoS
        # ============================================================
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )
        normal_qos = QoSProfile(depth=10)

        # ============================================================
        # Subscribers
        # ============================================================
        self.depth_sub = self.create_subscription(
            Image,
            self.depth_topic,
            self.depth_callback,
            sensor_qos,
        )
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            self.camera_info_topic,
            self.camera_info_callback,
            sensor_qos,
        )
        self.bboxes_sub = self.create_subscription(
            String,
            self.bboxes_topic,
            self.bboxes_callback,
            normal_qos,
        )

        # ============================================================
        # Publishers
        # ============================================================
        self.json_pub = self.create_publisher(String, self.objects_3d_json_topic, 10)
        self.marker_pub = self.create_publisher(MarkerArray, self.marker_topic, 10)

        self.get_logger().info("BBoxAll3DCubeMarkerNode ready.")
        self.get_logger().info(f"bboxes_topic              : {self.bboxes_topic}")
        self.get_logger().info(f"depth_topic               : {self.depth_topic}")
        self.get_logger().info(f"camera_info_topic         : {self.camera_info_topic}")
        self.get_logger().info(f"objects_3d_json_topic     : {self.objects_3d_json_topic}")
        self.get_logger().info(f"marker_topic              : {self.marker_topic}")
        self.get_logger().info(f"target_frame              : {self.target_frame}")
        self.get_logger().info(f"camera_frame_override     : {self.camera_frame_override}")
        self.get_logger().info(f"flatten_to_2d             : {self.flatten_to_2d}")
        self.get_logger().info(f"cube_size                 : {self.cube_size}")
        self.get_logger().info(f"text_scale                : {self.text_scale}")
        self.get_logger().info("Text marker only shows class name.")

    # ============================================================
    # Callbacks
    # ============================================================

    def depth_callback(self, msg: Image):
        self.last_depth_msg = msg

    def camera_info_callback(self, msg: CameraInfo):
        self.last_camera_info = msg

    def bboxes_callback(self, msg: String):
        self.last_skip_reasons = {}

        if self.last_depth_msg is None:
            self.get_logger().warn("No depth image received yet.")
            return

        if self.last_camera_info is None:
            self.get_logger().warn("No camera_info received yet.")
            return

        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse bbox JSON: {repr(e)}")
            return

        bboxes = payload.get("bboxes", [])
        if not isinstance(bboxes, list):
            self.get_logger().warn("bbox JSON field 'bboxes' is not a list.")
            return

        if not bboxes:
            if self.delete_when_empty:
                self.publish_delete_old_markers()
            self.publish_objects_json([], payload, {})
            self.get_logger().info("No bboxes in GroundingDINO result.")
            return

        if self.max_objects > 0:
            bboxes = bboxes[: self.max_objects]

        source_frame = self.get_source_camera_frame()
        if not source_frame:
            self.get_logger().warn("Cannot determine camera frame.")
            return

        depth_shape = self.get_depth_shape()
        payload_image_w = self.get_payload_image_width(payload)
        payload_image_h = self.get_payload_image_height(payload)

        objects_3d: List[Dict[str, Any]] = []

        for idx, det in enumerate(bboxes):
            obj = self.convert_one_detection(
                det=det,
                idx=idx,
                source_frame=source_frame,
                payload_image_w=payload_image_w,
                payload_image_h=payload_image_h,
                depth_shape=depth_shape,
            )
            if obj is not None:
                objects_3d.append(obj)

        self.publish_objects_json(objects_3d, payload, dict(self.last_skip_reasons))
        self.publish_markers(objects_3d)

        self.get_logger().info(
            f"Published {len(objects_3d)}/{len(bboxes)} 3D cube markers in {self.target_frame}; "
            f"skip={self.last_skip_reasons}"
        )

    def add_skip(self, reason: str):
        self.last_skip_reasons[reason] = self.last_skip_reasons.get(reason, 0) + 1

    # ============================================================
    # Payload / frame helpers
    # ============================================================

    def get_source_camera_frame(self) -> str:
        if self.camera_frame_override:
            return self.camera_frame_override
        if self.last_camera_info is not None and self.last_camera_info.header.frame_id:
            return str(self.last_camera_info.header.frame_id)
        if self.last_depth_msg is not None and self.last_depth_msg.header.frame_id:
            return str(self.last_depth_msg.header.frame_id)
        return ""

    def get_depth_shape(self) -> Optional[Tuple[int, int]]:
        if self.last_depth_msg is None:
            return None
        return int(self.last_depth_msg.height), int(self.last_depth_msg.width)

    @staticmethod
    def get_payload_image_width(payload: Dict[str, Any]) -> Optional[int]:
        for key in ["image_width", "width", "w"]:
            if key in payload:
                try:
                    return int(payload[key])
                except Exception:
                    pass
        if isinstance(payload.get("image_size"), dict):
            for key in ["width", "w"]:
                if key in payload["image_size"]:
                    try:
                        return int(payload["image_size"][key])
                    except Exception:
                        pass
        return None

    @staticmethod
    def get_payload_image_height(payload: Dict[str, Any]) -> Optional[int]:
        for key in ["image_height", "height", "h"]:
            if key in payload:
                try:
                    return int(payload[key])
                except Exception:
                    pass
        if isinstance(payload.get("image_size"), dict):
            for key in ["height", "h"]:
                if key in payload["image_size"]:
                    try:
                        return int(payload["image_size"][key])
                    except Exception:
                        pass
        return None

    # ============================================================
    # Conversion
    # ============================================================

    def convert_one_detection(
        self,
        det: Dict[str, Any],
        idx: int,
        source_frame: str,
        payload_image_w: Optional[int],
        payload_image_h: Optional[int],
        depth_shape: Optional[Tuple[int, int]],
    ) -> Optional[Dict[str, Any]]:
        try:
            score = float(det.get("score", 0.0))
            if score < self.min_score:
                self.add_skip("low_score")
                return None

            class_name = str(det.get("class", "object"))

            scaled_bbox = self.get_scaled_bbox(
                det,
                payload_image_w,
                payload_image_h,
                depth_shape,
            )
            if scaled_bbox is None:
                self.add_skip("bad_bbox")
                return None

            u, v = self.get_bbox_center_from_scaled_bbox(scaled_bbox)

            depth_m, depth_source = self.get_depth_for_detection(
                self.last_depth_msg,
                u,
                v,
                scaled_bbox,
            )
            if depth_m is None:
                self.get_logger().warn(f"No valid depth for {class_name} at u={u:.1f}, v={v:.1f}")
                self.add_skip("no_depth")
                return None

            camera_xyz = self.deproject_pixel_to_3d(
                u,
                v,
                depth_m,
                self.last_camera_info,
            )
            if camera_xyz is None:
                self.add_skip("deproject_failed")
                return None

            target_xyz = self.transform_point_to_target(
                camera_xyz,
                source_frame,
                self.target_frame,
            )
            if target_xyz is None:
                self.add_skip("tf_failed")
                return None

            return {
                "id": int(idx),
                "class": class_name,
                "score": float(score),
                "source_frame": source_frame,
                "target_frame": self.target_frame,
                "pixel": {
                    "u": float(u),
                    "v": float(v),
                },
                "depth_m": float(depth_m),
                "depth_source": str(depth_source),
                "camera_point": {
                    "x": float(camera_xyz[0]),
                    "y": float(camera_xyz[1]),
                    "z": float(camera_xyz[2]),
                },
                "base_point": {
                    "x": float(target_xyz[0]),
                    "y": float(target_xyz[1]),
                    "z": float(target_xyz[2]),
                },
                "bbox": det,
                "scaled_bbox_depth_px": scaled_bbox,
            }

        except Exception as e:
            self.get_logger().warn(f"Failed to convert detection {idx}: {repr(e)}")
            self.add_skip("exception")
            return None

    def get_scaled_bbox(
        self,
        det: Dict[str, Any],
        payload_image_w: Optional[int],
        payload_image_h: Optional[int],
        depth_shape: Optional[Tuple[int, int]],
    ) -> Optional[Dict[str, float]]:
        if all(k in det for k in ["x1", "y1", "x2", "y2"]):
            x1, y1 = float(det["x1"]), float(det["y1"])
            x2, y2 = float(det["x2"]), float(det["y2"])
        elif "cx" in det and "cy" in det and "w" in det and "h" in det:
            cx, cy = float(det["cx"]), float(det["cy"])
            bw, bh = float(det["w"]), float(det["h"])
            x1, y1 = cx - bw / 2.0, cy - bh / 2.0
            x2, y2 = cx + bw / 2.0, cy + bh / 2.0
        else:
            return None

        if depth_shape is None:
            return None

        depth_h, depth_w = depth_shape

        sx = 1.0
        sy = 1.0
        if (
            self.auto_scale_bbox_to_depth
            and payload_image_w is not None
            and payload_image_h is not None
            and payload_image_w > 0
            and payload_image_h > 0
        ):
            if payload_image_w != depth_w or payload_image_h != depth_h:
                sx = float(depth_w) / float(payload_image_w)
                sy = float(depth_h) / float(payload_image_h)

        x1 *= sx
        x2 *= sx
        y1 *= sy
        y2 *= sy

        x1 = max(0.0, min(float(depth_w - 1), x1))
        x2 = max(0.0, min(float(depth_w - 1), x2))
        y1 = max(0.0, min(float(depth_h - 1), y1))
        y2 = max(0.0, min(float(depth_h - 1), y2))

        if x2 <= x1 or y2 <= y1:
            return None

        return {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "scale_x": sx,
            "scale_y": sy,
        }

    @staticmethod
    def get_bbox_center_from_scaled_bbox(bbox: Dict[str, float]) -> Tuple[float, float]:
        return (bbox["x1"] + bbox["x2"]) / 2.0, (bbox["y1"] + bbox["y2"]) / 2.0

    # ============================================================
    # Depth
    # ============================================================

    def depth_image_to_array(self, msg: Image) -> np.ndarray:
        encoding = msg.encoding.lower()
        h = int(msg.height)
        w = int(msg.width)
        step = int(msg.step)

        if encoding in ["16uc1", "mono16"]:
            dtype = np.uint16
            bpp = 2
        elif encoding in ["32fc1"]:
            dtype = np.float32
            bpp = 4
        else:
            raise ValueError(f"Unsupported depth encoding: {msg.encoding}")

        data = np.frombuffer(msg.data, dtype=dtype)
        expected_step = w * bpp

        if step == expected_step:
            depth = data.reshape((h, w))
        else:
            row_elems = step // bpp
            depth = data.reshape((h, row_elems))[:, :w]

        return depth

    def depth_to_meter(self, msg: Image, patch: np.ndarray) -> np.ndarray:
        if msg.encoding.lower() in ["16uc1", "mono16"]:
            return patch.astype(np.float32) * self.depth_scale
        return patch.astype(np.float32)

    def valid_depth_values(self, arr_m: np.ndarray) -> np.ndarray:
        valid = arr_m[
            np.isfinite(arr_m)
            & (arr_m > self.min_depth_m)
            & (arr_m < self.max_depth_m)
        ]
        return valid.astype(np.float32)

    def get_depth_for_detection(
        self,
        msg: Image,
        u: float,
        v: float,
        bbox: Dict[str, float],
    ) -> Tuple[Optional[float], str]:
        center_depth = self.get_depth_at_pixel(
            msg,
            u,
            v,
            self.depth_window_radius,
        )
        if center_depth is not None:
            return center_depth, "center_patch"

        if self.use_bbox_depth_fallback:
            bbox_depth = self.get_depth_in_bbox(msg, bbox)
            if bbox_depth is not None:
                return bbox_depth, "bbox_fallback"

        return None, "none"

    def get_depth_at_pixel(
        self,
        msg: Image,
        u: float,
        v: float,
        radius: int,
    ) -> Optional[float]:
        try:
            depth = self.depth_image_to_array(msg)
        except Exception as e:
            self.get_logger().error(f"Depth convert failed: {repr(e)}")
            return None

        h, w = depth.shape[:2]
        px = int(round(u))
        py = int(round(v))

        if px < 0 or px >= w or py < 0 or py >= h:
            self.get_logger().warn(
                f"Pixel out of depth range: u={u:.1f}, v={v:.1f}, depth_size={w}x{h}"
            )
            return None

        r = max(0, int(radius))
        x1 = max(0, px - r)
        x2 = min(w, px + r + 1)
        y1 = max(0, py - r)
        y2 = min(h, py + r + 1)

        patch_m = self.depth_to_meter(msg, depth[y1:y2, x1:x2])
        valid = self.valid_depth_values(patch_m)
        if valid.size == 0:
            return None

        return float(np.median(valid))

    def get_depth_in_bbox(
        self,
        msg: Image,
        bbox: Dict[str, float],
    ) -> Optional[float]:
        try:
            depth = self.depth_image_to_array(msg)
        except Exception as e:
            self.get_logger().error(f"Depth convert failed: {repr(e)}")
            return None

        h, w = depth.shape[:2]

        x1 = float(bbox["x1"])
        y1 = float(bbox["y1"])
        x2 = float(bbox["x2"])
        y2 = float(bbox["y2"])

        ratio = max(0.1, min(1.0, float(self.bbox_depth_inner_ratio)))
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        bw = (x2 - x1) * ratio
        bh = (y2 - y1) * ratio

        ix1 = int(max(0, round(cx - bw / 2.0)))
        ix2 = int(min(w, round(cx + bw / 2.0)))
        iy1 = int(max(0, round(cy - bh / 2.0)))
        iy2 = int(min(h, round(cy + bh / 2.0)))

        if ix2 <= ix1 or iy2 <= iy1:
            return None

        patch = depth[iy1:iy2, ix1:ix2]
        flat = patch.reshape(-1)

        if self.bbox_depth_max_samples > 0 and flat.size > self.bbox_depth_max_samples:
            step = int(math.ceil(flat.size / float(self.bbox_depth_max_samples)))
            flat = flat[::step]

        patch_m = self.depth_to_meter(msg, flat)
        valid = self.valid_depth_values(patch_m)
        if valid.size == 0:
            return None

        percentile = max(0.0, min(100.0, float(self.bbox_depth_percentile)))
        return float(np.percentile(valid, percentile))

    # ============================================================
    # Projection / TF
    # ============================================================

    def deproject_pixel_to_3d(
        self,
        u: float,
        v: float,
        depth_m: float,
        camera_info: CameraInfo,
    ) -> Optional[Tuple[float, float, float]]:
        k = camera_info.k
        fx = float(k[0])
        fy = float(k[4])
        cx = float(k[2])
        cy = float(k[5])

        if abs(fx) < 1e-9 or abs(fy) < 1e-9:
            self.get_logger().warn("Invalid camera intrinsics: fx/fy is zero.")
            return None

        z = float(depth_m)
        x = (float(u) - cx) * z / fx
        y = (float(v) - cy) * z / fy

        if not all(math.isfinite(a) for a in [x, y, z]):
            return None

        return x, y, z

    def transform_point_to_target(
        self,
        xyz: Tuple[float, float, float],
        source_frame: str,
        target_frame: str,
    ) -> Optional[Tuple[float, float, float]]:
        if source_frame == target_frame:
            return float(xyz[0]), float(xyz[1]), float(xyz[2])

        point = PointStamped()
        point.header.stamp = Time().to_msg()
        point.header.frame_id = source_frame
        point.point.x = float(xyz[0])
        point.point.y = float(xyz[1])
        point.point.z = float(xyz[2])

        try:
            tf = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                Time(),
                timeout=Duration(seconds=0.5),
            )
            transformed = do_transform_point(point, tf)
            return (
                float(transformed.point.x),
                float(transformed.point.y),
                float(transformed.point.z),
            )
        except Exception as e:
            self.get_logger().warn(
                f"TF transform failed: {source_frame} -> {target_frame}: {repr(e)}"
            )
            return None

    # ============================================================
    # JSON publish
    # ============================================================

    def publish_objects_json(
        self,
        objects_3d: List[Dict[str, Any]],
        source_payload: Dict[str, Any],
        skip_reasons: Dict[str, int],
    ):
        msg = String()
        msg.data = json.dumps(
            {
                "target_frame": self.target_frame,
                "count": len(objects_3d),
                "objects": objects_3d,
                "skip_reasons": skip_reasons,
                "source_count": int(
                    source_payload.get(
                        "count",
                        len(source_payload.get("bboxes", [])),
                    )
                ),
                "source_frame": self.get_source_camera_frame(),
            },
            ensure_ascii=False,
        )
        self.json_pub.publish(msg)

    # ============================================================
    # Marker publish
    # ============================================================

    def publish_delete_old_markers(self):
        marker_array = MarkerArray()
        now = self.get_clock().now().to_msg()

        for i in range(self.last_marker_count):
            for ns in ["grounding_dino_objects_cube", "grounding_dino_objects_text"]:
                marker = Marker()
                marker.header.frame_id = self.target_frame
                marker.header.stamp = now
                marker.ns = ns
                marker.id = i
                marker.action = Marker.DELETE
                marker_array.markers.append(marker)

        if marker_array.markers:
            self.marker_pub.publish(marker_array)

        self.last_marker_count = 0

    def publish_markers(self, objects_3d: List[Dict[str, Any]]):
        marker_array = MarkerArray()
        now = self.get_clock().now().to_msg()

        # 刪掉上一輪多餘 marker
        for i in range(len(objects_3d), self.last_marker_count):
            for ns in ["grounding_dino_objects_cube", "grounding_dino_objects_text"]:
                marker = Marker()
                marker.header.frame_id = self.target_frame
                marker.header.stamp = now
                marker.ns = ns
                marker.id = i
                marker.action = Marker.DELETE
                marker_array.markers.append(marker)

        for i, obj in enumerate(objects_3d):
            real_x = float(obj["base_point"]["x"])
            real_y = float(obj["base_point"]["y"])
            real_z = float(obj["base_point"]["z"])

            disp_x = real_x
            disp_y = real_y

            if self.flatten_to_2d:
                disp_z = self.marker_z
            else:
                disp_z = real_z

            cls = str(obj["class"])
            r, g, b = self.color_from_class(cls)

            cube = self.make_cube_marker(
                marker_id=i,
                x=disp_x,
                y=disp_y,
                z=disp_z,
                r=r,
                g=g,
                b=b,
            )
            marker_array.markers.append(cube)

            text = self.make_text_marker(
                marker_id=i,
                x=disp_x,
                y=disp_y,
                z=disp_z + self.text_z_offset,
                class_name=cls,
            )
            marker_array.markers.append(text)

        self.marker_pub.publish(marker_array)
        self.last_marker_count = len(objects_3d)

    def make_cube_marker(
        self,
        marker_id: int,
        x: float,
        y: float,
        z: float,
        r: float,
        g: float,
        b: float,
    ) -> Marker:
        marker = Marker()
        marker.header.frame_id = self.target_frame
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = "grounding_dino_objects_cube"
        marker.id = int(marker_id)
        marker.type = Marker.CUBE
        marker.action = Marker.ADD

        marker.pose.position.x = float(x)
        marker.pose.position.y = float(y)
        marker.pose.position.z = float(z)
        marker.pose.orientation.w = 1.0

        # 關鍵：x/y/z 一樣，變成立體方塊
        marker.scale.x = float(self.cube_size)
        marker.scale.y = float(self.cube_size)
        marker.scale.z = float(self.cube_size)

        marker.color.r = float(r)
        marker.color.g = float(g)
        marker.color.b = float(b)
        marker.color.a = float(self.cube_alpha)

        if self.marker_lifetime_s > 0.0:
            marker.lifetime = Duration(seconds=float(self.marker_lifetime_s)).to_msg()

        return marker

    def make_text_marker(
        self,
        marker_id: int,
        x: float,
        y: float,
        z: float,
        class_name: str,
    ) -> Marker:
        marker = Marker()
        marker.header.frame_id = self.target_frame
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = "grounding_dino_objects_text"
        marker.id = int(marker_id)
        marker.type = Marker.TEXT_VIEW_FACING
        marker.action = Marker.ADD

        marker.pose.position.x = float(x)
        marker.pose.position.y = float(y)
        marker.pose.position.z = float(z)
        marker.pose.orientation.w = 1.0

        marker.scale.z = float(self.text_scale)

        marker.color.r = 1.0
        marker.color.g = 1.0
        marker.color.b = 1.0
        marker.color.a = 1.0

        # 關鍵：只顯示名稱，不顯示 confidence / id / xyz
        marker.text = str(class_name)

        if self.marker_lifetime_s > 0.0:
            marker.lifetime = Duration(seconds=float(self.marker_lifetime_s)).to_msg()

        return marker

    @staticmethod
    def color_from_class(class_name: str) -> Tuple[float, float, float]:
        digest = hashlib.md5(str(class_name).encode("utf-8")).digest()

        # 避免顏色太暗
        r = (digest[0] / 255.0) * 0.75 + 0.25
        g = (digest[1] / 255.0) * 0.75 + 0.25
        b = (digest[2] / 255.0) * 0.75 + 0.25

        return float(r), float(g), float(b)


def main(args=None):
    rclpy.init(args=args)
    node = BBoxAll3DCubeMarkerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()