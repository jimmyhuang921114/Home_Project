# Current State

這份文件記錄近期狀態與決策。若與程式碼或測試衝突，以程式碼與測試為準。

## Snapshot

- 專案目前只有 ROS2 semantic map 主流程，不再提供 legacy Replica runtime fallback。
- `data/semantic_map.json` 是暫時正式 snapshot；`data/replica_semantic_map.json` 可作較大的 Replica 轉換資料來源。
- `sql/semantic_map_schema.sql` 是唯一主流程 schema。
- Snapshot 可選擇包含 `regions`；第一版只支援 AABB region，`aliases` 為 optional。
- 舊 Replica SQL 已移到 `archive/legacy_replica/`，只作歷史參考。

## Runtime

- Agent 預設只暴露唯讀工具：
  - `search_semantic_map_object`
- 可選 fake robot tools：
  - `move_platform`
  - `use_vla`
- fake robot tools 預設不啟用；CLI/TUI 加 `--enable-robot-tools` 才會註冊。
- `scripts/agent_eval.py` 提供 Codex 輔助評估入口，保存 semantic map preflight、案例執行摘要與 raw traces。
- 固定提示詞由 `prompts/semantic_map_agent_v1.yaml` 管理；CLI/TUI/eval 可用 `--prompt-profile` 覆寫。
- 每個 `AgentSession` 只在首輪以完整 user prompt 預搜尋 top-3 候選，將精簡 `id + class` context 提供給模型。
- 每個 `AgentSession` 首輪也會提供 compact available-region catalog；若沒有 regions，明確要求模型不可猜測房間或區域。
- 評估 artifacts 位於 `.agent_eval/`，不提交 Git；runner 不自動評分，也不修改 DB。
- 第一版 ROS2 import service 位於 `ros2_ws/src/robot_object_retrieval_ros`，提供 `/semantic_map/import`，request 帶 semantic map JSON 與 `incremental` / `replace` / `regions` mode，response 回成功或錯誤摘要。
- HTTP agent service、Docker 與真實 robot adapters 尚未實作。

## Data Flow

```text
JSON snapshot
-> strict parser
-> class embeddings
-> transaction replace active semantic map or incremental object upsert
-> optional regions table
-> PostgreSQL + pgvector
-> search_semantic_map_object
-> AgentSession
```

初始化與匯入：

```powershell
.\.venv\Scripts\python.exe scripts\setup_semantic_map.py
.\.venv\Scripts\python.exe scripts\import_semantic_map.py --dry-run data\semantic_map.json
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\incremental_one_object.json --mode incremental
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\incremental_one_object_update.json --mode incremental
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json --mode regions
```

ROS2 匯入：

```bash
cd ros2_ws
colcon build
source install/setup.bash
ros2 run robot_object_retrieval_ros semantic_map_import_service_node
```

## Recent Decisions

- semantic map 是唯一正式資料流；舊 `objects/locations` CRUD 與舊 benchmark 已移除。
- 外部 JSON 或未來 ROS2 message 先轉成 `SemanticMapSnapshot`，核心 importer 不直接依賴 ROS2 topic shape。
- JSON import 支援 `replace`、`incremental` 與 `regions`。`incremental` 只新增或覆寫 JSON 中列出的 `(frame_id, id)` 物件，不刪除未列出的既有物件，也不接受 `regions`。`regions` 只替換同 frame 的 room/zone metadata，不呼叫 embedding。
- ROS2 第一版使用自訂 `ImportSemanticMap.srv` 承載 semantic map JSON 與同步匯入結果；自訂 semantic map object message、action 與 robot tool bridge 留待後續 adapter。
- incremental import record 的 `object_count` 代表該批 JSON 處理數，不代表目前 DB 中所有可搜尋物件總數。
- 未來若加入 agent service，`AgentSession` 維持純 Python runtime，ROS2 或 HTTP 作為外層 adapter。
- 小模型行為調整先透過 repo-local `robot-object-eval` skill 執行 read-only 評估，再依 trace 決定修改 prompt、tool contract、runtime guard 或 fake adapter。
- `search_semantic_map_object` 對模型回傳 `filter_status`、`match_status`、resolved location / near object 摘要，以及可信候選的 `id/class/xyz`。感知 `confidence` 與 embedding `similarity` 保留於直接搜尋 CLI 與 debug trace；兩者用途不同。
- `search_semantic_map_object` 可使用 `location` 與 `near_object_id` 篩選；未知 location、缺少 region metadata 或 unknown near object 不 fallback 到全域搜尋。
- `scripts/search_semantic_map.py` 也支援 `--location`、`--near-object-id` 與 `--near-radius-m`，作為不經過 Agent 的 filter/debug 入口。
- tool schema 開始收斂到 `ToolSchema` / `ToolSpec` 單一 source；semantic-map 與 fake robot tools 共享同一套 contract pattern，provider 端不再直接把 schema 細節散在 runtime 註冊邏輯裡。
- Prompt 已要求來源與目的地分開搜尋、理解「隨便一個」、缺 room metadata 時追問，以及卸貨完成後才可宣稱完成。
- 向量搜尋仍會對不存在物體回傳近似候選。小模型拒絕行為尚不穩定；後續需要設計 runtime 層候選門檻或結構化證據，不可只依賴 prompt。

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall src scripts tests
.\.venv\Scripts\python.exe scripts\agent_eval.py --case-id home_find_book --runs 1
```
