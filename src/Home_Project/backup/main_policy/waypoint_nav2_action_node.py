#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped


def yaw_to_quat(yaw: float):
    qz = math.sin(yaw * 0.5)
    qw = math.cos(yaw * 0.5)
    return qz, qw


class WaypointNav2ActionNode(Node):
    def __init__(
        self,
        yaml_file: str,
        start_delay: float = 5.0,
        goal_timeout: float = 120.0,
        retry: int = 1,
        retry_wait: float = 3.0,
        skip_on_fail: bool = True,
        pause_between_goals: float = 2.0,
        use_yaw: bool = False,
    ):
        super().__init__("waypoint_nav2_action_node")

        self.yaml_file = yaml_file
        self.frame_id, self.waypoints = self.load_waypoints(yaml_file)

        self.start_delay = float(start_delay)
        self.goal_timeout = float(goal_timeout)
        self.retry = int(retry)
        self.retry_wait = float(retry_wait)
        self.skip_on_fail = bool(skip_on_fail)
        self.pause_between_goals = float(pause_between_goals)
        self.use_yaw = bool(use_yaw)

        self.nav_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self.get_logger().info("Waypoint Nav2 ACTION node ready.")
        self.get_logger().info(f"YAML       : {self.yaml_file}")
        self.get_logger().info(f"frame_id   : {self.frame_id}")
        self.get_logger().info(f"waypoints  : {len(self.waypoints)}")
        self.get_logger().info(f"use_yaw    : {self.use_yaw}")
        self.get_logger().info(f"timeout    : {self.goal_timeout:.1f} sec")
        self.get_logger().info(f"retry      : {self.retry}")
        self.get_logger().info(f"skip_fail  : {self.skip_on_fail}")

    def load_waypoints(self, yaml_file: str):
        path = Path(yaml_file)
        if not path.exists():
            raise FileNotFoundError(f"YAML file not found: {yaml_file}")

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            raise RuntimeError("YAML is empty.")

        frame_id = data.get("frame_id", "map")
        waypoints = data.get("waypoints", [])

        if not waypoints:
            raise RuntimeError("No waypoints found in YAML.")

        return frame_id, waypoints

    def make_goal(self, wp) -> NavigateToPose.Goal:
        goal = NavigateToPose.Goal()

        pose = PoseStamped()
        pose.header.frame_id = self.frame_id
        pose.header.stamp = self.get_clock().now().to_msg()

        pose.pose.position.x = float(wp["x"])
        pose.pose.position.y = float(wp["y"])
        pose.pose.position.z = 0.0

        yaw = float(wp.get("yaw", 0.0)) if self.use_yaw else 0.0
        qz, qw = yaw_to_quat(yaw)

        pose.pose.orientation.x = 0.0
        pose.pose.orientation.y = 0.0
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw

        goal.pose = pose
        return goal

    def wait_future(self, future, timeout_sec: float | None = None) -> bool:
        start = time.time()

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)

            if future.done():
                return True

            if timeout_sec is not None and (time.time() - start) > timeout_sec:
                return False

        return False

    def cancel_goal(self, goal_handle):
        try:
            cancel_future = goal_handle.cancel_goal_async()
            self.wait_future(cancel_future, timeout_sec=3.0)
        except Exception as e:
            self.get_logger().warn(f"Cancel goal failed: {e}")

    def send_one_goal(self, wp, index: int):
        wp_id = wp.get("id", f"wp_{index:03d}")
        x = float(wp["x"])
        y = float(wp["y"])
        yaw = float(wp.get("yaw", 0.0))

        self.get_logger().info(
            f"[WAYPOINT] {index + 1}/{len(self.waypoints)} "
            f"{wp_id}, x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}"
        )

        if not self.nav_client.wait_for_server(timeout_sec=10.0):
            return False, "navigate_to_pose action server not available."

        goal = self.make_goal(wp)

        send_future = self.nav_client.send_goal_async(goal)
        ok = self.wait_future(send_future, timeout_sec=10.0)

        if not ok:
            return False, "send_goal timeout."

        goal_handle = send_future.result()

        if goal_handle is None:
            return False, "goal_handle is None."

        if not goal_handle.accepted:
            return False, "NavigateToPose goal rejected."

        self.get_logger().info(f"Goal accepted: {wp_id}")

        result_future = goal_handle.get_result_async()
        ok = self.wait_future(result_future, timeout_sec=self.goal_timeout)

        if not ok:
            self.get_logger().warn(f"Goal timeout. Canceling: {wp_id}")
            self.cancel_goal(goal_handle)
            return False, "goal timeout."

        result = result_future.result()
        status = result.status

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f"Goal succeeded: {wp_id}")
            return True, "succeeded."

        if status == GoalStatus.STATUS_ABORTED:
            return False, "aborted."

        if status == GoalStatus.STATUS_CANCELED:
            return False, "canceled."

        return False, f"failed with status={status}"

    def run(self):
        self.get_logger().info(f"Start after {self.start_delay:.1f} sec.")
        time.sleep(self.start_delay)

        for i, wp in enumerate(self.waypoints):
            if not rclpy.ok():
                break

            attempt = 0

            while rclpy.ok():
                success, msg = self.send_one_goal(wp, i)

                if success:
                    time.sleep(self.pause_between_goals)
                    break

                attempt += 1
                self.get_logger().warn(
                    f"Waypoint failed: {wp.get('id', f'wp_{i:03d}')}, "
                    f"attempt={attempt}/{self.retry + 1}, msg={msg}"
                )

                if attempt <= self.retry:
                    time.sleep(self.retry_wait)
                    continue

                if self.skip_on_fail:
                    self.get_logger().warn("Skip this waypoint.")
                    time.sleep(self.pause_between_goals)
                    break

                self.get_logger().error("Stop after fail.")
                return

        self.get_logger().info("All waypoints finished or stopped.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", required=True)
    parser.add_argument("--start-delay", type=float, default=5.0)
    parser.add_argument("--goal-timeout", type=float, default=120.0)
    parser.add_argument("--retry", type=int, default=1)
    parser.add_argument("--retry-wait", type=float, default=3.0)
    parser.add_argument("--pause-between-goals", type=float, default=2.0)
    parser.add_argument("--skip-on-fail", action="store_true")
    parser.add_argument("--use-yaw", action="store_true")
    args = parser.parse_args()

    rclpy.init()

    node = WaypointNav2ActionNode(
        yaml_file=args.yaml,
        start_delay=args.start_delay,
        goal_timeout=args.goal_timeout,
        retry=args.retry,
        retry_wait=args.retry_wait,
        skip_on_fail=args.skip_on_fail,
        pause_between_goals=args.pause_between_goals,
        use_yaw=args.use_yaw,
    )

    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
