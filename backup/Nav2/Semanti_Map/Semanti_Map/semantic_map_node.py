#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Semantic Map Node — SLAM / map frame 投影層

推薦架構：
  GroundingDINO / vision_package 只發布 2D bbox:
    /grounding_dino/bboxes

  Semanti_Map 負責：
    bbox + depth + camera_info + TF
    轉成 SLAM map frame 的 3D detection
    發布給 map_integrator_node.py

訂閱:
  - /grounding_dino/bboxes        std_msgs/String, JSON
  - /realsense/depth              sensor_msgs/Image
  - /realsense/camera_info        sensor_msgs/CameraInfo

發布:
  - /semantic_map/raw_detections  std_msgs/String, JSON

輸出 JSON 格式:
{
  "frame_id": "map",
  "detections": [
    {
      "class": "bottle",
      "score": 0.9,
      "position": {"x": 1.0, "y": 2.0, "z": 0.5},
      "pixel": {"u": 320.0, "v": 240.0},
      "depth_m": 1.25,
      "source_frame": "camera_color_optical_frame"
    }
  ]
}
"""

from __future__ import annotations

import json
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from std_msgs.msg import String
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PointStamped

import tf2_ros
from tf2_geometry_msgs import do_transform_point


class SemanticMapNode(Node):
    def __init__(self):
        super().__init__("semantic_map_node")

        # ---------- Topics ----------
        self.declare_parameter("detection_topic", "/grounding_dino/bboxes")
        self.declare_parameter("depth_topic", "/realsense/depth")
        self.declare_parameter("camera_info_topic", "/realsense/camera_info")
        self.declare_parameter("raw_detections_topic", "/semantic_map/raw_detections")

        # ---------- Frames ----------
        # camera_frame_override 空字串時，自動使用 CameraInfo.header.frame_id 或 Depth.header.frame_id
        self.declare_parameter("camera_frame_override", "")
        self.declare_parameter("map_frame", "map")

        # ---------- Filters ----------
        self.declare_parameter("min_confidence", 0.35)
        self.declare_parameter("depth_scale", 0.001)  # 16UC1 mm -> meter
        self.declare_parameter("depth_window_radius", 5)
        self.declare_parameter("min_depth_m", 0.05)
        self.declare_parameter("max_depth_m", 10.0)
        self.declare_parameter("max_objects", 100)

        self.detection_topic = str(self.get_parameter("detection_topic").value)
        self.depth_topic = str(self.get_parameter("depth_topic").value)
        self.camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        self.raw_detections_topic = str(self.get_parameter("raw_detections_topic").value)

        self.camera_frame_override = str(self.get_parameter("camera_frame_override").value)
        self.map_frame = str(self.get_parameter("map_frame").value)

        self.min_confidence = float(self.get_parameter("min_confidence").value)
        self.depth_scale = float(self.get_parameter("depth_scale").value)
        self.depth_window_radius = int(self.get_parameter("depth_window_radius").value)
        self.min_depth_m = float(self.get_parameter("min_depth_m").value)
        self.max_depth_m = float(self.get_parameter("max_depth_m").value)
        self.max_objects = int(self.get_parameter("max_objects").value)

        self._lock = Lock()
        self._depth_msg: Optional[Image] = None
        self._camera_info: Optional[CameraInfo] = None

        # ---------- TF ----------
        self.tf_buffer = tf2_ros.Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )

        normal_qos = QoSProfile(depth=10)

        self.create_subscription(
            Image,
            self.depth_topic,
            self._depth_callback,
            sensor_qos,
        )

        self.create_subscription(
            CameraInfo,
            self.camera_info_topic,
            self._info_callback,
            sensor_qos,
        )

        self.create_subscription(
            String,
            self.detection_topic,
            self._det_callback,
            normal_qos,
        )

        self.raw_pub = self.create_publisher(
            String,
            self.raw_detections_topic,
            10,
        )

        self.get_logger().info("SemanticMapNode ready. GroundingDINO bbox -> SLAM map frame.")
        self.get_logger().info(f"detection_topic       : {self.detection_topic}")
        self.get_logger().info(f"depth_topic           : {self.depth_topic}")
        self.get_logger().info(f"camera_info_topic     : {self.camera_info_topic}")
        self.get_logger().info(f"raw_detections_topic  : {self.raw_detections_topic}")
        self.get_logger().info(f"map_frame             : {self.map_frame}")
        self.get_logger().info(f"camera_frame_override : {self.camera_frame_override}")

    # ------------------------------------------------------------------
    # Cache sensor data
    # ------------------------------------------------------------------
    def _depth_callback(self, msg: Image):
        with self._lock:
            self._depth_msg = msg

    def _info_callback(self, msg: CameraInfo):
        with self._lock:
            self._camera_info = msg

    # ------------------------------------------------------------------
    # Main detection callback
    # ------------------------------------------------------------------
    def _det_callback(self, msg: String):
        with self._lock:
            depth_msg = self._depth_msg
            camera_info = self._camera_info

        if depth_msg is None:
            self.get_logger().warn("尚未收到 depth image", throttle_duration_sec=2.0)
            return

        if camera_info is None:
            self.get_logger().warn("尚未收到 camera_info", throttle_duration_sec=2.0)
            return

        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().warn(f"無法解析 bbox JSON: {e}")
            return

        detections_in = self._extract_detection_list(payload)
        if not detections_in:
            return

        if self.max_objects > 0:
            detections_in = detections_in[: self.max_objects]

        source_frame = self._get_source_camera_frame(depth_msg, camera_info)
        if not source_frame:
            self.get_logger().warn(
                "無法決定 camera frame，請設定 camera_frame_override 或確認 CameraInfo.header.frame_id"
            )
            return

        raw_results: List[Dict[str, Any]] = []

        for det in detections_in:
            converted = self._convert_detection_to_map(
                det,
                depth_msg,
                camera_info,
                source_frame,
            )
            if converted is not None:
                raw_results.append(converted)

        if not raw_results:
            return

        out = String()
        out.data = json.dumps(
            {
                "frame_id": self.map_frame,
                "detections": raw_results,
            },
            ensure_ascii=False,
        )
        self.raw_pub.publish(out)

        self.get_logger().info(
            f"Published {len(raw_results)}/{len(detections_in)} semantic detections in {self.map_frame}",
            throttle_duration_sec=1.0,
        )

    def _extract_detection_list(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        支援兩種格式：

        1. GroundingDINO bbox:
        {
          "bboxes": [
            {
              "class": "bottle",
              "score": 0.9,
              "x1": 100,
              "y1": 120,
              "x2": 300,
              "y2": 400
            }
          ]
        }

        2. detection center:
        {
          "detections": [
            {
              "class": "bottle",
              "score": 0.9,
              "center": {"x": 320, "y": 240}
            }
          ]
        }
        """
        if isinstance(payload.get("bboxes"), list):
            return payload["bboxes"]

        if isinstance(payload.get("detections"), list):
            return payload["detections"]

        return []

    def _convert_detection_to_map(
        self,
        det: Dict[str, Any],
        depth_msg: Image,
        camera_info: CameraInfo,
        source_frame: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            score = float(det.get("score", det.get("confidence", 0.0)))
            if score < self.min_confidence:
                return None

            class_name = str(det.get("class", det.get("label", "unknown")))

            uv = self._get_detection_center(det)
            if uv is None:
                return None

            u, v = uv

            depth_m = self._get_depth_at_pixel(depth_msg, u, v)
            if depth_m is None:
                return None

            cam_xyz = self._deproject_pixel_to_3d(
                u,
                v,
                depth_m,
                camera_info,
            )
            if cam_xyz is None:
                return None

            map_xyz = self._transform_point(
                cam_xyz,
                source_frame,
                self.map_frame,
            )
            if map_xyz is None:
                return None

            return {
                "class": class_name,
                "score": score,
                "position": {
                    "x": float(map_xyz[0]),
                    "y": float(map_xyz[1]),
                    "z": float(map_xyz[2]),
                },
                "pixel": {
                    "u": float(u),
                    "v": float(v),
                },
                "depth_m": float(depth_m),
                "source_frame": source_frame,
            }

        except Exception as e:
            self.get_logger().warn(f"轉換 detection 失敗: {repr(e)}")
            return None

    def _get_detection_center(self, det: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        # 格式 1: cx/cy
        if "cx" in det and "cy" in det:
            return float(det["cx"]), float(det["cy"])

        # 格式 2: x1/y1/x2/y2
        if all(k in det for k in ["x1", "y1", "x2", "y2"]):
            u = (float(det["x1"]) + float(det["x2"])) / 2.0
            v = (float(det["y1"]) + float(det["y2"])) / 2.0
            return u, v

        # 格式 3: center: {x, y}
        center = det.get("center")
        if isinstance(center, dict) and "x" in center and "y" in center:
            return float(center["x"]), float(center["y"])

        return None

    def _get_source_camera_frame(self, depth_msg: Image, camera_info: CameraInfo) -> str:
        if self.camera_frame_override:
            return self.camera_frame_override

        if camera_info.header.frame_id:
            return str(camera_info.header.frame_id)

        if depth_msg.header.frame_id:
            return str(depth_msg.header.frame_id)

        return ""

    # ------------------------------------------------------------------
    # Depth / Camera projection
    # ------------------------------------------------------------------
    def _depth_image_to_array(self, msg: Image) -> np.ndarray:
        encoding = msg.encoding.lower()
        h = int(msg.height)
        w = int(msg.width)
        step = int(msg.step)

        if encoding in ["16uc1", "16uc", "mono16"]:
            dtype = np.uint16
            bytes_per_pixel = 2
        elif encoding in ["32fc1", "32fc"]:
            dtype = np.float32
            bytes_per_pixel = 4
        else:
            raise ValueError(f"Unsupported depth encoding: {msg.encoding}")

        data = np.frombuffer(msg.data, dtype=dtype)

        expected_step = w * bytes_per_pixel
        if step == expected_step:
            depth = data.reshape((h, w))
        else:
            row_elems = step // bytes_per_pixel
            depth = data.reshape((h, row_elems))[:, :w]

        return depth

    def _get_depth_at_pixel(self, msg: Image, u: float, v: float) -> Optional[float]:
        try:
            depth = self._depth_image_to_array(msg)
        except Exception as e:
            self.get_logger().warn(f"depth 轉換失敗: {repr(e)}")
            return None

        h, w = depth.shape[:2]

        px = int(round(u))
        py = int(round(v))

        if px < 0 or px >= w or py < 0 or py >= h:
            return None

        r = max(0, self.depth_window_radius)

        x1 = max(0, px - r)
        x2 = min(w, px + r + 1)
        y1 = max(0, py - r)
        y2 = min(h, py + r + 1)

        patch = depth[y1:y2, x1:x2]

        enc = msg.encoding.lower()
        if enc in ["16uc1", "16uc", "mono16"]:
            patch_m = patch.astype(np.float32) * self.depth_scale
        else:
            patch_m = patch.astype(np.float32)

        valid = patch_m[
            np.isfinite(patch_m)
            & (patch_m > self.min_depth_m)
            & (patch_m < self.max_depth_m)
        ]

        if valid.size == 0:
            return None

        return float(np.median(valid))

    def _deproject_pixel_to_3d(
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

        if fx == 0.0 or fy == 0.0:
            self.get_logger().warn("CameraInfo 內參錯誤：fx/fy = 0")
            return None

        z = float(depth_m)
        x = (float(u) - cx) * z / fx
        y = (float(v) - cy) * z / fy

        return x, y, z

    def _transform_point(
        self,
        xyz: Tuple[float, float, float],
        source_frame: str,
        target_frame: str,
    ) -> Optional[Tuple[float, float, float]]:
        pt = PointStamped()
        pt.header.stamp = rclpy.time.Time().to_msg()
        pt.header.frame_id = source_frame
        pt.point.x = float(xyz[0])
        pt.point.y = float(xyz[1])
        pt.point.z = float(xyz[2])

        try:
            tf = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.3),
            )

            out = do_transform_point(pt, tf)

            return (
                float(out.point.x),
                float(out.point.y),
                float(out.point.z),
            )

        except tf2_ros.LookupException as e:
            self.get_logger().warn(
                f"TF 查詢失敗: {source_frame} -> {target_frame}: {e}",
                throttle_duration_sec=2.0,
            )

        except tf2_ros.ConnectivityException as e:
            self.get_logger().warn(
                f"TF 不連通: {source_frame} -> {target_frame}: {e}",
                throttle_duration_sec=2.0,
            )

        except tf2_ros.ExtrapolationException as e:
            self.get_logger().warn(
                f"TF 時間外推失敗: {source_frame} -> {target_frame}: {e}",
                throttle_duration_sec=2.0,
            )

        except Exception as e:
            self.get_logger().warn(
                f"TF transform failed: {source_frame} -> {target_frame}: {repr(e)}",
                throttle_duration_sec=2.0,
            )

        return None


def main(args=None):
    rclpy.init(args=args)
    node = SemanticMapNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()