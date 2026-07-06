# robot_object_retrieval

室內語意地圖搜尋與 agent tool runtime 原型。系統接收 ROS2 semantic map JSON snapshot，寫入 PostgreSQL + pgvector，並讓 agent 透過唯讀工具查詢物體位置。

## 目前功能

- 驗證並匯入 semantic map JSON；可完整替換 snapshot 或局部增量更新。
- Snapshot 可選擇包含 `regions`，第一版支援 AABB 區域，用於 location-aware 搜尋。
- 使用每個物體的 `class` 產生 embedding。
- 以單一 transaction 替換 active snapshot，或只新增/覆寫 JSON 中列出的物件。
- 用 `search_semantic_map_object` 查詢物體 `source_id`、`class` 與 `xyz`，可依 `location` 或 `near_object_id` 篩選。
- Agent 首輪會用完整 user prompt 預搜尋 top-3 候選，並提供 compact region catalog 協助小模型使用可用空間。
- 透過 CLI 或 Textual TUI 執行 agent。
- 可選啟用 `move_platform` / `use_vla` fake tools，測試高層任務規劃。

對接格式請見 `docs/interface_contracts.md`；該文件集中整理 semantic map JSON、ROS2 import service 與 CLI debug surface。

## 結構

```text
data/
  semantic_map.json
  semantic_map_regions_test.json
  incremental_one_object.json
  incremental_one_object_update.json
prompts/
  semantic_map_agent_v1.yaml
scripts/
  setup_semantic_map.py
  import_semantic_map.py
  search_semantic_map.py
  agent_cli.py
  agent_tui.py
  agent_eval.py
sql/
  semantic_map_schema.sql
src/robot_object_retrieval/
  application/
  infrastructure/
  models.py
  ports.py
ros2_ws/src/robot_object_retrieval_ros/
  robot_object_retrieval_ros_nodes/
    semantic_map_import_service_node.py
  srv/
    ImportSemanticMap.srv
```

舊 Replica SQL 已移到 `archive/legacy_replica/`，只作歷史參考，不再參與執行流程。

## 安裝

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

`.env` 至少需要 PostgreSQL、embedding API 與 chat API 設定。範例預設連線到本機 Ollama。

## 初始化與匯入

```powershell
.\.venv\Scripts\python.exe scripts\setup_semantic_map.py
.\.venv\Scripts\python.exe scripts\import_semantic_map.py --dry-run data\semantic_map.json
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map_regions_test.json --mode regions
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\incremental_one_object.json --mode incremental
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\incremental_one_object_update.json --mode incremental
```

`setup_semantic_map.py` 會依 embedding provider 回傳的維度建立 semantic map tables。正式匯入前可先用 `--dry-run` 完整驗證 JSON，不會呼叫 embedding，也不會修改 PostgreSQL。`--mode replace` 是預設行為，會整批替換 active objects 與同 frame regions；`--mode incremental` 只新增或覆寫 JSON 中列出的 `(frame_id, id)` 物件，未列出的既有物件與 regions 保留不動。`--mode regions` 只替換同 frame 的 room/zone metadata，不會產生 embedding，也不會修改 objects。`data/semantic_map_regions_test.json` 是搭配 `data/semantic_map.json` 的區域篩選驗收資料；`data/incremental_one_object*.json` 是最小增量匯入範例，第二個檔案用同一個 object id 驗證覆寫語意。

`regions` 是 optional。第一版只支援 `geometry.type = "aabb"`；`aliases` 可省略：

```json
{
  "id": "lobby",
  "name": "入口區",
  "aliases": ["入口", "門口"],
  "geometry": {
    "type": "aabb",
    "min_x": 0.0,
    "max_x": 2.0,
    "min_y": 0.0,
    "max_y": 3.0
  }
}
```

## ROS2 semantic map import

第一版 ROS2 通訊層位於 `ros2_ws/src/robot_object_retrieval_ros`。它只做 adapter：提供 `/semantic_map/import` service，request 帶目前 semantic map JSON payload，並呼叫既有 importer。`mode` 可用 `incremental`、`replace` 或 `regions`，空字串預設為 `incremental`。

先安裝核心 Python package，讓 ROS2 node 能正常 import：

```bash
cd <repo-root>
python -m pip install -e .
```

如果 ROS2 `ros2 run` 使用的是系統 Python，但核心 package 安裝在 repo `.venv`，啟動前需讓 ROS2 process 看得到 `.venv` 與 repo `src`：

```bash
export PROJECT_ROOT=$(pwd)
export PYTHONPATH=$PROJECT_ROOT/.venv/lib/python3.10/site-packages:$PROJECT_ROOT/src:$PYTHONPATH
```

在 ROS2 環境中 build 與啟動：

```bash
cd <repo-root>/ros2_ws
colcon build
source install/setup.bash
ros2 run robot_object_retrieval_ros semantic_map_import_service_node
```

另開一個已 source 同一個 ROS2 環境的 terminal 呼叫 service：

```bash
ros2 service call /semantic_map/import robot_object_retrieval_ros/srv/ImportSemanticMap \
  "{json_payload: '{\"frame_id\":\"map\",\"next_id\":2,\"objects\":[]}', mode: incremental}"
```

成功時 response 會回 `success=true`、`frame_id`、`source_next_id` 與 `object_count`。無效 JSON、payload 驗證錯誤、embedding 或 DB 失敗會回 `success=false`、`error_type` 與 `message`；node 會繼續等待下一次 request。

不經過 Agent，直接檢查向量搜尋候選：

```powershell
.\.venv\Scripts\python.exe scripts\search_semantic_map.py book --limit 5
.\.venv\Scripts\python.exe scripts\search_semantic_map.py chair --location 座位區 --limit 5
.\.venv\Scripts\python.exe scripts\search_semantic_map.py book --near-object-id table_10 --near-radius-m 1.5
```

輸出包含 `filter_status`、resolved location / near object 摘要、`id`、`class`、`xyz`、感知 `confidence` 與文字查詢 `similarity`，適合區分 retrieval、location filter 與小模型問題。`confidence` 與 `similarity` 只保留於直接搜尋與 debug trace，不暴露給小模型。

## Agent

```powershell
.\.venv\Scripts\python.exe scripts\agent_cli.py --model gemma4:e4b
.\.venv\Scripts\python.exe scripts\agent_tui.py --model gemma4:e4b
```

固定提示詞位於 `prompts/semantic_map_agent_v1.yaml`。需要比較不同提示詞版本時可使用：

```powershell
.\.venv\Scripts\python.exe scripts\agent_tui.py --prompt-profile prompts\semantic_map_agent_v1.yaml
.\.venv\Scripts\python.exe scripts\agent_eval.py --prompt-profile prompts\semantic_map_agent_v1.yaml
```

需要測試假的高層搬運規劃時加上：

```powershell
.\.venv\Scripts\python.exe scripts\agent_tui.py --model gemma4:e4b --enable-robot-tools
```

fake robot tools 不代表已接真實 AMR、VLA、導航或安全控制。

`search_semantic_map_object` 的 `query` 只放物體詞。若使用者指定房間或區域，工具參數使用 `location`；若要搜尋某個已知物體附近，使用先前工具結果中的 `near_object_id`，預設半徑為 `1.5m`。未知 location 或 unknown near object 不會 fallback 到全域搜尋。

## Codex 輔助評估

使用自然居家情境 regression cases 執行唯讀 preflight、Agent prompt、工具 trace 與本機 artifact 保存。預設 prompt 不會先教小模型工具順序：

```powershell
.\.venv\Scripts\python.exe scripts\agent_eval.py --model gemma4:e4b --provider ollama-native
.\.venv\Scripts\python.exe scripts\agent_eval.py --case-id home_move_any_book_to_xy
.\.venv\Scripts\python.exe scripts\agent_eval.py --prompt "幫我找一本書 放到房間桌上" --enable-robot-tools
```

輸出位於 `.agent_eval/<timestamp>/`，包含 `preflight.json`、`summary.json`、`runs.jsonl` 與 raw traces。Summary 會記錄 prompt profile；trace 會保存首輪預搜尋及工具查詢的完整分數證據。Runner 只保存證據，不自動判定 pass/fail，也不修改 DB。

底層 retrieval 與工具鏈診斷案例獨立放在 `benchmarks/semantic_map_diagnostic_cases.jsonl`，只在自然情境失敗後使用。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall src scripts tests
.\.venv\Scripts\python.exe scripts\agent_eval.py --case-id home_find_book --runs 1
```

架構、近期狀態與專案用語請見 [docs/architecture.md](docs/architecture.md)、[docs/current_state.md](docs/current_state.md) 與 [docs/terminology.md](docs/terminology.md)。
