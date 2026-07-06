# 系統架構

這份文件描述目前可執行的架構。程式碼與測試仍是最終事實；若文件與實作衝突，以實作為準。

## 分層總覽

```mermaid
flowchart TB
    subgraph ROS2["ROS2 Layer: 外部通訊 adapter"]
        Scan["Scanner / perception client"]
        Service["/semantic_map/import<br/>ImportSemanticMap.srv"]
        ServiceNode["semantic_map_import_service_node<br/>robot_object_retrieval_ros_nodes"]
    end

    subgraph Core["Core Python Application: 純 Python 業務邏輯"]
        Parser["parse_semantic_map_snapshot"]
        Importer["semantic_map_import_service<br/>incremental / replace"]
        ToolRegistry["ToolRegistry"]
        SearchTool["search_semantic_map_object"]
        SearchService["semantic_map_search_service"]
        Agent["AgentSession"]
    end

    subgraph Infra["Infrastructure: 具體外部系統"]
        Embedding["Embedding API<br/>Ollama / bge-m3"]
        DB[("PostgreSQL + pgvector")]
        Chat["Chat API<br/>Ollama / OpenAI compatible"]
    end

    subgraph UI["User Entrypoints"]
        CLI["scripts/*"]
        TUI["agent_cli.py / agent_tui.py"]
    end

    Scan --> Service --> ServiceNode
    ServiceNode --> Parser --> Importer
    Importer --> Embedding
    Importer --> DB

    CLI --> Parser
    CLI --> Importer

    TUI --> Agent
    Agent <--> Chat
    Agent <--> ToolRegistry
    ToolRegistry --> SearchTool --> SearchService
    SearchService --> Embedding
    SearchService --> DB
```

核心原則：ROS2 node 只做 adapter，負責接 service request、轉成 application input、回傳 response；`application/*` 不 import `rclpy`，也不依賴 ROS2 message shape。

## Semantic Map Import Flow

```mermaid
sequenceDiagram
    participant Client as ROS2 client
    participant Srv as /semantic_map/import
    participant Node as semantic_map_import_service_node
    participant Parser as parse_semantic_map_snapshot
    participant Importer as import service
    participant Embed as Embedding API
    participant DB as PostgreSQL + pgvector

    Client->>Srv: json_payload + mode
    Srv->>Node: ImportSemanticMap request
    Node->>Parser: parse JSON into SemanticMapSnapshot
    Parser-->>Node: SemanticMapSnapshot
    Node->>Importer: import incremental, replace, or regions
    Importer->>Embed: embed_texts(class names, except regions mode)
    Embed-->>Importer: embeddings
    Importer->>DB: transaction object write or region replace
    DB-->>Importer: committed
    Importer-->>Node: frame_id + object_count
    Node-->>Client: success / error response
```

正式 ROS2 匯入入口：

```text
service: /semantic_map/import
type: robot_object_retrieval_ros/srv/ImportSemanticMap
request: json_payload, mode
response: success, frame_id, source_next_id, object_count, error_type, message
```

`mode` 可用 `incremental`、`replace` 或 `regions`；空字串預設為 `incremental`。

## Agent Query Flow

```mermaid
sequenceDiagram
    participant UI as CLI / TUI
    participant Agent as AgentSession
    participant Chat as Chat API
    participant Registry as ToolRegistry
    participant Tool as search_semantic_map_object
    participant Search as semantic_map_search_service
    participant Embed as Embedding API
    participant DB as PostgreSQL + pgvector

    UI->>Agent: user task
    Agent->>Search: first-turn presearch(user prompt, 3)
    Search->>Embed: embed query
    Search->>DB: pgvector search + available regions
    Search-->>Agent: compact context + region catalog + trace evidence
    Agent->>Chat: messages + tool definitions
    Chat-->>Agent: tool call
    Agent->>Registry: dispatch tool
    Registry->>Tool: search request
    Tool->>Search: candidate search + optional location / near filters
    Search->>Embed: embed query
    Search->>DB: pgvector search
    Search-->>Tool: source_id + class + xyz
    Tool-->>Agent: model-safe result
    Agent->>Chat: tool result
    Chat-->>Agent: final answer
```

Agent tool 對模型暴露 `filter_status`、`match_status`、resolved location / near object 摘要，以及可信候選的 `id`、`class`、`xyz`。感知 `confidence` 與 embedding `similarity` 只保留在直接搜尋 CLI 與 debug trace，不交給小模型決策。若指定 `location` 或 `near_object_id` 無法解析，工具回空結果並標示原因，不 fallback 到全域搜尋。`scripts/search_semantic_map.py` 是同一套 search service 的 debug 入口，支援 `--location`、`--near-object-id` 與 `--near-radius-m`，並輸出完整 debug 分數。

## Python 邊界

```mermaid
flowchart LR
    Scripts["scripts/*<br/>CLI args + dependency wiring"]
    ROS["ros2_ws/src/robot_object_retrieval_ros<br/>ROS2 service adapter"]
    App["application/*<br/>business logic"]
    Ports["ports.py<br/>protocols"]
    Infra["infrastructure/*<br/>DB / API clients"]

    Scripts --> App
    ROS --> App
    App --> Ports
    Infra --> Ports
```

- `scripts/*` 只做 CLI 參數解析與 dependency wiring。
- `ros2_ws/src/robot_object_retrieval_ros` 只做 ROS2 service adapter 與 `.srv` interface。
- `application/*` 放 parser、import、search、agent runtime 與 tool groups。
- `infrastructure/*` 放 PostgreSQL、pgvector、embedding API、chat API 等具體實作。

## 原則

- 外部 JSON 或 ROS2 service request 先轉成 `SemanticMapSnapshot`，核心 importer 不依賴 ROS2 shape；snapshot 可選擇包含 AABB `regions`。
- Semantic map import 的正式 ROS2 入口是 `/semantic_map/import` service，不是 topic。
- Agent tool 對外使用 ROS2 `source_id`，不暴露 DB serial id。
- 真實 robot action / human interaction tools 後續應新增到 `application/tools/`，再由 ROS2 adapter bridge 到 service/action。
- 舊 Replica SQL 位於 `archive/legacy_replica/`，不再作為可執行入口。
