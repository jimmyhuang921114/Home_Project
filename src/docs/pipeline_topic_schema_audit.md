# ROS 2 Semantic Pipeline Topic and Schema Audit

```text
Status: pipeline/schema audit only
No package source files modified
Previous architecture audit: src/docs/architecture_audit_plan.md
Primary goal: decide one canonical semantic pipeline before migration
```

Audit workspace: `/home/jimmy/work_ws/home_project_ws`

This is a documentation-only record. No package source, manifest, setup file, launch file, configuration, map, README, package name, or `Nav2/COLCON_IGNORE` was modified.

## 1. Current discovered packages

`colcon list --base-paths src` discovered:

| Package | Source path | Build type | Role |
|---|---|---|---|
| `Semanti_Map` | `src/Home_Project/Semanti_Map` | `ament_python` | Alternate 2D detection + depth + TF projection path. |
| `main_policy` | `src/Home_Project/main_policy` | `ament_python` | Semantic map aggregation, persistence, navigation service, and waypoint orchestration. |
| `semantic_nav_interfaces` | `src/Home_Project/semantic_nav_interfaces` | `ament_cmake` | `NavToPoint.srv`. |
| `vision_package` | `src/vision_package` | `ament_python` | RAM tags, GroundingDINO detection, bbox filtering, depth projection, and 3D object output. |
| `robot_object_retrieval_ros` | `src/robot_object_retrieval-main/ros2_ws/src/robot_object_retrieval_ros` | `ament_cmake` | ROS service adapter for importing semantic-map JSON into the retrieval database. |

`Nav2/COLCON_IGNORE` remains in place, so duplicate Nav2 copies of `main_policy` and `Semanti_Map` were not discovered.

Colcon reports the existing naming warning that `Semanti_Map` contains uppercase characters. Renaming is outside this audit.

## 2. End-to-end semantic pipeline candidates

### Candidate A: `Semanti_Map` performs 2D-to-3D projection

```text
Unidentified /yolo/detections producer
  ├─ std_msgs/String JSON: {detections: [{class, score, center:{x,y}}]}
  ├─ /realsense/depth
  └─ /realsense/camera_info
          │
          ▼
Semanti_Map/semantic_map_node
  └─ TF camera frame -> map
          │
          ▼
/semantic_map/raw_detections
  JSON: {frame_id, detections:[{class, score, position:{x,y,z}}]}
          │
          ▼
main_policy/map_integrator_node
  ├─ /semantic_objects
  ├─ /semantic_map (MarkerArray)
  └─ semantic_map.json
```

Status: internally coherent only when paired with `map_integrator_node`. No discovered package publishes `/yolo/detections`. The current `semantic_pipeline.launch.py` starts `map_builder_node`, not `map_integrator_node`, so its defaults do not connect this candidate.

### Candidate B: `vision_package` performs 2D-to-3D projection

```text
/realsense/rgb
  ├───────────────────────────────────────────────┐
  ▼                                               │
ram_node                                          │
  └─ /ram/tags                                    │
          │                                       │
          ▼                                       ▼
grounding_dino_node <──────────────────── /realsense/rgb
  └─ /grounding_dino/bboxes_raw
          │
          ▼
bbox_filter_fusion_node
  └─ /grounding_dino/bboxes
          │
          ├─ /realsense/depth
          ├─ /realsense/camera_info
          ▼
bbox_all_3d_marker_node
  └─ TF camera frame -> configured target frame
          │
          ▼
/grounding_dino/objects_3d_json
          │
          ▼
main_policy/map_builder_node
  ├─ /semantic_objects
  ├─ /semantic_map (MarkerArray)
  ├─ map-builder status/services
  └─ semantic_map.json
```

Status: topic names and JSON parser are already directly compatible. This is the strongest canonical candidate. The critical frame condition is that `vision.launch.py` defaults `target_frame` to `odom`, while `map_builder_node` labels output and persistence using its default `map_frame=map`. Canonical operation requires `target_frame=map` and a valid camera-to-map TF chain, or an explicit decision that the map is actually odom-relative.

### Candidate C: retrieval import and semantic search

```text
main_policy semantic_map.json or /semantic_objects JSON
          │
          │ no automatic bridge currently exists
          ▼
ImportSemanticMap request: json_payload + mode
          │
          ▼
robot_object_retrieval_ros/semantic_map_import_service_node
  ├─ validates strict snapshot schema
  ├─ embeds object class strings
  └─ writes PostgreSQL + pgvector
          │
          ▼
robot_object_retrieval query/agent application
```

Status: the ROS importer is service-driven and does not subscribe to `/semantic_objects` or watch `semantic_map.json`. A caller/bridge is missing. The current map producer JSON also lacks strict importer fields `map_id` and `map_version`.

## 3. Topic publisher/subscriber matrix

### Vision and semantic mapping

| Topic | Type/schema | Publishers | Subscribers | Configurability | Result |
|---|---|---|---|---|---|
| `/realsense/rgb` | `sensor_msgs/Image` | External camera | `ram_node`, `grounding_dino_node` | Launch argument and node parameter | Connected if camera uses this name. |
| `/ram/tags` | `std_msgs/String`; CSV by current launch, JSON optionally | `ram_node` | `grounding_dino_node` | Node parameters; hardcoded in `vision.launch.py` | Connected; GroundingDINO parser accepts both CSV and JSON/list forms. |
| `/ram/debug_image` | `sensor_msgs/Image` | `ram_node` | None found | Node parameter | Diagnostic-only. |
| `/grounding_dino/bboxes_raw` | `std_msgs/String` JSON | `grounding_dino_node` | `bbox_filter_fusion_node` | Node parameters; fixed values in launch | Connected. |
| `/grounding_dino/debug_image` | `sensor_msgs/Image` | `grounding_dino_node` | None found | Node parameter | Diagnostic-only. |
| `/grounding_dino/detect_done` | `std_msgs/String` JSON | `grounding_dino_node` | None found | Node parameter | Completion signal currently unused. |
| `/grounding_dino/bboxes` | `std_msgs/String` JSON | `bbox_filter_fusion_node` | `bbox_center_3d_node`, `bbox_all_3d_marker_node` | Node parameters; fixed values in launch | Connected. |
| `/grounding_dino/filter_debug` | `std_msgs/String` JSON | `bbox_filter_fusion_node` | None found | Node parameter | Diagnostic-only. |
| `/realsense/depth` | `sensor_msgs/Image` | External camera | `bbox_center_3d_node`, `bbox_all_3d_marker_node`, `Semanti_Map/semantic_map_node` | Launch argument/parameters | Shared depth input. |
| `/realsense/camera_info` | `sensor_msgs/CameraInfo` | External camera | Both vision 3D nodes and `Semanti_Map/semantic_map_node` | Launch argument/parameters | Shared camera-intrinsic/frame input. |
| `/grounding_dino/center_3d` | `geometry_msgs/PointStamped` | `bbox_center_3d_node` | None found | Node parameter | Diagnostic/single-object output. |
| `/grounding_dino/center_3d_json` | `std_msgs/String` JSON | `bbox_center_3d_node` | None found | Node parameter | Diagnostic/single-object output. |
| `/grounding_dino/objects_3d_json` | `std_msgs/String` JSON | `bbox_all_3d_marker_node` | `map_builder_node` | Parameters on both ends; fixed consistently in current configs | Directly connected. |
| `/visualization_marker_array` | `visualization_msgs/MarkerArray` | `bbox_all_3d_marker_node` | RViz/user | Node parameter | Vision-level 3D visualization. |
| `/yolo/detections` | `std_msgs/String` JSON | No discovered publisher | `Semanti_Map/semantic_map_node` | `detection_topic` parameter/config | Broken input. |
| `/semantic_map/raw_detections` | `std_msgs/String` JSON | `Semanti_Map/semantic_map_node` | `map_integrator_node` only | Parameters on publisher and integrator | Coherent alternate path, but not used by current semantic pipeline launch. |
| `/semantic_objects` | `std_msgs/String` JSON | `map_builder_node` and `map_integrator_node` | No discovered ROS subscriber | Hardcoded in both producers | Duplicate publisher risk if both map nodes run. |
| `/semantic_map` | `visualization_msgs/MarkerArray` | `map_builder_node` and `map_integrator_node` | RViz/user | Hardcoded in both producers | Duplicate publisher risk if both map nodes run. |
| `/map_builder/status` | `std_msgs/String` | `map_builder_node` | None found | Hardcoded | Operator/status output. |
| `/map_builder/viewpoints_info` | `std_msgs/String` JSON | `map_builder_node` | None found | Hardcoded | Viewpoint diagnostic output. |
| `/tour/status` | `std_msgs/String` | `waypoint_tour_node` | None found | Hardcoded | Tour diagnostic output. |

### Nav2 and policy

| Topic/action | Type | Producer/server | Consumer/client | Configurability | Result |
|---|---|---|---|---|---|
| `/global_costmap/costmap` | `nav_msgs/OccupancyGrid` | Nav2 global costmap | `nav_service_node` | `costmap_topic` parameter | Connected when Nav2 is active. |
| `navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | Nav2 | `nav_service_node`, `waypoint_nav2_action_node` | Configurable in `nav_service_node`; hardcoded in waypoint action node | Two alternative clients. |

## 4. JSON/message schema matrix

| Interface | Producer | Expected consumer | Effective schema | Compatibility |
|---|---|---|---|---|
| `/ram/tags` | `ram_node` | `grounding_dino_node` | Current launch sets `publish_json=false`, producing comma-separated tags. Optional form is `{"tags":[...]}`. GroundingDINO accepts JSON dict/list or split text. | Compatible. |
| `/grounding_dino/bboxes_raw` | `grounding_dino_node` | bbox filter | Root includes `stamp`, `frame_id`, image dimensions, prompt, count, `bboxes`, raw/multi-frame/tile metadata. Each bbox includes at least `class`, `score`, `x1/y1/x2/y2`, derived `cx/cy/w/h/area`, and source metadata. | Compatible. |
| `/grounding_dino/bboxes` | bbox filter | both vision 3D nodes | Preserves source payload, replaces `bboxes`, and adds counts, filter flags, stats, elapsed time, and filter-node name. | Compatible. |
| `/grounding_dino/center_3d_json` | center 3D node | None found | `{frame_id,class,score,pixel:{u,v},depth_m,point_3d:{x,y,z},bbox}`. Coordinates remain in camera/depth frame; no TF transformation is performed. | Unused. |
| `/grounding_dino/objects_3d_json` | all-3D marker node | map builder | Root: `{target_frame,count,objects,skip_reasons,source_count,source_frame}`. Object: `{id,class,score,source_frame,target_frame,pixel,depth_m,depth_source,camera_point,base_point,bbox,scaled_bbox_depth_px}`. | Compatible: map builder explicitly converts `base_point` to its internal `position`. |
| `/semantic_map/raw_detections` | `Semanti_Map/semantic_map_node` | map integrator or map builder parser | `{frame_id, detections:[{class,score,position:{x,y,z}}]}`. | Compatible with `map_integrator_node`; parser-compatible with `map_builder_node`, but topic defaults differ. |
| `/semantic_objects` | either map node | External/retrieval bridge | Map builder: `{frame_id,count,objects:[{id,class,position,confidence,observe_count,viewpoint_count}]}`. Integrator omits `viewpoint_count`. | Structurally close to retrieval object schema, but root lacks required `map_id`, `map_version`, and `next_id` on the topic form. |
| `semantic_map.json` from map builder | map builder | retrieval importer/CLI | `{frame_id,next_id,objects:[{id,class,position,confidence,observe_count,viewpoint_count}]}`. | Fails current strict retrieval parser because `map_id` and `map_version` are required. Extra `viewpoint_count` is ignored by the current parser. |
| `semantic_map.json` from map integrator | map integrator | retrieval importer/CLI | `{frame_id,next_id,objects:[{id,class,position,confidence,observe_count}]}`. | Also fails strict retrieval parser because `map_id` and `map_version` are missing. |
| `ImportSemanticMap.srv` | caller | retrieval ROS node | Request: `string json_payload`, `string mode`. Response: `success`, `frame_id`, `source_next_id`, `object_count`, `error_type`, `message`. Modes: `incremental`, `replace`, `regions`. | Service is implemented; no pipeline caller found. |
| Retrieval strict snapshot | external producer | retrieval application | Required root fields: `map_id`, `map_version`, `frame_id`, `next_id`, `objects`; optional `regions`. Required object fields: `id`, `class`, `position.x/y/z`, `confidence`, `observe_count`. | Not produced by current map nodes. Even the inspected legacy `data/semantic_map.json` lacks `map_id` and `map_version`, so it is incompatible with the current strict parser. |
| `NavToPoint.srv` | waypoint clients | nav service | Request: `x`, `y`, `use_yaw`, `yaw`. Response: `success`, `message`, `final_x`, `final_y`, `final_yaw`. | Client/server schema aligned. |

## 5. Launch file pipeline matrix

| Launch file | Nodes/components started | Pipeline effect | Findings |
|---|---|---|---|
| `vision_package/launch/vision.launch.py` | RAM, GroundingDINO, bbox filter, bbox center 3D, bbox all-3D marker | Complete camera-to-3D-object pipeline | Defaults all components enabled. `target_frame` defaults to `odom`, not `map`. Contains source comments with stale absolute `/home/jimmy/work_ws/visual/...` paths. |
| `main_policy/launch/map_builder.launch.py` | `map_builder_node` | 3D-object aggregation and persistence | Reads config whose topic matches vision all-3D output. |
| `main_policy/launch/semantic_pipeline.launch.py` | `Semanti_Map/semantic_map_node` + `map_builder_node` | Intended semantic projection + map build | Broken by default: publisher uses `/semantic_map/raw_detections`; subscriber uses `/grounding_dino/objects_3d_json`. It does not start vision despite documentation references. |
| `main_policy/launch/nav_service.launch.py` | `nav_service_node` | NavToPoint-to-Nav2 adapter | Independent of semantic mapping. |
| `Semanti_Map/launch/semantic_map.launch.py` | semantic projection node | Candidate A projection only | Requires an undiscovered `/yolo/detections` publisher. |
| `Semanti_Map/launch/bringup.launch.py` | Nav2 localization/navigation, semantic projection, RViz | Nav2 + Candidate A projection | Does not start a map aggregator or visual detector. |
| `Semanti_Map/launch/nav_bringup.launch.py` | Nav2 localization/navigation, nav service, RViz | Navigation service stack | Does not start semantic projection/map builder. |
| `robot_object_retrieval_ros` | No launch file found | Import service must be started manually | Installed executable is `semantic_map_import_service_node`. |

Launch-specific defect: `vision.launch.py` passes parameter key `json_topic` to `bbox_center_3d_node`, but that node declares `point3d_json_topic`. The current values happen to point to the same default topic, but the override name is incorrect and may be ignored or rejected depending on parameter behavior.

## 6. Semantic map file flow

### Writers and readers

| Component | Reads file | Writes file | Path policy |
|---|---:|---:|---|
| `map_builder_node` | Yes, at startup | Yes, periodic/finalize/shutdown behavior in code | `map_save_path` parameter; default hardcoded `/home/hungyu/work_ws/semantic_map.json`. |
| `map_integrator_node` | Yes, at startup | Yes, periodically and on shutdown | Same parameter name and default hardcoded path. |
| `Semanti_Map/semantic_map_node` | No | No | Only transforms live detections. Its config contains stale map-save fields that the node does not declare/use. |
| Retrieval CLI `scripts/import_semantic_map.py` | Yes, explicit path argument | No | Parses and imports snapshot into database. |
| Retrieval ROS service node | No filesystem read | No filesystem write | Receives complete JSON text in service request. |
| Retrieval repository | No JSON file | Writes PostgreSQL tables and pgvector embeddings | Database configured outside ROS package. |

### Current missing file bridge

No discovered component automatically performs either of these:

- reads the map builder's saved file and calls `/semantic_map/import`;
- subscribes to `/semantic_objects` and calls `/semantic_map/import`.

The map builder's `/semantic_map/finalize` service saves the map but does not invoke the retrieval importer. Therefore the retrieval database is not part of the live ROS pipeline yet.

## 7. Nav2 / waypoint / policy flow

### Node/API inventory

| Executable | Node name | Subscriptions | Publications | Services provided | Services/actions called | Frames/TF/file behavior |
|---|---|---|---|---|---|---|
| `nav_service_node` | `nav_service_node` | Configurable global costmap (`OccupancyGrid`) | None | `nav_to_point` (`NavToPoint`) | Configurable `NavigateToPose` action | Parameters `map_frame=map`, `base_frame=base_link`; uses TF to determine robot pose and costmap-aware approach. No semantic JSON file. |
| `waypoint_tour_node` | `waypoint_tour_node` | None | `/tour/status` | `/tour/start` (`Trigger`) | `/nav_to_point`, `/vision/recognize`, `/semantic_map/confirm`, `/semantic_map/finalize` | Waypoints are hardcoded in Python. No TF. Orchestrates navigation/vision/map confirmation. |
| `waypoint_nav2_action_node` | `waypoint_nav2_action_node` | None | None | None | Hardcoded `navigate_to_pose` action | Reads external waypoint YAML; uses YAML `frame_id`, default `map`; no TF. |
| `sementic_map_node` | `waypoint_nav_to_point_step_service` | None | None | `/next_waypoint_nav`, `/reset_waypoint_nav`, `/skip_waypoint_nav`, `/start_waypoint_nav_auto`, `/stop_waypoint_nav_auto` | `/nav_to_point` | Despite its filename/executable, this is a waypoint controller. Reads external waypoint YAML; no semantic-map topic or file. |

### Broken waypoint vision trigger

`waypoint_tour_node` calls `/vision/recognize` (`std_srvs/Trigger`). No inspected node provides this service. The actual GroundingDINO trigger is configurable but currently launched as `/grounding_dino/detect_once`.

The waypoint tour's map services do match `map_builder_node`:

- `/semantic_map/confirm`
- `/semantic_map/finalize`

The navigation service also matches `/nav_to_point`.

## 8. `robot_object_retrieval_ros` integration flow

### ROS executable

| Field | Value |
|---|---|
| Executable | `semantic_map_import_service_node` (installed CMake script) |
| Node name | `semantic_map_import_service_node` |
| Topic subscriptions/publications | None |
| Service provided | `/semantic_map/import` by default; configurable with `service_name` parameter |
| Services/actions called | None |
| TF/frames | Does not use TF. It stores and returns the payload's `frame_id`; coordinates must already be in the canonical frame. |
| File access | Receives JSON text; does not read `semantic_map.json` itself. |
| Database behavior | Calls application importer, embedding provider, and PostgreSQL repository. Object class names are embedded and stored in a pgvector column. |

The ROS package manifest declares ROS interface/runtime dependencies but does not declare how the separately packaged Python module `robot_object_retrieval` and its database/embedding dependencies become available at runtime. Deployment must install that application package into the same Python environment.

### Import modes

| Mode | Behavior |
|---|---|
| `incremental` | Upserts listed `(frame_id, id)` objects; does not accept regions. |
| `replace` | Replaces the active object snapshot and imports regions. |
| `regions` | Replaces same-frame region metadata only; does not embed/update objects. |

### Retrieval data contract

The database stores map imports, objects, and optional regions. Object identity is based on source ID and frame. Semantic search embeds `class` text, stores it in pgvector, and returns object IDs/classes/coordinates plus similarity/confidence metadata through the non-ROS query and agent application.

No ROS query service or topic subscriber was found in `robot_object_retrieval_ros`; only import is exposed to ROS.

## 9. Mismatches and broken links

| Severity | Mismatch | Impact |
|---|---|---|
| Critical | `semantic_pipeline.launch.py`: semantic node publishes `/semantic_map/raw_detections`, while map builder subscribes `/grounding_dino/objects_3d_json`. | Launched nodes do not exchange detections. |
| Critical | No discovered publisher for `/yolo/detections`. | Candidate A cannot receive detections with current defaults. |
| Critical | Vision all-3D defaults `target_frame=odom`; map builder defaults `map_frame=map` and does not validate input root `target_frame`. | Odom coordinates can be mislabeled and persisted as map coordinates. |
| Critical | Retrieval parser requires `map_id` and `map_version`; map nodes do not emit them. | Direct file/service import fails validation. |
| High | No bridge calls `/semantic_map/import` or imports the finalized file. | Retrieval database is disconnected from live semantic mapping. |
| High | `waypoint_tour_node` calls `/vision/recognize`; vision exposes `/grounding_dino/detect_once`. | Tour vision step cannot trigger the inspected detector. |
| High | Running both map builder and map integrator creates duplicate publishers and two writers to the same default JSON path. | Conflicting maps, output ambiguity, and file races. |
| High | Home semantic TF exception paths refer to undefined `self.camera_frame`. | Connectivity/extrapolation failures can trigger another exception. |
| Medium | `vision.launch.py` uses `json_topic` instead of declared `point3d_json_topic`. | Intended override is not correctly connected. |
| Medium | `Semanti_Map/config/params.yaml` contains map persistence parameters not declared by its current node. | Misleading configuration; values have no effect. |
| Medium | Retrieval's inspected legacy example JSON also lacks newly required `map_id`/`map_version`. | Repository examples and current parser contract are out of sync. |
| Medium | `vision_package/package.xml` has no runtime dependencies despite extensive ROS/ML imports. | Dependency resolution and clean deployment are unreliable. |
| Medium | `robot_object_retrieval_ros` depends at runtime on a separate Python application package not represented in its manifest. | ROS executable may import-fail in a clean environment. |

## 10. Recommended single canonical pipeline

Use Candidate B as the canonical perception/mapping pipeline:

```text
Camera RGB
  -> RAM tags
  -> GroundingDINO raw bboxes
  -> bbox filter/fusion
  -> bbox_all_3d_marker_node with target_frame=map
  -> /grounding_dino/objects_3d_json
  -> map_builder_node
  -> /semantic_objects + semantic_map.json
  -> explicit retrieval import bridge/service call
  -> PostgreSQL + pgvector
```

Reasons:

1. `vision_package` already provides a complete detector-to-map-frame 3D conversion path.
2. `map_builder_node` defaults to its output topic and explicitly supports its `objects[].base_point` schema.
3. The map builder provides the preferred multi-frame/viewpoint confirmation workflow and matching services used by `waypoint_tour_node`.
4. Keeping a second depth/TF projection in `Semanti_Map` duplicates responsibilities and introduces another schema/topic boundary.
5. Retrieval should consume the finalized map snapshot, not every raw detection.

Canonical frame requirement: the all-3D vision node must output `target_frame=map`, and the TF tree must provide camera-to-map. If map localization is unavailable, semantic-map collection should not silently persist odom coordinates as map coordinates.

Canonical map producer: run `map_builder_node`; do not run `map_integrator_node` concurrently.

Role of `Semanti_Map`: retain it as an ignored/disabled alternative until migration decisions are complete, or repurpose its package later for bringup/map assets. No source change is performed by this audit.

## 11. Minimal changes needed to make the pipeline consistent

These are future recommendations only.

1. Make the canonical launch start `vision_package` and `map_builder_node`, and stop presenting `Semanti_Map/semantic_map_node + map_builder_node` as a connected default pipeline.
2. Set and document `vision.launch.py target_frame:=map`; fail clearly when the camera-to-map TF is unavailable.
3. Keep `map_builder_node.raw_detections_topic=/grounding_dino/objects_3d_json` for the canonical path.
4. Select `map_builder_node` as the only active semantic map writer/publisher; leave `map_integrator_node` as a legacy alternative.
5. Change the waypoint vision trigger contract so both sides use one service name, preferably the existing `/grounding_dino/detect_once`, or add a deliberately named adapter.
6. Extend the finalized snapshot contract with stable `map_id` and `map_version`, or explicitly relax/version the retrieval parser. Do not rely on implicit defaults without documenting identity/version semantics.
7. Add a small integration boundary after `/semantic_map/finalize`: either a client that reads the saved snapshot and calls `/semantic_map/import`, or a topic-to-service importer that wraps `/semantic_objects` with required snapshot metadata.
8. Decide whether retrieval import should use `replace` after full finalize and `incremental` for subsequent updates. Avoid importing partially confirmed live detections.
9. Correct the bbox-center launch parameter name (`point3d_json_topic`) even if the center-3D branch remains diagnostic-only.
10. Align package manifests with actual runtime imports and ensure the `robot_object_retrieval` Python application is installed in the ROS runtime environment.
11. Remove stale machine-specific source comments and hardcoded map-save defaults only in a separately approved implementation phase.

## 12. Human questions before modifying code

1. Is `bbox_all_3d_marker_node` confirmed as the production 2D-to-3D projection node?
2. Can the deployed TF tree reliably provide `map <- odom <- base_link <- camera`, or only camera-to-odom?
3. Should semantic objects be persisted in `map` coordinates exclusively, with collection blocked until localization exists?
4. Is `map_builder_node` the authoritative map algorithm, replacing the EMA `map_integrator_node` for normal operation?
5. Should a waypoint trigger perform one GroundingDINO request (`/grounding_dino/detect_once`) and then call map confirmation, or should confirmation itself trigger perception?
6. What stable values should define retrieval `map_id` and `map_version`?
7. Should `/semantic_map/finalize` cause a `replace` import automatically, or should database import remain an explicit operator action?
8. Are incremental updates required during a mission, and if so, what event marks an object batch as committed?
9. Should `viewpoint_count` become part of the retrieval schema or remain producer-only metadata?
10. Is a ROS semantic-map query service required, or is ROS import plus non-ROS agent/search access sufficient?
11. Should `Semanti_Map` remain as a supported alternate projection path, or become a bringup/map-assets package after migration?
12. Which installed ROS 2 Humble/Nav2 deployment provides the authoritative frame names and camera topics?

