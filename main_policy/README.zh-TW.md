# main_policy

ROS 2 套件，負責語意地圖的 **地圖整合層**。

## 節點說明

### `map_builder_node` ← 主要節點

**停站觀測式語意地圖建置器。**

設計原則：語意地圖的物件是靜態的，機器人可以停下來觀測再寫入，不需要 EMA 即時融合。

```
機器人停下來
     ↓
發布 trigger "start"
     ↓
收集 N 幀 YOLO 偵測（預設 10 幀）
     ↓
依 class 分組 → 空間叢集 → 取中位數
     ↓
一致性檢查（std_dev < 0.15m）
     ↓
通過 → 觀測次數加權寫入持久化地圖
失敗 → 捨棄（深度不可信）
```

**為何比 EMA 好：**
- EMA 適合追蹤**移動**物件；靜態物件用 EMA 反而引入漂移
- 停站收集多幀後取中位數，天然濾除深度 outlier
- `min_obs` 門檻過濾單幀誤偵測（假陽性）
- 一致性檢查過濾深度噪聲大的遠距觀測

### `dyn_ema_node` ← 保留備用

動態 EMA 版本，適合機器人**持續移動**時的即時建圖場景。

### `map_integrator_node` ← 舊版

固定 alpha EMA，保留相容。

---

## 套件結構

```
main_policy/
├── config/
│   ├── map_builder_params.yaml   # map_builder_node 參數
│   └── dyn_ema_params.yaml       # dyn_ema_node 參數
├── launch/
│   ├── map_builder.launch.py        # 單獨啟動 map_builder_node
│   ├── dyn_ema.launch.py            # 單獨啟動 dyn_ema_node
│   └── semantic_pipeline.launch.py  # 三節點整合管線（主要入口）
└── main_policy/
    ├── map_builder_node.py
    ├── dyn_ema_node.py
    └── map_integrator_node.py
```

---

## 安裝

```bash
colcon build --packages-select yolo Semanti_Map main_policy
source install/setup.bash
```

---

## 啟動

### 整合管線（三節點）—— 最常用

```bash
ros2 launch main_policy semantic_pipeline.launch.py
ros2 launch main_policy semantic_pipeline.launch.py use_sim_time:=true
```

### 單獨啟動 map_builder_node

```bash
ros2 launch main_policy map_builder.launch.py
```

---

## 建圖流程

啟動後節點處於 **IDLE** 狀態，等待 trigger。

### 觸發一次觀測

```bash
ros2 topic pub /semantic_map/trigger std_msgs/msg/String "data: 'start'" --once
```

### 其他指令

```bash
# 取消本次收集（收到 commit 之前）
ros2 topic pub /semantic_map/trigger std_msgs/msg/String "data: 'cancel'" --once

# 清空整張地圖
ros2 topic pub /semantic_map/trigger std_msgs/msg/String "data: 'clear'" --once
```

### 查看狀態

```bash
ros2 topic echo /map_builder/status
# 輸出範例：
# data: collecting 3/10
# data: idle (last committed 2)
```

---

## Launch 參數

### semantic_pipeline.launch.py

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `use_sim_time` | `false` | 套用至三個節點 |
| `model_path` | `yolov8n.pt` | YOLO 模型路徑 |
| `yolo_params_file` | `share/yolo/config/params.yaml` | YOLO 節點參數 |
| `sem_params_file` | `share/Semanti_Map/config/params.yaml` | SemanticMap 節點參數 |
| `map_builder_params_file` | `share/main_policy/config/map_builder_params.yaml` | MapBuilder 節點參數 |

---

## 節點參數（map_builder_params.yaml）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `collect_frames` | `10` | 每次 trigger 收幾幀偵測 |
| `collect_timeout` | `5.0` | 最長等待時間（秒），偵測稀疏時避免卡住 |
| `min_obs` | `5` | 叢集最少觀測數，低於此值為雜訊捨棄 |
| `max_std_dev` | `0.15` | 位置標準差上限（m），超過表示深度不穩定捨棄 |
| `merge_distance` | `0.50` | 同類別叢集半徑（m），同時用於跨 session 去重 |
| `map_save_path` | `.../semantic_map.json` | 存檔路徑 |
| `auto_save_interval` | `60.0` | 自動存檔週期（秒） |
| `publish_rate` | `2.0` | 地圖發布頻率（Hz） |

---

## Topics

### 訂閱

| Topic | 型別 | 說明 |
|-------|------|------|
| `/semantic_map/raw_detections` | `std_msgs/String` | 來自 Semanti_Map 的 map frame 3D 偵測 |
| `/semantic_map/trigger` | `std_msgs/String` | `"start"` / `"cancel"` / `"clear"` |

### 發布

| Topic | 型別 | 說明 |
|-------|------|------|
| `/semantic_map` | `visualization_msgs/MarkerArray` | RViz 球體 + 文字標籤（含觀測次數） |
| `/semantic_objects` | `std_msgs/String` | 全物件 JSON |
| `/map_builder/status` | `std_msgs/String` | 狀態字串 |

### `/semantic_objects` JSON 格式

```json
{
  "frame_id": "map",
  "count": 2,
  "objects": [
    {
      "id": "chair_0",
      "class": "chair",
      "position": {"x": 1.234, "y": -0.456, "z": 0.800},
      "confidence": 0.87,
      "observe_count": 18
    }
  ]
}
```
