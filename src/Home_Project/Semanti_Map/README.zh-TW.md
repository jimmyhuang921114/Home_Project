## 啟動

### 一鍵啟動（Nav2 + 語意地圖 + RViz2）

```bash
ros2 launch Semanti_Map bringup.launch.py
# Semanti_Map

<<<<<<< HEAD
ROS 2 套件，負責語意地圖的 **TF 投影層**：接收 YOLO 偵測結果，結合深度影像與相機內參將 2D pixel 座標投影為 map frame 3D 座標，轉發給下游地圖整合節點。
=======
使用模擬器時：

```bash
ros2 launch Semanti_Map bringup.launch.py use_sim_time:=true
```

ROS 2 套件，負責語意地圖的 **TF 投影層**：接收 GroundingDINO 偵測結果，結合深度影像與相機內參將 2D pixel 座標投影為 map frame 3D 座標，轉發給下游地圖整合節點處理。
>>>>>>> 87000aa918ba9ccbd01885deee1176eeb18fefe3

## 系統架構

```
/yolo/detections      ──┐
/realsense/depth        ├──► semantic_map_node ──► /semantic_map/raw_detections
/realsense/camera_info  ┘
```

本套件**不做**去重、融合、存檔，只負責感測資料的座標轉換。地圖整合邏輯由 `main_policy` 的 `dyn_ema_node` 處理。

## 2D → 3D 投影流程

```
YOLO center (u, v)  +  深度影像取 depth_window 視窗中位數 d
         ↓  相機內參 (fx, fy, cx, cy)
  cam_x = (u - cx) × d / fx
  cam_y = (v - cy) × d / fy
  cam_z = d
         ↓  TF2  (camera_frame → map_frame)
    (map_x, map_y, map_z)  →  發布至 /semantic_map/raw_detections
```

深度取樣使用 `depth_window` 半徑的視窗對有效值取**中位數**，避免單一無效像素造成誤差。

## 套件結構

```
Semanti_Map/
├── config/
│   ├── params.yaml          # 語意地圖節點參數
│   └── nav2_params.yaml     # Nav2 完整參數（AMCL、controller、planner 等）
├── map/
│   ├── map.yaml
│   └── map.png
├── launch/
│   ├── bringup.launch.py         # Nav2 + 語意地圖 + RViz2
│   └── semantic_map.launch.py    # 僅啟動語意地圖節點
└── Semanti_Map/
    └── semantic_map_node.py
```

## 依賴

| 套件 | 用途 |
|------|------|
| `nav2_bringup` | Nav2 定位與導航 launch 封裝（bringup 用） |
| `numpy` | 深度影像解碼與視窗取樣 |
| `tf2_ros` / `tf2_geometry_msgs` | 座標系轉換 |
| `rclpy` | ROS 2 Python 客戶端 |
| `sensor_msgs` | Image、CameraInfo |
| `geometry_msgs` | PointStamped |
| `std_msgs` | String（JSON） |

## 安裝

```bash
colcon build --packages-select Semanti_Map
source install/setup.bash
```


<<<<<<< HEAD
### 單獨啟動
=======
```



覆蓋地圖或參數：

```bash
ros2 launch Semanti_Map bringup.launch.py \
  map:=/path/to/other_map.yaml \
  nav2_params_file:=/path/to/nav2_params.yaml \
  use_rviz:=false
```

### 僅啟動語意地圖節點
>>>>>>> 87000aa918ba9ccbd01885deee1176eeb18fefe3

```bash
ros2 launch Semanti_Map semantic_map.launch.py
```

模擬器：

```bash
ros2 launch Semanti_Map semantic_map.launch.py use_sim_time:=true
```

覆蓋參數檔：

```bash
ros2 launch Semanti_Map semantic_map.launch.py \
  sem_params_file:=/path/to/my_params.yaml
```

### Nav2 + 導航服務 + RViz

```bash
ros2 launch Semanti_Map nav_bringup.launch.py
```

### 整合管線（三節點一起）

```bash
ros2 launch main_policy semantic_pipeline.launch.py
```

## Launch 參數

### semantic_map.launch.py

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `use_sim_time` | `false` | 模擬時鐘 |
| `sem_params_file` | `share/.../config/params.yaml` | 節點參數 YAML |

### nav_bringup.launch.py

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `map` | `share/.../map/map.yaml` | 地圖 YAML |
| `nav2_params_file` | `share/.../config/nav2_params.yaml` | Nav2 參數 |
| `nav_service_params_file` | `share/main_policy/config/nav_service_params.yaml` | 導航服務節點參數 |
| `use_sim_time` | `true` | 模擬時鐘 |
| `use_rviz` | `true` | 是否啟動 RViz2 |
| `use_nav2` | `true` | 是否啟動 Nav2 |

## 節點參數（params.yaml）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `detection_topic` | `/yolo/detections` | 偵測結果輸入 topic |
| `depth_topic` | `/realsense/depth` | 深度影像（16UC1 或 32FC1） |
| `camera_info_topic` | `/realsense/camera_info` | 相機內參 |
| `camera_frame` | `Camera_OmniVision_OV9782_Color` | 相機 TF frame |
| `map_frame` | `map` | 目標座標系 |
| `min_confidence` | `0.35` | 過濾低信心偵測 |
| `depth_scale` | `0.001` | 深度縮放（16UC1 mm→m 用 `0.001`；32FC1 用 `1.0`） |
| `depth_window` | `2` | 深度取樣視窗半徑（pixels） |

## Topics

### 訂閱

| Topic | 型別 | 說明 |
|-------|------|------|
| `/yolo/detections` | `std_msgs/String` | YOLO JSON 偵測結果 |
| `/realsense/depth` | `sensor_msgs/Image` | 深度影像 |
| `/realsense/camera_info` | `sensor_msgs/CameraInfo` | 相機內參 |

### 發布

| Topic | 型別 | 說明 |
|-------|------|------|
| `/semantic_map/raw_detections` | `std_msgs/String` | map frame 3D 偵測（未去重） |

### `/semantic_map/raw_detections` JSON 格式

```json
{
  "frame_id": "map",
  "detections": [
    {
      "class": "chair",
      "score": 0.87,
      "position": {"x": 1.23, "y": -0.45, "z": 0.80}
    }
  ]
}
```

## TF 錯誤說明

| 例外 | 原因 | 處理 |
|------|------|------|
| `LookupException` | frame 不存在（定位未初始化） | 略過，每 3 秒警告一次 |
| `ConnectivityException` | frame tree 中無連結路徑 | 略過，每 3 秒警告一次 |
| `ExtrapolationException` | TF buffer 尚未填滿（啟動競爭） | 略過，每 3 秒警告一次，數秒後自動恢復 |
