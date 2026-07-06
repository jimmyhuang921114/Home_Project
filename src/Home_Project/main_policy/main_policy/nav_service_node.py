#!/usr/bin/env python3
"""
Nav Service Node
================
提供 ROS 2 Service，讓其他節點或程式呼叫，
傳入地圖上的 (x, y) 座標與可選終點朝向，節點會：

  1. 在 global_costmap 上用 BFS 找離目標最近的可達點
  2. 以 NavigateToPose 導航過去
  3. 旋轉至指定朝向（use_yaw=true）或面向原始目標點（預設）
  4. 回傳 success / message / 實際抵達座標與朝向

Service：
  /nav_to_point  (semantic_nav_interfaces/srv/NavToPoint)

呼叫範例（CLI）：
  # 面向目標點（預設）
  ros2 service call /nav_to_point \
    semantic_nav_interfaces/srv/NavToPoint \
    "{x: 3.5, y: 1.2, use_yaw: false, yaw: 0.0}"

  # 自訂朝向（例如面向正北 yaw=1.5708 rad = 90°）
  ros2 service call /nav_to_point \
    semantic_nav_interfaces/srv/NavToPoint \
    "{x: 3.5, y: 1.2, use_yaw: true, yaw: 1.5708}"

呼叫範例（Python rclpy）：
  from semantic_nav_interfaces.srv import NavToPoint
  cli = node.create_client(NavToPoint, 'nav_to_point')
  req = NavToPoint.Request()
  req.x, req.y = 3.5, 1.2
  req.use_yaw = True       # 省略或設 False → 面向目標點
  req.yaw = 1.5708
  future = cli.call_async(req)
"""

import math
import threading
from collections import deque
from typing import Optional, Tuple

import rclpy
import rclpy.duration
import rclpy.qos
import rclpy.time
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

import tf2_ros
from tf2_ros import ConnectivityException, ExtrapolationException, LookupException

from semantic_nav_interfaces.srv import NavToPoint


# costmap 中 cost <= 此值的格子視為可導航目標點
_NAVIGABLE_COST = 65
# BFS 最大搜尋半徑
_SEARCH_RADIUS_M = 3.0


class NavServiceNode(Node):

    def __init__(self) -> None:
        super().__init__('nav_service_node')

        # ── 參數 ──────────────────────────────────────────────────────────────
        self.declare_parameter('nav_action',     'navigate_to_pose')
        self.declare_parameter('costmap_topic',  '/global_costmap/costmap')
        self.declare_parameter('map_frame',      'map')
        self.declare_parameter('base_frame',     'base_link')
        self.declare_parameter('nav_timeout',    120.0)   # 單次導航最長等待（秒）

        p = self.get_parameter
        self._action_name   = str(p('nav_action').value)
        self._costmap_topic = str(p('costmap_topic').value)
        self._map_frame     = str(p('map_frame').value)
        self._base_frame    = str(p('base_frame').value)
        self._nav_timeout   = float(p('nav_timeout').value)

        # ── 狀態 ──────────────────────────────────────────────────────────────
        self._costmap: Optional[OccupancyGrid] = None
        self._costmap_lock = threading.Lock()
        self._busy = False
        self._busy_lock = threading.Lock()

        # ── TF ────────────────────────────────────────────────────────────────
        self._tf_buffer   = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        # ── Callback group（允許 service callback 內部等待 action）────────────
        self._cbg = ReentrantCallbackGroup()

        # ── Nav2 action client ────────────────────────────────────────────────
        self._nav_client = ActionClient(
            self, NavigateToPose, self._action_name,
            callback_group=self._cbg,
        )

        # ── Costmap subscriber（TRANSIENT_LOCAL 才能拿到最新一幀）────────────
        costmap_qos = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.TRANSIENT_LOCAL,
            depth=1,
        )
        self.create_subscription(
            OccupancyGrid, self._costmap_topic,
            self._costmap_cb, costmap_qos,
            callback_group=self._cbg,
        )

        # ── Service server ────────────────────────────────────────────────────
        self.create_service(
            NavToPoint, 'nav_to_point',
            self._service_cb,
            callback_group=self._cbg,
        )

        self.get_logger().info(
            f'NavServiceNode started\n'
            f'  service     : /nav_to_point\n'
            f'  nav action  : {self._action_name}\n'
            f'  costmap     : {self._costmap_topic}\n'
            f'  nav_timeout : {self._nav_timeout} s'
        )

    # ── Costmap ────────────────────────────────────────────────────────────────
    def _costmap_cb(self, msg: OccupancyGrid) -> None:
        with self._costmap_lock:
            self._costmap = msg

    # ── Service callback ───────────────────────────────────────────────────────
    def _service_cb(
        self,
        request: NavToPoint.Request,
        response: NavToPoint.Response,
    ) -> NavToPoint.Response:

        # 拒絕重複呼叫
        with self._busy_lock:
            if self._busy:
                response.success = False
                response.message = 'Navigator busy — try again later'
                return response
            self._busy = True

        try:
            return self._handle(request, response)
        finally:
            with self._busy_lock:
                self._busy = False

    def _handle(
        self,
        request: NavToPoint.Request,
        response: NavToPoint.Response,
    ) -> NavToPoint.Response:

        tx, ty = request.x, request.y
        self.get_logger().info(
            f'[NavToPoint] target=({tx:.3f}, {ty:.3f})  '
            f'use_yaw={request.use_yaw}'
            + (f'  yaw={math.degrees(request.yaw):.1f}°' if request.use_yaw else '')
        )

        # ① 找最近可達點
        nx, ny = self._nearest_navigable(tx, ty)
        self.get_logger().info(f'[NavToPoint] nav_goal=({nx:.3f}, {ny:.3f})')

        # ② 導航過去
        if not self._navigate(nx, ny, yaw=None):
            response.success = False
            response.message = f'Navigation to ({nx:.3f}, {ny:.3f}) failed'
            response.final_x = nx
            response.final_y = ny
            response.final_yaw = 0.0
            return response

        # ③ 取得實際抵達位置
        rx, ry = self._robot_pos()
        if rx is None:
            rx, ry = nx, ny

        response.final_x = rx
        response.final_y = ry

        # ④ 決定終點朝向
        if request.use_yaw:
            final_yaw = request.yaw
            self.get_logger().info(
                f'[NavToPoint] rotating to custom yaw={math.degrees(final_yaw):.1f}°'
            )
        else:
            final_yaw = math.atan2(ty - ry, tx - rx)
            self.get_logger().info(
                f'[NavToPoint] rotating to face target  yaw={math.degrees(final_yaw):.1f}°'
            )

        response.final_yaw = final_yaw

        # ⑤ 執行旋轉
        if not self._navigate(rx, ry, yaw=final_yaw):
            self.get_logger().warn('[NavToPoint] rotation failed — arrived but not facing target')
            response.success = True
            response.message = 'Arrived but rotation failed'
            return response

        response.success = True
        response.message = (
            f'Done  yaw={math.degrees(final_yaw):.1f}°'
            + (' (custom)' if request.use_yaw else ' (facing target)')
        )
        self.get_logger().info('[NavToPoint] done ✓')
        return response

    # ── BFS 最近可達點 ──────────────────────────────────────────────────────────
    def _nearest_navigable(self, x: float, y: float) -> Tuple[float, float]:
        with self._costmap_lock:
            cm = self._costmap

        if cm is None:
            self.get_logger().warn('No costmap yet — using raw target')
            return x, y

        info = cm.info
        res  = info.resolution
        ox   = info.origin.position.x
        oy   = info.origin.position.y
        W, H = info.width, info.height

        def w2g(wx: float, wy: float) -> Tuple[int, int]:
            return int((wx - ox) / res), int((wy - oy) / res)

        def g2w(gx: int, gy: int) -> Tuple[float, float]:
            return (gx + 0.5) * res + ox, (gy + 0.5) * res + oy

        def navigable(gx: int, gy: int) -> bool:
            if not (0 <= gx < W and 0 <= gy < H):
                return False
            c = cm.data[gy * W + gx]
            return 0 <= c <= _NAVIGABLE_COST   # -1=unknown, 100=lethal → 排除

        max_cells = int(_SEARCH_RADIUS_M / res)
        sgx, sgy  = w2g(x, y)

        if navigable(sgx, sgy):
            return x, y

        # BFS 從目標點向外擴散
        visited: set = {(sgx, sgy)}
        queue: deque = deque([(sgx, sgy, 0)])

        while queue:
            cgx, cgy, depth = queue.popleft()
            if depth > max_cells:
                break
            if navigable(cgx, cgy):
                wx, wy = g2w(cgx, cgy)
                self.get_logger().info(
                    f'Nearest navigable: ({wx:.3f}, {wy:.3f})  '
                    f'dist={depth * res:.2f}m from target'
                )
                return wx, wy
            for dx, dy in ((0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)):
                nb = (cgx + dx, cgy + dy)
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb[0], nb[1], depth + 1))

        self.get_logger().warn(
            f'No navigable point within {_SEARCH_RADIUS_M}m — using raw target'
        )
        return x, y

    # ── NavigateToPose（blocking）──────────────────────────────────────────────
    def _navigate(self, x: float, y: float, yaw: Optional[float]) -> bool:
        if not self._nav_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('NavigateToPose action server not available')
            return False

        # yaw=None → 面向行進方向（讓 Nav2 自行決定），用 0 做預設
        goal_yaw = yaw if yaw is not None else 0.0

        goal     = NavigateToPose.Goal()
        goal.pose = self._make_pose(x, y, goal_yaw)
        goal.behavior_tree = ''

        done  = threading.Event()
        status_holder: list = [GoalStatus.STATUS_UNKNOWN]

        def on_goal(future):
            handle = future.result()
            if not handle.accepted:
                self.get_logger().warn('NavigateToPose goal rejected')
                status_holder[0] = GoalStatus.STATUS_ABORTED
                done.set()
                return
            handle.get_result_async().add_done_callback(on_result)

        def on_result(future):
            status_holder[0] = future.result().status
            done.set()

        self._nav_client.send_goal_async(goal).add_done_callback(on_goal)

        if not done.wait(timeout=self._nav_timeout):
            self.get_logger().error(f'Navigation timeout ({self._nav_timeout}s)')
            return False

        ok = status_holder[0] == GoalStatus.STATUS_SUCCEEDED
        if not ok:
            self.get_logger().warn(f'Navigation ended with status={status_holder[0]}')
        return ok

    # ── TF helper ─────────────────────────────────────────────────────────────
    def _robot_pos(self) -> Tuple[Optional[float], Optional[float]]:
        try:
            tf = self._tf_buffer.lookup_transform(
                self._map_frame, self._base_frame,
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=1.0),
            )
            return tf.transform.translation.x, tf.transform.translation.y
        except (LookupException, ConnectivityException, ExtrapolationException) as e:
            self.get_logger().warn(f'TF lookup failed: {e}')
            return None, None

    # ── 建立 PoseStamped ──────────────────────────────────────────────────────
    def _make_pose(self, x: float, y: float, yaw: float) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = self._map_frame
        ps.header.stamp    = self.get_clock().now().to_msg()
        ps.pose.position.x = x
        ps.pose.position.y = y
        ps.pose.position.z = 0.0
        # yaw → quaternion（繞 z 軸）
        ps.pose.orientation.z = math.sin(yaw / 2.0)
        ps.pose.orientation.w = math.cos(yaw / 2.0)
        return ps


# ──────────────────────────────────────────────────────────────────────────────
def main(args=None) -> None:
    rclpy.init(args=args)
    node = NavServiceNode()
    # MultiThreadedExecutor：讓 service callback 等待 action 時不阻塞其他 callbacks
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
