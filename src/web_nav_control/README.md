# web_nav_control

ROS2 + Nav2 Web 控制台 starter package。

功能：

- Main Map：顯示 `/map`、`/amcl_pose`、`/plan`
- Navigation Points：讀取 waypoint、點選後呼叫 `/nav_to_point`
- Polygon Tool：在地圖上匡選多邊形，自動產生 waypoint，匯出 YAML / JSON

建議放置位置：

```bash
/home/jimmy/work_ws/home_project_ws/src/web_nav_control
```

---

## 1. 解壓到 ROS2 workspace

假設 zip 在 `~/Downloads/web_nav_control.zip`：

```bash
cd /home/jimmy/work_ws/home_project_ws/src
unzip ~/Downloads/web_nav_control.zip
```

確認：

```bash
ls /home/jimmy/work_ws/home_project_ws/src/web_nav_control
```

---

## 2. 安裝 backend 需要的 Python 套件

不要 pip install rclpy，rclpy 由 ROS2 Humble 提供。

```bash
sudo apt update
sudo apt install -y python3-pip python3-fastapi python3-uvicorn python3-yaml
```

如果 apt 沒有 fastapi / uvicorn，才使用：

```bash
python3 -m pip install --user fastapi uvicorn pyyaml
```

---

## 3. build ROS2 package

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select web_nav_control
source install/setup.bash
```

---

## 4. 啟動 ROS2 backend

請先啟動你的 Nav2 / map / AMCL。

例如你原本的：

```bash
source /opt/ros/humble/setup.bash
source /home/jimmy/work_ws/home_project_ws/install/setup.bash
ros2 launch Semanti_Map nav_bringup.launch.py
```

然後開新 terminal：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run web_nav_control web_nav_api
```

Backend 預設：

```text
http://127.0.0.1:8000
```

測試：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/map
```

---

## 5. 啟動 frontend

```bash
cd /home/jimmy/work_ws/home_project_ws/src/web_nav_control/frontend
npm install
npm run dev -- --host 0.0.0.0
```

瀏覽器開：

```text
http://127.0.0.1:5173
```

---

## 6. API

### GET `/api/map`
取得 ROS2 `/map` cache。

### GET `/api/robot_pose`
取得 `/amcl_pose` cache。

### GET `/api/plan`
取得 `/plan` cache。

### GET `/api/waypoints`
取得目前 backend 載入的 waypoints。

### POST `/api/waypoints/load`
從 YAML 檔案載入 waypoints。

```json
{
  "path": "/home/jimmy/work_ws/home_project_ws/src/Semanti_Map/config/nav2_waypoints_margin_060.yaml"
}
```

### POST `/api/nav_to_point`
呼叫 ROS2 `/nav_to_point`。

```json
{
  "x": -2.335,
  "y": 3.775,
  "yaw": 0.0,
  "use_yaw": false
}
```

### POST `/api/generate_waypoints`
從 polygon 產生 waypoint。

```json
{
  "polygon": [[-2.0, 1.0], [-1.0, 3.0], [1.0, 3.0], [1.5, 1.0]],
  "spacing": 0.75,
  "margin": 0.60
}
```

### POST `/api/export_waypoints`
輸出 YAML / JSON。

```json
{
  "format": "yaml",
  "waypoints": [...]
}
```

---

## 注意

這是 starter package，不會強制改你原本的 ROS2 package。若你的 waypoint YAML 欄位不同，可以調整 `backend/web_nav_api/waypoint_io.py`。
