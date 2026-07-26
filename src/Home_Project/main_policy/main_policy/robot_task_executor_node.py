#!/usr/bin/env python3
"""Single-owner motion task executor for navigation and optional robot arm."""

from __future__ import annotations

import json
import math
import threading
import uuid
from typing import Any

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger

from semantic_nav_interfaces.action import ExecuteRobotTask
from semantic_nav_interfaces.msg import RobotFlowStatus

from .arm_adapter import ArmAdapter, ros_sleep


TASK_TYPES = {"navigate", "arm_joints", "arm_named_pose", "gripper", "stop"}
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "REJECTED", "CANCELED", "ERROR"}
FLOW_STATES = {
    "IDLE", "ACCEPTED", "VALIDATING", "LOADING_WAYPOINT", "WAITING_NAV2",
    "NAVIGATING", "NAVIGATION_SUCCEEDED", "WAITING_VISION",
    "DETECTING_OBJECTS", "UPDATING_SEMANTIC_MAP", "NEXT_WAYPOINT",
    "WAITING_ARM", "ARM_MOVING", "GRIPPER_MOVING", "SUCCEEDED", "FAILED",
    "REJECTED", "CANCELING", "CANCELED", "ERROR",
}


class RobotTaskExecutor(Node):
    def __init__(self) -> None:
        super().__init__("robot_task_executor_node")
        self.declare_parameter("nav_action", "/navigate_to_pose")
        self.declare_parameter("nav_server_timeout_s", 5.0)
        self.declare_parameter("nav_timeout_s", 180.0)
        self.declare_parameter("arm_enabled", False)
        self.declare_parameter("arm_action", "")
        self.declare_parameter("arm_joint_names", [""])
        self.declare_parameter("arm_timeout_s", 60.0)
        self.declare_parameter("arm_named_poses_json", "{}")

        p = self.get_parameter
        self._cbg = ReentrantCallbackGroup()
        self._nav_action = str(p("nav_action").value)
        self._nav_server_timeout = float(p("nav_server_timeout_s").value)
        self._nav_timeout = float(p("nav_timeout_s").value)
        self._arm_timeout = float(p("arm_timeout_s").value)
        try:
            self._named_poses = json.loads(str(p("arm_named_poses_json").value))
        except json.JSONDecodeError:
            self._named_poses = {}

        self._nav_client = ActionClient(
            self, NavigateToPose, self._nav_action, callback_group=self._cbg
        )
        self._arm = ArmAdapter(
            self,
            self._cbg,
            bool(p("arm_enabled").value),
            str(p("arm_action").value),
            [name for name in p("arm_joint_names").value if str(name)],
        )
        self._status_pub = self.create_publisher(
            RobotFlowStatus, "/robot_flow/status", 20
        )
        self._mode = "IDLE"
        self._busy = False
        self._busy_lock = threading.Lock()
        self._cancel_requested = threading.Event()
        self._nav_goal_handle = None
        self._current_goal_handle = None
        self._task_id = ""
        self._last_status = None

        self.create_subscription(
            String, "/robot_mode/status", self._mode_cb, 10, callback_group=self._cbg
        )
        self.create_service(
            Trigger,
            "/robot_flow/cancel_current",
            self._cancel_service_cb,
            callback_group=self._cbg,
        )
        self._server = ActionServer(
            self,
            ExecuteRobotTask,
            "/robot_flow/execute",
            execute_callback=self._execute_cb,
            goal_callback=self._goal_cb,
            cancel_callback=self._cancel_cb,
            callback_group=self._cbg,
        )
        self._publish("IDLE", "WAITING_COMMAND", 0.0, False, "Ready")

    def _mode_cb(self, msg: String) -> None:
        try:
            value = json.loads(msg.data)
            self._mode = str(value.get("mode", self._mode))
        except (json.JSONDecodeError, AttributeError):
            self._mode = str(msg.data)

    def _goal_cb(self, request: ExecuteRobotTask.Goal) -> GoalResponse:
        if request.task_type not in TASK_TYPES:
            self._publish(
                "REJECTED", "VALIDATING", 0.0, False,
                "UNSUPPORTED_TASK_TYPE", task_type=request.task_type,
            )
            return GoalResponse.REJECT
        with self._busy_lock:
            if request.task_type == "stop":
                self._cancel_requested.set()
                self._cancel_underlying()
                return GoalResponse.ACCEPT
            if self._busy and request.task_type != "stop":
                self._publish(
                    "REJECTED", "WAITING_COMMAND", 0.0, True,
                    "ROBOT_BUSY", task_type=request.task_type,
                )
                return GoalResponse.REJECT
            self._busy = True
        return GoalResponse.ACCEPT

    def _cancel_cb(self, goal_handle) -> CancelResponse:
        self._cancel_requested.set()
        self._publish("CANCELING", "CANCELING_MOTION", 0.0, True, "Cancel requested")
        self._cancel_underlying()
        return CancelResponse.ACCEPT

    def _cancel_service_cb(self, request, response):
        with self._busy_lock:
            busy = self._busy
        if not busy:
            response.success = True
            response.message = "No active motion"
            return response
        self._cancel_requested.set()
        self._cancel_underlying()
        response.success = True
        response.message = "Cancellation requested"
        return response

    def _cancel_underlying(self) -> None:
        handle = self._nav_goal_handle
        if handle is not None:
            try:
                handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().error(f"Nav cancellation failed: {exc}")

    def _task_uuid(self, goal_handle) -> str:
        try:
            return str(uuid.UUID(bytes=bytes(goal_handle.goal_id.uuid)))
        except Exception:
            return str(uuid.uuid4())

    async def _execute_cb(self, goal_handle):
        if goal_handle.request.task_type == "stop":
            result = ExecuteRobotTask.Result()
            self._cancel_requested.set()
            self._cancel_underlying()
            arm_canceled = await self._arm.cancel()
            result.success = bool(arm_canceled)
            result.final_state = "CANCELING" if arm_canceled else "FAILED"
            result.message = (
                "Stop propagated to active motion"
                if arm_canceled else "ARM_CANCEL_FAILED"
            )
            result.json_result = json.dumps(
                {"arm_cancel_requested": arm_canceled}, allow_nan=False
            )
            if arm_canceled:
                goal_handle.succeed()
            else:
                goal_handle.abort()
            return result
        self._current_goal_handle = goal_handle
        self._task_id = self._task_uuid(goal_handle)
        task_type = goal_handle.request.task_type
        result = ExecuteRobotTask.Result()
        self._cancel_requested.clear()
        self._publish("ACCEPTED", "QUEUED", 0.0, True, "Task accepted", task_type)
        try:
            payload = self._parse_payload(goal_handle.request.json_payload)
            requester_mode = str(payload.pop("_requester_mode", "USER_TASK"))
            self._publish("VALIDATING", "VALIDATING_PAYLOAD", 0.02, True, "Validating", task_type)
            if task_type != "stop" and self._mode != requester_mode:
                return self._finish(
                    goal_handle, result, False, "REJECTED",
                    f"MODE_CONFLICT: current={self._mode}, required={requester_mode}",
                    {"error_code": "MODE_CONFLICT"},
                )
            if task_type == "navigate":
                ok, message, detail = await self._navigate(goal_handle, payload)
            elif task_type == "arm_joints":
                ok, message, detail = await self._arm_joints(goal_handle, payload)
            elif task_type == "arm_named_pose":
                ok, message, detail = await self._arm_named(goal_handle, payload)
            elif task_type == "gripper":
                ok, message, detail = False, "ARM_SERVER_UNAVAILABLE", {
                    "error_code": "ARM_SERVER_UNAVAILABLE"
                }
            else:
                self._cancel_requested.set()
                self._cancel_underlying()
                ok, message, detail = True, "Stop requested", {}

            if self._cancel_requested.is_set() or goal_handle.is_cancel_requested:
                return self._finish(
                    goal_handle, result, False, "CANCELED", "Task canceled", detail
                )
            state = "SUCCEEDED" if ok else "FAILED"
            return self._finish(goal_handle, result, ok, state, message, detail)
        except ValueError as exc:
            return self._finish(
                goal_handle, result, False, "REJECTED", str(exc),
                {"error_code": "INVALID_PAYLOAD"},
            )
        except Exception as exc:
            self.get_logger().error(f"Task execution error: {exc}")
            return self._finish(
                goal_handle, result, False, "ERROR", str(exc),
                {"error_code": "INTERNAL_ERROR"},
            )
        finally:
            self._nav_goal_handle = None
            self._current_goal_handle = None
            with self._busy_lock:
                self._busy = False
            self._cancel_requested.clear()

    def _parse_payload(self, raw: str) -> dict:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"INVALID_JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("INVALID_PAYLOAD: JSON object required")
        return value

    async def _navigate(self, goal_handle, payload: dict):
        try:
            x = float(payload["x"])
            y = float(payload["y"])
            yaw = float(payload["yaw"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INVALID_NAVIGATION_PAYLOAD: x, y and yaw required") from exc
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            raise ValueError("INVALID_NAVIGATION_PAYLOAD: finite values required")
        frame = str(payload.get("frame_id", "map"))
        if frame != "map":
            raise ValueError("INVALID_FRAME: navigation frame_id must be map")

        self._publish("WAITING_NAV2", "WAITING_ACTION_SERVER", 0.05, True, "Waiting for Nav2", "navigate")
        start = self.get_clock().now().nanoseconds / 1e9
        while not self._nav_client.server_is_ready():
            if self._cancel_requested.is_set():
                return False, "CANCELED", {}
            now = self.get_clock().now().nanoseconds / 1e9
            if now - start >= self._nav_server_timeout:
                return False, "NAV2_SERVER_UNAVAILABLE", {
                    "error_code": "NAV2_SERVER_UNAVAILABLE"
                }
            await ros_sleep(self, 0.05)

        nav_goal = NavigateToPose.Goal()
        nav_goal.pose = self._pose(x, y, yaw, frame)
        nav_goal.behavior_tree = ""
        last_feedback: dict[str, Any] = {}

        def feedback_cb(msg) -> None:
            feedback = msg.feedback
            current = feedback.current_pose
            last_feedback.clear()
            last_feedback.update({
                "distance_remaining": float(feedback.distance_remaining),
                "current_pose": self._pose_json(current),
                "navigation_time": self._duration_seconds(feedback.navigation_time),
                "number_of_recoveries": int(feedback.number_of_recoveries),
            })
            self._publish(
                "NAVIGATING", "NAV2_FEEDBACK", 0.5, True,
                "Navigation in progress", "navigate", last_feedback, goal_handle,
            )

        send_future = self._nav_client.send_goal_async(
            nav_goal, feedback_callback=feedback_cb
        )
        while not send_future.done():
            if self._cancel_requested.is_set():
                return False, "CANCELED", last_feedback
            await ros_sleep(self, 0.02)
        handle = send_future.result()
        if not handle.accepted:
            return False, "NAV2_GOAL_REJECTED", {
                "error_code": "NAV2_GOAL_REJECTED"
            }
        self._nav_goal_handle = handle
        result_future = handle.get_result_async()
        start = self.get_clock().now().nanoseconds / 1e9
        cancel_sent = False
        while not result_future.done():
            if self._cancel_requested.is_set() or goal_handle.is_cancel_requested:
                self._publish("CANCELING", "CANCELING_NAV2", 0.5, True, "Canceling Nav2", "navigate")
                if not cancel_sent:
                    handle.cancel_goal_async()
                    cancel_sent = True
            now = self.get_clock().now().nanoseconds / 1e9
            if now - start >= self._nav_timeout:
                await handle.cancel_goal_async()
                return False, "NAVIGATION_TIMEOUT", {
                    **last_feedback, "error_code": "NAVIGATION_TIMEOUT"
                }
            await ros_sleep(self, 0.05)
        wrapped = result_future.result()
        status = wrapped.status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._publish(
                "NAVIGATION_SUCCEEDED", "NAV2_RESULT", 0.95, True,
                "Navigation succeeded", "navigate", last_feedback, goal_handle,
            )
            return True, "Navigation succeeded", last_feedback
        if status == GoalStatus.STATUS_CANCELED:
            return False, "Navigation canceled", last_feedback
        if status == GoalStatus.STATUS_ABORTED:
            return False, "NAVIGATION_ABORTED", {
                **last_feedback, "error_code": "NAVIGATION_ABORTED"
            }
        return False, f"NAVIGATION_STATUS_{status}", last_feedback

    async def _arm_joints(self, goal_handle, payload: dict):
        self._publish("WAITING_ARM", "WAITING_ACTION_SERVER", 0.05, True, "Waiting for arm", "arm_joints")

        def arm_feedback(detail):
            self._publish(
                "ARM_MOVING", "ARM_FEEDBACK", 0.5, True,
                "Arm moving", "arm_joints", detail, goal_handle,
            )

        ok, message, detail = await self._arm.execute_joints(
            payload,
            self._arm_timeout,
            lambda: self._cancel_requested.is_set() or goal_handle.is_cancel_requested,
            arm_feedback,
        )
        if not ok:
            detail = {**detail, "error_code": message}
        return ok, message, detail

    async def _arm_named(self, goal_handle, payload: dict):
        name = payload.get("name")
        if not isinstance(name, str) or name not in self._named_poses:
            raise ValueError("UNKNOWN_NAMED_POSE")
        joint_payload = dict(self._named_poses[name])
        joint_payload.setdefault("duration_s", payload.get("duration_s", 4.0))
        return await self._arm_joints(goal_handle, joint_payload)

    def _finish(self, handle, result, success, state, message, detail):
        result.success = bool(success)
        result.final_state = state
        result.message = message
        result.json_result = json.dumps(detail, ensure_ascii=False, allow_nan=False)
        if state == "CANCELED":
            if handle.is_cancel_requested:
                handle.canceled()
            else:
                # Internal stop/mode-switch cancellation has no outer action
                # cancel event, so ROS requires an ABORTED transport status.
                # final_state remains CANCELED for API/state consumers.
                handle.abort()
        elif success:
            handle.succeed()
        else:
            handle.abort()
        self._publish(state, "COMPLETE", 1.0, False, message, handle.request.task_type, detail)
        return result

    def _publish(
        self, state, step, progress, busy, message,
        task_type="", detail=None, goal_handle=None,
    ):
        msg = RobotFlowStatus()
        msg.stamp = self.get_clock().now().to_msg()
        msg.task_id = self._task_id
        msg.mode = self._mode
        msg.task_type = task_type
        msg.state = state
        msg.step = step
        msg.progress = float(progress)
        msg.busy = bool(busy)
        msg.message = str(message)
        msg.json_detail = json.dumps(detail or {}, ensure_ascii=False, allow_nan=False)
        self._last_status = msg
        self._status_pub.publish(msg)
        if goal_handle is not None:
            fb = ExecuteRobotTask.Feedback()
            fb.state = state
            fb.step = step
            fb.progress = float(progress)
            fb.message = str(message)
            fb.json_detail = msg.json_detail
            goal_handle.publish_feedback(fb)

    def _pose(self, x, y, yaw, frame):
        pose = PoseStamped()
        pose.header.frame_id = frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    @staticmethod
    def _duration_seconds(value) -> float:
        return float(value.sec) + float(value.nanosec) / 1e9

    @staticmethod
    def _pose_json(stamped) -> dict:
        q = stamped.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y*q.y + q.z*q.z))
        return {
            "frame_id": stamped.header.frame_id,
            "x": stamped.pose.position.x,
            "y": stamped.pose.position.y,
            "yaw": yaw,
        }


def main(args=None):
    rclpy.init(args=args)
    node = RobotTaskExecutor()
    executor = MultiThreadedExecutor(num_threads=4)
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
