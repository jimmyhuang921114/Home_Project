#!/usr/bin/env python3
"""Mutually exclusive robot operating-mode manager."""

from __future__ import annotations

import json
import threading
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger

from semantic_nav_interfaces.msg import RobotFlowStatus
from semantic_nav_interfaces.srv import SetRobotMode


MODES = {"IDLE", "BUILD_SEMANTIC_MAP", "USER_TASK", "ERROR"}


class RobotModeManager(Node):
    def __init__(self) -> None:
        super().__init__("robot_mode_manager_node")
        self.declare_parameter("default_mode", "IDLE")
        self.declare_parameter("cancel_timeout_s", 10.0)
        requested = str(self.get_parameter("default_mode").value).upper()
        self._mode = requested if requested in MODES else "IDLE"
        self._cancel_timeout = float(self.get_parameter("cancel_timeout_s").value)
        self._busy = False
        self._task_state = "IDLE"
        self._lock = threading.RLock()
        self._cbg = ReentrantCallbackGroup()

        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._publisher = self.create_publisher(String, "/robot_mode/status", qos)
        self._cancel_client = self.create_client(
            Trigger, "/robot_flow/cancel_current", callback_group=self._cbg
        )
        self._mapping_stop_client = self.create_client(
            Trigger, "/main_policy/stop", callback_group=self._cbg
        )
        self.create_subscription(
            RobotFlowStatus,
            "/robot_flow/status",
            self._flow_cb,
            20,
            callback_group=self._cbg,
        )
        self.create_service(
            SetRobotMode, "/robot_mode/set", self._set_cb, callback_group=self._cbg
        )
        self.create_service(
            Trigger, "/robot_mode/status", self._status_cb, callback_group=self._cbg
        )
        self.create_service(
            Trigger, "/robot_mode/stop", self._stop_cb, callback_group=self._cbg
        )
        self.create_service(
            Trigger, "/robot_mode/reset", self._reset_cb, callback_group=self._cbg
        )
        self.create_timer(0.5, self._publish, callback_group=self._cbg)
        self._publish()

    def _flow_cb(self, msg: RobotFlowStatus) -> None:
        with self._lock:
            self._busy = bool(msg.busy)
            self._task_state = str(msg.state)

    def _snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode,
                "busy": self._busy,
                "task_state": self._task_state,
                "allowed_modes": sorted(MODES),
            }

    def _publish(self) -> None:
        msg = String()
        msg.data = json.dumps(self._snapshot(), ensure_ascii=False)
        self._publisher.publish(msg)

    def _status_cb(self, request, response):
        response.success = True
        response.message = json.dumps(self._snapshot(), ensure_ascii=False)
        return response

    def _set_cb(self, request, response):
        target = str(request.mode).upper().strip()
        with self._lock:
            original = self._mode
            busy = self._busy
        response.current_mode = original
        if target not in MODES:
            response.success = False
            response.message = f"INVALID_MODE: {target}"
            return response
        if original == "ERROR" and target != "ERROR":
            response.success = False
            response.message = "ERROR_REQUIRES_RESET"
            return response
        if target == original:
            response.success = True
            response.message = "Mode unchanged"
            return response
        if busy:
            ok, message = self._cancel_and_wait()
            if not ok:
                response.success = False
                response.current_mode = original
                response.message = message
                return response
        with self._lock:
            if self._busy:
                response.success = False
                response.current_mode = original
                response.message = "ROBOT_BUSY"
                return response
            self._mode = target
        self._publish()
        response.success = True
        response.current_mode = target
        response.message = f"Mode changed from {original} to {target}"
        return response

    def _stop_cb(self, request, response):
        with self._lock:
            busy = self._busy
        if not busy:
            response.success = True
            response.message = "No active motion"
            return response
        response.success, response.message = self._cancel_and_wait()
        return response

    def _reset_cb(self, request, response):
        with self._lock:
            if self._busy:
                response.success = False
                response.message = "ROBOT_BUSY"
                return response
            self._mode = "IDLE"
            self._task_state = "IDLE"
        self._publish()
        response.success = True
        response.message = "Mode reset to IDLE"
        return response

    def _cancel_and_wait(self) -> tuple[bool, str]:
        with self._lock:
            mode = self._mode
        if mode == "BUILD_SEMANTIC_MAP":
            if not self._mapping_stop_client.wait_for_service(timeout_sec=2.0):
                return False, "MAPPING_STOP_SERVICE_UNAVAILABLE"
            mapping_future = self._mapping_stop_client.call_async(Trigger.Request())
            mapping_deadline = time.monotonic() + self._cancel_timeout
            while not mapping_future.done() and time.monotonic() < mapping_deadline:
                time.sleep(0.02)
            if (
                not mapping_future.done()
                or mapping_future.result() is None
                or not mapping_future.result().success
            ):
                return False, "MAPPING_CANCEL_FAILED"
        if not self._cancel_client.wait_for_service(timeout_sec=2.0):
            return False, "CANCEL_SERVICE_UNAVAILABLE"
        future = self._cancel_client.call_async(Trigger.Request())
        deadline = time.monotonic() + self._cancel_timeout
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done() or future.result() is None:
            return False, "CANCEL_REQUEST_FAILED"
        if not future.result().success:
            return False, str(future.result().message)
        while time.monotonic() < deadline:
            with self._lock:
                if not self._busy:
                    return True, "Motion canceled"
            time.sleep(0.02)
        return False, "CANCEL_TIMEOUT"


def main(args=None):
    rclpy.init(args=args)
    node = RobotModeManager()
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
