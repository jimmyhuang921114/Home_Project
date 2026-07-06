# 首次部署指南

## 前置條件

- Python 3.10+
- PostgreSQL + pgvector
- 可用的 OpenAI-compatible embedding API
- 可用的 OpenAI-compatible chat API，或 Ollama native chat API

## PostgreSQL

使用含 pgvector 的 PostgreSQL image：

```bash
docker run --name robot-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=robot_db \
  -p 5432:5432 \
  -v robot_pgdata:/var/lib/postgresql \
  -d pgvector/pgvector:pg18-bookworm
```

## Python 與設定

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

修改 `.env` 的 PostgreSQL 密碼、embedding endpoint 與 chat endpoint。程式只讀 repo root 的 `.env`。

## 初始化與資料匯入

```bash
python scripts/setup_semantic_map.py
python scripts/import_semantic_map.py --dry-run data/semantic_map.json
python scripts/import_semantic_map.py data/semantic_map.json
```

`setup_semantic_map.py` 會依 embedding provider 維度建立 semantic map tables。正式匯入會以 transaction 整批替換 active snapshot。

## Agent

```bash
python scripts/agent_cli.py --model gemma4:e4b
python scripts/agent_tui.py --model gemma4:e4b
```

規劃 smoke test 可加 `--enable-robot-tools`，但 fake tools 不代表已接真實機器人。

## 最小成功標準

- PostgreSQL 可連線。
- `setup_semantic_map.py` 執行成功。
- `import_semantic_map.py --dry-run data/semantic_map.json` 通過。
- 正式匯入成功。
- Agent 能透過 `search_semantic_map_object` 查到物體。
