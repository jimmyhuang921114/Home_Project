# AGENTS.md

台灣中文。

本檔是 repo root 的 Codex 專案指令，適用於整個 repository。它只放穩定工作規則；短期狀態與近期決策請看 `docs/current_state.md`。

## Source of Truth

- 程式碼與測試是最終事實；文件若與實作衝突，以目前程式碼為準。
- README 面向使用者，避免塞入短期操作歷史或 agent 工作紀錄。
- `docs/current_state.md` 可記錄目前狀態、近期決策、已知過時點與下一步。

## Repository Expectations

- 保持 `scripts/* -> application/* -> ports.py <- infrastructure/*` 分層。
- `scripts/*` 只做 CLI 參數解析與 dependency wiring，不承載主要業務規則。
- `application/tools/*` 放 agent tool groups；新工具不要直接寫死在 `agent_service.py`。
- `infrastructure/*` 放 PostgreSQL、pgvector、chat API、embedding API 等具體實作。
- 舊 Replica SQL 位於 `archive/legacy_replica/`，只作歷史參考，不可重新接回主流程。

## Graphify Workflow

- 新對話若主要目的是探索 repo 結構、模組關係、資料流或既有術語，優先使用 `graphify` skill / 現有 `graphify-out/` 圖譜導覽。
- 若任務是精準改碼、單點 bug 排查或測試修正，直接讀 code 與 tests，不必優先依賴圖譜。
- 經歷大幅重構、tool contract 變更或主要資料流改寫後，再手動更新 `graphify-out/`。
- `graphify-out/` 屬本地工作流程 artifact，預設不提交 Git。

## Agent Tool Rules

- 現有 semantic map tool：
  - `search_semantic_map_object`
- 可選 fake robot tools：
  - `move_platform`
  - `use_vla`
- 新 tool group 先透過 `ToolRegistry` 註冊 schema 與 handler。
- 未來 robot action / human interaction tools 應新增到 `application/tools/`。
- 不要新增假裝已接真實機器人的 mock 行為，除非任務明確要求 stub 或測試替身。

## Validation Commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall src scripts tests
.\.venv\Scripts\python.exe scripts\import_semantic_map.py --dry-run data\semantic_map.json
.\.venv\Scripts\python.exe scripts\search_semantic_map.py book --limit 5
.\.venv\Scripts\python.exe scripts\search_semantic_map.py chair --location 座位區 --limit 5
.\.venv\Scripts\python.exe scripts\agent_eval.py --case-id home_find_book --runs 1
```

資料庫初始化與匯入：

```powershell
.\.venv\Scripts\python.exe scripts\setup_semantic_map.py
.\.venv\Scripts\python.exe scripts\import_semantic_map.py data\semantic_map.json
```

## Coding Rules

- Python 使用 4 空白縮排、`snake_case` 函式/模組、`PascalCase` 類別、常數全大寫。
- 優先延續既有 `dataclass`、型別註記、小型純函式風格。
- SQL 盡量集中在 infrastructure DB repository 或 `sql/`。
- 文件更新保持短而可維護；短期狀態優先更新 `docs/current_state.md`。

## Security

- 不要提交 `.env`、資料庫密碼、API key、Hugging Face token。
- 程式只應讀 repo root `.env` 或明確指定的 env file，不要意外往父目錄找 secrets。
