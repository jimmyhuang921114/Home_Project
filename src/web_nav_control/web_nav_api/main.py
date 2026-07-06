from __future__ import annotations

import threading

import rclpy
import uvicorn

from .app import create_app
from .ros_node import WebNavRosNode


def ros_spin(node: WebNavRosNode) -> None:
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()


def main() -> None:
    rclpy.init()
    node = WebNavRosNode()

    thread = threading.Thread(target=ros_spin, args=(node,), daemon=True)
    thread.start()

    app = create_app(node)
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')

    rclpy.shutdown()


if __name__ == '__main__':
    main()
