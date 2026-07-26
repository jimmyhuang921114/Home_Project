#!/usr/bin/env python3
"""Aggregate a consistent, hardware-tolerant robot state JSON snapshot."""

from __future__ import annotations

import json
import math
import threading
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

from semantic_nav_interfaces.msg import RobotFlowStatus


class RobotStateNode(Node):
    def __init__(self) -> None:
        super().__init__("robot_state_node")
        self.declare_parameter("publish_rate_hz", 5.0)
        self.declare_parameter("pose_stale_s", 2.0)
        self.declare_parameter("joint_state_stale_s", 2.0)
        self.declare_parameter("arm_enabled", False)
        self._pose_stale_s = float(self.get_parameter("pose_stale_s").value)
        self._joint_stale_s = float(self.get_parameter("joint_state_stale_s").value)
        self._arm_enabled = bool(self.get_parameter("arm_enabled").value)
        self._lock = threading.RLock()
        self._cbg = ReentrantCallbackGroup()
        self._mode = "IDLE"
        self._flow = {
            "task_id": "", "task_type": "", "state": "IDLE",
            "step": "WAITING_COMMAND", "progress": 0.0, "message": "",
        }
        self._busy = False
        self._pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self._pose_frame = "map"
        self._pose_source = ""
        self._pose_updated = 0.0
        self._joints = {"joint_names": [], "positions": [], "velocities": [], "efforts": []}
        self._joints_updated = 0.0
        self._nav_detail = {}
        self._errors: list[dict] = []

        self.create_subscription(
            JointState, "/joint_states", self._joints_cb, 20, callback_group=self._cbg
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self._amcl_cb,
            10,
            callback_group=self._cbg,
        )
        self.create_subscription(
            Odometry, "/odom", self._odom_cb, 20, callback_group=self._cbg
        )
        self.create_subscription(
            RobotFlowStatus,
            "/robot_flow/status",
            self._flow_cb,
            20,
            callback_group=self._cbg,
        )
        self.create_subscription(
            String, "/robot_mode/status", self._mode_cb, 10, callback_group=self._cbg
        )
        self._publisher = self.create_publisher(String, "/robot/state_json", 10)
        rate = max(0.1, float(self.get_parameter("publish_rate_hz").value))
        self.create_timer(1.0 / rate, self._publish, callback_group=self._cbg)

    @staticmethod
    def _yaw(q) -> float:
        return math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )

    def _amcl_cb(self, msg) -> None:
        pose = msg.pose.pose
        with self._lock:
            self._pose = {"x": pose.position.x, "y": pose.position.y, "yaw": self._yaw(pose.orientation)}
            self._pose_frame = msg.header.frame_id or "map"
            self._pose_source = "amcl_pose"
            self._pose_updated = time.time()

    def _odom_cb(self, msg) -> None:
        with self._lock:
            if self._pose_source == "amcl_pose" and time.time() - self._pose_updated <= self._pose_stale_s:
                return
            pose = msg.pose.pose
            self._pose = {"x": pose.position.x, "y": pose.position.y, "yaw": self._yaw(pose.orientation)}
            self._pose_frame = msg.header.frame_id or "odom"
            self._pose_source = "odom"
            self._pose_updated = time.time()

    def _joints_cb(self, msg) -> None:
        with self._lock:
            self._joints = {
                "joint_names": list(msg.name),
                "positions": list(msg.position),
                "velocities": list(msg.velocity),
                "efforts": list(msg.effort),
            }
            self._joints_updated = time.time()

    def _mode_cb(self, msg) -> None:
        try:
            value = json.loads(msg.data)
            mode = str(value.get("mode", "IDLE"))
        except (json.JSONDecodeError, AttributeError):
            mode = str(msg.data)
        with self._lock:
            self._mode = mode

    def _flow_cb(self, msg) -> None:
        try:
            detail = json.loads(msg.json_detail or "{}")
        except json.JSONDecodeError:
            detail = {}
        with self._lock:
            self._busy = bool(msg.busy)
            self._flow = {
                "task_id": msg.task_id,
                "task_type": msg.task_type,
                "state": msg.state,
                "step": msg.step,
                "progress": float(msg.progress),
                "message": msg.message,
            }
            self._nav_detail = detail if msg.task_type == "navigate" else {}
            if msg.state in {"FAILED", "ERROR"}:
                self._errors.append({
                    "timestamp": time.time(),
                    "state": msg.state,
                    "message": msg.message,
                })
                self._errors = self._errors[-20:]

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            pose_stale = self._pose_updated == 0.0 or now - self._pose_updated > self._pose_stale_s
            joint_stale = self._joints_updated == 0.0 or now - self._joints_updated > self._joint_stale_s
            current_pose = self._nav_detail.get("current_pose")
            pose = dict(self._pose)
            frame = self._pose_frame
            if isinstance(current_pose, dict):
                pose = {
                    "x": float(current_pose.get("x", pose["x"])),
                    "y": float(current_pose.get("y", pose["y"])),
                    "yaw": float(current_pose.get("yaw", pose["yaw"])),
                }
                frame = str(current_pose.get("frame_id", frame))
                pose_stale = False
            return {
                "timestamp": now,
                "mode": self._mode,
                "busy": self._busy,
                "task": dict(self._flow),
                "navigation": {
                    "available": self._pose_updated > 0.0 or bool(current_pose),
                    "active": self._busy and self._flow["task_type"] == "navigate",
                    "frame_id": frame,
                    "pose": pose,
                    "distance_remaining": self._nav_detail.get("distance_remaining"),
                    "navigation_time": self._nav_detail.get("navigation_time"),
                    "number_of_recoveries": self._nav_detail.get("number_of_recoveries"),
                    "last_update": self._pose_updated or None,
                    "stale": pose_stale,
                },
                "arm": {
                    "available": self._arm_enabled and self._joints_updated > 0.0,
                    "active": self._busy and self._flow["task_type"] in {
                        "arm_joints", "arm_named_pose", "gripper",
                    },
                    **dict(self._joints),
                    "last_update": self._joints_updated or None,
                    "stale": joint_stale,
                },
                "errors": list(self._errors),
            }

    def _publish(self) -> None:
        msg = String()
        msg.data = json.dumps(
            self.snapshot(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        self._publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = RobotStateNode()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
