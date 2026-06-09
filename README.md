<<<<<<< HEAD


## 需要做的事

`bbox_all_3d_marker_node` 預設把 3D 座標投影到 `base_link`（機器人本體）。

**啟動 vision_package 時，把 `target_frame` 改成 `map`：**

```bash
# 在 vision.launch.py 對應的 Node() 裡，parameters 加上：
{"target_frame": "map"}

去main_policy做waypoint_tour_node的call視覺服務
```

---

## 串接後的完整流程

```
ros2 launch Semanti_Map nav_bringup.launch.py
ros2 launch main_policy semantic_pipeline.launch.py
ros2 launch main_policy nav_service.launch.py
開視覺
導航腳本
ros2 run main_policy waypoint_tour_node


---


---


```
=======
一鍵啟動（Nav2 + 語意地圖 + RViz2）
ros2 launch Semanti_Map bringup.launch.py
# Semanti_Map

使用模擬器時：

```bash
ros2 launch Semanti_Map bringup.launch.py use_sim_time:=true
>>>>>>> 87000aa918ba9ccbd01885deee1176eeb18fefe3
