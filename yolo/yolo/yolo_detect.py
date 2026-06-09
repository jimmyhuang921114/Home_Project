#!/usr/bin/env python3
import json
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String


class YoloDetectNode(Node):
    def __init__(self):
        super().__init__('yolo_detect_node')

        self.declare_parameter('image_topic', '/realsense/rgb')
        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('confidence_threshold', 0.35)
        self.declare_parameter('min_period_s', 0.10)

        self.image_topic = str(self.get_parameter('image_topic').value)
        model_path = str(self.get_parameter('model_path').value)
        self.conf_threshold = float(self.get_parameter('confidence_threshold').value)
        self.min_period_s = float(self.get_parameter('min_period_s').value)

        from ultralytics import YOLO
        self.get_logger().info(f'Loading YOLO model: {model_path}')
        self.model = YOLO(model_path)
        self.get_logger().info('YOLO model loaded.')

        self._last_process_time = 0.0
        self._is_processing = False

        self.create_subscription(Image, self.image_topic, self._image_callback, 10)
        self._det_pub = self.create_publisher(String, '/yolo/detections', 10)

        self.get_logger().info(f'YoloDetectNode started. Subscribed to {self.image_topic}')

    def _image_callback(self, msg: Image):
        now = time.time()
        if self._is_processing:
            return
        if now - self._last_process_time < self.min_period_s:
            return
        self._last_process_time = now
        self._is_processing = True
        try:
            img = self._ros_to_cv2(msg)
            results = self.model(img, conf=self.conf_threshold, verbose=False)
            detections = self._parse_results(results)
            self._publish(detections)
        except Exception as e:
            self.get_logger().error(f'YOLO detection error: {e}')
        finally:
            self._is_processing = False

    def _ros_to_cv2(self, msg: Image) -> np.ndarray:
        enc = msg.encoding.lower()
        h, w = msg.height, msg.width
        data = np.frombuffer(msg.data, dtype=np.uint8)
        if enc in ('rgb8', 'bgr8'):
            img = data.reshape((h, w, 3))
            if enc == 'rgb8':
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        elif enc in ('rgba8', 'bgra8'):
            img = data.reshape((h, w, 4))
            if enc == 'rgba8':
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif enc == 'mono8':
            img = data.reshape((h, w))
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError(f'Unsupported encoding: {msg.encoding}')
        return img.copy()

    def _parse_results(self, results) -> list:
        detections = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                class_name = self.model.names[cls_id]
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                detections.append({
                    'class': class_name,
                    'score': round(conf, 4),
                    'center': {'x': round(cx, 2), 'y': round(cy, 2)},
                    'bbox': [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                })
        return detections

    def _publish(self, detections: list):
        msg = String()
        msg.data = json.dumps({'detections': detections}, ensure_ascii=False)
        self._det_pub.publish(msg)
        if detections:
            self.get_logger().debug(f'Published {len(detections)} detections')


def main(args=None):
    rclpy.init(args=args)
    node = YoloDetectNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
