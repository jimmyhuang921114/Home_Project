#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
bbox_filter_fusion_node.py

GroundingDINO bbox 過濾 / 去重 / 同義詞融合工具。

用途：
/grounding_dino/bboxes_raw
  -> score filter
  -> area filter
  -> blocked class filter
  -> class alias canonicalization
  -> tile seam / huge box filter
  -> class-aware NMS
  -> class-agnostic NMS
  -> containment filter
  -> optional temporal confirm
  -> /grounding_dino/bboxes

注意：
1. 這支不跑模型。
2. 不提供 /grounding_dino/detect_once。
3. /grounding_dino/detect_once 必須由 grounding_dino_node.py 提供。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile

from std_msgs.msg import String


def normalize_tag(tag: Any) -> str:
    tag = str(tag).lower().strip()
    tag = tag.replace("_", " ")
    tag = re.sub(r"\s+", " ", tag)
    tag = tag.strip(" .,:;[](){}\"'")
    tag = re.sub(r"^(a|an|the)\s+", "", tag)
    return tag.strip()


def parse_csv_set(text: str) -> Set[str]:
    out: Set[str] = set()
    for item in str(text).replace("|", ",").replace(";", ",").split(","):
        item = normalize_tag(item)
        if item:
            out.add(item)
    return out


def canonical_class(label: Any) -> str:
    cls = normalize_tag(label)

    # 完全不要的類別
    ignore = {
        "indoor", "outdoor", "room", "dining room", "kitchen", "scene", "image",
        "photo", "picture", "background", "wall", "floor", "ceiling", "lighting",
        "light", "shadow", "reflection", "object", "modern", "wood", "metal",
        "plastic", "black", "white", "gray", "grey", "red", "blue", "green",
        "yellow",
    }
    if cls in ignore:
        return ""

    # 同義詞合併
    alias = {
        "dinning table": "table",
        "dining table": "table",
        "coffee table": "table",
        "desk": "table",
        "table top": "table",

        "dining chair": "chair",
        "office chair": "chair",
        "armchair": "chair",
        "stool": "chair",

        "counter top": "counter",
        "countertop": "counter",
        "kitchen counter": "counter",
        "kitchen island": "counter",
        "island": "counter",

        "exhaust hood": "hood",
        "range hood": "hood",
        "kitchen hood": "hood",

        "television": "tv",
        "tv monitor": "tv",

        "couch": "sofa",

        "sink basin": "sink",
        "washbasin": "sink",
    }

    return alias.get(cls, cls)


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
    """
    Intersection over Smaller box.
    用來處理大框包小框但 IoU 不高的情況。
    """
    inter = bbox_intersection(a, b)
    small = min(bbox_area(a), bbox_area(b))
    if small <= 1e-6:
        return 0.0
    return float(inter / small)


def update_bbox_fields(det: Dict[str, Any]):
    det["cx"] = float((float(det["x1"]) + float(det["x2"])) / 2.0)
    det["cy"] = float((float(det["y1"]) + float(det["y2"])) / 2.0)
    det["w"] = float(float(det["x2"]) - float(det["x1"]))
    det["h"] = float(float(det["y2"]) - float(det["y1"]))
    det["area"] = float(det["w"] * det["h"])


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
    ]
    return palette[index % len(palette)]


class BBoxFilterFusionNode(Node):
    def __init__(self):
        super().__init__("bbox_filter_fusion_node")

        # Topic
        self.declare_parameter("input_topic", "/grounding_dino/bboxes_raw")
        self.declare_parameter("output_topic", "/grounding_dino/bboxes")
        self.declare_parameter("debug_topic", "/grounding_dino/filter_debug")

        # Basic filters
        self.declare_parameter("min_score", 0.18)
        self.declare_parameter("min_area_ratio", 0.00012)
        self.declare_parameter("max_area_ratio", 0.65)
        self.declare_parameter("min_width_px", 8.0)
        self.declare_parameter("min_height_px", 8.0)
        self.declare_parameter("max_aspect_ratio", 12.0)

        self.declare_parameter("allowed_classes", "")
        self.declare_parameter(
            "blocked_classes",
            "background,ceiling,floor,image,photo,room,wall,kitchen,dining room,modern,object",
        )

        # NMS / de-duplicate
        self.declare_parameter("class_aware_nms_iou", 0.55)
        self.declare_parameter("class_aware_containment", 0.92)
        self.declare_parameter("class_agnostic_nms_iou", 0.90)
        self.declare_parameter("class_agnostic_containment", 0.98)

        # Tile seam / edge filters
        self.declare_parameter("enable_tile_seam_filter", False)
        self.declare_parameter("tile_rows", 2)
        self.declare_parameter("tile_cols", 2)
        self.declare_parameter("seam_margin_ratio", 0.025)
        self.declare_parameter("drop_large_tile_edge_boxes", False)

        # Temporal
        self.declare_parameter("enable_temporal_filter", False)
        self.declare_parameter("confirm_hits", 1)
        self.declare_parameter("temporal_iou", 0.35)
        self.declare_parameter("track_ttl_s", 3.0)
        self.declare_parameter("publish_unconfirmed", True)

        # Output
        self.declare_parameter("max_output_detections", 180)
        self.declare_parameter("publish_empty", True)

        # Read params
        self.input_topic = str(self.get_parameter("input_topic").value)
        self.output_topic = str(self.get_parameter("output_topic").value)
        self.debug_topic = str(self.get_parameter("debug_topic").value)

        self.min_score = float(self.get_parameter("min_score").value)
        self.min_area_ratio = float(self.get_parameter("min_area_ratio").value)
        self.max_area_ratio = float(self.get_parameter("max_area_ratio").value)
        self.min_width_px = float(self.get_parameter("min_width_px").value)
        self.min_height_px = float(self.get_parameter("min_height_px").value)
        self.max_aspect_ratio = float(self.get_parameter("max_aspect_ratio").value)

        self.allowed_classes = parse_csv_set(str(self.get_parameter("allowed_classes").value))
        self.blocked_classes = parse_csv_set(str(self.get_parameter("blocked_classes").value))

        self.class_aware_nms_iou = float(self.get_parameter("class_aware_nms_iou").value)
        self.class_aware_containment = float(self.get_parameter("class_aware_containment").value)
        self.class_agnostic_nms_iou = float(self.get_parameter("class_agnostic_nms_iou").value)
        self.class_agnostic_containment = float(self.get_parameter("class_agnostic_containment").value)

        self.enable_tile_seam_filter = bool(self.get_parameter("enable_tile_seam_filter").value)
        self.tile_rows = max(1, int(self.get_parameter("tile_rows").value))
        self.tile_cols = max(1, int(self.get_parameter("tile_cols").value))
        self.seam_margin_ratio = float(self.get_parameter("seam_margin_ratio").value)
        self.drop_large_tile_edge_boxes = bool(self.get_parameter("drop_large_tile_edge_boxes").value)

        self.enable_temporal_filter = bool(self.get_parameter("enable_temporal_filter").value)
        self.confirm_hits = max(1, int(self.get_parameter("confirm_hits").value))
        self.temporal_iou = float(self.get_parameter("temporal_iou").value)
        self.track_ttl_s = float(self.get_parameter("track_ttl_s").value)
        self.publish_unconfirmed = bool(self.get_parameter("publish_unconfirmed").value)

        self.max_output_detections = int(self.get_parameter("max_output_detections").value)
        self.publish_empty = bool(self.get_parameter("publish_empty").value)

        self.tracks: List[Dict[str, Any]] = []
        self.next_track_id = 1

        qos = QoSProfile(depth=10)
        self.sub = self.create_subscription(String, self.input_topic, self.callback, qos)
        self.pub = self.create_publisher(String, self.output_topic, 10)
        self.debug_pub = self.create_publisher(String, self.debug_topic, 10)

        self.get_logger().info("BBoxFilterFusionNode ready.")
        self.get_logger().info(f"input_topic              : {self.input_topic}")
        self.get_logger().info(f"output_topic             : {self.output_topic}")
        self.get_logger().info(f"debug_topic              : {self.debug_topic}")
        self.get_logger().info(f"min_score                : {self.min_score}")
        self.get_logger().info(f"min_area_ratio           : {self.min_area_ratio}")
        self.get_logger().info(f"max_area_ratio           : {self.max_area_ratio}")
        self.get_logger().info(f"allowed_classes          : {sorted(self.allowed_classes)}")
        self.get_logger().info(f"blocked_classes          : {sorted(self.blocked_classes)}")
        self.get_logger().info(f"class_aware_nms_iou      : {self.class_aware_nms_iou}")
        self.get_logger().info(f"class_agnostic_nms_iou   : {self.class_agnostic_nms_iou}")
        self.get_logger().info(f"enable_tile_seam_filter  : {self.enable_tile_seam_filter}")
        self.get_logger().info(f"enable_temporal_filter   : {self.enable_temporal_filter}")
        self.get_logger().info(f"confirm_hits             : {self.confirm_hits}")

    def callback(self, msg: String):
        t0 = time.time()
        stats: Dict[str, int] = {}

        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse input JSON: {repr(e)}")
            return

        raw_bboxes = payload.get("bboxes", [])
        if not isinstance(raw_bboxes, list):
            raw_bboxes = []

        image_w, image_h = self.get_image_size(payload, raw_bboxes)

        normalized = self.normalize_and_basic_filter(raw_bboxes, image_w, image_h, stats)

        if self.enable_tile_seam_filter and image_w > 0 and image_h > 0:
            normalized = self.tile_seam_filter(normalized, image_w, image_h, stats)

        class_aware = self.nms(
            normalized,
            iou_threshold=self.class_aware_nms_iou,
            containment_threshold=self.class_aware_containment,
            same_class_only=True,
            stats=stats,
            stat_key="drop_class_aware_nms",
        )

        class_agnostic = self.nms(
            class_aware,
            iou_threshold=self.class_agnostic_nms_iou,
            containment_threshold=self.class_agnostic_containment,
            same_class_only=False,
            stats=stats,
            stat_key="drop_class_agnostic_nms",
        )

        if self.enable_temporal_filter and self.confirm_hits > 1:
            final = self.temporal_filter(class_agnostic, stats)
        else:
            final = class_agnostic

        final.sort(
            key=lambda d: (
                int(d.get("frame_votes", 1)),
                float(d.get("score", 0.0)),
                float(d.get("area", 0.0)),
            ),
            reverse=True,
        )

        if self.max_output_detections > 0:
            final = final[: self.max_output_detections]

        for i, det in enumerate(final):
            det["id"] = int(i)
            det["draw_id"] = int(i)
            color = get_bbox_color(i)
            det["color_bgr"] = [int(color[0]), int(color[1]), int(color[2])]

        out_payload = dict(payload)
        out_payload["raw_count"] = len(raw_bboxes)
        out_payload["count"] = len(final)
        out_payload["bboxes"] = final
        out_payload["raw"] = False
        out_payload["filtered"] = True
        out_payload["filter_stats"] = stats
        out_payload["filter_elapsed_s"] = float(time.time() - t0)
        out_payload["filter_node"] = "bbox_filter_fusion_node"

        if final or self.publish_empty:
            out = String()
            out.data = json.dumps(out_payload, ensure_ascii=False)
            self.pub.publish(out)

        debug = String()
        debug.data = json.dumps(
            {
                "raw_count": len(raw_bboxes),
                "after_basic": len(normalized),
                "after_class_aware": len(class_aware),
                "after_class_agnostic": len(class_agnostic),
                "final_count": len(final),
                "stats": stats,
                "elapsed_s": float(time.time() - t0),
            },
            ensure_ascii=False,
        )
        self.debug_pub.publish(debug)

        self.get_logger().info(
            f"Filtered bboxes: raw={len(raw_bboxes)} -> final={len(final)}, stats={stats}"
        )

    def add_stat(self, stats: Dict[str, int], key: str):
        stats[key] = stats.get(key, 0) + 1

    def get_image_size(self, payload: Dict[str, Any], bboxes: List[Dict[str, Any]]) -> Tuple[int, int]:
        image_w = 0
        image_h = 0

        for key in ["image_width", "width", "w"]:
            if key in payload:
                try:
                    image_w = int(payload[key])
                    break
                except Exception:
                    pass

        for key in ["image_height", "height", "h"]:
            if key in payload:
                try:
                    image_h = int(payload[key])
                    break
                except Exception:
                    pass

        if image_w <= 0 or image_h <= 0:
            max_x = 0.0
            max_y = 0.0
            for d in bboxes:
                try:
                    max_x = max(max_x, float(d.get("x2", 0.0)), float(d.get("cx", 0.0)))
                    max_y = max(max_y, float(d.get("y2", 0.0)), float(d.get("cy", 0.0)))
                except Exception:
                    pass
            image_w = int(max_x) if image_w <= 0 else image_w
            image_h = int(max_y) if image_h <= 0 else image_h

        return max(1, image_w), max(1, image_h)

    def normalize_and_basic_filter(
        self,
        bboxes: List[Dict[str, Any]],
        image_w: int,
        image_h: int,
        stats: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        image_area = max(1.0, float(image_w * image_h))

        for det in bboxes:
            try:
                score = float(det.get("score", 0.0))
                if score < self.min_score:
                    self.add_stat(stats, "drop_low_score")
                    continue

                raw_label = det.get("raw_label", det.get("class", "object"))
                can = canonical_class(raw_label)
                if not can:
                    self.add_stat(stats, "drop_ignored_class")
                    continue

                if can in self.blocked_classes:
                    self.add_stat(stats, "drop_blocked_class")
                    continue

                if self.allowed_classes and can not in self.allowed_classes:
                    self.add_stat(stats, "drop_not_allowed_class")
                    continue

                new_det = dict(det)
                new_det["raw_label"] = normalize_tag(raw_label)
                new_det["class"] = can

                if all(k in new_det for k in ["x1", "y1", "x2", "y2"]):
                    new_det["x1"] = float(new_det["x1"])
                    new_det["y1"] = float(new_det["y1"])
                    new_det["x2"] = float(new_det["x2"])
                    new_det["y2"] = float(new_det["y2"])
                elif all(k in new_det for k in ["cx", "cy", "w", "h"]):
                    cx = float(new_det["cx"])
                    cy = float(new_det["cy"])
                    bw = float(new_det["w"])
                    bh = float(new_det["h"])
                    new_det["x1"] = cx - bw / 2.0
                    new_det["y1"] = cy - bh / 2.0
                    new_det["x2"] = cx + bw / 2.0
                    new_det["y2"] = cy + bh / 2.0
                else:
                    self.add_stat(stats, "drop_bad_bbox")
                    continue

                new_det["x1"] = max(0.0, min(float(image_w - 1), float(new_det["x1"])))
                new_det["y1"] = max(0.0, min(float(image_h - 1), float(new_det["y1"])))
                new_det["x2"] = max(0.0, min(float(image_w - 1), float(new_det["x2"])))
                new_det["y2"] = max(0.0, min(float(image_h - 1), float(new_det["y2"])))

                if new_det["x2"] <= new_det["x1"] or new_det["y2"] <= new_det["y1"]:
                    self.add_stat(stats, "drop_bad_bbox")
                    continue

                update_bbox_fields(new_det)

                if new_det["w"] < self.min_width_px or new_det["h"] < self.min_height_px:
                    self.add_stat(stats, "drop_too_small_px")
                    continue

                area_ratio = float(new_det["area"]) / image_area
                new_det["area_ratio"] = area_ratio

                if area_ratio < self.min_area_ratio:
                    self.add_stat(stats, "drop_too_small_area")
                    continue

                if area_ratio > self.max_area_ratio:
                    self.add_stat(stats, "drop_too_large_area")
                    continue

                aspect = max(float(new_det["w"]) / max(1e-6, float(new_det["h"])),
                             float(new_det["h"]) / max(1e-6, float(new_det["w"])))
                new_det["aspect_ratio"] = aspect

                if aspect > self.max_aspect_ratio:
                    self.add_stat(stats, "drop_bad_aspect")
                    continue

                out.append(new_det)

            except Exception:
                self.add_stat(stats, "drop_exception")

        return out

    def tile_seam_filter(
        self,
        detections: List[Dict[str, Any]],
        image_w: int,
        image_h: int,
        stats: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        if not detections:
            return []

        seams_x = [image_w * c / float(self.tile_cols) for c in range(1, self.tile_cols)]
        seams_y = [image_h * r / float(self.tile_rows) for r in range(1, self.tile_rows)]
        margin_x = image_w * self.seam_margin_ratio
        margin_y = image_h * self.seam_margin_ratio

        out: List[Dict[str, Any]] = []

        for det in detections:
            source_region = str(det.get("source_region", ""))
            from_tile = source_region.startswith("tile_")
            if not from_tile:
                out.append(det)
                continue

            cx = float(det["cx"])
            cy = float(det["cy"])

            near_vertical_seam = any(abs(cx - sx) <= margin_x for sx in seams_x)
            near_horizontal_seam = any(abs(cy - sy) <= margin_y for sy in seams_y)
            near_seam = near_vertical_seam or near_horizontal_seam

            # 只丟掉 tile 來源、很大、又卡在切割線附近的框。
            # 小物體在 seam 附近仍保留。
            if (
                self.drop_large_tile_edge_boxes
                and near_seam
                and float(det.get("area_ratio", 0.0)) > 0.08
            ):
                self.add_stat(stats, "drop_tile_seam_large")
                continue

            out.append(det)

        return out

    def nms(
        self,
        detections: List[Dict[str, Any]],
        iou_threshold: float,
        containment_threshold: float,
        same_class_only: bool,
        stats: Dict[str, int],
        stat_key: str,
    ) -> List[Dict[str, Any]]:
        if not detections:
            return []

        detections = sorted(detections, key=lambda d: float(d.get("score", 0.0)), reverse=True)
        kept: List[Dict[str, Any]] = []

        for det in detections:
            keep = True

            for kept_det in kept:
                if same_class_only and str(det.get("class", "")) != str(kept_det.get("class", "")):
                    continue

                iou = bbox_iou(det, kept_det)
                ios = bbox_ios(det, kept_det)

                if iou >= iou_threshold or ios >= containment_threshold:
                    keep = False
                    self.add_stat(stats, stat_key)

                    # 合併來源資訊，方便 debug
                    regions = set(kept_det.get("source_regions", []))
                    regions.update(det.get("source_regions", []))
                    kept_det["source_regions"] = sorted(regions)

                    raw_labels = set(kept_det.get("raw_labels", []))
                    if kept_det.get("raw_label"):
                        raw_labels.add(str(kept_det.get("raw_label")))
                    if det.get("raw_label"):
                        raw_labels.add(str(det.get("raw_label")))
                    raw_labels.update(det.get("raw_labels", []))
                    kept_det["raw_labels"] = sorted(raw_labels)

                    kept_det["source_count"] = int(kept_det.get("source_count", 1)) + int(det.get("source_count", 1))
                    break

            if keep:
                det["source_count"] = int(det.get("source_count", 1))
                raw_labels = set(det.get("raw_labels", []))
                if det.get("raw_label"):
                    raw_labels.add(str(det.get("raw_label")))
                det["raw_labels"] = sorted(raw_labels)
                kept.append(det)

        return kept

    def temporal_filter(self, detections: List[Dict[str, Any]], stats: Dict[str, int]) -> List[Dict[str, Any]]:
        now = time.time()

        # 清掉過期 track
        self.tracks = [
            tr for tr in self.tracks
            if now - float(tr.get("last_seen", 0.0)) <= self.track_ttl_s
        ]

        output: List[Dict[str, Any]] = []

        for det in detections:
            best_track = None
            best_iou = 0.0

            for tr in self.tracks:
                rep = tr["det"]
                if str(rep.get("class", "")) != str(det.get("class", "")):
                    continue

                iou = bbox_iou(rep, det)
                if iou >= self.temporal_iou and iou > best_iou:
                    best_iou = iou
                    best_track = tr

            if best_track is None:
                best_track = {
                    "track_id": self.next_track_id,
                    "det": det,
                    "hits": 0,
                    "last_seen": now,
                }
                self.next_track_id += 1
                self.tracks.append(best_track)

            best_track["hits"] = int(best_track.get("hits", 0)) + 1
            best_track["last_seen"] = now
            best_track["det"] = det

            det["track_id"] = int(best_track["track_id"])
            det["confirm_hits"] = int(best_track["hits"])

            if int(best_track["hits"]) >= self.confirm_hits:
                output.append(det)
            elif self.publish_unconfirmed:
                det["unconfirmed"] = True
                output.append(det)
                self.add_stat(stats, "keep_unconfirmed")
            else:
                self.add_stat(stats, "drop_unconfirmed")

        return output


def main(args=None):
    rclpy.init(args=args)
    node = BBoxFilterFusionNode()
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