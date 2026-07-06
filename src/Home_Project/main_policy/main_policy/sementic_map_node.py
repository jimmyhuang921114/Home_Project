#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple

import yaml
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_srvs.srv import Trigger

from semantic_nav_interfaces.srv import NavToPoint


class WaypointNavToPointStepService(Node):
    def __init__(
        self,
        yaml_file: str,
        auto_start: bool = False,
        start_delay: float = 3.0,
        retry_on_fail: bool = True,
        skip_on_fail: bool = True,
        stop_after_fail: bool = False,
        max_fail_retries: int = 3,
        busy_wait: float = 3.0,
        fail_retry_wait: float = 3.0,
        success_delay: float = 2.0,
        skip_delay: float = 2.0,
        service_wait_timeout: float = 5.0,
        service_result_timeout: float = 180.0,
        use_yaw: bool = True,
    ):
        super().__init__("waypoint_nav_to_point_step_service")

        self.yaml_file = yaml_file
        self.frame_id, self.waypoints = self.load_waypoints(yaml_file)
        self.current_index = 0

        self.auto_start = auto_start
        self.start_delay = start_delay
        self.retry_on_fail = retry_on_fail
        self.skip_on_fail = skip_on_fail
        self.stop_after_fail = stop_after_fail

        # 這裡改成至少 1，避免 max_fail_retries=0 導致邏輯怪掉
        self.max_fail_retries = max(1, int(max_fail_retries))

        self.busy_wait = max(0.1, float(busy_wait))
        self.fail_retry_wait = max(0.1, float(fail_retry_wait))
        self.success_delay = max(0.0, float(success_delay))
        self.skip_delay = max(0.0, float(skip_delay))
        self.service_wait_timeout = max(0.1, float(service_wait_timeout))
        self.service_result_timeout = max(1.0, float(service_result_timeout))
        self.use_yaw = bool(use_yaw)

        self.running = False
        self.manual_running = False
        self.stop_requested = False
        self.lock = threading.Lock()

        # 單一 waypoint 的連續失敗次數
        self.fail_count = 0
        self.busy_count = 0

        # 統計資料
        self.success_count = 0
        self.failed_count = 0
        self.manual_skip_count = 0

        self.failed_attempt_count = 0
        self.busy_attempt_count = 0

        self.success_waypoints: list[dict[str, Any]] = []
        self.failed_waypoints: list[dict[str, Any]] = []
        self.manual_skipped_waypoints: list[dict[str, Any]] = []

        self.summary_logged = False

        self.auto_thread: Optional[threading.Thread] = None
        self.auto_timer: Optional[threading.Timer] = None

        self.cbg = ReentrantCallbackGroup()

        self.nav_client = self.create_client(
            NavToPoint,
            "/nav_to_point",
            callback_group=self.cbg,
        )

        self.next_srv = self.create_service(
            Trigger,
            "/next_waypoint_nav",
            self.handle_next_waypoint,
            callback_group=self.cbg,
        )

        self.reset_srv = self.create_service(
            Trigger,
            "/reset_waypoint_nav",
            self.handle_reset_waypoint,
            callback_group=self.cbg,
        )

        self.skip_srv = self.create_service(
            Trigger,
            "/skip_waypoint_nav",
            self.handle_skip_waypoint,
            callback_group=self.cbg,
        )

        self.start_srv = self.create_service(
            Trigger,
            "/start_waypoint_nav_auto",
            self.handle_start_auto,
            callback_group=self.cbg,
        )

        self.stop_srv = self.create_service(
            Trigger,
            "/stop_waypoint_nav_auto",
            self.handle_stop_auto,
            callback_group=self.cbg,
        )

        self.stats_srv = self.create_service(
            Trigger,
            "/waypoint_nav_stats",
            self.handle_stats,
            callback_group=self.cbg,
        )

        self.get_logger().info("Waypoint NavToPoint service ready.")
        self.get_logger().info(f"YAML: {self.yaml_file}")
        self.get_logger().info(f"frame_id: {self.frame_id}")
        self.get_logger().info(f"waypoints: {len(self.waypoints)}")
        self.get_logger().info("Manual service: /next_waypoint_nav")
        self.get_logger().info("Reset service : /reset_waypoint_nav")
        self.get_logger().info("Skip service  : /skip_waypoint_nav")
        self.get_logger().info("Auto start    : /start_waypoint_nav_auto")
        self.get_logger().info("Auto stop     : /stop_waypoint_nav_auto")
        self.get_logger().info("Stats service : /waypoint_nav_stats")
        self.get_logger().info(f"use_yaw       : {self.use_yaw}")
        self.get_logger().info(f"max failures  : {self.max_fail_retries}")
        self.get_logger().info(f"busy wait     : {self.busy_wait:.1f} sec")
        self.get_logger().info(f"retry wait    : {self.fail_retry_wait:.1f} sec")
        self.get_logger().info(f"retry_on_fail : {self.retry_on_fail}")
        self.get_logger().info(f"skip_on_fail  : {self.skip_on_fail}")

        if self.auto_start:
            self.get_logger().info(
                f"Auto mode enabled. Will start after {self.start_delay:.1f} sec."
            )
            self.auto_timer = threading.Timer(self.start_delay, self.start_auto_thread)
            self.auto_timer.daemon = True
            self.auto_timer.start()

    def load_waypoints(self, yaml_file: str):
        path = Path(yaml_file)
        if not path.exists():
            raise FileNotFoundError(f"YAML file not found: {yaml_file}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise RuntimeError(f"YAML is empty: {yaml_file}")

        frame_id = data.get("frame_id", "map")
        waypoints = data.get("waypoints", [])

        if not waypoints:
            raise RuntimeError("No waypoints found in YAML.")

        return frame_id, waypoints

    def sleep_interruptible(self, seconds: float):
        end_time = time.time() + seconds
        while rclpy.ok() and not self.stop_requested and time.time() < end_time:
            time.sleep(min(0.1, max(0.0, end_time - time.time())))

    def is_busy_message(self, msg: str) -> bool:
        text = (msg or "").lower()
        return "busy" in text or "try again later" in text

    def wait_for_future_done(self, future, timeout_sec: float) -> bool:
        start = time.time()
        while rclpy.ok() and not self.stop_requested:
            if future.done():
                return True

            if time.time() - start > timeout_sec:
                return False

            time.sleep(0.05)

        return False

    def call_nav_to_point(self, wp) -> Tuple[bool, str, Any]:
        if not self.nav_client.wait_for_service(timeout_sec=self.service_wait_timeout):
            return False, "/nav_to_point service not available.", None

        nav_req = NavToPoint.Request()
        nav_req.x = float(wp["x"])
        nav_req.y = float(wp["y"])

        nav_req.use_yaw = self.use_yaw
        nav_req.yaw = float(wp.get("yaw", 0.0))

        future = self.nav_client.call_async(nav_req)

        done = self.wait_for_future_done(
            future,
            timeout_sec=self.service_result_timeout,
        )

        if not done:
            return False, "NavToPoint service call timeout.", None

        if future.result() is None:
            exc = future.exception()
            if exc is not None:
                return False, f"NavToPoint future exception: {exc}", None
            return False, "NavToPoint future result is None.", None

        nav_res = future.result()
        return bool(nav_res.success), str(nav_res.message), nav_res

    def get_wp_id(self, index: int, wp) -> str:
        return str(wp.get("id", f"wp_{index:03d}"))

    def make_wp_record(
        self,
        index: int,
        wp,
        reason: str = "",
        attempts: int = 0,
        message: str = "",
    ) -> dict[str, Any]:
        return {
            "index": index,
            "seq": index + 1,
            "id": self.get_wp_id(index, wp),
            "source_node_id": wp.get("source_node_id", "unknown"),
            "x": float(wp.get("x", float("nan"))),
            "y": float(wp.get("y", float("nan"))),
            "yaw": float(wp.get("yaw", 0.0)),
            "attempts": int(attempts),
            "reason": str(reason),
            "message": str(message),
        }

    def record_success(self, index: int, wp, message: str):
        self.success_count += 1
        self.success_waypoints.append(
            self.make_wp_record(
                index=index,
                wp=wp,
                message=message,
            )
        )
        self.summary_logged = False

    def mark_current_waypoint_failed_and_skip(self, reason: str, attempts: int) -> str:
        if self.current_index >= len(self.waypoints):
            return "No current waypoint to mark failed."

        wp = self.waypoints[self.current_index]
        wp_id = self.get_wp_id(self.current_index, wp)

        self.failed_count += 1
        self.failed_waypoints.append(
            self.make_wp_record(
                index=self.current_index,
                wp=wp,
                reason=reason,
                attempts=attempts,
                message=reason,
            )
        )

        old_index = self.current_index
        self.current_index += 1

        self.fail_count = 0
        self.busy_count = 0
        self.summary_logged = False

        msg = (
            f"Waypoint marked FAILED and skipped: {wp_id}, "
            f"index={old_index}, attempts={attempts}, reason={reason}"
        )
        self.get_logger().error(msg)
        return msg

    def format_stats_summary(self) -> str:
        decided_total = self.success_count + self.failed_count

        if decided_total > 0:
            success_rate = self.success_count / decided_total * 100.0
            failed_rate = self.failed_count / decided_total * 100.0
        else:
            success_rate = 0.0
            failed_rate = 0.0

        remaining = max(0, len(self.waypoints) - self.current_index)

        lines = []
        lines.append("")
        lines.append("========== WAYPOINT NAV SUMMARY ==========")
        lines.append(f"YAML                  : {self.yaml_file}")
        lines.append(f"Total waypoints       : {len(self.waypoints)}")
        lines.append(f"Current index         : {self.current_index}")
        lines.append(f"Remaining             : {remaining}")
        lines.append(f"Success waypoints     : {self.success_count}")
        lines.append(f"Failed waypoints      : {self.failed_count}")
        lines.append(f"Manual skipped        : {self.manual_skip_count}")
        lines.append(f"Success / Failed      : {self.success_count}:{self.failed_count}")
        lines.append(f"Success rate          : {success_rate:.2f}%")
        lines.append(f"Failed rate           : {failed_rate:.2f}%")
        lines.append(f"Failed nav attempts   : {self.failed_attempt_count}")
        lines.append(f"Busy attempts         : {self.busy_attempt_count}")
        lines.append(f"Max failures per wp   : {self.max_fail_retries}")

        if self.failed_waypoints:
            lines.append("")
            lines.append("Failed waypoint list:")
            for rec in self.failed_waypoints:
                lines.append(
                    f"  - #{rec['seq']}/{len(self.waypoints)} "
                    f"id={rec['id']}, "
                    f"source_node_id={rec['source_node_id']}, "
                    f"x={rec['x']:.3f}, y={rec['y']:.3f}, yaw={rec['yaw']:.3f}, "
                    f"attempts={rec['attempts']}, "
                    f"reason={rec['reason']}"
                )
        else:
            lines.append("")
            lines.append("Failed waypoint list: none")

        if self.manual_skipped_waypoints:
            lines.append("")
            lines.append("Manual skipped waypoint list:")
            for rec in self.manual_skipped_waypoints:
                lines.append(
                    f"  - #{rec['seq']}/{len(self.waypoints)} "
                    f"id={rec['id']}, "
                    f"source_node_id={rec['source_node_id']}, "
                    f"x={rec['x']:.3f}, y={rec['y']:.3f}, yaw={rec['yaw']:.3f}"
                )

        lines.append("==========================================")
        return "\n".join(lines)

    def log_summary(self, force: bool = False):
        if self.summary_logged and not force:
            return

        self.summary_logged = True
        self.get_logger().info(self.format_stats_summary())

    def run_one_waypoint(self):
        if self.current_index >= len(self.waypoints):
            return False, "All waypoints finished."

        wp = self.waypoints[self.current_index]

        wp_id = self.get_wp_id(self.current_index, wp)
        source_node_id = wp.get("source_node_id", "unknown")

        x = float(wp["x"])
        y = float(wp["y"])
        yaw = float(wp.get("yaw", 0.0))

        current_index_before_call = self.current_index

        self.get_logger().info(
            f"[WAYPOINT] {self.current_index + 1}/{len(self.waypoints)} "
            f"{wp_id}, source_node_id={source_node_id}, "
            f"x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}, "
            f"fail_count={self.fail_count}/{self.max_fail_retries}"
        )

        if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(yaw):
            msg = f"Waypoint invalid: {wp_id}, x/y/yaw is not finite."
            self.get_logger().warn(msg)
            return False, msg

        success, message, nav_res = self.call_nav_to_point(wp)

        if success:
            self.current_index += 1
            self.fail_count = 0
            self.busy_count = 0

            if nav_res is not None:
                msg = (
                    f"Waypoint done: {wp_id}, "
                    f"final=({nav_res.final_x:.3f}, {nav_res.final_y:.3f}), "
                    f"yaw={nav_res.final_yaw:.3f}, message={message}"
                )
            else:
                msg = f"Waypoint done: {wp_id}, message={message}"

            self.record_success(
                index=current_index_before_call,
                wp=wp,
                message=msg,
            )

            self.get_logger().info(msg)
            return True, msg

        msg = f"Waypoint failed: {wp_id}, message={message}"
        self.get_logger().warn(msg)
        return False, msg

    def handle_failed_waypoint(self, msg: str, auto_mode: bool = True) -> Tuple[bool, str]:
        """
        Return:
        - keep_running=True  : auto mode 繼續跑
        - keep_running=False : auto mode 停止

        重要行為：
        - 同一點第 1 次失敗：不算正式失敗，重試同一點
        - 同一點第 2 次失敗：不算正式失敗，重試同一點
        - 同一點第 3 次失敗：正式記錄 failed waypoint，跳到下一點
        """

        # busy 獨立計算，避免 navigator 短暫 busy 就直接算 waypoint fail
        if self.is_busy_message(msg):
            self.busy_count += 1
            self.busy_attempt_count += 1

            if self.busy_count < self.max_fail_retries:
                action_msg = (
                    f"Navigator busy. Retry same waypoint later. "
                    f"busy_count={self.busy_count}/{self.max_fail_retries}, "
                    f"wait={self.busy_wait:.1f} sec"
                )
                self.get_logger().warn(action_msg)

                if auto_mode:
                    self.sleep_interruptible(self.busy_wait)

                return True, action_msg

            reason = (
                f"Navigator busy {self.busy_count}/{self.max_fail_retries}. "
                f"Original message: {msg}"
            )

            if self.skip_on_fail:
                action_msg = self.mark_current_waypoint_failed_and_skip(
                    reason=reason,
                    attempts=self.busy_count,
                )

                if auto_mode:
                    self.sleep_interruptible(self.skip_delay)

                return True, action_msg

            if self.stop_after_fail:
                action_msg = "Stop after busy enabled. Auto navigation stopped."
                self.get_logger().error(action_msg)
                return False, action_msg

            return False, reason

        # 一般導航失敗
        self.busy_count = 0
        self.fail_count += 1
        self.failed_attempt_count += 1

        # 注意這裡是 <，不是 <=
        # max_fail_retries=3 時：
        # 第 1 次 fail：retry
        # 第 2 次 fail：retry
        # 第 3 次 fail：記錄失敗並跳過
        if self.fail_count < self.max_fail_retries:
            action_msg = (
                f"Waypoint failed attempt "
                f"{self.fail_count}/{self.max_fail_retries}. "
                f"Retry same waypoint after {self.fail_retry_wait:.1f} sec. "
                f"Original message: {msg}"
            )
            self.get_logger().warn(action_msg)

            if auto_mode:
                self.sleep_interruptible(self.fail_retry_wait)

            return True, action_msg

        reason = (
            f"Waypoint failed {self.fail_count}/{self.max_fail_retries}. "
            f"Original message: {msg}"
        )

        if self.skip_on_fail:
            action_msg = self.mark_current_waypoint_failed_and_skip(
                reason=reason,
                attempts=self.fail_count,
            )

            if auto_mode:
                self.sleep_interruptible(self.skip_delay)

            return True, action_msg

        if self.stop_after_fail:
            action_msg = "Stop after fail enabled. Auto navigation stopped."
            self.get_logger().error(action_msg)
            return False, action_msg

        return False, reason

    def auto_loop(self):
        with self.lock:
            if self.running:
                self.get_logger().warn("Auto waypoint navigation already running.")
                return

            self.running = True
            self.stop_requested = False
            self.fail_count = 0
            self.busy_count = 0

        self.get_logger().info("Auto waypoint navigation started.")

        try:
            while rclpy.ok():
                if self.stop_requested:
                    self.get_logger().warn("Auto waypoint navigation stopped by request.")
                    break

                if self.current_index >= len(self.waypoints):
                    self.get_logger().info("All waypoints finished.")
                    break

                ok, msg = self.run_one_waypoint()

                if ok:
                    self.sleep_interruptible(self.success_delay)
                    continue

                keep_running, action_msg = self.handle_failed_waypoint(
                    msg,
                    auto_mode=True,
                )

                if not keep_running:
                    self.get_logger().error(action_msg)
                    break

        finally:
            with self.lock:
                self.running = False

            self.get_logger().info("Auto waypoint navigation ended.")
            self.log_summary(force=True)

    def start_auto_thread(self):
        with self.lock:
            if self.running:
                self.get_logger().warn("Auto waypoint navigation already running.")
                return

        self.auto_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self.auto_thread.start()

    def handle_start_auto(self, request, response):
        with self.lock:
            if self.running or self.manual_running:
                response.success = False
                response.message = "Navigation is already running."
                return response

        self.start_auto_thread()
        response.success = True
        response.message = "Auto waypoint navigation started."
        return response

    def handle_stop_auto(self, request, response):
        self.stop_requested = True
        response.success = True
        response.message = "Stop requested."
        return response

    def handle_next_waypoint(self, request, response):
        """
        Manual step mode:
        - 每次呼叫只跑目前 current_index 這一個 waypoint
        - 成功才 current_index += 1
        - 失敗會累積 fail_count
        - fail_count 達到 max_fail_retries 後，記錄失敗並跳過這點
        """
        with self.lock:
            if self.running:
                response.success = False
                response.message = "Auto mode is running. Stop it before manual next."
                return response

            if self.manual_running:
                response.success = False
                response.message = "Manual waypoint navigation is already running."
                return response

            if self.current_index >= len(self.waypoints):
                response.success = False
                response.message = "All waypoints finished."
                self.log_summary(force=True)
                return response

            self.manual_running = True
            self.stop_requested = False

        try:
            ok, msg = self.run_one_waypoint()

            if ok:
                response.success = True
                response.message = msg

                if self.current_index >= len(self.waypoints):
                    self.log_summary(force=True)

                return response

            _, action_msg = self.handle_failed_waypoint(
                msg,
                auto_mode=False,
            )

            response.success = False
            response.message = action_msg

            if self.current_index >= len(self.waypoints):
                self.log_summary(force=True)

            return response

        finally:
            with self.lock:
                self.manual_running = False

    def handle_skip_waypoint(self, request, response):
        """
        Manual skip:
        - 手動跳過不算 failed_count
        - 會另外記錄 manual_skip_count
        """
        with self.lock:
            if self.running:
                response.success = False
                response.message = "Auto mode is running. Stop it before skip."
                return response

            if self.manual_running:
                response.success = False
                response.message = "Manual waypoint navigation is running. Cannot skip now."
                return response

            if self.current_index >= len(self.waypoints):
                response.success = False
                response.message = "All waypoints finished."
                return response

            wp = self.waypoints[self.current_index]
            wp_id = self.get_wp_id(self.current_index, wp)

            self.manual_skip_count += 1
            self.manual_skipped_waypoints.append(
                self.make_wp_record(
                    index=self.current_index,
                    wp=wp,
                    reason="manual skip",
                )
            )

            self.current_index += 1
            self.fail_count = 0
            self.busy_count = 0
            self.summary_logged = False

        response.success = True
        response.message = f"Manually skipped waypoint: {wp_id}. Current index is now {self.current_index}."
        self.get_logger().warn(response.message)
        return response

    def handle_reset_waypoint(self, request, response):
        with self.lock:
            if self.running or self.manual_running:
                response.success = False
                response.message = "Navigation is running. Stop/wait before reset."
                return response

            self.current_index = 0

            self.fail_count = 0
            self.busy_count = 0

            self.success_count = 0
            self.failed_count = 0
            self.manual_skip_count = 0

            self.failed_attempt_count = 0
            self.busy_attempt_count = 0

            self.success_waypoints.clear()
            self.failed_waypoints.clear()
            self.manual_skipped_waypoints.clear()

            self.summary_logged = False

        response.success = True
        response.message = "Waypoint index and stats reset to 0."
        self.get_logger().info("Waypoint index and stats reset to 0.")
        return response

    def handle_stats(self, request, response):
        response.success = True
        response.message = self.format_stats_summary()
        self.get_logger().info(response.message)
        return response

    def destroy_node(self):
        self.stop_requested = True

        if self.auto_timer is not None:
            try:
                self.auto_timer.cancel()
            except Exception:
                pass

        return super().destroy_node()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yaml",
        default="/home/jimmy/work_ws/home_project_ws/config/swagger_regen_reachable_20260623_014740/nav2_waypoints_swagger_reachable.yaml",
    )
    parser.add_argument("--auto-start", action="store_true")
    parser.add_argument("--start-delay", type=float, default=3.0)

    # 預設開啟：失敗會重試，達到 3 次後會跳過
    parser.add_argument("--retry-on-fail", dest="retry_on_fail", action="store_true", default=True)
    parser.add_argument("--no-retry-on-fail", dest="retry_on_fail", action="store_false")

    parser.add_argument("--skip-on-fail", dest="skip_on_fail", action="store_true", default=True)
    parser.add_argument("--no-skip-on-fail", dest="skip_on_fail", action="store_false")

    parser.add_argument("--max-fail-retries", type=int, default=3)
    parser.add_argument("--busy-wait", type=float, default=3.0)
    parser.add_argument("--fail-retry-wait", type=float, default=3.0)
    parser.add_argument("--success-delay", type=float, default=2.0)
    parser.add_argument("--skip-delay", type=float, default=2.0)

    parser.add_argument("--service-wait-timeout", type=float, default=5.0)
    parser.add_argument("--service-result-timeout", type=float, default=180.0)

    parser.add_argument("--use-yaw", dest="use_yaw", action="store_true", default=True)
    parser.add_argument("--no-use-yaw", dest="use_yaw", action="store_false")

    args = parser.parse_args()

    rclpy.init()

    stop_after_fail = not args.retry_on_fail and not args.skip_on_fail

    node = WaypointNavToPointStepService(
        yaml_file=args.yaml,
        auto_start=args.auto_start,
        start_delay=args.start_delay,
        retry_on_fail=args.retry_on_fail,
        skip_on_fail=args.skip_on_fail,
        stop_after_fail=stop_after_fail,
        max_fail_retries=args.max_fail_retries,
        busy_wait=args.busy_wait,
        fail_retry_wait=args.fail_retry_wait,
        success_delay=args.success_delay,
        skip_delay=args.skip_delay,
        service_wait_timeout=args.service_wait_timeout,
        service_result_timeout=args.service_result_timeout,
        use_yaw=args.use_yaw,
    )

    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        node.stop_requested = True
        node.log_summary(force=True)
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