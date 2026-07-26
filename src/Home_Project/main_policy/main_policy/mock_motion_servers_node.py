#!/usr/bin/env python3
"""Explicit mock-only Nav2 and arm action servers for safe integration tests."""

from __future__ import annotations

import rclpy
from control_msgs.action import FollowJointTrajectory
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from .arm_adapter import ros_sleep

try:
    from openarm_interfaces.action import PickPlaceSegment
except ImportError:
    PickPlaceSegment = None


class MockMotionServers(Node):
    def __init__(self) -> None:
        super().__init__("mock_motion_servers_node")
        self.declare_parameter("nav_action", "/mock_navigate_to_pose")
        self.declare_parameter(
            "arm_action", "/mock_arm_controller/follow_joint_trajectory"
        )
        self.declare_parameter("vla_action", "/mock_pickplace_segment")
        self._cbg = ReentrantCallbackGroup()
        self._nav = ActionServer(
            self,
            NavigateToPose,
            str(self.get_parameter("nav_action").value),
            execute_callback=self._nav_execute,
            goal_callback=lambda goal: GoalResponse.ACCEPT,
            cancel_callback=lambda goal: CancelResponse.ACCEPT,
            callback_group=self._cbg,
        )
        self._arm = ActionServer(
            self,
            FollowJointTrajectory,
            str(self.get_parameter("arm_action").value),
            execute_callback=self._arm_execute,
            goal_callback=lambda goal: GoalResponse.ACCEPT,
            cancel_callback=lambda goal: CancelResponse.ACCEPT,
            callback_group=self._cbg,
        )
        self._vla = None
        if PickPlaceSegment is not None:
            self._vla = ActionServer(
                self,
                PickPlaceSegment,
                str(self.get_parameter("vla_action").value),
                execute_callback=self._vla_execute,
                goal_callback=lambda goal: GoalResponse.ACCEPT,
                cancel_callback=lambda goal: CancelResponse.ACCEPT,
                callback_group=self._cbg,
            )
        self.get_logger().warn("MOCK motion servers active; no hardware is controlled")

    async def _nav_execute(self, goal_handle):
        steps = 20
        for index in range(steps):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                return NavigateToPose.Result()
            feedback = NavigateToPose.Feedback()
            feedback.current_pose = goal_handle.request.pose
            feedback.distance_remaining = float(steps - index - 1) / 10.0
            feedback.navigation_time.sec = index
            feedback.number_of_recoveries = 0
            goal_handle.publish_feedback(feedback)
            await ros_sleep(self, 0.1)
        goal_handle.succeed()
        return NavigateToPose.Result()

    async def _arm_execute(self, goal_handle):
        names = list(goal_handle.request.trajectory.joint_names)
        point = goal_handle.request.trajectory.points[-1]
        steps = 20
        for index in range(steps):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = FollowJointTrajectory.Result()
                result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
                return result
            feedback = FollowJointTrajectory.Feedback()
            feedback.joint_names = names
            feedback.desired = point
            feedback.actual.positions = [
                value * float(index + 1) / float(steps) for value in point.positions
            ]
            goal_handle.publish_feedback(feedback)
            await ros_sleep(self, 0.1)
        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    async def _vla_execute(self, goal_handle):
        """Only available when the real OpenArm interface overlay is installed."""
        segment = int(goal_handle.request.segment)
        stage = 1 if segment == 1 else 4
        for index in range(10):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = PickPlaceSegment.Result()
                result.success, result.result_code, result.message = False, 1, "mock canceled"
                result.final_state = [0.0] * 8
                return result
            feedback = PickPlaceSegment.Feedback()
            feedback.stage = stage
            feedback.detail = "mock VLA progress"
            feedback.grip_rad = -0.05 if segment == 1 else 0.0
            feedback.lift_delta = 0.1 if segment == 1 else 0.0
            feedback.home_dist = 0.0
            feedback.elapsed_sec = float(index) / 10.0
            goal_handle.publish_feedback(feedback)
            await ros_sleep(self, 0.1)
        goal_handle.succeed()
        result = PickPlaceSegment.Result()
        result.success, result.result_code, result.message = True, 0, "mock detected"
        result.final_state = [0.0] * 8
        result.elapsed_sec = 1.0
        return result

    def destroy_node(self):
        self._nav.destroy()
        self._arm.destroy()
        if self._vla is not None:
            self._vla.destroy()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MockMotionServers()
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
