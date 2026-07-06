# Interface Contracts

本文件整理目前對外介面的穩定資料契約。實作與測試仍是最終事實；若本文件與 parser、ROS2 `.srv` 或 CLI 參數衝突，以程式碼為準。

## Semantic Map JSON Snapshot

Semantic map JSON snapshot 是目前 CLI import、ROS2 import service 與未來 HTTP API 可共用的核心 payload。外層必須是 JSON object。

```json
{
  "frame_id": "map",
  "next_id": 19,
  "objects": [
    {
      "id": "chair_5",
      "class": "chair",
      "position": {
        "x": 0.7855,
        "y": 0.2371,
        "z": 2.3793
      },
      "confidence": 0.438,
      "observe_count": 616
    }
  ],
  "regions": [
    {
      "id": "seating_area",
      "name": "座位區",
      "aliases": ["椅子區", "沙發區", "seating"],
      "geometry": {
        "type": "aabb",
        "min_x": 0.6,
        "max_x": 1.7,
        "min_y": 0.0,
        "max_y": 0.7
      }
    }
  ]
}
```

### Snapshot Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `frame_id` | string | yes | Coordinate frame id, normally `map`. |
| `next_id` | integer | yes | Source-side next id marker preserved from the producer. |
| `objects` | array | yes | Semantic map objects. May be empty for `mode=regions`. |
| `regions` | array | no | Room/zone metadata for location-aware search. Omitted means no regions. |

### Object Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Stable object source id within the same `frame_id`. Duplicate ids in the same snapshot are invalid. |
| `class` | string | yes | Object class text used for embedding and semantic search. |
| `position.x` | number | yes | X coordinate in the snapshot frame. |
| `position.y` | number | yes | Y coordinate in the snapshot frame. |
| `position.z` | number | yes | Z coordinate in the snapshot frame. |
| `confidence` | number | yes | Detection or map confidence from the producer. |
| `observe_count` | integer | yes | Observation count from the producer. |

Coordinates are treated as meters by current search and debug tools. Near-object filtering uses only 2D `x/y`; `z` is preserved in results but not used for distance filtering.

### Region Fields

`regions` are optional. The first supported geometry is AABB only; the `geometry.type` field is reserved so future `polygon` support can be added without changing the top-level region shape.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Stable region id within the same `frame_id`. Duplicate region ids are invalid. |
| `name` | string | yes | Human-readable room or zone name. |
| `aliases` | array of strings | no | Optional alternative names for location resolution. |
| `geometry.type` | string | yes | Must be `aabb` in the current implementation. |
| `geometry.min_x` | number | yes | AABB minimum x. Must be `<= max_x`. |
| `geometry.max_x` | number | yes | AABB maximum x. |
| `geometry.min_y` | number | yes | AABB minimum y. Must be `<= max_y`. |
| `geometry.max_y` | number | yes | AABB maximum y. |

Location resolution order is `region.id`, then `region.name`, then optional `aliases`.

## ROS2 Import Interface

Current ROS2 adapter exposes one synchronous import service.

```text
service: /semantic_map/import
type: robot_object_retrieval_ros/srv/ImportSemanticMap
```

Service definition:

```srv
string json_payload
string mode
---
bool success
string frame_id
int64 source_next_id
int64 object_count
string error_type
string message
```

### Request

| Field | Type | Notes |
| --- | --- | --- |
| `json_payload` | string | JSON-encoded semantic map snapshot. |
| `mode` | string | `incremental`, `replace`, `regions`, or empty string. Empty string defaults to `incremental`. |

### Import Modes

| Mode | Behavior |
| --- | --- |
| `incremental` | Insert or update listed objects only. Does not delete unlisted objects. Rejects payloads that include `regions`. |
| `replace` | Replace active objects and same-frame regions from the payload. |
| `regions` | Replace same-frame region metadata only. Does not update objects and does not call embedding. |
| empty string | Same as `incremental`. |

### Response

| Field | Type | Notes |
| --- | --- | --- |
| `success` | bool | `true` when import completed. |
| `frame_id` | string | Imported snapshot frame id, when available. |
| `source_next_id` | int64 | Imported snapshot `next_id`, when available. |
| `object_count` | int64 | Count from the processed payload or import result. For incremental import, this is not the total DB object count. |
| `error_type` | string | Stable error category for failures. |
| `message` | string | Human-readable success or failure detail. |

Invalid `mode`, invalid JSON, payload validation errors, embedding failures, and database failures return `success=false`. The node stays alive for later requests.

Example call:

```bash
ros2 service call /semantic_map/import robot_object_retrieval_ros/srv/ImportSemanticMap \
  "{json_payload: '{\"frame_id\":\"map\",\"next_id\":2,\"objects\":[]}', mode: incremental}"
```

## CLI Debug Interfaces

CLI scripts are local validation and debug surfaces. They are useful for reproducing import/search behavior before wiring ROS2 or a future HTTP API, but they are not themselves the long-term public API.

### Import CLI

```powershell
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json --mode replace
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map_regions_test.json --mode regions
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json --dry-run
```

Stable arguments:

| Argument | Notes |
| --- | --- |
| `snapshot_path` | Path to a semantic map JSON snapshot. |
| `--mode replace` | Default CLI mode. Replaces objects and regions. |
| `--mode incremental` | Updates listed objects only; rejects `regions`. |
| `--mode regions` | Replaces region metadata only. |
| `--dry-run` | Validates and summarizes payload without embedding or database writes. |

### Search Debug CLI

```powershell
.\.venv\Scripts\python.exe scripts\search_semantic_map.py book --limit 5
.\.venv\Scripts\python.exe scripts\search_semantic_map.py chair --location 座位區 --limit 5
.\.venv\Scripts\python.exe scripts\search_semantic_map.py book --near-object-id table_10 --near-radius-m 1.5
```

Stable arguments:

| Argument | Notes |
| --- | --- |
| `query` | Object text to embed and search. |
| `--limit` | Maximum candidates to return. |
| `--location` | Optional region filter resolved by id, name, or alias. Unknown locations do not fall back to global search. |
| `--near-object-id` | Optional source object id used as the 2D distance anchor. Unknown ids do not fall back to global search. |
| `--near-radius-m` | 2D radius in meters for `--near-object-id`; default is `1.5`. |

Search output includes `filter_status`, `match_status`, candidates, resolved filter summaries, and debug evidence such as similarity/confidence.

## Future API Notes

When an HTTP API is added, it should reuse the Semantic Map JSON Snapshot contract above instead of defining a separate object or region shape. HTTP endpoint paths, status codes, and auth rules should be added as a new section in this file.
