---
name: robot-object-eval
description: Evaluate the robot_object_retrieval semantic-map agent with read-only DB preflight, repeatable scenarios, saved traces, and a Codex engineering assessment. Use for small-model tool-use debugging before changing prompts or runtime code.
---

# Robot Object Evaluation

Work in `C:\Users\morgan1020\Project\robot_object_retrieval`.

Use this skill to evaluate the semantic-map agent from outside the product runtime. Do not mutate the DB. Do not modify prompts, tools, or runtime code during the evaluation pass. `move_platform` and `use_vla` are fake planning tools, not real robot execution.

## Workflow

1. Check repo state:

```powershell
git status --short
git log -1 --oneline
```

2. Run human-style home scenarios first. These prompts intentionally resemble user requests and do not teach the model the expected tool sequence:

```powershell
.\.venv\Scripts\python.exe scripts\agent_eval.py --model gemma4:e4b --provider ollama-native --runs 1
```

Run one home scenario:

```powershell
.\.venv\Scripts\python.exe scripts\agent_eval.py --model gemma4:e4b --provider ollama-native --case-id home_move_any_book_to_xy
```

When a home scenario fails, run lower-level diagnostic cases separately:

```powershell
.\.venv\Scripts\python.exe scripts\agent_eval.py --model gemma4:e4b --provider ollama-native --cases benchmarks\semantic_map_diagnostic_cases.jsonl
.\.venv\Scripts\python.exe scripts\search_semantic_map.py plate --limit 5
```

Run one exploratory human prompt:

```powershell
.\.venv\Scripts\python.exe scripts\agent_eval.py --model gemma4:e4b --provider ollama-native --prompt "幫我找一本書 放到房間桌上" --enable-robot-tools
```

3. Read the timestamped `.agent_eval\<timestamp>\` output:

```text
preflight.json
summary.json
runs.jsonl
traces\
```

Start with `preflight.json` and `summary.json`. Confirm the recorded `prompt_profile_id`. Do not dump full `runs.jsonl` or raw trace JSON by default.

Use the compact trace summarizer before opening raw traces:

```powershell
.\.venv\Scripts\python.exe .\.codex\skills\robot-object-eval\scripts\summarize_agent_trace.py --eval-dir .agent_eval\<timestamp>
.\.venv\Scripts\python.exe .\.codex\skills\robot-object-eval\scripts\summarize_agent_trace.py --trace .agent_eval\<timestamp>\traces\trace_x.json
```

The summarizer keeps only tool calls, compact search results, robot state, `task_complete`, `next_required_tool/action`, assistant text, and final answer. Only open raw trace JSON when the compact summary is insufficient, such as prompt visibility, retrieval ranking, model-visible payload, or `confidence` / `similarity` diagnostics. Raw traces preserve first-turn presearch evidence and full `confidence` / `similarity` values even though the small model receives compact search payloads.

4. Produce an engineering assessment:

```markdown
# Semantic-Map Agent Evaluation

## Preflight
- Active snapshot:
- Frame / object count:
- Class distribution:
- Data readiness:

## Scenario Evidence
| Case | Turns | Tool Sequence | Final Answer | Assessment |
| --- | --- | --- | --- | --- |

## Diagnosis
- Data state:
- Retrieval:
- Prompt:
- Tool schema:
- Runtime guard:
- Fake adapter:
- Model capability:

## Proposed Bounded Fix
- Evidence:
- Proposed change:
- Cases to rerun:
```

5. Stop after reporting evidence and a bounded fix. Wait for user confirmation before editing code. After an approved fix, rerun the same case ids and compare artifacts.

## Evaluation Rules

- Treat code, preflight, compact trace summaries, `runs.jsonl`, and raw traces as the source of truth.
- Prefer `summary.json` plus `summarize_agent_trace.py` output for normal diagnosis. Avoid dumping full raw traces or full `runs.jsonl` unless compact evidence cannot answer the question.
- Start from natural home scenarios. Use diagnostic prompts and direct semantic-map search only after identifying a failure.
- Keep expected behavior outside the model prompt. Do not teach the model the tool sequence in the scenario under evaluation.
- The runner preserves evidence and does not produce pass/fail scores. Codex judges reasonableness.
- Separate DB coverage, vector retrieval, model candidate selection, tool schema, runtime loop, and fake adapter behavior.
- Treat `confidence` as perception confidence and `similarity` as embedding similarity. Use them as Codex diagnostic evidence, not as model-visible instructions.
- Do not classify a reasonable clarification question as a failure when the prompt is ambiguous.
- If tool sequence is plausible but the final answer ignores tool results, classify it as grounding or response synthesis weakness.
- If the model claims success while fake tool state disagrees, report both the model issue and the fake adapter limitation.
