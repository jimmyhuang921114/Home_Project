"""Optional FollowJointTrajectory adapter.

The adapter is inert unless it is explicitly enabled and both an action name and
an allow-list of joint names are configured.  No hardware interface is guessed.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

try:
    from control_msgs.action import FollowJointTrajectory
    from trajectory_msgs.msg import JointTrajectoryPoint
except ImportError:  # Keep navigation usable on robots without arm packages.
    FollowJointTrajectory = None
    JointTrajectoryPoint = None

from rclpy.action import ActionClient
from rclpy.task import Future


async def ros_sleep(node, seconds: float) -> None:
    future = Future()
    timer = None

    def wake() -> None:
        if not future.done():
            future.set_result(True)

    timer = node.create_timer(max(0.001, seconds), wake)
    try:
        await future
    finally:
        node.destroy_timer(timer)


class ArmAdapter:
    def __init__(
        self,
        node,
        callback_group,
        enabled: bool,
        action_name: str,
        allowed_joint_names: list[str],
    ) -> None:
        self._node = node
        self.enabled = bool(enabled)
        self.action_name = str(action_name)
        self.allowed_joint_names = tuple(str(v) for v in allowed_joint_names)
        self._goal_handle = None
        self._client = None

        if self.enabled and FollowJointTrajectory is not None and self.action_name:
            self._client = ActionClient(
                node,
                FollowJointTrajectory,
                self.action_name,
                callback_group=callback_group,
            )

    @property
    def available(self) -> bool:
        return bool(self._client and self._client.server_is_ready())

    async def cancel(self) -> bool:
        handle = self._goal_handle
        if handle is None:
            return True
        try:
            response = await handle.cancel_goal_async()
            return bool(response.goals_canceling)
        except Exception:
            return False

    async def execute_joints(
        self,
        payload: dict,
        timeout_s: float,
        cancel_requested: Callable[[], bool],
        feedback_cb: Callable[[dict], None],
    ) -> tuple[bool, str, dict]:
        if not self.enabled or self._client is None:
            return False, "ARM_SERVER_UNAVAILABLE", {}

        names = payload.get("joint_names")
        positions = payload.get("positions")
        duration_s = payload.get("duration_s", 4.0)

        if not isinstance(names, list) or not names:
            return False, "INVALID_JOINT_NAMES", {}
        if not isinstance(positions, list) or not positions:
            return False, "INVALID_POSITIONS", {}
        if len(names) != len(positions):
            return False, "JOINT_POSITION_LENGTH_MISMATCH", {}
        if not all(isinstance(n, str) and n for n in names):
            return False, "INVALID_JOINT_NAMES", {}
        if not all(n in self.allowed_joint_names for n in names):
            return False, "UNKNOWN_JOINT_NAME", {}
        try:
            positions = [float(v) for v in positions]
            duration_s = float(duration_s)
        except (TypeError, ValueError):
            return False, "INVALID_ARM_PAYLOAD", {}
        if not all(math.isfinite(v) for v in positions):
            return False, "INVALID_POSITIONS", {}
        if not math.isfinite(duration_s) or duration_s <= 0.0:
            return False, "INVALID_DURATION", {}

        wait_start = self._node.get_clock().now().nanoseconds / 1e9
        while not self._client.server_is_ready():
            now = self._node.get_clock().now().nanoseconds / 1e9
            if now - wait_start >= min(timeout_s, 5.0):
                return False, "ARM_SERVER_UNAVAILABLE", {}
            if cancel_requested():
                return False, "CANCELED", {}
            await ros_sleep(self._node, 0.05)

        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(names)
        point = JointTrajectoryPoint()
        point.positions = positions
        whole = int(duration_s)
        point.time_from_start.sec = whole
        point.time_from_start.nanosec = int((duration_s - whole) * 1e9)
        goal.trajectory.points = [point]

        def on_feedback(msg) -> None:
            actual = list(getattr(msg.feedback.actual, "positions", []))
            desired = list(getattr(msg.feedback.desired, "positions", []))
            feedback_cb({"actual_positions": actual, "desired_positions": desired})

        handle = await self._client.send_goal_async(goal, feedback_callback=on_feedback)
        if not handle.accepted:
            return False, "ARM_GOAL_REJECTED", {}
        self._goal_handle = handle
        result_future = handle.get_result_async()
        start = self._node.get_clock().now().nanoseconds / 1e9
        try:
            while not result_future.done():
                if cancel_requested():
                    await self.cancel()
                now = self._node.get_clock().now().nanoseconds / 1e9
                if now - start >= timeout_s:
                    await self.cancel()
                    return False, "ARM_TIMEOUT", {}
                await ros_sleep(self._node, 0.05)
            wrapped = result_future.result()
            code = int(getattr(wrapped.result, "error_code", -1))
            if code == 0:
                return True, "Arm motion succeeded", {"error_code": code}
            return False, "ARM_ABORTED", {"error_code": code}
        finally:
            self._goal_handle = None
