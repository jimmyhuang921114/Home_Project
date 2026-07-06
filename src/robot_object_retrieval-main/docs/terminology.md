# 術語表

這份文件只收目前 `robot_object_retrieval` repo 已存在、且常拿來描述需求的用語。
目標是讓你和 Codex 溝通時有固定詞可用，不追求完整教科書定義。
若文件與程式或測試衝突，以程式與測試為準。

## 詞條

### prompt profile

- 在本專案中的意思：一份 YAML prompt 設定，將 agent 的固定指令拆成 `base_assistant`、`search_strategy`、`robot_planning`、`response_style` 幾段，供 CLI、TUI、eval 載入。
- 不要混淆成什麼：不是單次對話內容，也不是動態 retrieved context。
- 例子/相關位置：`prompts/semantic_map_agent_v1.yaml`、`src/robot_object_retrieval/infrastructure/prompt_profiles.py`

### first-turn presearch

- 在本專案中的意思：`AgentSession` 只在第一輪 user turn 先用完整 user prompt 做一次 semantic map 預搜尋，並取 top-3 候選做後續提示。
- 不要混淆成什麼：不是每輪都做的 retrieval，也不是正式 tool call。
- 例子/相關位置：`docs/current_state.md`、`docs/architecture.md`

### retrieved context

- 在本專案中的意思：presearch 後整理給模型看的額外 system context，用來提供精簡候選背景。
- 不要混淆成什麼：不是 raw search results，也不是 debug trace。
- 例子/相關位置：`src/robot_object_retrieval/application/agent_instructions.py`、`docs/architecture.md`

### AgentSession

- 在本專案中的意思：agent runtime 的核心 session 物件，負責組 messages、呼叫 chat model、處理 tool calls、保存 trace。
- 不要混淆成什麼：不是單一 prompt profile，也不是單一 tool。
- 例子/相關位置：`src/robot_object_retrieval/application/agent_service.py`、`docs/current_state.md`

### tool definition

- 在本專案中的意思：提供給 chat model 的工具 schema，描述工具名稱、用途與參數格式。
- 不要混淆成什麼：不是工具實作本身，也不是 runtime dispatch result。
- 例子/相關位置：`src/robot_object_retrieval/application/tools/semantic_map.py`、`src/robot_object_retrieval/application/tool_registry.py`

### ToolRegistry

- 在本專案中的意思：集中管理 agent tools 的註冊、schema 暴露與 dispatch 的 registry 邊界。
- 不要混淆成什麼：不是某一個 tool group，也不是 chat model 自己的 tool-calling 功能。
- 例子/相關位置：`src/robot_object_retrieval/application/tool_registry.py`、`docs/architecture.md`

### ToolDispatchResult

- 在本專案中的意思：tool dispatch 的雙輸出結構，分開保存 `model_output` 與 `debug_output`。
- 不要混淆成什麼：不是單純 JSON 字串，也不是 chat model 的最終回答。
- 例子/相關位置：`src/robot_object_retrieval/application/tool_registry.py`

### dispatch_with_debug

- 在本專案中的意思：ToolRegistry 的 dispatch 入口之一，會保留 `model_output` 與 `debug_output` 兩份結果，而不是只回單一字串。
- 不要混淆成什麼：不是一般 `dispatch()`，也不是 tool handler 本身。
- 例子/相關位置：`src/robot_object_retrieval/application/tool_registry.py`、`src/robot_object_retrieval/application/agent_service.py`

### model-visible payload

- 在本專案中的意思：允許直接給模型看的工具結果，內容只保留安全且必要的 grounding 資訊，例如 `id`、`class`、`position`。
- 不要混淆成什麼：不是完整 debug payload，也不應包含 `similarity`、`confidence` 這類 ranking evidence。
- 例子/相關位置：`src/robot_object_retrieval/application/tools/semantic_map.py`

### debug payload

- 在本專案中的意思：保留給 trace、TUI 或除錯看的完整工具結果，會含 `similarity`、`confidence`、`model_visible` 等欄位。
- 不要混淆成什麼：不是模型實際看到的 payload，也不是使用者回答。
- 例子/相關位置：`src/robot_object_retrieval/application/tools/semantic_map.py`、`scripts/agent_tui.py`

### match_status

- 在本專案中的意思：semantic map search 的結果狀態欄位，用來標示這次搜尋是 `found`、`low_confidence` 或 `no_results`。
- 不要混淆成什麼：不是單一候選的信心分數，也不是最終任務成功與否。
- 例子/相關位置：`src/robot_object_retrieval/application/tools/semantic_map.py`

### filter_status

- 在本專案中的意思：semantic map search 的篩選狀態欄位，用來標示是否套用 `location`、`near_object_id`，或是否遇到 `unknown_location`、`location_unavailable`、`unknown_near_object`。
- 不要混淆成什麼：不是向量搜尋分數，也不是候選物件的感知信心。
- 例子/相關位置：`src/robot_object_retrieval/application/semantic_map_search_service.py`、`src/robot_object_retrieval/application/tools/semantic_map.py`

### region

- 在本專案中的意思：semantic map snapshot 中可選的 room/zone metadata，用來描述可用空間，例如 `座位區`、`收納區`。
- 不要混淆成什麼：不是 object，也不是模型自己猜出的 room name。
- 例子/相關位置：`data/semantic_map_regions_test.json`、`src/robot_object_retrieval/models.py`

### AABB

- 在本專案中的意思：第一版 region geometry 使用的矩形範圍，透過 `min_x/max_x/min_y/max_y` 判斷物體是否在區域內。
- 不要混淆成什麼：不是 polygon，也不是 navigation map。
- 例子/相關位置：`data/semantic_map_regions_test.json`、`sql/semantic_map_schema.sql`

### location

- 在本專案中的意思：`search_semantic_map_object` 的可選參數，用來放使用者指定的已知房間或區域，會依 region `id/name/aliases` resolve。
- 不要混淆成什麼：不是完整 user prompt，也不是物體 query。
- 例子/相關位置：`src/robot_object_retrieval/application/tools/semantic_map.py`、`scripts/search_semantic_map.py`

### near_object_id

- 在本專案中的意思：`search_semantic_map_object` 的可選參數，必須放已知 semantic map object id，用來做 2D 距離篩選。
- 不要混淆成什麼：不是自然語言 near query，也不是 class name。
- 例子/相關位置：`src/robot_object_retrieval/application/semantic_map_search_service.py`、`scripts/search_semantic_map.py`

### available-region catalog

- 在本專案中的意思：`AgentSession` 首輪提供給模型看的 compact region 清單，只列 `id/name/aliases`，讓模型知道 `location` 可用哪些空間。
- 不要混淆成什麼：不是 geometry，也不是 DB 中完整 region record。
- 例子/相關位置：`src/robot_object_retrieval/application/agent_service.py`

### source_id

- 在本專案中的意思：semantic map object 對外使用的物件識別值，會出現在 import、search 與 tool 結果中。
- 不要混淆成什麼：不是資料庫 serial id，也不是物件 class name。
- 例子/相關位置：`src/robot_object_retrieval/models.py`、`docs/architecture.md`

### frame_id

- 在本專案中的意思：semantic map snapshot 與搜尋結果所屬的座標框架識別值，例如 `map`。
- 不要混淆成什麼：不是 source id，也不是 room name。
- 例子/相關位置：`src/robot_object_retrieval/application/semantic_map_import_service.py`、`src/robot_object_retrieval/application/tools/semantic_map.py`

### semantic map snapshot

- 在本專案中的意思：匯入流程的正式資料形狀，外部 JSON 或未來 ROS2 request 都先轉成這個核心結構再進 importer。
- 不要混淆成什麼：不是資料庫 schema，也不是 ROS2 message shape 本身。
- 例子/相關位置：`src/robot_object_retrieval/application/semantic_map_import_service.py`、`docs/current_state.md`

### incremental import

- 在本專案中的意思：只新增或覆寫該批 JSON 中列出的 `(frame_id, id)` 物件，不刪除未列出的既有資料。
- 不要混淆成什麼：不是 append-only，也不是整份 snapshot 重建。
- 例子/相關位置：`docs/current_state.md`、`docs/architecture.md`

### replace import

- 在本專案中的意思：以該批 semantic map snapshot 取代 active semantic map 的正式重建流程。
- 不要混淆成什麼：不是 incremental update，也不是單物件 patch。
- 例子/相關位置：`docs/current_state.md`、`docs/architecture.md`

### regions import

- 在本專案中的意思：`--mode regions` / ROS2 `mode=regions`，只替換同 frame 的 room/zone metadata，不更新 objects，也不呼叫 embedding。
- 不要混淆成什麼：不是 replace import，也不是 incremental object update。
- 例子/相關位置：`scripts/import_semantic_map.py`、`ros2_ws/src/robot_object_retrieval_ros/robot_object_retrieval_ros_nodes/semantic_map_import_service_node.py`

### preflight

- 在本專案中的意思：在 eval 或讀取前先確認目前 semantic map 狀態的摘要資料，例如是否已載入、frame 與 object_count。
- 不要混淆成什麼：不是正式搜尋結果，也不是 import 寫入流程。
- 例子/相關位置：`src/robot_object_retrieval/application/agent_eval_service.py`、`src/robot_object_retrieval/infrastructure/db/semantic_map_repository.py`

### fake robot tools

- 在本專案中的意思：`move_platform` 與 `use_vla` 這類測試/示範用工具，只用來驗證任務規劃與 tool flow。
- 不要混淆成什麼：不代表真實 robot adapter 已接好，也不代表真機已安全執行。
- 例子/相關位置：`docs/current_state.md`、`prompts/semantic_map_agent_v1.yaml`、`src/robot_object_retrieval/application/tools/robot_mock.py`

## 常用描述模板

- `只改 <術語>，不要動 <排除範圍>。`
- `我說的 <術語 A> 是指這個 repo 裡的意思，不是 <容易混淆詞>。`
- `模型可見的只留 <model-visible payload 內容>，其餘留在 debug payload 或 trace。`
