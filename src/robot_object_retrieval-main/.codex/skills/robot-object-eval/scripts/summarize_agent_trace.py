from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_TOP_RESULTS = 3


def summarize_trace(trace_path: Path, *, top_results: int = DEFAULT_TOP_RESULTS) -> dict[str, Any]:
    resolved_path = trace_path.resolve()
    trace = _read_json(resolved_path)
    return summarize_trace_payload(trace, trace_path=resolved_path, top_results=top_results)


def summarize_trace_payload(
    trace: dict[str, Any],
    *,
    trace_path: Path | str,
    top_results: int = DEFAULT_TOP_RESULTS,
) -> dict[str, Any]:
    steps = [
        _summarize_step(step, top_results=top_results)
        for step in trace.get("steps", [])
        if isinstance(step, dict)
    ]
    return {
        "trace_path": str(trace_path),
        "model": trace.get("model"),
        "prompt_profile": trace.get("prompt_profile"),
        "user_input": trace.get("user_input"),
        "final_answer": trace.get("final_answer"),
        "steps": steps,
    }


def summarize_eval_dir(eval_dir: Path, *, top_results: int = DEFAULT_TOP_RESULTS) -> dict[str, Any]:
    resolved_dir = eval_dir.resolve()
    runs_path = resolved_dir / "runs.jsonl"
    traces: list[dict[str, Any]] = []
    for record in _read_jsonl(runs_path):
        if not isinstance(record, dict):
            continue
        for turn in record.get("turns", []):
            if not isinstance(turn, dict):
                continue
            trace_path_text = turn.get("trace_path")
            if not trace_path_text:
                traces.append(
                    {
                        "case_id": record.get("case_id"),
                        "run_index": record.get("run_index"),
                        "turn_index": turn.get("turn_index"),
                        "error": turn.get("error") or record.get("error"),
                        "trace_path": None,
                    }
                )
                continue
            trace_summary = summarize_trace(Path(str(trace_path_text)), top_results=top_results)
            trace_summary["case_id"] = record.get("case_id")
            trace_summary["run_index"] = record.get("run_index")
            trace_summary["turn_index"] = turn.get("turn_index")
            traces.append(trace_summary)
    return {"eval_dir": str(resolved_dir), "runs_path": str(runs_path), "traces": traces}


def _summarize_step(step: dict[str, Any], *, top_results: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"step": step.get("step")}
    assistant_text = _assistant_text(step)
    if assistant_text:
        summary["assistant_text"] = assistant_text
    tool_calls = [
        _summarize_tool_call(tool_call)
        for tool_call in step.get("tool_calls", [])
        if isinstance(tool_call, dict)
    ]
    if tool_calls:
        summary["tool_calls"] = tool_calls
    tool_results = [
        _summarize_tool_result(tool_result, top_results=top_results)
        for tool_result in step.get("tool_results", [])
        if isinstance(tool_result, dict)
    ]
    if tool_results:
        summary["tool_results"] = tool_results
    return summary


def _assistant_text(step: dict[str, Any]) -> str:
    assistant_message = step.get("assistant_message")
    if not isinstance(assistant_message, dict):
        return ""
    content = assistant_message.get("content")
    return str(content).strip() if content else ""


def _summarize_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return {"name": ""}
    name = str(function.get("name", ""))
    return {"name": name, "arguments": _compact_arguments(name, function.get("arguments"))}


def _compact_arguments(tool_name: str, arguments: Any) -> dict[str, Any]:
    args = _normalize_arguments(arguments)
    if tool_name == "search_semantic_map_object":
        return _keep_keys(args, ("query", "limit", "frame_id"))
    if tool_name == "move_platform":
        return _keep_keys(args, ("x", "y", "label"))
    if tool_name == "use_vla":
        return _keep_keys(args, ("action", "instruction"))
    return args


def _summarize_tool_result(tool_result: dict[str, Any], *, top_results: int) -> dict[str, Any]:
    tool_name = str(tool_result.get("tool_name", ""))
    result = tool_result.get("result")
    if not isinstance(result, dict):
        return {"tool_name": tool_name}
    if tool_name == "search_semantic_map_object":
        return _summarize_search_result(tool_name, result, top_results=top_results)
    if tool_name in {"move_platform", "use_vla"}:
        return _summarize_robot_result(tool_name, result)
    payload = {"tool_name": tool_name}
    for key in ("success", "error"):
        if key in result:
            payload[key] = result.get(key)
    return payload


def _summarize_search_result(
    tool_name: str,
    result: dict[str, Any],
    *,
    top_results: int,
) -> dict[str, Any]:
    results = result.get("results")
    candidates = results if isinstance(results, list) else []
    return {
        "tool_name": tool_name,
        "query": result.get("query"),
        "limit": result.get("limit"),
        "result_count": len(candidates),
        "top_results": [
            _keep_keys(candidate, ("id", "class"))
            for candidate in candidates[: max(top_results, 0)]
            if isinstance(candidate, dict)
        ],
    }


def _summarize_robot_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "success": result.get("success"),
        "state": result.get("state") if isinstance(result.get("state"), dict) else None,
    }
    for key in (
        "vla_action",
        "task_complete",
        "next_required_tool",
        "next_required_action",
        "error",
    ):
        if key in result:
            payload[key] = result.get(key)
    return payload


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _keep_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize robot-object agent debug traces.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trace", type=Path, help="Path to one raw trace JSON file.")
    source.add_argument("--eval-dir", type=Path, help="Path to one .agent_eval timestamp directory.")
    parser.add_argument("--top-results", type=int, default=DEFAULT_TOP_RESULTS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.trace:
        payload = summarize_trace(args.trace, top_results=args.top_results)
    else:
        payload = summarize_eval_dir(args.eval_dir, top_results=args.top_results)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
