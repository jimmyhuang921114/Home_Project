# Home Project ROS 2 Workspace

## 1. 專案簡介

這是 `/home/jimmy/work_ws/home_project_ws` 底下的 ROS 2 colcon workspace。主要內容是 Nav2 導航、waypoint 巡航、semantic map 建置、GroundingDINO/RAM 視覺偵測，以及 semantic map object retrieval / web navigation control。

本 README 是依照實際讀取 `src/` 內的 `package.xml`、`setup.py`、`CMakeLists.txt`、launch、config、srv 與 Python node 程式整理。若用途無法從程式碼明確判斷，會標註「需要再確認」。

## 2. Workspace 路徑

```bash
cd /home/jimmy/work_ws/home_project_ws
```

主要 source 路徑：

```text
/home/jimmy/work_ws/home_project_ws/src
```

目前根目錄包含 `src/`、`build/`、`install/`、`log/`，因此是 colcon workspace。

## 3. 系統需求

已從 package 與程式碼看到的需求：

- ROS 2，程式註解與 README 範例偏向 Humble。
- `colcon`、`ament_python`、`ament_cmake`、`rosidl_default_generators`。
- Nav2：`nav2_bringup`、`nav2_msgs`、`nav2_amcl`、`nav2_bt_navigator` 等。
- ROS messages：`rclpy`、`nav_msgs`、`geometry_msgs`、`std_msgs`、`std_srvs`、`sensor_msgs`、`visualization_msgs`、`tf2_ros`。
- Vision：`torch`、`transformers`、`opencv-python`、`Pillow`、`numpy`，以及 RAM / recognize-anything 與 GroundingDINO 相關模型。
- Web UI backend：`fastapi`、`uvicorn`、`pyyaml`。
- object retrieval：PostgreSQL / pgvector、embedding provider、chat/agent provider；實際設定在 `src/robot_object_retrieval-main/.env` 或 `robot_object.env`，不要上傳公開 repo。

常見環境載入：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
```

## 4. 專案 Tree

以下是整理後的 `src` tree，已排除 `.git`、`__pycache__`、`build`、`install`、`log`、大型模型權重與常見二進位輸出。

```text
src
├── docs
│   ├── architecture_audit_plan.md
│   └── pipeline_topic_schema_audit.md
├── Grounding_DINO
│   ├── groundingdino.py
│   └── recognize-anything-plus-model
│       ├── .gitattributes
│       └── README.md
├── Home_Project
│   ├── backup
│   │   └── main_policy
│   │       ├── map_integrator_node.py
│   │       ├── semantic_pipeline.launch.py
│   │       ├── waypoint_nav2_action_node.py
│   │       └── *.bak*
│   ├── main_policy
│   │   ├── config
│   │   │   ├── map_builder_params.yaml
│   │   │   └── nav_service_params.yaml
│   │   ├── launch
│   │   │   ├── main_policy_bringup.launch.py
│   │   │   ├── task_orchestrator.launch.py
│   │   │   └── vision_mapping.launch.py
│   │   ├── main_policy
│   │   │   ├── map_builder_node.py
│   │   │   ├── nav_service_node.py
│   │   │   ├── robot_task_orchestrator_node.py
│   │   │   └── sementic_map_node.py
│   │   ├── package.xml
│   │   ├── setup.cfg
│   │   └── setup.py
│   ├── semantic_nav_interfaces
│   │   ├── CMakeLists.txt
│   │   ├── package.xml
│   │   └── srv
│   │       └── NavToPoint.srv
│   └── Semanti_Map
│       ├── config
│       │   ├── localization.yaml
│       │   └── nav2_params.yaml
│       ├── launch
│       │   └── nav_bringup.launch.py
│       ├── map
│       │   ├── map.png
│       │   └── map.yaml
│       ├── package.xml
│       ├── setup.cfg
│       ├── setup.py
│       └── Semanti_Map
│           └── semantic_map_node.py
├── recognize-anything
│   ├── COLCON_IGNORE
│   ├── ram
│   ├── pretrained
│   ├── requirements.txt
│   ├── setup.py
│   └── README.md
├── robot_object_retrieval-main
│   ├── data
│   ├── docs
│   ├── prompts
│   ├── ros2_ws
│   │   └── src
│   │       └── robot_object_retrieval_ros
│   ├── scripts
│   ├── sql
│   ├── src
│   │   └── robot_object_retrieval
│   ├── tests
│   ├── .env -> /home/jimmy/work_ws/docker/robot_object.env
│   ├── .env.example
│   ├── pyproject.toml
│   ├── README.md
│   └── robot_object.env
├── test_video
│   ├── courtyard-design-2.jpg
│   ├── modern-sofa-1.jpg
│   └── *.mp4
├── user_interface
├── vision_package
│   ├── config
│   │   ├── limit_prompt.yaml
│   │   ├── vision_high_recall_params.yaml
│   │   └── vision_stationary_balanced_params.yaml
│   ├── launch
│   │   └── vision.launch.py
│   ├── package.xml
│   ├── setup.cfg
│   ├── setup.py
│   └── vision_package
│       ├── bbox_all_3d_marker_node.py
│       ├── bbox_center_3d_node.py
│       ├── bbox_filter_fusion_node.py
│       ├── grounding_dino_node.py
│       └── ram_node.py
└── web_nav_control
    ├── frontend
    ├── runtime
    │   ├── map
    │   │   ├── map.png
    │   │   └── map.yaml
    │   └── waypoints
    │       └── nav2_waypoints.yaml
    ├── scripts
    ├── package.xml
    ├── setup.py
    └── web_nav_api
        ├── app.py
        ├── main.py
        ├── ros_node.py
        ├── static_map.py
        ├── waypoint_generator.py
        └── waypoint_io.py
```

## 5. Packages 總覽

| Package / 目錄 | 類型 | 主要用途 |
|---|---|---|
| `main_policy` | `ament_python` | NavToPoint service、semantic map builder、waypoint runner、task orchestrator |
| `Semanti_Map` | `ament_python` | Nav2 bringup 與舊式 semantic map TF 投影層 |
| `semantic_nav_interfaces` | `ament_cmake` interface package | 定義 `NavToPoint.srv` |
| `vision_package` | `ament_python` | RAM、GroundingDINO、bbox filter、depth 3D projection、RViz marker |
| `web_nav_control` | `ament_python` + frontend | FastAPI backend、Nav2 web dashboard、waypoint / polygon tool |
| `robot_object_retrieval_ros` | `ament_cmake` interface + Python node | 提供 `/semantic_map/import` service，銜接 object retrieval DB importer |
| `recognize-anything` | third-party repo，含 `COLCON_IGNORE` | RAM / RAM++ 原始碼與模型相關內容 |
| `Grounding_DINO` | script / model 相關目錄 | GroundingDINO standalone script 與 RAM++ model card；非 ROS package |
| `robot_object_retrieval-main` | third-party / app repo，內含巢狀 `ros2_ws` | semantic map object retrieval、agent、DB、ROS adapter |

## 6. Package 詳細說明

### `main_policy`

- 路徑：`src/Home_Project/main_policy`
- 類型：`ament_python`
- 依賴：`semantic_nav_interfaces`、`robot_object_retrieval_ros`、`nav2_msgs`、`nav_msgs`、`geometry_msgs`、`std_msgs`、`visualization_msgs`、`tf2_ros`
- 主要用途：
  - `/nav_to_point` service 封裝 Nav2 `NavigateToPose`。
  - 從 `/grounding_dino/objects_3d_json` 建立 semantic map。
  - waypoint 巡航與 task orchestrator。
  - 可選匯入 semantic map snapshot 到 `/semantic_map/import`。
- Nodes：
  - `nav_service_node`
  - `map_builder_node`
  - `sementic_map_node`
  - `robot_task_orchestrator_node`
- Launch：
  - `main_policy_bringup.launch.py`
  - `task_orchestrator.launch.py`
  - `vision_mapping.launch.py`
- Config：
  - `config/map_builder_params.yaml`
  - `config/nav_service_params.yaml`
- 主要 topic / service / action：
  - Service server：`/nav_to_point`
  - Service server：`/semantic_map/confirm`
  - Service server：`/semantic_map/finalize`
  - Service server：`/semantic_map/clear_viewpoints`
  - Service server：`/semantic_map/clear_map`
  - Service server：`/next_waypoint_nav`
  - Service server：`/reset_waypoint_nav`
  - Service server：`/skip_waypoint_nav`
  - Service server：`/start_waypoint_nav_auto`
  - Service server：`/stop_waypoint_nav_auto`
  - Service server：`/waypoint_nav_stats`
  - Service server：`/task/detect_here`
  - Service server：`/task/go_to_point_and_detect`
  - Service server：`/main_policy/next`
  - Service server：`/main_policy/start`
  - Service server：`/main_policy/stop`
  - Service server：`/main_policy/reset`
  - Service server：`/main_policy/status`
  - Service server：`/main_policy/export_records`
  - Service client：`/grounding_dino/detect_once`
  - Service client：`/semantic_map/import`
  - Action client：`navigate_to_pose`
  - Subscribe：`/global_costmap/costmap`
  - Subscribe：`/grounding_dino/objects_3d_json`
  - Publish：`/semantic_objects`
  - Publish：`/semantic_map`
  - Publish：`/map_builder/status`
  - Publish：`/map_builder/viewpoints_info`
- 與其他 package 關係：
  - 使用 `semantic_nav_interfaces/srv/NavToPoint`。
  - 需要 `Semanti_Map/nav_bringup.launch.py` 啟動 Nav2 與 map。
  - 需要 `vision_package` 提供 `/grounding_dino/objects_3d_json`。
  - `robot_task_orchestrator_node` 會呼叫 `robot_object_retrieval_ros/srv/ImportSemanticMap`。
- 需要再確認：
  - `main_policy_bringup.launch.py` include `main_policy/launch/map_builder.launch.py`，但目前該檔不存在。
  - `use_tour` 會啟動 `waypoint_tour_node`，但 `setup.py` 沒有此 executable。
  - 預設 waypoint YAML 指到 `/home/jimmy/work_ws/home_project_ws/src/Semanti_Map/config/nav2_waypoints_margin_060.yaml`，目前未在 `src/Home_Project/Semanti_Map/config` 看到該檔。

### `Semanti_Map`

- 路徑：`src/Home_Project/Semanti_Map`
- 類型：`ament_python`
- 主要用途：
  - `nav_bringup.launch.py` include Nav2 localization / navigation。
  - `semantic_map_node` 將 2D detection + depth + TF 投影成 map frame 3D detection。
- Nodes：
  - `semantic_map_node`
- Launch：
  - `nav_bringup.launch.py`
- Config / map：
  - `config/localization.yaml`
  - `config/nav2_params.yaml`
  - `map/map.yaml`
  - `map/map.png`
- 主要 topic：
  - Subscribe：`/yolo/detections`，可由參數 `detection_topic` 改。
  - Subscribe：`/realsense/depth`
  - Subscribe：`/realsense/camera_info`
  - Publish：`/semantic_map/raw_detections`
- 主要 frame：
  - `map`
  - `odom`
  - `base_link`
  - `Camera_OmniVision_OV9782_Color`
- 與其他 package 關係：
  - `nav_bringup.launch.py` 會啟動 `main_policy/nav_service_node`。
  - 可選啟動 `main_policy/sementic_map_node` waypoint runner。
- 需要再確認：
  - `nav_bringup.launch.py` 宣告 `sem_params_file` 預設為 `Semanti_Map/config/params.yaml`，但目前 config 目錄沒有 `params.yaml`。
  - `semantic_map_node` 預設訂閱 `/yolo/detections`，但目前 vision pipeline 是 `/grounding_dino/*`。

### `semantic_nav_interfaces`

- 路徑：`src/Home_Project/semantic_nav_interfaces`
- 類型：`ament_cmake` interface package
- 主要用途：定義 semantic navigation service。
- Interface：
  - `srv/NavToPoint.srv`
- 與其他 package 關係：
  - `main_policy/nav_service_node` 提供 `/nav_to_point`。
  - `main_policy/sementic_map_node`、`robot_task_orchestrator_node`、`web_nav_control` 呼叫 `/nav_to_point`。

### `vision_package`

- 路徑：`src/vision_package`
- 類型：`ament_python`
- 主要用途：以 RAM/RAM++ 產生 tag，GroundingDINO 依 tag/prompt 偵測 bbox，過濾後透過 depth/camera_info/TF 轉成 3D object 與 RViz marker。
- Nodes：
  - `ram_node`
  - `grounding_dino_node`
  - `bbox_filter_fusion_node`
  - `bbox_center_3d_node`
  - `bbox_all_3d_marker_node`
- Launch：
  - `vision.launch.py`
- Config：
  - `config/vision_stationary_balanced_params.yaml`
  - `config/vision_high_recall_params.yaml`
  - `config/limit_prompt.yaml`
- 主要 topic / service：
  - Service：`/ram/run_once`
  - Publish：`/ram/tags`
  - Service：`/grounding_dino/detect_once`
  - Publish：`/grounding_dino/bboxes_raw`
  - Publish：`/grounding_dino/detect_done`
  - Publish：`/grounding_dino/debug_image`
  - Subscribe：`/grounding_dino/bboxes_raw`
  - Publish：`/grounding_dino/bboxes`
  - Publish：`/grounding_dino/filter_debug`
  - Subscribe：`/realsense/depth`
  - Subscribe：`/realsense/camera_info`
  - Publish：`/grounding_dino/center_3d`
  - Publish：`/grounding_dino/center_3d_json`
  - Publish：`/grounding_dino/objects_3d_json`
  - Publish：`/visualization_marker_array`
- 與其他 package 關係：
  - `main_policy/map_builder_node` 預設吃 `/grounding_dino/objects_3d_json`。
  - `main_policy/robot_task_orchestrator_node` 會觸發 `/grounding_dino/detect_once`。
- 需要再確認：
  - config 中 RAM repo 與 checkpoint 預設為 `/workspace/visual/src/recognize-anything/...`，但本 workspace 實際 repo 在 `/home/jimmy/work_ws/home_project_ws/src/recognize-anything`。
  - `bbox_all_3d_marker_node.py` 的 node name 是 `bbox_all_2d_marker_node`，executable 名稱是 `bbox_all_3d_marker_node`。

### `web_nav_control`

- 路徑：`src/web_nav_control`
- 類型：`ament_python` + React/Vite frontend
- 主要用途：FastAPI backend 讀 ROS `/map`、`/amcl_pose`、`/plan`，呼叫 `/nav_to_point`，提供 waypoint / polygon 操作與 Web UI。
- Node：
  - `web_nav_api`
- Backend topics / services：
  - Subscribe：`/map`
  - Subscribe：`/amcl_pose`
  - Subscribe：`/plan`
  - TF lookup：`map -> base_link` 或 `map -> base_footprint`
  - Service client：`/nav_to_point`
- HTTP API：
  - `GET /api/health`
  - `GET /api/map`
  - `GET /api/robot_pose`
  - `GET /api/plan`
  - `GET /api/waypoints`
  - `POST /api/waypoints/load`
  - `POST /api/upload_waypoints`
  - `POST /api/waypoints`
  - `POST /api/nav_to_point`
  - `POST /api/generate_waypoints`
  - `POST /api/export_waypoints`
- Runtime data：
  - `runtime/map/map.yaml`
  - `runtime/map/map.png`
  - `runtime/waypoints/nav2_waypoints.yaml`

### `robot_object_retrieval_ros`

- 路徑：`src/robot_object_retrieval-main/ros2_ws/src/robot_object_retrieval_ros`
- 類型：`ament_cmake` + `ament_cmake_python` + interface package
- 主要用途：ROS 2 adapter，提供 semantic map JSON import service。
- Executable：
  - `semantic_map_import_service_node`
- Interface：
  - `srv/ImportSemanticMap.srv`
- Service：
  - `/semantic_map/import`
- 與其他 package 關係：
  - `main_policy/robot_task_orchestrator_node` 預設會呼叫 `/semantic_map/import`。
  - 背後依賴 `robot_object_retrieval` Python package、DB repository 與 embedding provider。
- 需要再確認：
  - 若只在 workspace 根目錄 `colcon build`，需確認 `robot_object_retrieval` Python package 已可被 ROS process import，例如安裝 `pip install -e src/robot_object_retrieval-main` 或設定 `PYTHONPATH`。

### `recognize-anything`

- 路徑：`src/recognize-anything`
- 類型：第三方 repo，已有 `COLCON_IGNORE`
- 主要用途：RAM / RAM++ image tagging。
- 注意：
  - 含模型權重 `pretrained/ram_plus_swin_large_14m.pth`，不適合上傳 GitHub。
  - 不應完整展開到 README。

### `Grounding_DINO`

- 路徑：`src/Grounding_DINO`
- 類型：非 ROS package / script 目錄
- 主要用途：
  - `groundingdino.py` 是 standalone GroundingDINO video/script。
  - `recognize-anything-plus-model` 含 RAM++ model card 與 `.pth` 權重。
- 需要再確認：
  - 目前 ROS `vision_package/grounding_dino_node.py` 使用 Hugging Face `IDEA-Research/grounding-dino-tiny`，不直接 import 此 `Grounding_DINO/groundingdino.py`。

## 7. Build 指令

完整 build：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

只 build 特定 package：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select main_policy
```

常用 packages：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select semantic_nav_interfaces Semanti_Map main_policy vision_package web_nav_control robot_object_retrieval_ros
```

清除後重建：

```bash
cd /home/jimmy/work_ws/home_project_ws
rm -rf build install log
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

## 8. Source 指令

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
```

若要使用 `robot_object_retrieval_ros` 且核心 Python package 尚未安裝：

```bash
cd /home/jimmy/work_ws/home_project_ws/src/robot_object_retrieval-main
python3 -m pip install -e .
```

或臨時設定：

```bash
export PROJECT_ROOT=/home/jimmy/work_ws/home_project_ws/src/robot_object_retrieval-main
export PYTHONPATH=$PROJECT_ROOT/src:$PYTHONPATH
```

## 9. Launch 指令

### `Semanti_Map/launch/nav_bringup.launch.py`

啟動 Nav2 localization、navigation、`/nav_to_point` service，可選 semantic projection / waypoint runner / RViz。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch Semanti_Map nav_bringup.launch.py
```

常用參數：

```bash
ros2 launch Semanti_Map nav_bringup.launch.py use_sim_time:=true use_rviz:=true use_nav2:=true use_nav_service:=true use_semantic_projection:=false use_waypoint_node:=false
```

### `main_policy/launch/vision_mapping.launch.py`

啟動 `vision_package/vision.launch.py`，包含 RAM、GroundingDINO、bbox filter、3D projection 與 marker。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy vision_mapping.launch.py
```

指定 camera topics：

```bash
ros2 launch main_policy vision_mapping.launch.py image_topic:=/realsense/rgb depth_topic:=/realsense/depth camera_info_topic:=/realsense/camera_info target_frame:=map camera_frame_override:=Camera_OmniVision_OV9782_Color
```

### `vision_package/launch/vision.launch.py`

直接啟動 vision pipeline。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_package vision.launch.py
```

### `main_policy/launch/task_orchestrator.launch.py`

啟動 waypoint task orchestrator。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy task_orchestrator.launch.py waypoint_yaml:=/home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml auto_start:=false enable_map_confirm:=false
```

### `main_policy/launch/main_policy_bringup.launch.py`

此 launch 預期整合 Nav2、NavToPoint、Map Builder 與可選 waypoint tour。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy main_policy_bringup.launch.py
```

需要再確認：此 launch include `main_policy/launch/map_builder.launch.py`，但目前檔案不存在；也引用未安裝的 `waypoint_tour_node`。

### 備份 launch

`src/Home_Project/backup/main_policy/semantic_pipeline.launch.py` 在備份目錄，不一定會被安裝到 package share。若要使用需先確認是否有被 package 安裝。

## 10. ROS 2 Nodes 指令

| package | executable | 指令 | 功能 |
|---|---|---|---|
| `main_policy` | `nav_service_node` | `ros2 run main_policy nav_service_node` | 提供 `/nav_to_point`，呼叫 Nav2 `navigate_to_pose` |
| `main_policy` | `map_builder_node` | `ros2 run main_policy map_builder_node --ros-args --params-file /home/jimmy/work_ws/home_project_ws/src/Home_Project/main_policy/config/map_builder_params.yaml` | 從 vision 3D objects 收集多視角 semantic map |
| `main_policy` | `sementic_map_node` | `ros2 run main_policy sementic_map_node -- /home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml` | waypoint runner，逐點呼叫 `/nav_to_point` |
| `main_policy` | `robot_task_orchestrator_node` | `ros2 run main_policy robot_task_orchestrator_node` | waypoint + navigation + detect_once + records/import orchestration |
| `Semanti_Map` | `semantic_map_node` | `ros2 run Semanti_Map semantic_map_node` | 舊式 detection + depth + TF 3D 投影 |
| `vision_package` | `ram_node` | `ros2 run vision_package ram_node` | RAM/RAM++ tag publisher，提供 `/ram/run_once` |
| `vision_package` | `grounding_dino_node` | `ros2 run vision_package grounding_dino_node` | GroundingDINO detector，提供 `/grounding_dino/detect_once` |
| `vision_package` | `bbox_filter_fusion_node` | `ros2 run vision_package bbox_filter_fusion_node` | bbox 過濾、去重、同義詞融合 |
| `vision_package` | `bbox_center_3d_node` | `ros2 run vision_package bbox_center_3d_node` | 單一 bbox center 反投影 3D |
| `vision_package` | `bbox_all_3d_marker_node` | `ros2 run vision_package bbox_all_3d_marker_node` | 所有 bbox 反投影到 target frame，發布 marker 與 JSON |
| `web_nav_control` | `web_nav_api` | `ros2 run web_nav_control web_nav_api` | FastAPI backend for web dashboard |
| `robot_object_retrieval_ros` | `semantic_map_import_service_node` | `ros2 run robot_object_retrieval_ros semantic_map_import_service_node` | 提供 `/semantic_map/import` |

## 11. Services / Messages / Actions

### `semantic_nav_interfaces/srv/NavToPoint`

檔案：`src/Home_Project/semantic_nav_interfaces/srv/NavToPoint.srv`

Request：

```text
float64 x
float64 y
bool use_yaw
float64 yaw
```

Response：

```text
bool success
string message
float64 final_x
float64 final_y
float64 final_yaw
```

範例：面向目標點。

```bash
ros2 service call /nav_to_point semantic_nav_interfaces/srv/NavToPoint "{x: 3.5, y: 1.2, use_yaw: false, yaw: 0.0}"
```

範例：指定終點 yaw。

```bash
ros2 service call /nav_to_point semantic_nav_interfaces/srv/NavToPoint "{x: 3.5, y: 1.2, use_yaw: true, yaw: 1.5708}"
```

### `robot_object_retrieval_ros/srv/ImportSemanticMap`

檔案：`src/robot_object_retrieval-main/ros2_ws/src/robot_object_retrieval_ros/srv/ImportSemanticMap.srv`

Request：

```text
string json_payload
string mode
```

Response：

```text
bool success
string frame_id
int64 source_next_id
int64 object_count
string error_type
string message
```

`mode` 可用 `incremental`、`replace`、`regions`。

範例：

```bash
ros2 service call /semantic_map/import robot_object_retrieval_ros/srv/ImportSemanticMap "{json_payload: '{\"frame_id\":\"map\",\"next_id\":0,\"objects\":[]}', mode: 'replace'}"
```

### Standard services

```bash
ros2 service call /semantic_map/confirm std_srvs/srv/Trigger "{}"
ros2 service call /semantic_map/finalize std_srvs/srv/Trigger "{}"
ros2 service call /semantic_map/clear_viewpoints std_srvs/srv/Trigger "{}"
ros2 service call /semantic_map/clear_map std_srvs/srv/Trigger "{}"
ros2 service call /grounding_dino/detect_once std_srvs/srv/Trigger "{}"
ros2 service call /ram/run_once std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/next std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/status std_srvs/srv/Trigger "{}"
```

### Actions

Nav2 action：

```bash
ros2 action info /navigate_to_pose
```

## 12. Semantic Map / Object Retrieval 流程

核心資料流：

```text
/grounding_dino/objects_3d_json
  -> main_policy/map_builder_node
  -> /semantic_map/confirm 收集 viewpoint snapshot
  -> /semantic_map/finalize 融合 semantic map
  -> /semantic_objects 與 /semantic_map
  -> robot_object_retrieval_ros /semantic_map/import
  -> PostgreSQL / pgvector
  -> search_semantic_map.py 或 agent tool search_semantic_map_object
```

啟動 import service：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run robot_object_retrieval_ros semantic_map_import_service_node
```

觸發匯入最小 snapshot：

```bash
ros2 service call /semantic_map/import robot_object_retrieval_ros/srv/ImportSemanticMap "{json_payload: '{\"frame_id\":\"map\",\"next_id\":0,\"objects\":[]}', mode: 'replace'}"
```

使用 repo script 搜尋物件：

```bash
cd /home/jimmy/work_ws/home_project_ws/src/robot_object_retrieval-main
python3 scripts/search_semantic_map.py book --limit 5
```

需要再確認：`robot_task_orchestrator_node` 內部會建立 `/semantic_map/import` client，但實際匯入 payload 格式與 DB 連線需依 `robot_object_retrieval-main/docs/interface_contracts.md` 與 `.env` 設定確認。

## 13. Vision / GroundingDINO / RAM 流程

啟動 vision pipeline：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_package vision.launch.py
```

觸發 RAM：

```bash
ros2 service call /ram/run_once std_srvs/srv/Trigger "{}"
ros2 topic echo /ram/tags
```

觸發 GroundingDINO 一次偵測：

```bash
ros2 service call /grounding_dino/detect_once std_srvs/srv/Trigger "{}"
```

查看 vision pipeline 輸出：

```bash
ros2 topic echo /grounding_dino/bboxes_raw
ros2 topic echo /grounding_dino/bboxes
ros2 topic echo /grounding_dino/objects_3d_json
ros2 topic echo /visualization_marker_array
```

若要改相機 topic：

```bash
ros2 launch vision_package vision.launch.py image_topic:=/realsense/rgb depth_topic:=/realsense/depth camera_info_topic:=/realsense/camera_info target_frame:=map camera_frame_override:=Camera_OmniVision_OV9782_Color
```

## 14. Nav2 / Waypoint 流程

啟動 Nav2 / map / localization：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch Semanti_Map nav_bringup.launch.py use_sim_time:=true use_rviz:=true use_nav2:=true use_nav_service:=true use_semantic_projection:=false
```

確認 `/nav_to_point`：

```bash
ros2 service list | grep nav_to_point
ros2 service type /nav_to_point
ros2 service call /nav_to_point semantic_nav_interfaces/srv/NavToPoint "{x: 1.0, y: 1.0, use_yaw: false, yaw: 0.0}"
```

啟動 waypoint runner：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run main_policy sementic_map_node -- /home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml
```

手動下一點：

```bash
ros2 service call /next_waypoint_nav std_srvs/srv/Trigger "{}"
```

自動巡航：

```bash
ros2 service call /start_waypoint_nav_auto std_srvs/srv/Trigger "{}"
ros2 service call /stop_waypoint_nav_auto std_srvs/srv/Trigger "{}"
ros2 service call /waypoint_nav_stats std_srvs/srv/Trigger "{}"
```

啟動 orchestrator：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy task_orchestrator.launch.py waypoint_yaml:=/home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml auto_start:=false enable_map_confirm:=false
```

控制 orchestrator：

```bash
ros2 service call /main_policy/next std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/start std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/stop std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/status std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/export_records std_srvs/srv/Trigger "{}"
```

## 15. 常用 Debug 指令

ROS graph：

```bash
ros2 node list
ros2 topic list
ros2 service list
ros2 action list
ros2 topic echo <topic>
ros2 service type <service>
ros2 interface show <interface>
```

Nav2 / map：

```bash
ros2 topic echo /map --once
ros2 topic echo /amcl_pose
ros2 topic echo /plan
ros2 topic echo /global_costmap/costmap --once
ros2 action info /navigate_to_pose
```

TF：

```bash
ros2 run tf2_tools view_frames
ros2 topic echo /tf
ros2 topic echo /tf_static
ros2 run tf2_ros tf2_echo map odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_ros tf2_echo map base_link
ros2 run tf2_ros tf2_echo map Camera_OmniVision_OV9782_Color
```

Vision：

```bash
ros2 topic echo /realsense/rgb --once
ros2 topic echo /realsense/depth --once
ros2 topic echo /realsense/camera_info --once
ros2 topic echo /ram/tags
ros2 topic echo /grounding_dino/bboxes_raw
ros2 topic echo /grounding_dino/bboxes
ros2 topic echo /grounding_dino/objects_3d_json
ros2 topic echo /visualization_marker_array
```

Interfaces：

```bash
ros2 interface show semantic_nav_interfaces/srv/NavToPoint
ros2 interface show robot_object_retrieval_ros/srv/ImportSemanticMap
ros2 interface show std_srvs/srv/Trigger
```

## 16. Git / .env / nested repo 注意事項

Git status 檢查時看到目前 workspace 有既有變更與未追蹤檔：

```text
 M .gitignore
 D backup/Nav2/...
 D data/main_policy_records.jsonl
?? PROJECT_STRUCTURE_AND_RUN_GUIDE.md
```

這些不是本 README 產生過程修改的原始碼，請在 commit 前自行確認。

不適合上傳 GitHub 或需小心處理：

- `src/robot_object_retrieval-main/.env` 是 symlink，指向 `/home/jimmy/work_ws/docker/robot_object.env`。
- `src/robot_object_retrieval-main/robot_object.env`
- `src/robot_object_retrieval-main/.env.example` 可公開前仍建議檢查是否含敏感預設。
- `src/recognize-anything/pretrained/ram_plus_swin_large_14m.pth`
- `src/Grounding_DINO/recognize-anything-plus-model/*.pth`
- 根目錄 `build/`、`install/`、`log/`
- `src/robot_object_retrieval-main/ros2_ws/build/`、`install/`、`log/`
- `src/web_nav_control/frontend/node_modules/`

Nested repo / 外部 repo：

- 沒有在 `src` 內找到 nested `.git` 目錄。
- `src/recognize-anything` 是第三方 repo 內容，且有 `COLCON_IGNORE`。
- `src/robot_object_retrieval-main` 是外部 app repo 風格，內含自己的 `ros2_ws`、`build/install/log` 與 `.env`。
- `src/Grounding_DINO/recognize-anything-plus-model` 是模型/README 目錄，含大檔權重。

## 17. 疑似問題與待確認事項

- `main_policy_bringup.launch.py` include `main_policy/launch/map_builder.launch.py`，但目前不存在。
- `main_policy_bringup.launch.py` 會啟動 `waypoint_tour_node`，但 `main_policy/setup.py` 沒有註冊此 executable。
- `Semanti_Map/nav_bringup.launch.py` 預設 `sem_params_file` 是 `config/params.yaml`，但目前沒有此檔。
- `task_orchestrator.launch.py` 與 `robot_task_orchestrator_node.py` 預設 waypoint YAML 指到 `/home/jimmy/work_ws/home_project_ws/src/Semanti_Map/config/nav2_waypoints_margin_060.yaml`，目前實際可見 waypoint YAML 是 `src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml`。
- `vision_package` config 預設 RAM repo/checkpoint 位於 `/workspace/visual/src/recognize-anything`，但本 workspace 實際有 `src/recognize-anything`；執行前需確認路徑。
- `Semanti_Map/semantic_map_node.py` 預設 detection topic 是 `/yolo/detections`，但目前主要 vision pipeline 是 `/grounding_dino/*`。
- `map_builder_params.yaml` 的 `map_save_path` 是 `/home/hungyu/work_ws/semantic_map.json`，與目前 workspace 使用者/路徑不一致，是否仍有效需要再確認。
- `robot_object_retrieval_ros` 需要 `robot_object_retrieval` Python package、DB 與 embedding provider；ROS build 成功不代表 runtime import/DB 一定可用。
- `src/vision_package/launch/` 底下出現 `build/install/log` 與 `COLCON_IGNORE`，位置不尋常，需要再確認是否誤放。

## 18. 最小啟動範例

目標：啟動 Nav2、提供 `/nav_to_point`，並呼叫一次導航 service。

Terminal 1：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select semantic_nav_interfaces Semanti_Map main_policy
source install/setup.bash
ros2 launch Semanti_Map nav_bringup.launch.py use_sim_time:=true use_rviz:=true use_nav2:=true use_nav_service:=true use_semantic_projection:=false
```

Terminal 2：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 service list | grep nav_to_point
ros2 service call /nav_to_point semantic_nav_interfaces/srv/NavToPoint "{x: 1.0, y: 1.0, use_yaw: false, yaw: 0.0}"
```

## 19. 完整啟動範例

目標：Nav2 + vision + object import + orchestrator。

Terminal 1：build。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select semantic_nav_interfaces robot_object_retrieval_ros Semanti_Map main_policy vision_package web_nav_control
source install/setup.bash
```

Terminal 2：Nav2 / map / localization / `/nav_to_point`。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch Semanti_Map nav_bringup.launch.py use_sim_time:=true use_rviz:=true use_nav2:=true use_nav_service:=true use_semantic_projection:=false
```

Terminal 3：vision pipeline。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy vision_mapping.launch.py image_topic:=/realsense/rgb depth_topic:=/realsense/depth camera_info_topic:=/realsense/camera_info target_frame:=map camera_frame_override:=Camera_OmniVision_OV9782_Color
```

Terminal 4：semantic map import service。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export PROJECT_ROOT=/home/jimmy/work_ws/home_project_ws/src/robot_object_retrieval-main
export PYTHONPATH=$PROJECT_ROOT/src:$PYTHONPATH
ros2 run robot_object_retrieval_ros semantic_map_import_service_node
```

Terminal 5：task orchestrator。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch main_policy task_orchestrator.launch.py waypoint_yaml:=/home/jimmy/work_ws/home_project_ws/src/web_nav_control/runtime/waypoints/nav2_waypoints.yaml auto_start:=false enable_map_confirm:=false
```

Terminal 6：手動觸發流程。

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 service call /grounding_dino/detect_once std_srvs/srv/Trigger "{}"
ros2 topic echo /grounding_dino/objects_3d_json --once
ros2 service call /main_policy/next std_srvs/srv/Trigger "{}"
ros2 service call /main_policy/status std_srvs/srv/Trigger "{}"
```

Web backend：

```bash
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run web_nav_control web_nav_api
```

Web frontend：

```bash
cd /home/jimmy/work_ws/home_project_ws/src/web_nav_control/frontend
npm install
npm run dev -- --host 0.0.0.0
```

Backend 預設：

```text
http://127.0.0.1:8000
```

Frontend 預設：

```text
http://127.0.0.1:5173
```
