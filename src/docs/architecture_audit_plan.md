# ROS 2 Humble Project Architecture Audit

```text
Status: audit only
No package files modified
Recommended base: Home_Project
Duplicate package source: Nav2 kept ignored by COLCON_IGNORE
Do not remove Nav2 until migration is complete
Primary unresolved decision: semantic pipeline topic/schema
```

Audit workspace: `/home/jimmy/work_ws/home_project_ws/src`

This document is an audit record only. No package source, manifest, launch, configuration, map, README, package name, or `COLCON_IGNORE` change is authorized by this document.

## 1. Project current structure summary

```text
src/
├── Home_Project/                 # Current recommended base
│   ├── README.md                 # Contains unresolved merge conflict
│   ├── temp                      # Unnamed waypoint/pose draft
│   ├── main_policy/
│   │   ├── launch/               # Three launch files
│   │   ├── config/               # Two configuration files
│   │   └── main_policy/          # Seven nodes and one backup file
│   ├── semantic_nav_interfaces/
│   │   └── srv/NavToPoint.srv
│   └── Semanti_Map/
│       ├── launch/               # Three launch files
│       ├── config/               # Semantic and Nav2 parameters
│       └── map/                  # map.yaml and map.png
└── Nav2/
    ├── COLCON_IGNORE             # Prevents normal colcon discovery
    ├── map.yaml / map.png
    ├── main_policy/              # Reduced duplicate version
    └── Semanti_Map/              # Different semantic node version
```

Another near-duplicate source tree exists at `/home/jimmy/visual/src`. Compared with it, the audited `home_project_ws` copy contains additional waypoint-related nodes and a different `nav2_params.yaml`. A single authoritative workspace must be selected before migration.

## 2. Package dependency graph

```text
nav2_bringup ───────────────┐
rviz2 ──────────────────────┤
sensor_msgs                 │
tf2_ros                     ▼
tf2_geometry_msgs ────> Semanti_Map
std_msgs                    │
numpy                       │ /semantic_map/raw_detections
                            ▼
vision_package ───────> main_policy ─────> nav2_msgs/NavigateToPose
                           │
                           └────> semantic_nav_interfaces/NavToPoint
```

The graph above reflects imports and launch behavior, not only declared manifest dependencies.

| Package | Dependency audit |
|---|---|
| `semantic_nav_interfaces` | `rosidl_default_generators` and `rosidl_default_runtime` are configured appropriately. |
| Home `main_policy` | Correctly declares `semantic_nav_interfaces`, but is missing dependencies used by its code, including `std_srvs`, `python3-numpy`, `python3-yaml`, and launch-related runtime dependencies. |
| Home `Semanti_Map` | Declares no runtime dependencies despite importing `rclpy`, `sensor_msgs`, `geometry_msgs`, `std_msgs`, TF packages, and NumPy, and launching Nav2/RViz components. |
| Nav2 duplicate packages | Their manifests contain test dependencies only and do not describe their runtime requirements. |
| Python packages | Their manifests also lack the common `ament_python` build-tool dependency. |

Home `main_policy` imports `semantic_nav_interfaces.srv.NavToPoint`, and its `package.xml` correctly declares a direct dependency on `semantic_nav_interfaces`.

## 3. Duplicate files table

### `main_policy`

| File or area | Comparison result |
|---|---|
| `setup.cfg` | Identical. |
| `resource/main_policy` | Identical. |
| `main_policy/__init__.py` | Identical. |
| Three test files | Identical according to recursive diff. |
| `map_integrator_node.py` | Only the default `map_save_path` differs. |
| `package.xml` | Home version declares substantially more dependencies. |
| `setup.py` | Home version installs launch/config data and provides six entry points; Nav2 provides only `map_integrator_node`. |
| launch/config | Present only in Home. |
| Additional Python nodes | Present only in Home. |

### `Semanti_Map`

| File or area | Comparison result |
|---|---|
| `setup.cfg`, resource marker, `__init__.py`, tests | Identical. |
| `semantic_map_node.py` | Substantially different implementations. |
| `semantic_map.launch.py` | Different parameter interfaces and installed configuration paths. |
| Home `config/params.yaml` vs Nav2 `params.yaml` | Different locations and detection-topic settings. |
| Map files | Home package map and Nav2 root map are byte-identical. |
| Additional Home content | `bringup.launch.py`, `nav_bringup.launch.py`, Nav2 parameters, and package-local map files. |

## 4. Conflicting package names table

| Package name | Home_Project | Nav2 | Result |
|---|---:|---:|---|
| `main_policy` | Present | Present | Duplicate package-name conflict. |
| `Semanti_Map` | Present | Present | Duplicate package-name conflict. |
| `semantic_nav_interfaces` | Present | Absent | No duplicate. |

Normal `colcon list --base-paths src` discovery currently returns only the Home versions because `Nav2/COLCON_IGNORE` suppresses the Nav2 tree.

When all five package paths were explicitly passed to `colcon list`, colcon discovered two `main_policy` packages and two `Semanti_Map` packages. If `COLCON_IGNORE` is removed, or both copies otherwise become discoverable, a normal build is expected to reject the duplicate package names.

Colcon also warns that `Semanti_Map` does not follow ROS package naming conventions because it contains uppercase letters. Package renaming is outside this audit's scope.

## 5. Which version seems newer / more complete

File modification times do not reliably establish which copy is newer; many files have matching timestamps.

- `Home_Project/main_policy` is clearly more complete and is the recommended integration base.
- `Home_Project/Semanti_Map` has the more complete package layout, launch/config installation, and package-local map installation.
- `Nav2/Semanti_Map/Semanti_Map/semantic_map_node.py` appears more defensive and feature-complete at the implementation level:
  - supports bbox and center-based detection inputs;
  - handles image row stride;
  - configures sensor QoS;
  - includes minimum/maximum depth and object-count limits;
  - contains more complete TF and exception handling.
- The shorter Home semantic node contains an error risk: TF exception branches reference an undefined `self.camera_frame` attribute.

The final semantic node cannot be selected by timestamp or file size alone. Its input parser must match the actual upstream detection topic and JSON schema.

## 6. Critical integration findings

### Semantic pipeline is not connected by default

`semantic_pipeline.launch.py` starts:

```text
Semanti_Map/semantic_map_node
    publishes /semantic_map/raw_detections

main_policy/map_builder_node
    subscribes /grounding_dino/objects_3d_json
```

The two nodes do not communicate with their current default parameters. This is the highest-priority integration defect.

### Multiple incompatible upstream architectures are mixed

The code and documentation refer to all of these inputs:

- `/yolo/detections`
- `/grounding_dino/bboxes`
- `/grounding_dino/detections`
- `/grounding_dino/objects_3d_json`

They imply at least two competing architectures:

1. A 2D detector publishes pixels or bounding boxes, and `Semanti_Map` performs depth projection and TF transformation.
2. `vision_package` already publishes 3D objects in the map frame, and `map_builder_node` consumes them directly.

One architecture and one message schema must be designated as authoritative before code changes.

### Nav2 parameter compatibility is uncertain

`Home_Project/Semanti_Map/config/nav2_params.yaml` appears to include settings from a newer Nav2 release rather than a clean Humble baseline. Examples include route server, docking, introspection settings, and `nav2_controller::FeasiblePathHandler`. These must be checked against the Nav2 packages actually installed with ROS 2 Humble.

The same YAML also defines duplicate top-level keys:

- `map_server` appears twice.
- `map_saver` appears twice.

Later YAML definitions can override earlier definitions, making the effective configuration ambiguous.

## 7. Launch/config/map review

| Item | Audit result |
|---|---|
| Home launch installation | Both Home `setup.py` files install `launch/*.py`. |
| Home main-policy config installation | Installed under the package share directory. |
| Home semantic config/map installation | Both config and map directories are installed. |
| Nav2 main-policy launch/config | Not present and therefore not installed. |
| Nav2 semantic parameters | Installed into the package-share root, matching its launch implementation. |
| Nav2 root map | Outside the package and not installed as package data. |
| Home launch path handling | Primarily uses `get_package_share_directory()`, so moving the repository as a whole should not break these paths. |
| Persistent map path | Several files hard-code `/home/hungyu/work_ws/semantic_map.json`. |
| Nav2 old persistent path | Hard-codes `/home/jimmy/work_ws/visual/semantic_map.json`. |
| Waypoint YAML | CLI `--yaml` is required, but no formal waypoint config or launch file packages such a YAML file. |

`bringup.launch.py` and `nav_bringup.launch.py` overlap heavily but launch different application nodes: one starts the semantic node, while the other starts the navigation service. Their responsibilities and names are not sufficiently clear for a deliverable project.

## 8. Python import and entry-point review

All six Home `main_policy` console entry points resolve to existing modules with a `main()` function:

- `map_integrator_node`
- `map_builder_node`
- `nav_service_node`
- `waypoint_tour_node`
- `waypoint_nav2_action_node`
- `sementic_map_node`

The Home `Semanti_Map` entry point also resolves correctly to `Semanti_Map.semantic_map_node:main`.

Risks:

- `sementic_map_node` is misspelled and the misspelling is now part of the executable interface.
- `Semanti_Map/semantic_map_node` and `main_policy/sementic_map_node` have confusingly similar names but different responsibilities.
- `sementic_map_node.py.bak_manual_step` is a manual source backup inside the package tree.
- Waypoint nodes use PyYAML without a declared package dependency.
- Map builder and semantic projection code use NumPy without complete manifest declarations.
- Moving the outer repository directory should not break imports if each package's nested Python package structure is preserved, such as `main_policy/main_policy/*.py`.
- Linux imports and ROS package lookup are case-sensitive; the existing `Semanti_Map` capitalization must remain consistent unless a separately approved rename migration is performed.

## 9. Risky files that need human review

| File | Risk |
|---|---|
| `Home_Project/README.md` | Contains unresolved merge-conflict markers and incomplete content. |
| `Home_Project/Semanti_Map/README.zh-TW.md` | Contains multiple unresolved merge-conflict sections. |
| `Home_Project/main_policy/README.zh-TW.md` | References nonexistent `dyn_ema_node.py`, `dyn_ema.launch.py`, `dyn_ema_params.yaml`, and a `yolo` package. |
| `main_policy/launch/semantic_pipeline.launch.py` | Default publisher and subscriber topics do not connect. |
| `Semanti_Map/launch/bringup.launch.py` and `nav_bringup.launch.py` | Overlapping responsibilities with different included application nodes. |
| Home `Semanti_Map/semantic_map_node.py` | Exception handling references undefined `self.camera_frame`. |
| Nav2 `Semanti_Map/semantic_map_node.py` | More robust, but its parameter names and schema differ from Home configuration. |
| `Semanti_Map/config/nav2_params.yaml` | Duplicate YAML keys and likely non-Humble configuration sections. |
| `main_policy/config/map_builder_params.yaml` | Hard-coded save path and pipeline topic mismatch. |
| `Home_Project/temp` | Extensionless, structurally incomplete waypoint/pose draft. |
| `sementic_map_node.py.bak_manual_step` | Manual backup in source tree. |
| `Semanti_Map/launch/__pycache__/*.pyc` | Generated artifact that should not be part of a clean deliverable. |
| Home_Project and Nav2 `.git/` directories | Would become nested repositories if copied directly under a new repository root. |

## 10. Recommended final clean structure

Without renaming packages:

```text
semantic_navigation_project/
├── README.md
├── .gitignore
├── docs/
│   ├── architecture_audit_plan.md
│   ├── system_architecture.md
│   └── interfaces.md
└── src/
    ├── semantic_nav_interfaces/
    │   ├── CMakeLists.txt
    │   ├── package.xml
    │   └── srv/NavToPoint.srv
    ├── main_policy/
    │   ├── package.xml
    │   ├── setup.py
    │   ├── setup.cfg
    │   ├── launch/
    │   ├── config/
    │   ├── resource/
    │   ├── main_policy/
    │   └── test/
    └── Semanti_Map/
        ├── package.xml
        ├── setup.py
        ├── setup.cfg
        ├── launch/
        ├── config/
        ├── map/
        ├── resource/
        ├── Semanti_Map/
        └── test/
```

The final repository should expose only one copy of each ROS package to colcon. Nav2 should remain ignored until migration and validation are complete. Historical copies can later be retained outside the colcon search path or represented through Git history rather than duplicate package directories.

## 11. Step-by-step migration plan

1. Confirm whether `/home/jimmy/work_ws/home_project_ws/src` or `/home/jimmy/visual/src` is the authoritative source tree.
2. Confirm the actual visual input topic and JSON schema.
3. Decide whether `Semanti_Map` performs 2D-to-3D projection or whether `vision_package` supplies map-frame 3D objects directly.
4. Use Home `main_policy` as the consolidation base.
5. Compare and manually merge the two semantic-node implementations according to the selected schema.
6. Make the semantic pipeline publisher and subscriber topics consistent.
7. Define clear responsibilities for `bringup.launch.py` and `nav_bringup.launch.py`, with one documented primary entry point.
8. Resolve README conflict markers and synchronize documentation with actual files, topics, and launches.
9. Add complete package dependencies based on imports and launch usage.
10. Replace machine-specific save paths with an explicitly selected runtime-data policy and configurable parameters.
11. Rebuild or reduce `nav2_params.yaml` against the installed ROS 2 Humble Nav2 version.
12. Keep one verified map pair and confirm its resolution, origin, and frame assumptions against the target environment.
13. Move duplicate Nav2 packages out of colcon discovery only after preserving a reviewed backup; do not delete them directly.
14. Run `colcon list` and confirm each package name appears once.
15. Run package-select builds, tests, and launch smoke tests.
16. Remove obsolete copies and generated artifacts only after functional validation and explicit approval.

## 12. Files that should probably be deleted, moved, or kept

These are recommendations only. No action has been taken.

| Recommended action | Item |
|---|---|
| Keep | Entire Home `semantic_nav_interfaces` package. |
| Keep as base | Home `main_policy`. |
| Keep as layout base | Home `Semanti_Map` package, launch, config, and map layout. |
| Merge manually | Defensive parsing, image handling, QoS, and TF behavior from Nav2 `semantic_map_node.py`. |
| Keep one copy | `map.yaml` and `map.png`; the compared copies are identical. |
| Move/archive after validation | Nav2 duplicate `main_policy` and `Semanti_Map` packages. |
| Human review, then move | `Home_Project/temp`. |
| Probably delete after approval | `launch/__pycache__` and `.pyc` files. |
| Probably delete after comparison | `sementic_map_node.py.bak_manual_step`. |
| Resolve rather than delete | README files containing conflicts or stale references. |
| Consolidate during final repository migration | Nested `.git` metadata, leaving one repository root. |
| Keep during migration | `Nav2/COLCON_IGNORE`. |

## 13. Questions before modifying anything

1. Is `home_project_ws/src` or `/home/jimmy/visual/src` the authoritative source?
2. Which topic and JSON schema does the upstream vision system currently publish: `/yolo/detections`, `/grounding_dino/bboxes`, `/grounding_dino/detections`, or `/grounding_dino/objects_3d_json`?
3. Should `Semanti_Map` continue performing depth and TF projection, or does `vision_package` already provide map-frame 3D objects?
4. Should `map_builder_node` or the older `map_integrator_node` be the primary map builder?
5. Is `main_policy/sementic_map_node` actually a waypoint controller, and must its misspelled executable name remain for compatibility?
6. Where is the authoritative waypoint YAML, and should it be packaged as configuration?
7. Where should `semantic_map.json` be stored at runtime: user home, a workspace data directory, or an explicitly supplied path?
8. Was `nav2_params.yaml` generated for Humble, and what exact Nav2 package versions are installed?
9. Should the Nav2 directory eventually be archived outside the repository or deleted only after the migration is validated?
10. Should both bringup launch entry points remain, or should the final project expose one primary bringup launch?

