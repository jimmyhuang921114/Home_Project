#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
grounding_dino_node.py

真正的 GroundingDINO 偵測 node。

重點：
1. 這支位於 vision_package/vision_package/grounding_dino_node.py

2. 它會提供 service：
   /grounding_dino/detect_once

3. 它會輸出 raw bbox：
   /grounding_dino/bboxes_raw

4. 後面再接 bbox_filter_fusion_node.py：
   /grounding_dino/bboxes_raw -> /grounding_dino/bboxes

架構：
/realsense/rgb + /ram/tags
  -> /grounding_dino/detect_once 觸發
  -> full image + tile inference
  -> basic NMS + multi-frame merge
  -> /grounding_dino/bboxes_raw
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np
import torch
from PIL import Image as PILImage

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_srvs.srv import Trigger

from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor


@dataclass
class FrameItem:
    bgr: np.ndarray
    frame_id: str
    stamp_sec: int
    stamp_nanosec: int
    receive_time: float


def normalize_tag(tag: Any) -> str:
    tag = str(tag).lower().strip()
    tag = tag.replace("_", " ")
    tag = re.sub(r"\s+", " ", tag)
    tag = tag.strip(" .,:;[](){}\"'")
    tag = re.sub(r"^(a|an|the)\s+", "", tag)
    return tag.strip()


def split_tags(text: str) -> List[str]:
    text = str(text).strip()
    if not text:
        return []

    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and "tags" in payload:
            raw_items = payload["tags"]
        elif isinstance(payload, list):
            raw_items = payload
        else:
            raw_items = []
    except Exception:
        text = text.replace("|", ",").replace(";", ",")
        raw_items = text.split(",")

    tags: List[str] = []
    used: Set[str] = set()
    for item in raw_items:
        tag = normalize_tag(item)
        if not tag or tag in used:
            continue
        used.add(tag)
        tags.append(tag)
    return tags


def split_prompt_text(text: str) -> List[str]:
    # GroundingDINO prompt usually uses "class . class ." format.
    # This helper lets us merge default_prompt with RAM tags without duplicates.
    raw_items = re.split(r"[.,;|]+", str(text))
    tags: List[str] = []
    used: Set[str] = set()
    for item in raw_items:
        tag = normalize_tag(item)
        if not tag or tag in used:
            continue
        used.add(tag)
        tags.append(tag)
    return tags


def build_prompt(tags: List[str]) -> str:
    clean: List[str] = []
    used: Set[str] = set()
    for tag in tags:
        tag = normalize_tag(tag)
        if not tag or tag in used:
            continue
        used.add(tag)
        clean.append(tag)
    if not clean:
        return ""
    return " . ".join(clean) + " ."


def bbox_area(det: Dict[str, Any]) -> float:
    return max(0.0, float(det["x2"]) - float(det["x1"])) * max(
        0.0, float(det["y2"]) - float(det["y1"])
    )


def bbox_intersection(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ix1 = max(float(a["x1"]), float(b["x1"]))
    iy1 = max(float(a["y1"]), float(b["y1"]))
    ix2 = min(float(a["x2"]), float(b["x2"]))
    iy2 = min(float(a["y2"]), float(b["y2"]))
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def bbox_iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    inter = bbox_intersection(a, b)
    union = bbox_area(a) + bbox_area(b) - inter
    if union <= 1e-6:
        return 0.0
    return float(inter / union)


def bbox_ios(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    inter = bbox_intersection(a, b)
    small = min(bbox_area(a), bbox_area(b))
    if small <= 1e-6:
        return 0.0
    return float(inter / small)


def same_class(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return str(a.get("class", "")) == str(b.get("class", ""))


def get_bbox_color(index: int) -> Tuple[int, int, int]:
    # OpenCV BGR
    palette = [
        (0, 255, 0),
        (0, 0, 255),
        (255, 0, 0),
        (0, 255, 255),
        (255, 0, 255),
        (255, 255, 0),
        (0, 128, 255),
        (255, 128, 0),
        (128, 0, 255),
        (0, 255, 128),
        (128, 255, 0),
        (255, 0, 128),
        (128, 128, 255),
        (128, 255, 255),
        (255, 128, 128),
    ]
    return palette[index % len(palette)]


class HFGroundingDINOMultiFrameTiledNode(Node):
    def __init__(self):
        super().__init__("grounding_dino_node")

        # Topics
        self.declare_parameter("image_topic", "/realsense/rgb")
        self.declare_parameter("ram_tags_topic", "/ram/tags")
        self.declare_parameter("bboxes_topic", "/grounding_dino/bboxes_raw")
        self.declare_parameter("debug_image_topic", "/grounding_dino/debug_image")
        self.declare_parameter("done_topic", "/grounding_dino/detect_done")

        # Service
        self.declare_parameter("trigger_service", "/grounding_dino/detect_once")
        self.declare_parameter("done_service_name", "")

        # Optional RAM trigger. In waypoint mode, RAM should not run continuously.
        # GroundingDINO can call /ram/run_once at the beginning of detect_once and
        # wait briefly for fresh tags before running open-vocabulary detection.
        self.declare_parameter("trigger_ram_before_detection", True)
        self.declare_parameter("ram_trigger_service", "/ram/run_once")
        self.declare_parameter("ram_wait_timeout_s", 4.0)

        # Hugging Face model
        self.declare_parameter("hf_model_name", "IDEA-Research/grounding-dino-tiny")
        self.declare_parameter("device", "cuda")

        # Prompt
        self.declare_parameter("use_ram_tags", True)
        self.declare_parameter(
            "default_prompt",
            "chair . table . desk . counter . kitchen counter . cabinet . door . sink . hood . exhaust hood . sofa . bottle . cup . mug . bowl . box . book . monitor . tv . laptop . keyboard . mouse . trash can . refrigerator . microwave . oven . drawer . shelf . plant .",
        )
        self.declare_parameter("max_ram_tags", 60)
        self.declare_parameter("min_ram_tags", 1)
        self.declare_parameter("ram_tags_timeout_s", 8.0)
        self.declare_parameter(
            "ignore_tags",
            "indoor,outdoor,wall,floor,ceiling,room,scene,image,photo,picture,"
            "background,light,lighting,wood,metal,plastic,black,white,red,blue,"
            "green,yellow,gray,grey,color,modern",
        )

        # Prompt memory / high recall mode
        # Keep recent RAM tags and merge them with the default prompt. This increases recall
        # and avoids losing default classes when RAM misses one frame.
        self.declare_parameter("use_ram_tag_memory", True)
        self.declare_parameter("ram_tag_memory_s", 12.0)
        self.declare_parameter("always_include_default_prompt", False)
        self.declare_parameter("max_prompt_tags", 60)

        # Detection threshold
        self.declare_parameter("threshold", 0.16)
        self.declare_parameter("box_threshold", 0.16)
        self.declare_parameter("text_threshold", 0.14)

        # Multi-frame
        self.declare_parameter("multi_frame_count", 3)
        self.declare_parameter("min_frame_votes", 1)
        self.declare_parameter("frame_collect_timeout_s", 4.0)
        self.declare_parameter("allow_partial_frames", True)
        self.declare_parameter("use_latest_image_on_trigger", True)
        self.declare_parameter("min_period_s", 0.10)

        # Tiling
        self.declare_parameter("use_tiled_inference", True)
        self.declare_parameter("include_full_image", True)
        self.declare_parameter("tile_rows", 2)
        self.declare_parameter("tile_cols", 2)
        self.declare_parameter("tile_overlap_ratio", 0.08)
        self.declare_parameter("min_tile_size", 64)
        # Full image first; only run 2x2 tiles when full image finds too few boxes.
        self.declare_parameter("auto_tile_if_few_detections", True)
        self.declare_parameter("auto_tile_min_full_detections", 10)

        # Basic merge
        self.declare_parameter("nms_iou_threshold", 0.62)
        self.declare_parameter("nms_containment_threshold", 0.96)
        self.declare_parameter("merge_iou_threshold", 0.60)
        self.declare_parameter("merge_containment_threshold", 0.95)
        self.declare_parameter("same_class_only", True)
        self.declare_parameter("min_final_score", 0.0)

        # Limits
        self.declare_parameter("max_detections_per_region", 150)
        self.declare_parameter("max_final_detections", 250)

        # Publish
        self.declare_parameter("publish_empty", True)
        self.declare_parameter("publish_debug_image", True)
        self.declare_parameter("draw_tile_grid", False)

        # Read params
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.ram_tags_topic = str(self.get_parameter("ram_tags_topic").value)
        self.bboxes_topic = str(self.get_parameter("bboxes_topic").value)
        self.debug_image_topic = str(self.get_parameter("debug_image_topic").value)
        self.done_topic = str(self.get_parameter("done_topic").value)

        self.trigger_service = str(self.get_parameter("trigger_service").value)
        self.done_service_name = str(self.get_parameter("done_service_name").value).strip()
        self.trigger_ram_before_detection = bool(self.get_parameter("trigger_ram_before_detection").value)
        self.ram_trigger_service = str(self.get_parameter("ram_trigger_service").value).strip()
        self.ram_wait_timeout_s = float(self.get_parameter("ram_wait_timeout_s").value)

        self.hf_model_name = str(self.get_parameter("hf_model_name").value)

        requested_device = str(self.get_parameter("device").value).lower().strip()
        if requested_device == "cuda" and torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        self.use_ram_tags = bool(self.get_parameter("use_ram_tags").value)
        self.default_prompt = str(self.get_parameter("default_prompt").value)
        self.max_ram_tags = int(self.get_parameter("max_ram_tags").value)
        self.min_ram_tags = int(self.get_parameter("min_ram_tags").value)
        self.ram_tags_timeout_s = float(self.get_parameter("ram_tags_timeout_s").value)

        ignore_tags_text = str(self.get_parameter("ignore_tags").value)
        self.ignore_tags = set(
            normalize_tag(x)
            for x in ignore_tags_text.split(",")
            if normalize_tag(x)
        )

        self.use_ram_tag_memory = bool(self.get_parameter("use_ram_tag_memory").value)
        self.ram_tag_memory_s = float(self.get_parameter("ram_tag_memory_s").value)
        self.always_include_default_prompt = bool(self.get_parameter("always_include_default_prompt").value)
        self.max_prompt_tags = int(self.get_parameter("max_prompt_tags").value)

        self.threshold = float(self.get_parameter("threshold").value)
        self.box_threshold = float(self.get_parameter("box_threshold").value)
        self.text_threshold = float(self.get_parameter("text_threshold").value)

        self.multi_frame_count = max(1, int(self.get_parameter("multi_frame_count").value))
        self.min_frame_votes = max(1, int(self.get_parameter("min_frame_votes").value))
        self.frame_collect_timeout_s = float(self.get_parameter("frame_collect_timeout_s").value)
        self.allow_partial_frames = bool(self.get_parameter("allow_partial_frames").value)
        self.use_latest_image_on_trigger = bool(self.get_parameter("use_latest_image_on_trigger").value)
        self.min_period_s = float(self.get_parameter("min_period_s").value)

        self.use_tiled_inference = bool(self.get_parameter("use_tiled_inference").value)
        self.include_full_image = bool(self.get_parameter("include_full_image").value)
        self.tile_rows = max(1, int(self.get_parameter("tile_rows").value))
        self.tile_cols = max(1, int(self.get_parameter("tile_cols").value))
        self.tile_overlap_ratio = max(0.0, float(self.get_parameter("tile_overlap_ratio").value))
        self.min_tile_size = max(16, int(self.get_parameter("min_tile_size").value))
        self.auto_tile_if_few_detections = bool(self.get_parameter("auto_tile_if_few_detections").value)
        self.auto_tile_min_full_detections = max(0, int(self.get_parameter("auto_tile_min_full_detections").value))

        self.nms_iou_threshold = float(self.get_parameter("nms_iou_threshold").value)
        self.nms_containment_threshold = float(self.get_parameter("nms_containment_threshold").value)
        self.merge_iou_threshold = float(self.get_parameter("merge_iou_threshold").value)
        self.merge_containment_threshold = float(self.get_parameter("merge_containment_threshold").value)
        self.same_class_only = bool(self.get_parameter("same_class_only").value)
        self.min_final_score = float(self.get_parameter("min_final_score").value)

        self.max_detections_per_region = int(self.get_parameter("max_detections_per_region").value)
        self.max_final_detections = int(self.get_parameter("max_final_detections").value)

        self.publish_empty = bool(self.get_parameter("publish_empty").value)
        self.publish_debug_image = bool(self.get_parameter("publish_debug_image").value)
        self.draw_tile_grid_enabled = bool(self.get_parameter("draw_tile_grid").value)

        # Runtime state
        self.processor = None
        self.model = None

        self.last_ram_tags: List[str] = []
        self.last_ram_time = 0.0
        self.ram_tag_history: List[Tuple[float, List[str]]] = []

        self.latest_frame: Optional[FrameItem] = None
        self.collected_frames: List[FrameItem] = []
        self.is_active = False
        self.is_processing = False
        self.active_started_time = 0.0
        self.last_capture_time = 0.0
        self.request_id = 0
        self.ram_trigger_client = None
        self.ram_trigger_future = None
        self.ram_trigger_waiting = False
        self.ram_trigger_start_time = 0.0

        self.get_logger().info("Initializing HF GroundingDINO detector node...")
        self.get_logger().info(f"image_topic              : {self.image_topic}")
        self.get_logger().info(f"ram_tags_topic           : {self.ram_tags_topic}")
        self.get_logger().info(f"bboxes_topic             : {self.bboxes_topic}")
        self.get_logger().info(f"debug_image_topic        : {self.debug_image_topic}")
        self.get_logger().info(f"done_topic               : {self.done_topic}")
        self.get_logger().info(f"trigger_service          : {self.trigger_service}")
        self.get_logger().info(f"trigger_ram_before_det   : {self.trigger_ram_before_detection}")
        self.get_logger().info(f"ram_trigger_service      : {self.ram_trigger_service}")
        self.get_logger().info(f"hf_model_name            : {self.hf_model_name}")
        self.get_logger().info(f"device                   : {self.device}")
        self.get_logger().info(f"use_ram_tags             : {self.use_ram_tags}")
        self.get_logger().info(f"default_prompt           : {self.default_prompt}")
        self.get_logger().info(f"multi_frame_count        : {self.multi_frame_count}")
        self.get_logger().info(f"min_frame_votes          : {self.min_frame_votes}")
        self.get_logger().info(f"use_tiled_inference      : {self.use_tiled_inference}")
        self.get_logger().info(f"include_full_image       : {self.include_full_image}")
        self.get_logger().info(f"tile_rows x tile_cols    : {self.tile_rows} x {self.tile_cols}")
        self.get_logger().info(f"auto_tile_if_few_dets    : {self.auto_tile_if_few_detections}")
        self.get_logger().info(f"auto_tile_min_full_dets  : {self.auto_tile_min_full_detections}")
        self.get_logger().info(f"always_include_default   : {self.always_include_default_prompt}")
        self.get_logger().info(f"max_prompt_tags          : {self.max_prompt_tags}")

        self.load_model()

        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
        )
        normal_qos = QoSProfile(depth=10)

        self.image_sub = self.create_subscription(
            Image,
            self.image_topic,
            self.image_callback,
            sensor_qos,
        )

        self.ram_tags_sub = self.create_subscription(
            String,
            self.ram_tags_topic,
            self.ram_tags_callback,
            normal_qos,
        )

        self.bboxes_pub = self.create_publisher(String, self.bboxes_topic, 10)
        self.debug_image_pub = self.create_publisher(Image, self.debug_image_topic, 10)
        self.done_pub = self.create_publisher(String, self.done_topic, 10)

        self.trigger_srv = self.create_service(
            Trigger,
            self.trigger_service,
            self.detect_once_callback,
        )

        self.done_client = None
        if self.done_service_name:
            self.done_client = self.create_client(Trigger, self.done_service_name)

        if self.trigger_ram_before_detection and self.ram_trigger_service:
            self.ram_trigger_client = self.create_client(Trigger, self.ram_trigger_service)

        self.timer = self.create_timer(0.2, self.timer_callback)

        self.get_logger().info("HF GroundingDINO detector node ready.")
        self.get_logger().info(f"Trigger service ready: {self.trigger_service}")

    def load_model(self):
        self.get_logger().info("Loading Hugging Face GroundingDINO model...")
        self.processor = AutoProcessor.from_pretrained(self.hf_model_name, local_files_only=True)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            self.hf_model_name
        ).to(self.device)
        self.model.eval()

        if self.device == "cuda":
            torch.backends.cudnn.benchmark = True

        self.get_logger().info("HF GroundingDINO model loaded.")

    # ============================================================
    # ROS callbacks
    # ============================================================

    def detect_once_callback(self, request: Trigger.Request, response: Trigger.Response):
        if self.is_active or self.is_processing:
            response.success = False
            response.message = (
                f"Detection is already running. active={self.is_active}, "
                f"processing={self.is_processing}"
            )
            return response

        self.request_id += 1
        self.collected_frames = []
        self.is_active = True
        self.is_processing = False
        self.active_started_time = time.time()
        self.last_capture_time = 0.0
        self._trigger_ram_once_if_enabled()

        if self.use_latest_image_on_trigger and self.latest_frame is not None:
            self.collected_frames.append(self.latest_frame)
            self.last_capture_time = self.latest_frame.receive_time
            self.get_logger().info(
                f"Use latest image as first frame. "
                f"frames={len(self.collected_frames)}/{self.multi_frame_count}"
            )

        response.success = True
        response.message = (
            f"Started detection request_id={self.request_id}, "
            f"target_frames={self.multi_frame_count}"
        )
        self.get_logger().info(response.message)
        return response

    def timer_callback(self):
        if not self.is_active or self.is_processing:
            return

        elapsed = time.time() - self.active_started_time

        if len(self.collected_frames) >= self.multi_frame_count:
            if self._should_wait_for_ram():
                return
            self.start_processing_collected_frames("frame_count_reached")
            return

        if elapsed >= self.frame_collect_timeout_s:
            if self.allow_partial_frames and len(self.collected_frames) > 0:
                if self._should_wait_for_ram():
                    return
                self.get_logger().warn(
                    f"Frame collection timeout. Use partial frames: "
                    f"{len(self.collected_frames)}/{self.multi_frame_count}"
                )
                self.start_processing_collected_frames("timeout_partial")
            else:
                self.finish_detection_failed(
                    f"Frame collection timeout. No frames: "
                    f"{len(self.collected_frames)}/{self.multi_frame_count}"
                )

    def image_callback(self, msg: Image):
        try:
            bgr = self.ros_image_to_cv2(msg)
        except Exception as e:
            self.get_logger().error(f"Image convert failed: {repr(e)}")
            return

        frame = FrameItem(
            bgr=bgr,
            frame_id=str(msg.header.frame_id),
            stamp_sec=int(msg.header.stamp.sec),
            stamp_nanosec=int(msg.header.stamp.nanosec),
            receive_time=time.time(),
        )
        self.latest_frame = frame

        if not self.is_active or self.is_processing:
            return

        now = time.time()
        if now - self.last_capture_time < self.min_period_s:
            return

        if len(self.collected_frames) >= self.multi_frame_count:
            return

        self.collected_frames.append(frame)
        self.last_capture_time = now

        self.get_logger().info(
            f"Collected frame {len(self.collected_frames)}/{self.multi_frame_count}"
        )

        if len(self.collected_frames) >= self.multi_frame_count:
            if not self._should_wait_for_ram():
                self.start_processing_collected_frames("frame_count_reached")

    def ram_tags_callback(self, msg: String):
        tags = split_tags(msg.data)
        self._update_ram_tags(tags, source="topic")

    def _update_ram_tags(self, tags: List[str], source: str = "topic"):
        filtered: List[str] = []
        used: Set[str] = set()
        for tag in tags:
            tag = normalize_tag(tag)
            if not tag or tag in self.ignore_tags or tag in used:
                continue
            used.add(tag)
            filtered.append(tag)

        if self.max_ram_tags > 0:
            filtered = filtered[: self.max_ram_tags]

        now = time.time()
        self.last_ram_tags = filtered
        self.last_ram_time = now
        self.ram_tag_history.append((now, list(filtered)))
        self.ram_tag_history = [
            (t, ts) for (t, ts) in self.ram_tag_history
            if now - t <= self.ram_tag_memory_s
        ]

        prompt = build_prompt(filtered)
        self.get_logger().info(f"RAM tags received from {source} ({len(filtered)}): {filtered}")
        self.get_logger().info(
            f"GroundingDINO prompt from RAM: {prompt if prompt else '[empty]'}"
        )

    def _trigger_ram_once_if_enabled(self):
        self.ram_trigger_future = None
        self.ram_trigger_waiting = False
        self.ram_trigger_start_time = 0.0

        if not self.trigger_ram_before_detection:
            return
        if self.ram_trigger_client is None:
            self.get_logger().warn("RAM trigger client is not initialized.")
            return
        if not self.ram_trigger_client.service_is_ready():
            # Do not block the robot forever. If RAM service is not ready, we fall back
            # to fresh existing tags or default prompt.
            self.get_logger().warn(
                f"RAM trigger service not ready: {self.ram_trigger_service}. "
                "Detection will use fresh existing RAM tags or default prompt."
            )
            return

        req = Trigger.Request()
        self.ram_trigger_start_time = time.time()
        self.ram_trigger_waiting = True
        future = self.ram_trigger_client.call_async(req)
        self.ram_trigger_future = future
        future.add_done_callback(self._ram_trigger_done_callback)
        self.get_logger().info(f"Triggered RAM once: {self.ram_trigger_service}")

    def _ram_trigger_done_callback(self, future):
        try:
            result = future.result()
            if result is None:
                self.get_logger().warn("RAM trigger returned no result.")
                return

            if result.success:
                try:
                    payload = json.loads(str(result.message))
                    tags = payload.get("tags", []) if isinstance(payload, dict) else []
                    if isinstance(tags, list):
                        self._update_ram_tags(tags, source="service")
                except Exception:
                    pass
                self.get_logger().info(f"RAM trigger done: {result.message}")
            else:
                self.get_logger().warn(f"RAM trigger failed: {result.message}")
        except Exception as e:
            self.get_logger().warn(f"RAM trigger exception: {repr(e)}")
        finally:
            self.ram_trigger_waiting = False

    def _should_wait_for_ram(self) -> bool:
        if not self.ram_trigger_waiting:
            return False

        elapsed = time.time() - self.ram_trigger_start_time
        if elapsed < self.ram_wait_timeout_s:
            return True

        self.ram_trigger_waiting = False
        self.get_logger().warn(
            f"RAM trigger wait timeout after {elapsed:.2f}s. "
            "Use fresh existing RAM tags or default prompt."
        )
        return False

    # ============================================================
    # Pipeline
    # ============================================================

    def get_current_prompt(self) -> str:
        """Build prompt with RAM-first fallback behavior.

        Default behavior in this v2 module:
          1. If RAM is fresh and has at least min_ram_tags, use RAM prompt.
          2. If RAM is stale or too few tags, fall back to default_prompt.
          3. If always_include_default_prompt=True, merge default_prompt after RAM tags.

        This matches:
          RAM fresh 且 tags 數量夠 -> 用 RAM prompt
          RAM 不新鮮或太少 -> 用 default_prompt
        """
        if not self.use_ram_tags:
            return self.default_prompt

        now = time.time()
        ram_is_fresh = (now - self.last_ram_time) <= self.ram_tags_timeout_s

        # Important: do not use old RAM tags when the latest RAM message is stale.
        if (not ram_is_fresh) or (len(self.last_ram_tags) < self.min_ram_tags):
            return self.default_prompt

        candidates: List[str] = []
        used: Set[str] = set()

        def add_tag(tag: Any):
            t = normalize_tag(tag)
            if not t or t in self.ignore_tags or t in used:
                return
            used.add(t)
            candidates.append(t)

        if self.use_ram_tag_memory:
            self.ram_tag_history = [
                (t, ts) for (t, ts) in self.ram_tag_history
                if now - t <= self.ram_tag_memory_s
            ]
            # Newer tags first. This increases recall while still requiring fresh RAM.
            for _, tags in reversed(self.ram_tag_history):
                for tag in tags:
                    add_tag(tag)
        else:
            for tag in self.last_ram_tags:
                add_tag(tag)

        if len(candidates) < self.min_ram_tags:
            return self.default_prompt

        if self.always_include_default_prompt:
            for tag in split_prompt_text(self.default_prompt):
                add_tag(tag)

        if self.max_prompt_tags > 0:
            candidates = candidates[: self.max_prompt_tags]

        prompt = build_prompt(candidates)
        return prompt if prompt else self.default_prompt

    def start_processing_collected_frames(self, reason: str):
        if self.is_processing:
            return

        frames = list(self.collected_frames)
        request_id = self.request_id

        self.is_active = False
        self.is_processing = True
        self.collected_frames = []

        if not frames:
            self.is_processing = False
            self.finish_detection_failed("No frames collected.")
            return

        prompt = self.get_current_prompt()
        start_t = time.time()

        self.get_logger().info(
            f"Start detection request_id={request_id}, reason={reason}, "
            f"frames={len(frames)}, prompt='{prompt}'"
        )

        try:
            detections = self.process_frames(frames, prompt)
            elapsed = time.time() - start_t

            self.publish_bboxes(
                frames=frames,
                prompt=prompt,
                detections=detections,
                request_id=request_id,
                elapsed_s=elapsed,
                reason=reason,
            )

            if self.publish_debug_image:
                debug = self.draw_debug_image(
                    bgr=frames[-1].bgr,
                    detections=detections,
                    prompt=prompt,
                    frames_used=len(frames),
                    elapsed_s=elapsed,
                )
                self.debug_image_pub.publish(
                    self.cv2_to_ros_image(debug, frames[-1].frame_id)
                )

            self.publish_done(
                True,
                (
                    f"Detection done. request_id={request_id}, frames={len(frames)}, "
                    f"count={len(detections)}, elapsed={elapsed:.3f}s"
                ),
                request_id,
                len(detections),
                elapsed,
            )

            self.get_logger().info(
                f"Detection done. request_id={request_id}, "
                f"count={len(detections)}, elapsed={elapsed:.3f}s"
            )

        except Exception as e:
            elapsed = time.time() - start_t
            self.get_logger().error(f"Detection failed: {repr(e)}")
            self.publish_done(False, f"Detection failed: {repr(e)}", request_id, 0, elapsed)

        finally:
            self.is_processing = False

    def finish_detection_failed(self, message: str):
        self.is_active = False
        self.is_processing = False
        self.collected_frames = []
        self.get_logger().warn(message)
        self.publish_done(False, message, self.request_id, 0, 0.0)

    def process_frames(self, frames: List[FrameItem], prompt: str) -> List[Dict[str, Any]]:
        if not prompt:
            self.get_logger().warn("Prompt is empty. No detection.")
            return []

        all_frame_detections: List[Dict[str, Any]] = []

        for frame_index, frame in enumerate(frames):
            h, w = frame.bgr.shape[:2]

            raw = self.run_detection_full_and_tiles(
                bgr=frame.bgr,
                prompt=prompt,
                image_h=h,
                image_w=w,
                frame_index=frame_index,
            )

            frame_dets = self.nms_detections(
                raw,
                iou_threshold=self.nms_iou_threshold,
                containment_threshold=self.nms_containment_threshold,
            )

            self.get_logger().info(
                f"Frame {frame_index}: raw={len(raw)}, after_basic_nms={len(frame_dets)}"
            )
            all_frame_detections.extend(frame_dets)

        final = self.merge_across_frames(all_frame_detections, total_frames=len(frames))
        return final

    def run_detection_full_and_tiles(
        self,
        bgr: np.ndarray,
        prompt: str,
        image_h: int,
        image_w: int,
        frame_index: int,
    ) -> List[Dict[str, Any]]:
        """Run detection in original-first mode.

        1. Always try the original full image first when include_full_image=True.
        2. If use_tiled_inference=False, return full-image detections only.
        3. If auto_tile_if_few_detections=True, run 2x2 tiles only when the full
           image finds fewer than auto_tile_min_full_detections raw boxes.
        4. If auto_tile_if_few_detections=False, run full + tiles like the old code.
        """
        all_detections: List[Dict[str, Any]] = []

        def run_one_region(x1: int, y1: int, x2: int, y2: int, region_index: int, region_name: str) -> List[Dict[str, Any]]:
            crop = bgr[y1:y2, x1:x2]
            crop_h, crop_w = crop.shape[:2]
            if crop_w < self.min_tile_size or crop_h < self.min_tile_size:
                return []

            dets = self.run_detection(
                bgr=crop,
                prompt=prompt,
                image_h=crop_h,
                image_w=crop_w,
                frame_index=frame_index,
                region_index=region_index,
                region_name=region_name,
            )

            for det in dets:
                det["x1"] = float(det["x1"] + x1)
                det["y1"] = float(det["y1"] + y1)
                det["x2"] = float(det["x2"] + x1)
                det["y2"] = float(det["y2"] + y1)

                det["x1"] = max(0.0, min(float(image_w - 1), det["x1"]))
                det["y1"] = max(0.0, min(float(image_h - 1), det["y1"]))
                det["x2"] = max(0.0, min(float(image_w - 1), det["x2"]))
                det["y2"] = max(0.0, min(float(image_h - 1), det["y2"]))

                if det["x2"] <= det["x1"] or det["y2"] <= det["y1"]:
                    continue

                self.update_bbox_fields(det)

                det["source_region"] = region_name
                det["source_regions"] = [region_name]
                det["region_offset"] = {
                    "x": int(x1),
                    "y": int(y1),
                    "w": int(crop_w),
                    "h": int(crop_h),
                }

            return dets

        # Full image first.
        full_dets: List[Dict[str, Any]] = []
        if self.include_full_image:
            full_dets = run_one_region(0, 0, image_w, image_h, 0, "full")
            all_detections.extend(full_dets)

        if not self.use_tiled_inference:
            return all_detections

        should_run_tiles = True
        if self.auto_tile_if_few_detections and self.include_full_image:
            should_run_tiles = len(full_dets) < self.auto_tile_min_full_detections

        if not should_run_tiles:
            self.get_logger().info(
                f"Frame {frame_index}: full-image raw={len(full_dets)} >= "
                f"auto_tile_min_full_detections={self.auto_tile_min_full_detections}; skip tiles."
            )
            return all_detections

        tile_regions = [r for r in self.build_regions(image_w, image_h) if r[4] != "full"]
        tile_start_index = 1 if self.include_full_image else 0
        for tile_i, (x1, y1, x2, y2, region_name) in enumerate(tile_regions):
            all_detections.extend(
                run_one_region(x1, y1, x2, y2, tile_start_index + tile_i, region_name)
            )

        self.get_logger().info(
            f"Frame {frame_index}: full_raw={len(full_dets)}, total_raw_with_tiles={len(all_detections)}"
        )
        return all_detections

    def build_regions(self, image_w: int, image_h: int) -> List[Tuple[int, int, int, int, str]]:
        regions: List[Tuple[int, int, int, int, str]] = []

        if self.include_full_image:
            regions.append((0, 0, image_w, image_h, "full"))

        if not self.use_tiled_inference:
            return regions

        tile_w = int(math.ceil(image_w / float(self.tile_cols)))
        tile_h = int(math.ceil(image_h / float(self.tile_rows)))

        overlap_x = int(round(tile_w * self.tile_overlap_ratio))
        overlap_y = int(round(tile_h * self.tile_overlap_ratio))

        for r in range(self.tile_rows):
            for c in range(self.tile_cols):
                base_x1 = c * tile_w
                base_y1 = r * tile_h
                base_x2 = min(image_w, (c + 1) * tile_w)
                base_y2 = min(image_h, (r + 1) * tile_h)

                x1 = max(0, base_x1 - overlap_x)
                y1 = max(0, base_y1 - overlap_y)
                x2 = min(image_w, base_x2 + overlap_x)
                y2 = min(image_h, base_y2 + overlap_y)

                if x2 <= x1 or y2 <= y1:
                    continue

                regions.append((x1, y1, x2, y2, f"tile_{r}_{c}"))

        return regions

    def run_detection(
        self,
        bgr: np.ndarray,
        prompt: str,
        image_h: int,
        image_w: int,
        frame_index: int,
        region_index: int,
        region_name: str,
    ) -> List[Dict[str, Any]]:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_image = PILImage.fromarray(rgb)

        inputs = self.processor(
            images=pil_image,
            text=prompt,
            return_tensors="pt",
        ).to(self.device)

        if self.device == "cuda":
            torch.cuda.synchronize()

        with torch.inference_mode():
            outputs = self.model(**inputs)

        if self.device == "cuda":
            torch.cuda.synchronize()

        results = self.post_process(outputs, inputs.input_ids, image_h, image_w)

        if not results:
            return []

        result = results[0]
        boxes = result.get("boxes", [])
        scores = result.get("scores", [])
        labels = result.get("labels", [])

        if hasattr(boxes, "detach"):
            boxes = boxes.detach().cpu().numpy()
        if hasattr(scores, "detach"):
            scores = scores.detach().cpu().numpy()

        detections: List[Dict[str, Any]] = []

        for idx, (box, score, label) in enumerate(zip(boxes, scores, labels)):
            if self.max_detections_per_region > 0 and idx >= self.max_detections_per_region:
                break

            x1, y1, x2, y2 = [float(x) for x in box]

            x1 = max(0.0, min(float(image_w - 1), x1))
            y1 = max(0.0, min(float(image_h - 1), y1))
            x2 = max(0.0, min(float(image_w - 1), x2))
            y2 = max(0.0, min(float(image_h - 1), y2))

            if x2 <= x1 or y2 <= y1:
                continue

            raw_label = normalize_tag(label)
            if not raw_label:
                raw_label = "object"

            score = float(score)
            if not np.isfinite(score):
                score = 0.0

            det = {
                "id": int(idx),
                "class": raw_label,
                "raw_label": raw_label,
                "score": score,
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "frame_index": int(frame_index),
                "region_index": int(region_index),
                "source_region": str(region_name),
                "source_regions": [str(region_name)],
            }
            self.update_bbox_fields(det)
            detections.append(det)

        detections.sort(key=lambda x: float(x["score"]), reverse=True)
        return detections

    def post_process(self, outputs, input_ids, image_h: int, image_w: int):
        target_sizes = [(image_h, image_w)]

        # transformers 版本不同，參數名稱可能不同
        try:
            return self.processor.post_process_grounded_object_detection(
                outputs=outputs,
                input_ids=input_ids,
                box_threshold=self.box_threshold,
                text_threshold=self.text_threshold,
                target_sizes=target_sizes,
            )
        except TypeError:
            return self.processor.post_process_grounded_object_detection(
                outputs,
                input_ids,
                threshold=self.threshold,
                target_sizes=target_sizes,
            )

    @staticmethod
    def update_bbox_fields(det: Dict[str, Any]):
        det["cx"] = float((float(det["x1"]) + float(det["x2"])) / 2.0)
        det["cy"] = float((float(det["y1"]) + float(det["y2"])) / 2.0)
        det["w"] = float(float(det["x2"]) - float(det["x1"]))
        det["h"] = float(float(det["y2"]) - float(det["y1"]))
        det["area"] = float(det["w"] * det["h"])

    def nms_detections(
        self,
        detections: List[Dict[str, Any]],
        iou_threshold: float,
        containment_threshold: float,
    ) -> List[Dict[str, Any]]:
        if not detections:
            return []

        detections = sorted(
            detections,
            key=lambda d: float(d.get("score", 0.0)),
            reverse=True,
        )

        kept: List[Dict[str, Any]] = []

        for det in detections:
            keep = True

            for kept_det in kept:
                if self.same_class_only and not same_class(det, kept_det):
                    continue

                iou = bbox_iou(det, kept_det)
                ios = bbox_ios(det, kept_det)

                if iou >= iou_threshold or ios >= containment_threshold:
                    keep = False

                    regions = set(kept_det.get("source_regions", []))
                    regions.update(det.get("source_regions", []))
                    kept_det["source_regions"] = sorted(regions)
                    kept_det["source_count"] = int(kept_det.get("source_count", 1)) + 1
                    break

            if keep:
                det["source_count"] = 1
                kept.append(det)

        return kept

    def merge_across_frames(
        self,
        detections: List[Dict[str, Any]],
        total_frames: int,
    ) -> List[Dict[str, Any]]:
        if not detections:
            return []

        detections = sorted(
            detections,
            key=lambda d: float(d.get("score", 0.0)),
            reverse=True,
        )

        groups: List[Dict[str, Any]] = []

        for det in detections:
            best_group = None
            best_metric = 0.0

            for group in groups:
                rep = group["rep"]

                if self.same_class_only and not same_class(det, rep):
                    continue

                iou = bbox_iou(det, rep)
                ios = bbox_ios(det, rep)
                metric = max(iou, ios)

                if (iou >= self.merge_iou_threshold or ios >= self.merge_containment_threshold) and metric > best_metric:
                    best_group = group
                    best_metric = metric

            if best_group is None:
                groups.append({"rep": det, "members": [det]})
            else:
                best_group["members"].append(det)
                if float(det.get("score", 0.0)) > float(best_group["rep"].get("score", 0.0)):
                    best_group["rep"] = det

        final: List[Dict[str, Any]] = []
        required_votes = min(self.min_frame_votes, max(1, total_frames))

        for group in groups:
            members: List[Dict[str, Any]] = group["members"]

            frame_indices = sorted(
                {int(m.get("frame_index", -1)) for m in members if int(m.get("frame_index", -1)) >= 0}
            )
            frame_votes = len(frame_indices)

            if frame_votes < required_votes:
                continue

            scores = np.array(
                [max(float(m.get("score", 0.0)), 1e-6) for m in members],
                dtype=np.float64,
            )
            weight_sum = float(np.sum(scores))
            if weight_sum <= 1e-6:
                scores = np.ones(len(members), dtype=np.float64)
                weight_sum = float(np.sum(scores))

            def weighted_value(key: str) -> float:
                values = np.array([float(m[key]) for m in members], dtype=np.float64)
                return float(np.sum(values * scores) / weight_sum)

            x1 = weighted_value("x1")
            y1 = weighted_value("y1")
            x2 = weighted_value("x2")
            y2 = weighted_value("y2")

            if x2 <= x1 or y2 <= y1:
                continue

            max_score = max(float(m.get("score", 0.0)) for m in members)
            mean_score = float(np.mean([float(m.get("score", 0.0)) for m in members]))

            if max_score < self.min_final_score:
                continue

            rep = group["rep"]
            cls = str(rep.get("class", "object"))

            source_regions: Set[str] = set()
            raw_labels: Set[str] = set()
            for m in members:
                source_regions.update(str(r) for r in m.get("source_regions", []))
                if m.get("raw_label"):
                    raw_labels.add(str(m.get("raw_label")))

            det = {
                "id": 0,
                "draw_id": 0,
                "class": cls,
                "raw_label": cls,
                "raw_labels": sorted(raw_labels),
                "score": float(max_score),
                "mean_score": float(mean_score),
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "frame_votes": int(frame_votes),
                "total_frames": int(total_frames),
                "stability_score": float(frame_votes / max(1, total_frames)),
                "source_frames": frame_indices,
                "source_regions": sorted(source_regions),
                "source_count": int(len(members)),
            }
            self.update_bbox_fields(det)
            final.append(det)

        final.sort(
            key=lambda d: (
                int(d.get("frame_votes", 0)),
                float(d.get("score", 0.0)),
            ),
            reverse=True,
        )

        if self.max_final_detections > 0:
            final = final[: self.max_final_detections]

        for idx, det in enumerate(final):
            color = get_bbox_color(idx)
            det["id"] = int(idx)
            det["draw_id"] = int(idx)
            det["color_bgr"] = [int(color[0]), int(color[1]), int(color[2])]

        return final

    # ============================================================
    # Publish
    # ============================================================

    def publish_bboxes(
        self,
        frames: List[FrameItem],
        prompt: str,
        detections: List[Dict[str, Any]],
        request_id: int,
        elapsed_s: float,
        reason: str,
    ):
        if not frames:
            return

        last_frame = frames[-1]
        h, w = last_frame.bgr.shape[:2]

        out = String()
        out.data = json.dumps(
            {
                "stamp": {
                    "sec": int(last_frame.stamp_sec),
                    "nanosec": int(last_frame.stamp_nanosec),
                },
                "frame_id": str(last_frame.frame_id),
                "image_width": int(w),
                "image_height": int(h),
                "prompt": str(prompt),
                "count": len(detections),
                "bboxes": detections,
                "raw": True,
                "multi_frame": {
                    "enabled": True,
                    "request_id": int(request_id),
                    "frames_used": int(len(frames)),
                    "target_frames": int(self.multi_frame_count),
                    "min_frame_votes": int(self.min_frame_votes),
                    "reason": str(reason),
                    "elapsed_s": float(elapsed_s),
                },
                "tiled_inference": {
                    "enabled": bool(self.use_tiled_inference),
                    "include_full_image": bool(self.include_full_image),
                    "tile_rows": int(self.tile_rows),
                    "tile_cols": int(self.tile_cols),
                    "tile_overlap_ratio": float(self.tile_overlap_ratio),
                },
            },
            ensure_ascii=False,
        )

        if detections or self.publish_empty:
            self.bboxes_pub.publish(out)

        self.get_logger().info(
            f"Published {len(detections)} raw merged bboxes to {self.bboxes_topic}"
        )

    def publish_done(
        self,
        success: bool,
        message: str,
        request_id: int,
        count: int,
        elapsed_s: float,
    ):
        msg = String()
        msg.data = json.dumps(
            {
                "success": bool(success),
                "message": str(message),
                "request_id": int(request_id),
                "count": int(count),
                "elapsed_s": float(elapsed_s),
            },
            ensure_ascii=False,
        )
        self.done_pub.publish(msg)

        if self.done_client is not None:
            try:
                if self.done_client.service_is_ready():
                    req = Trigger.Request()
                    self.done_client.call_async(req)
                    self.get_logger().info(f"Called done service: {self.done_service_name}")
                else:
                    self.get_logger().warn(f"Done service not ready: {self.done_service_name}")
            except Exception as e:
                self.get_logger().warn(
                    f"Failed to call done service {self.done_service_name}: {repr(e)}"
                )

    # ============================================================
    # Image conversion / debug image
    # ============================================================

    def ros_image_to_cv2(self, ros_image: Image) -> np.ndarray:
        encoding = ros_image.encoding.lower()
        height = int(ros_image.height)
        width = int(ros_image.width)
        step = int(ros_image.step)

        data = np.frombuffer(ros_image.data, dtype=np.uint8)

        if encoding in ["rgb8", "bgr8"]:
            channels = 3
            expected_step = width * channels

            if step == expected_step:
                img = data.reshape((height, width, channels))
            else:
                rows = data.reshape((height, step))
                img = rows[:, :expected_step].reshape((height, width, channels))

            if encoding == "rgb8":
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            return img.copy()

        if encoding in ["rgba8", "bgra8"]:
            channels = 4
            expected_step = width * channels

            if step == expected_step:
                img = data.reshape((height, width, channels))
            else:
                rows = data.reshape((height, step))
                img = rows[:, :expected_step].reshape((height, width, channels))

            if encoding == "rgba8":
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            return img.copy()

        if encoding == "mono8":
            expected_step = width

            if step == expected_step:
                img = data.reshape((height, width))
            else:
                rows = data.reshape((height, step))
                img = rows[:, :expected_step].reshape((height, width))

            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR).copy()

        raise ValueError(f"Unsupported image encoding: {ros_image.encoding}")

    def cv2_to_ros_image(self, bgr: np.ndarray, frame_id: str) -> Image:
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        msg.height = int(bgr.shape[0])
        msg.width = int(bgr.shape[1])
        msg.encoding = "bgr8"
        msg.is_bigendian = False
        msg.step = int(bgr.shape[1] * 3)
        msg.data = bgr.tobytes()
        return msg

    def draw_debug_image(
        self,
        bgr: np.ndarray,
        detections: List[Dict[str, Any]],
        prompt: str,
        frames_used: int,
        elapsed_s: float,
    ) -> np.ndarray:
        debug = bgr.copy()
        h, w = debug.shape[:2]

        if self.draw_tile_grid_enabled:
            self.draw_regions_on_image(debug)

        for draw_idx, det in enumerate(detections):
            x1 = max(0, min(w - 1, int(round(det["x1"]))))
            y1 = max(0, min(h - 1, int(round(det["y1"]))))
            x2 = max(0, min(w - 1, int(round(det["x2"]))))
            y2 = max(0, min(h - 1, int(round(det["y2"]))))

            cls = str(det["class"])
            score = float(det["score"])
            votes = int(det.get("frame_votes", 1))
            total = int(det.get("total_frames", frames_used))

            color_list = det.get("color_bgr", list(get_bbox_color(draw_idx)))
            color = (int(color_list[0]), int(color_list[1]), int(color_list[2]))

            cv2.rectangle(debug, (x1, y1), (x2, y2), color, 2)

            cx = int(round(det["cx"]))
            cy = int(round(det["cy"]))
            cv2.circle(debug, (cx, cy), 4, color, -1)

            label = f"{draw_idx}: {cls} {score:.2f} v={votes}/{total}"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 2

            text_size, baseline = cv2.getTextSize(label, font, font_scale, thickness)
            text_w, text_h = text_size

            label_x1 = x1
            label_y1 = max(0, y1 - text_h - baseline - 8)
            label_x2 = min(debug.shape[1] - 1, label_x1 + text_w + 8)
            label_y2 = min(debug.shape[0] - 1, label_y1 + text_h + baseline + 8)

            cv2.rectangle(debug, (label_x1, label_y1), (label_x2, label_y2), color, -1)
            cv2.putText(
                debug,
                label,
                (label_x1 + 4, label_y2 - baseline - 4),
                font,
                font_scale,
                (0, 0, 0),
                thickness,
                cv2.LINE_AA,
            )

        prompt_text = prompt[:110]
        status_text = f"RAW frames={frames_used}, count={len(detections)}, elapsed={elapsed_s:.2f}s"

        cv2.putText(
            debug,
            f"prompt: {prompt_text}",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.putText(
            debug,
            status_text,
            (10, 56),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return debug

    def draw_regions_on_image(self, img: np.ndarray):
        h, w = img.shape[:2]
        regions = self.build_regions(image_w=w, image_h=h)

        for x1, y1, x2, y2, name in regions:
            if name == "full":
                continue

            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 255, 255), 1)
            cv2.putText(
                img,
                name,
                (int(x1) + 5, int(y1) + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )


def main(args=None):
    rclpy.init(args=args)
    node = HFGroundingDINOMultiFrameTiledNode()

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
