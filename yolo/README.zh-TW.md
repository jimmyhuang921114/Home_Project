# yolo

ROS 2 套件，負責語意地圖管線的 **影像偵測層**：從 RealSense RGB 影像中偵測物件，輸出與 GroundingDINO 相容的 JSON 格式，供下游 `Semanti_Map` 進行 TF 投影。

## 系統架構

```
/realsense/rgb ──► yolo_detect_node ──► /yolo/detections  (std_msgs/String, JSON)
```

## 偵測輸出格式

```json
{
  "detections": [
    {
      "class": "chair",
      "score": 0.8714,
      "center": {"x": 318.5, "y": 241.2},
      "bbox": [210.3, 155.1, 426.7, 327.3]
    }
  ]
}
```

## 套件結構

```
yolo/
├── config/
│   └── params.yaml          # 節點預設參數
├── launch/
│   └── yolo_detect.launch.py
└── yolo/
    └── yolo_detect.py
```

## 依賴

| 套件 | 用途 |
|------|------|
| `ultralytics` | YOLOv8/v11 推理（`pip install ultralytics`） |
| `opencv-python` | ROS Image → numpy 轉換 |
| `rclpy` | ROS 2 Python 客戶端 |
| `sensor_msgs` | Image |
| `std_msgs` | String（JSON 發布） |

## 安裝

```bash
pip install ultralytics
colcon build --packages-select yolo
source install/setup.bash
```

## 啟動

### 單獨啟動

```bash
ros2 launch yolo yolo_detect.launch.py
```

模擬器 + 自訂模型：

```bash
ros2 launch yolo yolo_detect.launch.py \
  use_sim_time:=true \
  model_path:=/abs/path/to/yolov8s.pt
```

### 整合管線（三節點一起）

```bash
ros2 launch main_policy semantic_pipeline.launch.py
```

## Launch 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `use_sim_time` | `false` | 模擬時鐘（Gazebo / rosbag） |
| `model_path` | `yolov8n.pt` | YOLO 模型路徑，相對路徑由 ultralytics 自動下載 |
| `yolo_params_file` | `share/.../config/params.yaml` | 節點參數 YAML 覆蓋路徑 |

## 節點參數（params.yaml）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `image_topic` | `/realsense/rgb` | 輸入 RGB 影像 topic |
| `model_path` | `yolov8n.pt` | YOLO 模型路徑 |
| `confidence_threshold` | `0.35` | 偵測信心度門檻 |
| `min_period_s` | `0.10` | 最短推理間隔（秒），避免 GPU 過載 |

## Topics

### 訂閱

| Topic | 型別 | 說明 |
|-------|------|------|
| `/realsense/rgb` | `sensor_msgs/Image` | RGB 影像（支援 rgb8 / bgr8 / rgba8 / mono8） |

### 發布

| Topic | 型別 | 說明 |
|-------|------|------|
| `/yolo/detections` | `std_msgs/String` | JSON 偵測結果，格式與 GroundingDINO 相容 |
