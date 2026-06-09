#!/usr/bin/env python3
"""
Waypoint Tour Node
==================
依序導航至預設的 6 個航點，每到一點呼叫視覺辨識服務，
全部走完後呼叫語意地圖儲存服務。

流程：
  for each waypoint:
    1. /nav_to_point       → 導航至該點並面向指定方向
    2. /vision/recognize   → 呼叫視覺辨識（佔位，隊友實作）
    3. /semantic_map/confirm → 收集當前視角快照
  after all:
    4. /semantic_map/finalize → 跨視角融合，寫入語意地圖

啟動後自動開始，或透過 /tour/start service 觸發。
"""

import math
import threading
from typing import Optional

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from std_msgs.msg import String
from std_srvs.srv import Trigger

from semantic_nav_interfaces.srv import NavToPoint


# ── 航點定義（x, y, yaw_rad）──────────────────────────────────────────────────
# yaw 由 RViz 擷取的 quaternion (qz, qw) 轉換：yaw = 2 * atan2(qz, qw)
WAYPOINTS = [
    (-0.0046, -0.0133, -2.2569),   # wp1  yaw=-129.3°
    (-0.0281, -4.2932,  2.5866),   # wp2  yaw= 148.2°
    ( 0.0815,  0.6672,  1.9462),   # wp3  yaw= 111.5°
    (-2.6200,  0.6756,  1.1646),   # wp4  yaw=  66.7°
    (-2.4840,  4.9975, -0.4729),   # wp5  yaw= -27.1°
    ( 0.0554,  5.0396, -2.0718),   # wp6  yaw=-118.7°
]


class WaypointTourNode(Node):

    def __init__(self) -> None:
        super().__init__('waypoint_tour_node')

        self.declare_parameter('auto_start', True)
        self.declare_parameter('nav_timeout', 120.0)
        self.declare_parameter('vision_timeout', 30.0)
        self.declare_parameter('confirm_timeout', 10.0)
        self.declare_parameter('pause_between_s', 1.0)

        self._auto_start      = bool(self.get_parameter('auto_start').value)
        self._nav_timeout     = float(self.get_parameter('nav_timeout').value)
        self._vision_timeout  = float(self.get_parameter('vision_timeout').value)
        self._confirm_timeout = float(self.get_parameter('confirm_timeout').value)
        self._pause_s         = float(self.get_parameter('pause_between_s').value)

        self._cbg = ReentrantCallbackGroup()

        # ── Service clients ───────────────────────────────────────────────────
        self._nav_cli      = self.create_client(
            NavToPoint, '/nav_to_point', callback_group=self._cbg)
        self._vision_cli   = self.create_client(
            Trigger, '/vision/recognize', callback_group=self._cbg)
        self._confirm_cli  = self.create_client(
            Trigger, '/semantic_map/confirm', callback_group=self._cbg)
        self._finalize_cli = self.create_client(
            Trigger, '/semantic_map/finalize', callback_group=self._cbg)

        # ── Status publisher ──────────────────────────────────────────────────
        self._status_pub = self.create_publisher(String, '/tour/status', 10)

        # ── Manual trigger service ────────────────────────────────────────────
        self.create_service(
            Trigger, '/tour/start', self._start_cb, callback_group=self._cbg)

        self._running = False

        self.get_logger().info(
            f'WaypointTourNode ready  ({len(WAYPOINTS)} waypoints)\n'
            f'  auto_start     : {self._auto_start}\n'
            f'  nav_timeout    : {self._nav_timeout} s\n'
            f'  vision_timeout : {self._vision_timeout} s\n'
            f'  Call /tour/start to trigger manually.'
        )

        if self._auto_start:
            # 延遲 2 秒讓其他節點就緒後自動開始
            threading.Timer(2.0, self._run_tour).start()

    # ── Manual start ──────────────────────────────────────────────────────────
    def _start_cb(
        self, request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        if self._running:
            response.success = False
            response.message = 'Tour already running'
            return response
        threading.Thread(target=self._run_tour, daemon=True).start()
        response.success = True
        response.message = 'Tour started'
        return response

    # ── Main tour ─────────────────────────────────────────────────────────────
    def _run_tour(self) -> None:
        if self._running:
            return
        self._running = True
        n = len(WAYPOINTS)

        self.get_logger().info(f'=== Tour started: {n} waypoints ===')
        self._pub_status(f'Tour started ({n} waypoints)')

        failed_wps = []

        for idx, (x, y, yaw) in enumerate(WAYPOINTS, start=1):
            self.get_logger().info(
                f'─── Waypoint {idx}/{n}: ({x:.3f}, {y:.3f})  '
                f'yaw={math.degrees(yaw):.1f}°'
            )
            self._pub_status(f'[{idx}/{n}] Navigating to ({x:.2f}, {y:.2f})')

            # ① 導航
            nav_ok = self._call_nav(idx, x, y, yaw)
            if not nav_ok:
                self.get_logger().error(f'Waypoint {idx} navigation failed — skipping')
                failed_wps.append(idx)
                continue

            # ② 視覺辨識（佔位）
            self._pub_status(f'[{idx}/{n}] Calling vision service')
            vision_ok = self._call_vision(idx)
            if not vision_ok:
                self.get_logger().warn(f'Waypoint {idx} vision service failed — continuing')

            # ③ 語意地圖視角快照
            self._pub_status(f'[{idx}/{n}] Collecting viewpoint snapshot')
            self._call_confirm(idx)

            # 點與點之間稍作暫停
            if idx < n and self._pause_s > 0:
                import time; time.sleep(self._pause_s)

        # ④ 所有點走完後 finalize
        self.get_logger().info('=== All waypoints done — finalizing semantic map ===')
        self._pub_status('Finalizing semantic map...')
        self._call_finalize(failed_wps)

        self._running = False

    # ── Nav ───────────────────────────────────────────────────────────────────
    def _call_nav(self, idx: int, x: float, y: float, yaw: float) -> bool:
        if not self._nav_cli.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('/nav_to_point service not available')
            return False

        req = NavToPoint.Request()
        req.x = x
        req.y = y
        req.use_yaw = True
        req.yaw = yaw

        future = self._nav_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=self._nav_timeout)

        if not future.done():
            self.get_logger().error(f'wp{idx}: nav timeout ({self._nav_timeout}s)')
            return False

        res = future.result()
        if res.success:
            self.get_logger().info(
                f'wp{idx}: arrived ({res.final_x:.3f}, {res.final_y:.3f})  '
                f'yaw={math.degrees(res.final_yaw):.1f}°'
            )
            return True

        self.get_logger().error(f'wp{idx}: nav failed — {res.message}')
        return False

    # ── Vision（佔位）────────────────────────────────────────────────────────
    def _call_vision(self, idx: int) -> bool:
        if not self._vision_cli.wait_for_service(timeout_sec=3.0):
            self.get_logger().warn(
                f'wp{idx}: /vision/recognize not available — skipping (placeholder)'
            )
            return False

        future = self._vision_cli.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=self._vision_timeout)

        if not future.done():
            self.get_logger().warn(f'wp{idx}: vision timeout ({self._vision_timeout}s)')
            return False

        res = future.result()
        if res.success:
            self.get_logger().info(f'wp{idx}: vision done — {res.message}')
        else:
            self.get_logger().warn(f'wp{idx}: vision failed — {res.message}')
        return res.success

    # ── Confirm ───────────────────────────────────────────────────────────────
    def _call_confirm(self, idx: int) -> bool:
        if not self._confirm_cli.wait_for_service(timeout_sec=3.0):
            self.get_logger().warn(f'wp{idx}: /semantic_map/confirm not available')
            return False

        future = self._confirm_cli.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=self._confirm_timeout)

        if not future.done():
            self.get_logger().warn(f'wp{idx}: confirm timeout')
            return False

        res = future.result()
        self.get_logger().info(f'wp{idx}: confirm — {res.message}')
        return res.success

    # ── Finalize ──────────────────────────────────────────────────────────────
    def _call_finalize(self, failed_wps: list) -> None:
        if not self._finalize_cli.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('/semantic_map/finalize not available')
            self._pub_status('ERROR: finalize service not available')
            return

        future = self._finalize_cli.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=15.0)

        if not future.done():
            self.get_logger().error('finalize timeout')
            self._pub_status('ERROR: finalize timeout')
            return

        res = future.result()
        summary = (
            f'Tour complete — {res.message}'
            + (f'  (failed wp: {failed_wps})' if failed_wps else '')
        )
        self.get_logger().info(f'=== {summary} ===')
        self._pub_status(summary)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _pub_status(self, text: str) -> None:
        msg = String()
        msg.data = text
        self._status_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WaypointTourNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
