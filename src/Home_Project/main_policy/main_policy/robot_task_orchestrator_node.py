#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Tuple

import yaml
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.action import ActionClient

from std_msgs.msg import String
from std_srvs.srv import Trigger

from semantic_nav_interfaces.action import ExecuteRobotTask
from semantic_nav_interfaces.msg import RobotFlowStatus
from semantic_nav_interfaces.srv import NavToPoint, SetRobotMode

from robot_object_retrieval_ros.srv import ImportSemanticMap


def get_project_root() -> Path:
    env = os.environ.get("HOME_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").exists():
            return parent
    return p.parents[4]


class RobotTaskOrchestrator(Node):
    """
    Main Policy / Task Orchestrator

    建立在前一版 robot_task_orchestrator_node.py 上。

    功能：
    1. 讀 waypoint YAML
    2. 使用 service 決定是否跑 waypoint
    3. 將 waypoint x/y/yaw 丟給 /nav_to_point
    4. /nav_to_point 再交給 Nav2 NavigateToPose
    5. 到點後呼叫 /grounding_dino/detect_once
    6. 等待 /grounding_dino/objects_3d_json
    7. 記錄每個 waypoint 的導航與 vision 結果

    第一版不直接：
    - 寫 database
    - 跑 GroundingDINO 模型
    - 直接控制 Nav2 action
    - 控制 UI
    """

    def __init__(self):
        super().__init__("robot_task_orchestrator_node")
        project_root = get_project_root()
        default_waypoint_yaml = (
            project_root / "src" / "web_nav_control" / "runtime" / "waypoints" / "nav2_waypoints.yaml"
        )
        default_records_path = project_root / "data" / "main_policy_records.jsonl"

        # ============================================================
        # Parameters
        # ============================================================
        self.declare_parameter(
            "waypoint_yaml",
            str(default_waypoint_yaml),
        )

        self.declare_parameter("auto_start", False)
        self.declare_parameter("start_delay_s", 3.0)

        self.declare_parameter("use_yaw", True)
        self.declare_parameter("skip_on_fail", True)
        self.declare_parameter("pause_after_nav_s", 0.5)
        self.declare_parameter("pause_after_vision_s", 0.5)

        self.declare_parameter("nav_service", "/nav_to_point")
        self.declare_parameter("nav_timeout_s", 180.0)
        self.declare_parameter("robot_flow_action", "/robot_flow/execute")
        self.declare_parameter("robot_flow_server_timeout_s", 5.0)
        self.declare_parameter("prefer_robot_flow", True)

        self.declare_parameter("vision_trigger_service", "/grounding_dino/detect_once")
        self.declare_parameter("objects_json_topic", "/grounding_dino/objects_3d_json")
        self.declare_parameter("vision_service_timeout_s", 10.0)
        self.declare_parameter("objects_wait_timeout_s", 8.0)

        # 先保留，但預設關閉。
        # 如果之後要到點後自動存入 map_builder，才打開。
        self.declare_parameter("enable_map_confirm", False)
        self.declare_parameter("map_confirm_service", "/semantic_map/confirm")
        self.declare_parameter("map_confirm_timeout_s", 10.0)

        self.declare_parameter(
            "records_save_path",
            str(default_records_path),
        )

        # Database import through /semantic_map/import
        self.declare_parameter("enable_db_import", True)
        self.declare_parameter("semantic_import_service", "/semantic_map/import")
        self.declare_parameter("semantic_import_mode", "replace")
        self.declare_parameter("semantic_import_timeout_s", 60.0)

        # Filters before importing records into DB
        self.declare_parameter("semantic_import_min_score", 0.35)
        self.declare_parameter("semantic_import_min_z", -0.10)
        self.declare_parameter("semantic_import_max_z", 2.80)
        self.declare_parameter("semantic_import_max_dist_from_wp", 8.0)
        self.declare_parameter("semantic_import_max_objects_per_record", 20)

        p = self.get_parameter

        self.waypoint_yaml = str(p("waypoint_yaml").value)

        self.auto_start = bool(p("auto_start").value)
        self.start_delay_s = float(p("start_delay_s").value)

        self.use_yaw = bool(p("use_yaw").value)
        self.skip_on_fail = bool(p("skip_on_fail").value)
        self.pause_after_nav_s = float(p("pause_after_nav_s").value)
        self.pause_after_vision_s = float(p("pause_after_vision_s").value)

        self.nav_service = str(p("nav_service").value)
        self.nav_timeout_s = float(p("nav_timeout_s").value)
        self.robot_flow_action = str(p("robot_flow_action").value)
        self.robot_flow_server_timeout_s = float(
            p("robot_flow_server_timeout_s").value
        )
        self.prefer_robot_flow = bool(p("prefer_robot_flow").value)

        self.vision_trigger_service = str(p("vision_trigger_service").value)
        self.objects_json_topic = str(p("objects_json_topic").value)
        self.vision_service_timeout_s = float(p("vision_service_timeout_s").value)
        self.objects_wait_timeout_s = float(p("objects_wait_timeout_s").value)

        self.enable_map_confirm = bool(p("enable_map_confirm").value)
        self.map_confirm_service = str(p("map_confirm_service").value)
        self.map_confirm_timeout_s = float(p("map_confirm_timeout_s").value)

        self.records_save_path = str(p("records_save_path").value)

        self.enable_db_import = bool(p("enable_db_import").value)
        self.semantic_import_service = str(p("semantic_import_service").value)
        self.semantic_import_mode = str(p("semantic_import_mode").value)
        self.semantic_import_timeout_s = float(p("semantic_import_timeout_s").value)

        self.semantic_import_min_score = float(p("semantic_import_min_score").value)
        self.semantic_import_min_z = float(p("semantic_import_min_z").value)
        self.semantic_import_max_z = float(p("semantic_import_max_z").value)
        self.semantic_import_max_dist_from_wp = float(
            p("semantic_import_max_dist_from_wp").value
        )
        self.semantic_import_max_objects_per_record = int(
            p("semantic_import_max_objects_per_record").value
        )

        # ============================================================
        # Runtime state
        # ============================================================
        self.frame_id, self.waypoints = self._load_waypoints(self.waypoint_yaml)
        self.current_index = 0

        self.running = False
        self.manual_running = False
        self.stop_requested = False

        self.success_count = 0
        self.failed_count = 0
        self.records: list[dict[str, Any]] = []

        self.last_message = "idle"

        self.lock = threading.Lock()

        self._latest_objects_raw: Optional[str] = None
        self._latest_objects_stamp = 0.0
        self._objects_lock = threading.Lock()

        self.auto_thread: Optional[threading.Thread] = None
        self.auto_timer: Optional[threading.Timer] = None
        self._active_flow_goal = None
        self._active_flow_lock = threading.Lock()
        self._mapping_task_id = ""

        # ============================================================
        # ROS clients / subscribers / services
        # ============================================================
        self.cbg = ReentrantCallbackGroup()

        self.nav_client = self.create_client(
            NavToPoint,
            self.nav_service,
            callback_group=self.cbg,
        )
        self.flow_client = ActionClient(
            self,
            ExecuteRobotTask,
            self.robot_flow_action,
            callback_group=self.cbg,
        )
        self.mode_client = self.create_client(
            SetRobotMode,
            "/robot_mode/set",
            callback_group=self.cbg,
        )
        self.flow_status_pub = self.create_publisher(
            RobotFlowStatus,
            "/robot_flow/status",
            20,
        )

        self.vision_client = self.create_client(
            Trigger,
            self.vision_trigger_service,
            callback_group=self.cbg,
        )

        self.map_confirm_client = self.create_client(
            Trigger,
            self.map_confirm_service,
            callback_group=self.cbg,
        )

        self.semantic_import_client = self.create_client(
            ImportSemanticMap,
            self.semantic_import_service,
            callback_group=self.cbg,
        )

        self.create_subscription(
            String,
            self.objects_json_topic,
            self._objects_cb,
            10,
            callback_group=self.cbg,
        )

        # 保留前一版：原地偵測
        self.create_service(
            Trigger,
            "/task/detect_here",
            self.handle_detect_here,
            callback_group=self.cbg,
        )

        # 保留前一版：單點導航 + 偵測
        self.create_service(
            NavToPoint,
            "/task/go_to_point_and_detect",
            self.handle_go_to_point_and_detect,
            callback_group=self.cbg,
        )

        # 新增 main_policy waypoint 控制
        self.create_service(
            Trigger,
            "/main_policy/next",
            self.handle_next,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/start",
            self.handle_start,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/stop",
            self.handle_stop,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/reset",
            self.handle_reset,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/status",
            self.handle_status,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/export_records",
            self.handle_export_records,
            callback_group=self.cbg,
        )

        self.create_service(
            Trigger,
            "/main_policy/import_records",
            self.handle_import_records,
            callback_group=self.cbg,
        )

        self.get_logger().info(
            "RobotTaskOrchestrator started\n"
            f"  waypoint_yaml          : {self.waypoint_yaml}\n"
            f"  frame_id               : {self.frame_id}\n"
            f"  waypoints              : {len(self.waypoints)}\n"
            f"  nav_service            : {self.nav_service}\n"
            f"  vision_trigger_service : {self.vision_trigger_service}\n"
            f"  objects_json_topic     : {self.objects_json_topic}\n"
            f"  enable_map_confirm     : {self.enable_map_confirm}\n"
            f"  records_save_path      : {self.records_save_path}\n"
            "  services:\n"
            "    /task/detect_here\n"
            "    /task/go_to_point_and_detect\n"
            "    /main_policy/next\n"
            "    /main_policy/start\n"
            "    /main_policy/stop\n"
            "    /main_policy/reset\n"
            "    /main_policy/status\n"
            "    /main_policy/export_records"
        )

        if self.auto_start:
            self.get_logger().info(
                f"auto_start enabled, will start after {self.start_delay_s:.1f}s"
            )
            self.auto_timer = threading.Timer(
                self.start_delay_s,
                self.start_auto_thread,
            )
            self.auto_timer.daemon = True
            self.auto_timer.start()

    # ============================================================
    # Waypoint loading
    # ============================================================
    def _load_waypoints(self, yaml_file: str) -> Tuple[str, list[dict[str, Any]]]:
        path = Path(yaml_file)

        if not path.exists():
            raise FileNotFoundError(f"Waypoint YAML not found: {yaml_file}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise RuntimeError(f"Waypoint YAML is empty: {yaml_file}")

        frame_id = data.get("frame_id", "map")
        waypoints = data.get("waypoints", [])

        if not waypoints:
            raise RuntimeError(f"No waypoints found in YAML: {yaml_file}")

        return frame_id, waypoints

    def _get_wp_id(self, index: int, wp: dict[str, Any]) -> str:
        return str(wp.get("id", f"wp_{index:03d}"))

    # ============================================================
    # ROS callbacks
    # ============================================================
    def _objects_cb(self, msg: String):
        with self._objects_lock:
            self._latest_objects_raw = msg.data
            self._latest_objects_stamp = time.time()

    # ============================================================
    # Public services: old version
    # ============================================================
    def handle_detect_here(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        ok, summary, raw = self._run_vision_once()

        response.success = ok
        response.message = summary
        return response

    def handle_go_to_point_and_detect(
        self,
        request: NavToPoint.Request,
        response: NavToPoint.Response,
    ) -> NavToPoint.Response:
        self.get_logger().info(
            f"[TASK] go_to_point_and_detect: "
            f"x={request.x:.3f}, y={request.y:.3f}, "
            f"use_yaw={request.use_yaw}, yaw={request.yaw:.3f}"
        )

        nav_ok, nav_msg, nav_res = self._call_nav_to_point(request)

        if not nav_ok:
            response.success = False
            response.message = f"Navigation failed: {nav_msg}"
            response.final_x = request.x
            response.final_y = request.y
            response.final_yaw = request.yaw
            return response

        time.sleep(self.pause_after_nav_s)

        vision_ok, vision_summary, raw = self._run_vision_once()

        response.success = vision_ok
        response.message = (
            f"Navigation done. Nav: {nav_msg}. Vision: {vision_summary}"
        )

        if nav_res is not None:
            response.final_x = nav_res.final_x
            response.final_y = nav_res.final_y
            response.final_yaw = nav_res.final_yaw
        else:
            response.final_x = request.x
            response.final_y = request.y
            response.final_yaw = request.yaw

        return response

    # ============================================================
    # Public services: waypoint main policy
    # ============================================================
    def handle_next(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        mode_ok, mode_msg = self._ensure_mapping_mode()
        if not mode_ok:
            response.success = False
            response.message = mode_msg
            return response
        with self.lock:
            if self.running:
                response.success = False
                response.message = "Auto mode is running. Stop it before manual next."
                return response

            if self.manual_running:
                response.success = False
                response.message = "Manual waypoint is already running."
                return response

            if self.current_index >= len(self.waypoints):
                response.success = False
                response.message = "All waypoints finished."
                return response

            self.manual_running = True
            self.stop_requested = False

        try:
            ok, msg = self.run_current_waypoint()
            response.success = ok
            response.message = msg
            return response

        finally:
            with self.lock:
                self.manual_running = False

    def handle_start(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        mode_ok, mode_msg = self._ensure_mapping_mode()
        if not mode_ok:
            response.success = False
            response.message = mode_msg
            return response
        with self.lock:
            if self.running:
                response.success = False
                response.message = "Auto mode already running."
                return response

            if self.manual_running:
                response.success = False
                response.message = "Manual waypoint is running."
                return response

            if self.current_index >= len(self.waypoints):
                response.success = False
                response.message = "All waypoints already finished. Reset first."
                return response

            self.stop_requested = False

        self.start_auto_thread()

        response.success = True
        response.message = "Main policy auto waypoint task started."
        return response

    def handle_stop(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        self.stop_requested = True
        cancel_ok = self._cancel_active_flow_goal()
        self._publish_mapping_status(
            "CANCELED", "STOPPED", 1.0, False, "Mapping stop requested"
        )
        response.success = cancel_ok
        response.message = (
            "Stop requested and underlying Robot Flow cancellation requested."
            if cancel_ok
            else "Stop requested, but underlying Robot Flow cancellation failed."
        )
        return response

    def handle_reset(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        with self.lock:
            if self.running or self.manual_running:
                response.success = False
                response.message = "Task is running. Stop/wait before reset."
                return response

            self.current_index = 0
            self.success_count = 0
            self.failed_count = 0
            self.records.clear()
            self.last_message = "reset"

        response.success = True
        response.message = "Main policy index and records reset."
        return response

    def handle_status(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        with self.lock:
            status = {
                "running": self.running,
                "manual_running": self.manual_running,
                "stop_requested": self.stop_requested,
                "waypoint_yaml": self.waypoint_yaml,
                "frame_id": self.frame_id,
                "total_waypoints": len(self.waypoints),
                "current_index": self.current_index,
                "remaining": max(0, len(self.waypoints) - self.current_index),
                "success_count": self.success_count,
                "failed_count": self.failed_count,
                "records_count": len(self.records),
                "last_message": self.last_message,
            }

        response.success = True
        response.message = json.dumps(status, ensure_ascii=False, indent=2)
        return response

    def handle_export_records(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        try:
            out_path = self._export_records_snapshot()
            response.success = True
            response.message = f"Records exported: {out_path}"
        except OSError as e:
            response.success = False
            response.message = f"Export records failed: {e}"

        return response


    def handle_import_records(
        self,
        request: Trigger.Request,
        response: Trigger.Response,
    ) -> Trigger.Response:
        """
        Main version:
        read main_policy_records.jsonl, convert to semantic-map snapshot,
        then call /semantic_map/import.
        """
        if not self.enable_db_import:
            response.success = False
            response.message = "DB import disabled: enable_db_import=false"
            return response

        with self.lock:
            if self.running or self.manual_running:
                response.success = False
                response.message = (
                    "Task is running. Stop/wait before importing records."
                )
                return response

        try:
            records = self._load_records_for_import()
            snapshot, stats = self._build_semantic_map_snapshot_from_records(records)

            if not snapshot.get("objects"):
                response.success = False
                response.message = json.dumps(
                    {
                        "error": "no valid objects to import",
                        "records_path": self.records_save_path,
                        "stats": stats,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                return response

            if not self.semantic_import_client.wait_for_service(timeout_sec=5.0):
                response.success = False
                response.message = (
                    f"{self.semantic_import_service} service not available"
                )
                return response

            req = ImportSemanticMap.Request()
            req.json_payload = json.dumps(snapshot, ensure_ascii=False)
            req.mode = self.semantic_import_mode

            self.get_logger().info(
                "[MAIN_POLICY] import_records: "
                f"mode={req.mode}, objects={len(snapshot['objects'])}, "
                f"service={self.semantic_import_service}"
            )

            future = self.semantic_import_client.call_async(req)

            start = time.time()
            while rclpy.ok():
                if future.done():
                    break

                if time.time() - start > self.semantic_import_timeout_s:
                    response.success = False
                    response.message = "semantic import service timeout"
                    return response

                time.sleep(0.05)

            if future.result() is None:
                exc = future.exception()
                response.success = False
                response.message = (
                    f"semantic import exception: {exc}"
                    if exc else "semantic import result is None"
                )
                return response

            res = future.result()

            response.success = bool(res.success)
            response.message = json.dumps(
                {
                    "success": bool(res.success),
                    "message": str(res.message),
                    "error_type": str(res.error_type),
                    "mode": self.semantic_import_mode,
                    "frame_id": str(res.frame_id),
                    "source_next_id": int(res.source_next_id),
                    "object_count": int(res.object_count),
                    "records_path": self.records_save_path,
                    "stats": stats,
                },
                ensure_ascii=False,
                indent=2,
            )

            self.last_message = (
                f"import_records success={res.success}, "
                f"objects={res.object_count}, mode={self.semantic_import_mode}"
            )

            return response

        except Exception as e:
            self.get_logger().error(f"Import records failed: {e}")
            response.success = False
            response.message = f"Import records failed: {e}"
            return response

    # ============================================================
    # Auto loop
    # ============================================================
    def start_auto_thread(self):
        with self.lock:
            if self.running:
                return

            self.running = True
            self.stop_requested = False
            self._mapping_task_id = str(uuid.uuid4())

        self.auto_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self.auto_thread.start()

    def auto_loop(self):
        self.get_logger().info("[MAIN_POLICY] auto loop started")

        try:
            while rclpy.ok():
                if self.stop_requested:
                    self.get_logger().warn("[MAIN_POLICY] stop requested")
                    break

                if self.current_index >= len(self.waypoints):
                    self.get_logger().info("[MAIN_POLICY] all waypoints finished")
                    break

                ok, msg = self.run_current_waypoint()
                self.get_logger().info(f"[MAIN_POLICY] waypoint result: {msg}")

                if not ok and not self.skip_on_fail:
                    self.get_logger().error(
                        "[MAIN_POLICY] failed and skip_on_fail=false, stop auto loop"
                    )
                    break

                time.sleep(self.pause_after_vision_s)

        finally:
            with self.lock:
                self.running = False

            self.get_logger().info("[MAIN_POLICY] auto loop ended")

    # ============================================================
    # Core task
    # ============================================================
    def run_current_waypoint(self) -> Tuple[bool, str]:
        if self.current_index >= len(self.waypoints):
            return False, "All waypoints finished."

        index = self.current_index
        wp = self.waypoints[index]
        wp_id = self._get_wp_id(index, wp)

        try:
            x = float(wp["x"])
            y = float(wp["y"])
            yaw = float(wp.get("yaw", 0.0))
        except (KeyError, TypeError, ValueError) as e:
            msg = f"Invalid waypoint {wp_id}: {e}"
            self._record_result(
                index=index,
                wp=wp,
                status="invalid_waypoint",
                nav_success=False,
                nav_message=msg,
                vision_success=False,
                vision_summary="not executed",
                objects_raw=None,
            )
            self.failed_count += 1

            if self.skip_on_fail:
                self.current_index += 1

            self.last_message = msg
            return False, msg

        self.get_logger().info(
            f"[MAIN_POLICY] waypoint {index + 1}/{len(self.waypoints)} "
            f"id={wp_id}, x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}"
        )
        self._publish_mapping_status(
            "LOADING_WAYPOINT",
            f"WAYPOINT_{index + 1}",
            index / max(1, len(self.waypoints)),
            True,
            f"Loading waypoint {wp_id}",
            {"waypoint_id": wp_id, "index": index},
        )

        nav_req = NavToPoint.Request()
        nav_req.x = x
        nav_req.y = y
        nav_req.use_yaw = self.use_yaw
        nav_req.yaw = yaw

        nav_ok, nav_msg, nav_res = self._call_nav_to_point(nav_req)

        if not nav_ok:
            msg = f"Waypoint {wp_id} navigation failed: {nav_msg}"

            self._record_result(
                index=index,
                wp=wp,
                status="nav_failed",
                nav_success=False,
                nav_message=nav_msg,
                vision_success=False,
                vision_summary="not executed",
                objects_raw=None,
                nav_res=nav_res,
            )

            self.failed_count += 1

            if self.skip_on_fail:
                self.current_index += 1

            self.last_message = msg
            return False, msg

        time.sleep(self.pause_after_nav_s)

        self._publish_mapping_status(
            "WAITING_VISION", "WAITING_DETECT_ONCE", 0.7, True,
            "Waiting for vision", {"waypoint_id": wp_id},
        )
        vision_ok, vision_summary, objects_raw = self._run_vision_once()

        map_confirm_msg = ""
        if self.enable_map_confirm:
            self._publish_mapping_status(
                "UPDATING_SEMANTIC_MAP", "MAP_CONFIRM", 0.9, True,
                "Updating semantic map", {"waypoint_id": wp_id},
            )
            confirm_ok, confirm_msg = self._call_map_confirm()
            map_confirm_msg = f" map_confirm={confirm_ok}: {confirm_msg}"

        status = "done" if vision_ok else "vision_failed"

        self._record_result(
            index=index,
            wp=wp,
            status=status,
            nav_success=True,
            nav_message=nav_msg,
            vision_success=vision_ok,
            vision_summary=vision_summary,
            objects_raw=objects_raw,
            nav_res=nav_res,
            map_confirm_message=map_confirm_msg,
        )

        if vision_ok:
            self.success_count += 1
        else:
            self.failed_count += 1

        self.current_index += 1

        msg = (
            f"Waypoint {wp_id} done. "
            f"Nav: {nav_msg}. "
            f"Vision: {vision_summary}."
            f"{map_confirm_msg}"
        )

        self.last_message = msg
        next_state = (
            "SUCCEEDED"
            if self.current_index >= len(self.waypoints)
            else "NEXT_WAYPOINT"
        )
        self._publish_mapping_status(
            next_state,
            "WAYPOINT_COMPLETE",
            self.current_index / max(1, len(self.waypoints)),
            self.current_index < len(self.waypoints),
            msg,
            {"waypoint_id": wp_id, "vision_success": vision_ok},
        )
        return vision_ok, msg

    # ============================================================
    # Nav helper
    # ============================================================
    def _call_nav_to_point(self, nav_req: NavToPoint.Request):
        if self.prefer_robot_flow:
            flow_result = self._call_robot_flow_nav(nav_req)
            if flow_result is not None:
                return flow_result
            self.get_logger().warn(
                f"{self.robot_flow_action} unavailable; falling back to {self.nav_service}"
            )
        if not self.nav_client.wait_for_service(timeout_sec=5.0):
            return False, "/nav_to_point service not available", None

        future = self.nav_client.call_async(nav_req)

        start = time.time()
        while rclpy.ok():
            if future.done():
                break

            if time.time() - start > self.nav_timeout_s:
                return False, "nav service timeout", None

            time.sleep(0.05)

        if future.result() is None:
            exc = future.exception()
            if exc:
                return False, f"nav exception: {exc}", None
            return False, "nav result is None", None

        res = future.result()
        return bool(res.success), str(res.message), res

    def _call_robot_flow_nav(self, nav_req: NavToPoint.Request):
        if not self.flow_client.wait_for_server(
            timeout_sec=self.robot_flow_server_timeout_s
        ):
            return None
        goal = ExecuteRobotTask.Goal()
        goal.task_type = "navigate"
        goal.json_payload = json.dumps(
            {
                "x": float(nav_req.x),
                "y": float(nav_req.y),
                "yaw": float(nav_req.yaw),
                "frame_id": "map",
                "_requester_mode": "BUILD_SEMANTIC_MAP",
            },
            allow_nan=False,
        )
        send_future = self.flow_client.send_goal_async(goal)
        deadline = time.monotonic() + self.robot_flow_server_timeout_s
        while rclpy.ok() and not send_future.done():
            if self.stop_requested or time.monotonic() >= deadline:
                return False, "robot flow goal acceptance timeout/canceled", None
            time.sleep(0.02)
        handle = send_future.result()
        if handle is None or not handle.accepted:
            return False, "robot flow goal rejected", None
        with self._active_flow_lock:
            self._active_flow_goal = handle
        result_future = handle.get_result_async()
        deadline = time.monotonic() + self.nav_timeout_s
        while rclpy.ok() and not result_future.done():
            if self.stop_requested:
                handle.cancel_goal_async()
            if time.monotonic() >= deadline:
                handle.cancel_goal_async()
                with self._active_flow_lock:
                    self._active_flow_goal = None
                return False, "robot flow navigation timeout", None
            time.sleep(0.02)
        with self._active_flow_lock:
            self._active_flow_goal = None
        wrapped = result_future.result()
        if wrapped is None:
            return False, "robot flow result unavailable", None
        result = wrapped.result
        detail = {}
        try:
            detail = json.loads(result.json_result or "{}")
        except json.JSONDecodeError:
            pass
        pose = detail.get("current_pose", {})
        compat = SimpleNamespace(
            final_x=float(pose.get("x", nav_req.x)),
            final_y=float(pose.get("y", nav_req.y)),
            final_yaw=float(pose.get("yaw", nav_req.yaw)),
        )
        return bool(result.success), str(result.message), compat

    def _cancel_active_flow_goal(self) -> bool:
        with self._active_flow_lock:
            handle = self._active_flow_goal
        if handle is None:
            return True
        try:
            future = handle.cancel_goal_async()
            deadline = time.monotonic() + 5.0
            while not future.done() and time.monotonic() < deadline:
                time.sleep(0.02)
            return bool(future.done() and future.result().goals_canceling)
        except Exception as exc:
            self.get_logger().error(f"Robot Flow cancel failed: {exc}")
            return False

    def _ensure_mapping_mode(self) -> Tuple[bool, str]:
        if not self.mode_client.wait_for_service(timeout_sec=2.0):
            return False, "/robot_mode/set service not available"
        request = SetRobotMode.Request()
        request.mode = "BUILD_SEMANTIC_MAP"
        future = self.mode_client.call_async(request)
        deadline = time.monotonic() + 5.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done() or future.result() is None:
            return False, "mode change timeout"
        response = future.result()
        return bool(response.success), str(response.message)

    def _publish_mapping_status(
        self, state, step, progress, busy, message, detail=None
    ) -> None:
        msg = RobotFlowStatus()
        msg.stamp = self.get_clock().now().to_msg()
        msg.task_id = self._mapping_task_id
        msg.mode = "BUILD_SEMANTIC_MAP"
        msg.task_type = "semantic_mapping"
        msg.state = state
        msg.step = step
        msg.progress = float(progress)
        msg.busy = bool(busy)
        msg.message = str(message)
        msg.json_detail = json.dumps(detail or {}, ensure_ascii=False, allow_nan=False)
        self.flow_status_pub.publish(msg)

    # ============================================================
    # Vision helper
    # ============================================================
    def _run_vision_once(self) -> Tuple[bool, str, Optional[str]]:
        if not self.vision_client.wait_for_service(
            timeout_sec=self.vision_service_timeout_s
        ):
            return False, "/grounding_dino/detect_once service not available", None

        with self._objects_lock:
            old_stamp = self._latest_objects_stamp

        self.get_logger().info("[MAIN_POLICY] trigger vision detect_once")
        self._publish_mapping_status(
            "DETECTING_OBJECTS", "DETECT_ONCE", 0.8, True,
            "Detecting objects",
        )

        future = self.vision_client.call_async(Trigger.Request())

        start = time.time()
        while rclpy.ok():
            if future.done():
                break

            if time.time() - start > self.vision_service_timeout_s:
                return False, "vision trigger service timeout", None

            time.sleep(0.05)

        if future.result() is None:
            exc = future.exception()
            if exc:
                return False, f"vision trigger exception: {exc}", None
            return False, "vision trigger result is None", None

        trig_res = future.result()
        if not trig_res.success:
            self.get_logger().warn(
                f"vision trigger returned false: {trig_res.message}"
            )

        wait_start = time.time()
        while rclpy.ok():
            with self._objects_lock:
                got_new = (
                    self._latest_objects_raw is not None
                    and self._latest_objects_stamp > old_stamp
                )
                raw = self._latest_objects_raw

            if got_new:
                return True, self._summarize_objects(raw), raw

            if time.time() - wait_start > self.objects_wait_timeout_s:
                return False, "timeout waiting for objects_3d_json", None

            time.sleep(0.05)

        return False, "rclpy stopped while waiting vision result", None

    def _summarize_objects(self, raw: Optional[str]) -> str:
        if not raw:
            return "no objects json"

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "objects json decode failed"

        objects = data.get("objects", [])
        if not objects:
            return "detected 0 objects"

        texts = []
        for obj in objects[:8]:
            cls = obj.get("class", "unknown")
            score = obj.get("score", None)
            bp = obj.get("base_point", {})

            try:
                x = float(bp.get("x", 0.0))
                y = float(bp.get("y", 0.0))
            except (TypeError, ValueError):
                x, y = 0.0, 0.0

            if score is None:
                texts.append(f"{cls}@({x:.2f},{y:.2f})")
            else:
                texts.append(f"{cls}:{float(score):.2f}@({x:.2f},{y:.2f})")

        return f"detected {len(objects)} objects: " + ", ".join(texts)

    # ============================================================
    # Optional map builder confirm
    # ============================================================
    def _call_map_confirm(self) -> Tuple[bool, str]:
        if not self.map_confirm_client.wait_for_service(timeout_sec=3.0):
            return False, "/semantic_map/confirm service not available"

        future = self.map_confirm_client.call_async(Trigger.Request())

        start = time.time()
        while rclpy.ok():
            if future.done():
                break

            if time.time() - start > self.map_confirm_timeout_s:
                return False, "map confirm timeout"

            time.sleep(0.05)

        if future.result() is None:
            exc = future.exception()
            if exc:
                return False, f"map confirm exception: {exc}"
            return False, "map confirm result is None"

        res = future.result()
        return bool(res.success), str(res.message)

    # ============================================================
    # Records
    # ============================================================
    def _record_result(
        self,
        index: int,
        wp: dict[str, Any],
        status: str,
        nav_success: bool,
        nav_message: str,
        vision_success: bool,
        vision_summary: str,
        objects_raw: Optional[str],
        nav_res: Any = None,
        map_confirm_message: str = "",
    ):
        wp_id = self._get_wp_id(index, wp)

        object_count = 0
        objects_compact = []

        if objects_raw:
            try:
                data = json.loads(objects_raw)
                objs = data.get("objects", [])
                object_count = len(objs)
                for obj in objs[:20]:
                    bp = obj.get("base_point", {})
                    objects_compact.append({
                        "class": obj.get("class", "unknown"),
                        "score": obj.get("score", None),
                        "x": bp.get("x", None),
                        "y": bp.get("y", None),
                        "z": bp.get("z", None),
                    })
            except json.JSONDecodeError:
                pass

        record = {
            "time": time.time(),
            "status": status,
            "index": index,
            "seq": index + 1,
            "id": wp_id,
            "source_node_id": wp.get("source_node_id", "unknown"),
            "target": {
                "x": float(wp.get("x", 0.0)),
                "y": float(wp.get("y", 0.0)),
                "yaw": float(wp.get("yaw", 0.0)),
            },
            "nav": {
                "success": nav_success,
                "message": nav_message,
                "final_x": getattr(nav_res, "final_x", None),
                "final_y": getattr(nav_res, "final_y", None),
                "final_yaw": getattr(nav_res, "final_yaw", None),
            },
            "vision": {
                "success": vision_success,
                "summary": vision_summary,
                "object_count": object_count,
                "objects": objects_compact,
            },
            "map_confirm": map_confirm_message,
        }

        self.records.append(record)
        self._append_record_jsonl(record)

    def _append_record_jsonl(self, record: dict[str, Any]):
        path = Path(self.records_save_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _export_records_snapshot(self) -> str:
        base = Path(self.records_save_path)
        base.parent.mkdir(parents=True, exist_ok=True)

        out_path = base.with_suffix(".snapshot.json")

        data = {
            "waypoint_yaml": self.waypoint_yaml,
            "frame_id": self.frame_id,
            "total_waypoints": len(self.waypoints),
            "current_index": self.current_index,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "records": self.records,
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(out_path)


    def _load_records_for_import(self) -> list[dict[str, Any]]:
        """
        Prefer JSONL file because it survives node restart.
        Fallback to in-memory records.
        """
        path = Path(self.records_save_path)
        records: list[dict[str, Any]] = []

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        self.get_logger().warn(
                            f"Skip invalid JSONL line {line_no} in {path}"
                        )

        if not records:
            records = list(self.records)

        return records

    def _normalize_class_name(self, raw: Any) -> str:
        cls = " ".join(str(raw or "unknown").lower().strip().split())

        mapping = {
            "hood exhaust hood": "hood",
            "exhaust hood": "hood",
            "table counter kitchen counter": "counter",
            "table counter kitchen": "counter",
            "table counter": "counter",
            "counter kitchen counter cabinet": "counter",
            "counter kitchen counter": "counter",
            "kitchen counter door": "counter",
            "cabinet door": "cabinet",
            "chair sofa": "chair",
            "chair table": "chair",
            "bottle cup": "cup",
        }

        return mapping.get(cls, cls)

    def _build_semantic_map_snapshot_from_records(
        self,
        records: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        objects: list[dict[str, Any]] = []

        stats = {
            "records_total": len(records),
            "records_used": 0,
            "records_skipped_nav_failed": 0,
            "records_skipped_vision_failed": 0,
            "objects_total": 0,
            "objects_imported": 0,
            "objects_skipped_low_score": 0,
            "objects_skipped_bad_xyz": 0,
            "objects_skipped_bad_z": 0,
            "objects_skipped_far_from_wp": 0,
        }

        used_ids: set[str] = set()

        for rec in records:
            nav = rec.get("nav", {})
            vision = rec.get("vision", {})
            target = rec.get("target", {})

            if not nav.get("success", False):
                stats["records_skipped_nav_failed"] += 1
                continue

            if not vision.get("success", False):
                stats["records_skipped_vision_failed"] += 1
                continue

            stats["records_used"] += 1

            rec_id = str(rec.get("id", f"record_{rec.get('index', 0)}"))
            rec_index = int(rec.get("index", 0))

            try:
                tx = float(target.get("x", 0.0))
                ty = float(target.get("y", 0.0))
                tyaw = float(target.get("yaw", 0.0))
            except (TypeError, ValueError):
                tx, ty, tyaw = 0.0, 0.0, 0.0

            raw_objects = vision.get("objects", [])
            raw_objects = raw_objects[: self.semantic_import_max_objects_per_record]

            for obj_i, obj in enumerate(raw_objects):
                stats["objects_total"] += 1

                try:
                    score = float(obj.get("score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0

                if score < self.semantic_import_min_score:
                    stats["objects_skipped_low_score"] += 1
                    continue

                try:
                    x = float(obj.get("x"))
                    y = float(obj.get("y"))
                    z = float(obj.get("z"))
                except (TypeError, ValueError):
                    stats["objects_skipped_bad_xyz"] += 1
                    continue

                if not all(math.isfinite(v) for v in (x, y, z)):
                    stats["objects_skipped_bad_xyz"] += 1
                    continue

                if z < self.semantic_import_min_z or z > self.semantic_import_max_z:
                    stats["objects_skipped_bad_z"] += 1
                    continue

                if self.semantic_import_max_dist_from_wp > 0.0:
                    dist = math.hypot(x - tx, y - ty)
                    if dist > self.semantic_import_max_dist_from_wp:
                        stats["objects_skipped_far_from_wp"] += 1
                        continue

                class_name = self._normalize_class_name(obj.get("class", "unknown"))
                if not class_name:
                    class_name = "unknown"

                source_id = f"{rec_id}_obj_{obj_i:02d}"
                if source_id in used_ids:
                    source_id = f"{source_id}_r{rec_index:04d}"

                used_ids.add(source_id)

                objects.append(
                    {
                        "id": source_id,
                        "class": class_name,
                        "confidence": score,
                        "position": {
                            "x": x,
                            "y": y,
                            "z": z,
                        },
                        "metadata": {
                            "source": "main_policy",
                            "record_id": rec_id,
                            "record_index": rec_index,
                            "raw_class": obj.get("class", "unknown"),
                            "waypoint": {
                                "x": tx,
                                "y": ty,
                                "yaw": tyaw,
                            },
                        },
                    }
                )

                stats["objects_imported"] += 1

        snapshot = {
            "frame_id": self.frame_id,
            "next_id": len(objects),
            "objects": objects,
        }

        return snapshot, stats

    # ============================================================
    # Cleanup
    # ============================================================
    def destroy_node(self):
        self.stop_requested = True
        self._cancel_active_flow_goal()

        if self.auto_timer is not None:
            try:
                self.auto_timer.cancel()
            except Exception:
                pass

        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    node = RobotTaskOrchestrator()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        node.stop_requested = True
    finally:
        try:
            executor.shutdown()
        except Exception:
            pass

        try:
            node.destroy_node()
        except Exception:
            pass

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
