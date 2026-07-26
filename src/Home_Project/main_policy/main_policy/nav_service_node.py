#!/usr/bin/env python3
"""Legacy /nav_to_point compatibility proxy.

This node intentionally owns no Nav2 ActionClient.  All motion is delegated to
the single-owner /robot_flow/execute action.
"""

from __future__ import annotations

import json
import math
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from semantic_nav_interfaces.action import ExecuteRobotTask
from semantic_nav_interfaces.srv import NavToPoint


class NavServiceNode(Node):
    def __init__(self) -> None:
        super().__init__("nav_service_node")
        self.declare_parameter("robot_flow_action", "/robot_flow/execute")
        self.declare_parameter("server_timeout_s", 5.0)
        self.declare_parameter("nav_timeout", 180.0)
        p = self.get_parameter
        self._timeout = float(p("nav_timeout").value)
        self._server_timeout = float(p("server_timeout_s").value)
        self._mode = "USER_TASK"
        self._busy = False
        self._lock = threading.Lock()
        self._cbg = ReentrantCallbackGroup()
        self._client = ActionClient(
            self,
            ExecuteRobotTask,
            str(p("robot_flow_action").value),
            callback_group=self._cbg,
        )
        self.create_subscription(
            String, "/robot_mode/status", self._mode_cb, 10, callback_group=self._cbg
        )
        self.create_service(
            NavToPoint,
            "/nav_to_point",
            self._service_cb,
            callback_group=self._cbg,
        )
        self.get_logger().info(
            "Legacy /nav_to_point proxy ready; motion owner is /robot_flow/execute"
        )

    def _mode_cb(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            self._mode = str(data.get("mode", self._mode))
        except json.JSONDecodeError:
            self._mode = str(msg.data)

    def _service_cb(self, request, response):
        with self._lock:
            if self._busy:
                response.success = False
                response.message = "ROBOT_BUSY"
                return response
            self._busy = True
        try:
            return self._execute(request, response)
        finally:
            with self._lock:
                self._busy = False

    def _execute(self, request, response):
        values = (float(request.x), float(request.y), float(request.yaw))
        if not all(math.isfinite(value) for value in values):
            response.success = False
            response.message = "INVALID_NAVIGATION_PAYLOAD"
            return response
        if not self._client.wait_for_server(timeout_sec=self._server_timeout):
            response.success = False
            response.message = "ROBOT_FLOW_UNAVAILABLE"
            return response

        goal = ExecuteRobotTask.Goal()
        goal.task_type = "navigate"
        goal.json_payload = json.dumps({
            "x": values[0],
            "y": values[1],
            "yaw": values[2] if request.use_yaw else 0.0,
            "frame_id": "map",
            "_requester_mode": self._mode,
        }, allow_nan=False)
        send_future = self._client.send_goal_async(goal)
        deadline = time.monotonic() + self._server_timeout
        while not send_future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not send_future.done() or send_future.result() is None:
            response.success = False
            response.message = "ROBOT_FLOW_ACCEPT_TIMEOUT"
            return response
        handle = send_future.result()
        if not handle.accepted:
            response.success = False
            response.message = "ROBOT_BUSY"
            return response
        result_future = handle.get_result_async()
        deadline = time.monotonic() + self._timeout
        while not result_future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not result_future.done() or result_future.result() is None:
            handle.cancel_goal_async()
            response.success = False
            response.message = "NAVIGATION_TIMEOUT"
            return response
        result = result_future.result().result
        try:
            detail = json.loads(result.json_result or "{}")
        except json.JSONDecodeError:
            detail = {}
        pose = detail.get("current_pose", {})
        response.success = bool(result.success)
        response.message = str(result.message)
        response.final_x = float(pose.get("x", request.x))
        response.final_y = float(pose.get("y", request.y))
        response.final_yaw = float(pose.get("yaw", request.yaw))
        return response


def main(args=None):
    rclpy.init(args=args)
    node = NavServiceNode()
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
