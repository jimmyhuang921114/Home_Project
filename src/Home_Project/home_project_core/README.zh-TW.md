# home_project_core

`home_project_core` 整合原 `main_policy` 與 `Semanti_Map` 的核心 ROS 2
節點與資源。Vision、interfaces、object retrieval 與第三方模型仍是獨立
package/repository。

主要入口：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch home_project_core home_project.launch.py
```

預設只啟動隔離名稱的 mock motion server 與 robot-flow 狀態節點，不啟動
Nav2、Vision、semantic-map import、API，也不送出任何 goal。

主要開關：

```text
use_sim_time:=false
enable_navigation:=false
enable_semantic_map:=false
enable_vision:=false
enable_db_import:=false
enable_api:=false
use_mock_motion:=true
vision_backend:=mock
```

### 實體機器人語意建圖

實體機器人使用專用入口，不會啟動 Isaac Sim，且預設
`use_sim_time:=false`：

```bash
ros2 launch home_project_core real_robot_semantic.launch.py \
  vision_backend:=remote \
  rgb_topic:=/camera/color/image_raw \
  depth_topic:=/camera/aligned_depth_to_color/image_raw \
  camera_info_topic:=/camera/color/camera_info \
  compressed_rgb_topic:=/camera/color/image_raw/compressed \
  global_frame:=map \
  use_database:=true
```

啟動前，實體機器人必須已提供底盤驅動、定位/Nav2、`map -> odom -> base_link`
TF 與上述 RGB-D topic；本入口只啟動語意建圖與查詢物件導航節點，不會假造
感測器、TF 或 `/cmd_vel`。`vision_backend:=remote` 需要外部 typed vision
Action；若使用本機 legacy vision，改成 `vision_backend:=legacy` 並確保相容
vision adapter 已啟動。

外部 waypoint 可使用 `waypoint_yaml:=/absolute/path/file.yaml` 指定。語意地圖
輸出路徑使用 `map_save_path` ROS parameter，必須是明確的絕對路徑。

舊 executable `sementic_map_node` 暫時保留為 deprecated alias；新名稱是
`waypoint_navigation_node`。ROS topic、service、action、parameter 與 JSON
schema 在第一階段維持相容。

Python runtime 仍需 FastAPI、Uvicorn 與 PyYAML；這些 dependency 同時記錄於
`package.xml`。核心 package 不包含 CUDA、Transformers、模型 loader 或
PostgreSQL connection。
# 語意建圖與物件導航

新的 `BUILD_SEMANTIC_MAP` Action、Thor/legacy Vision Action contract、runtime
checkpoint，以及 `GO_TO_OBJECT` service 操作方式請見
[`SEMANTIC_FLOWS.md`](SEMANTIC_FLOWS.md)。舊 `/yolo/detections` 地圖流程保留為
相容路徑，不由新的 launch 啟動。
