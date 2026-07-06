from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Callable

from robot_object_retrieval.application.agent_service import AgentSession
from robot_object_retrieval.models import SemanticMapPreflight


@dataclass(frozen=True)
class AgentEvalScenario:
    id: str
    turns: tuple[str, ...]
    enable_robot_tools: bool
    kind: str = "home_scenario"
    expected_behavior: str = ""
    review_focus: str = ""


SessionFactory = Callable[[bool, Path], AgentSession]
PreflightLoader = Callable[[], SemanticMapPreflight]


def load_scenarios(path: Path) -> list[AgentEvalScenario]:
    scenarios: list[AgentEvalScenario] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        scenarios.append(_parse_scenario(payload, path=path, line_number=line_number))
    if not scenarios:
        raise ValueError(f"No evaluation scenarios found in {path}")
    return scenarios


def select_scenarios(
    scenarios: list[AgentEvalScenario],
    scenario_ids: list[str] | None,
) -> list[AgentEvalScenario]:
    if not scenario_ids:
        return scenarios
    selected_ids = set(scenario_ids)
    selected = [scenario for scenario in scenarios if scenario.id in selected_ids]
    missing = sorted(selected_ids - {scenario.id for scenario in selected})
    if missing:
        raise ValueError(f"Unknown case id(s): {', '.join(missing)}")
    return selected


def make_prompt_scenario(prompt: str, *, enable_robot_tools: bool) -> AgentEvalScenario:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("--prompt must not be empty")
    return AgentEvalScenario(
        id="adhoc_prompt",
        turns=(normalized_prompt,),
        enable_robot_tools=enable_robot_tools,
        kind="adhoc",
        expected_behavior="Codex reviews this ad-hoc prompt from the saved trace.",
        review_focus="Inspect tool use, grounding, and final answer quality.",
    )


def default_output_dir(project_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return project_root / ".agent_eval" / timestamp


def run_evaluation(
    *,
    model: str,
    provider: str,
    prompt_profile_id: str,
    prompt_profile_path: str,
    scenarios: list[AgentEvalScenario],
    runs: int,
    output_dir: Path,
    session_factory: SessionFactory,
    preflight_loader: PreflightLoader,
) -> dict:
    if runs < 1:
        raise ValueError("--runs must be >= 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = output_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    preflight = asdict(preflight_loader())
    _write_json(output_dir / "preflight.json", preflight)

    records = [
        _run_scenario(
            model=model,
            provider=provider,
            scenario=scenario,
            run_index=run_index,
            traces_dir=traces_dir,
            session_factory=session_factory,
        )
        for run_index in range(1, runs + 1)
        for scenario in scenarios
    ]
    runs_path = output_dir / "runs.jsonl"
    with runs_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "output_dir": str(output_dir),
        "preflight_path": str(output_dir / "preflight.json"),
        "runs_path": str(runs_path),
        "prompt_profile_id": prompt_profile_id,
        "prompt_profile_path": prompt_profile_path,
        "run_count": len(records),
        "error_count": sum(1 for record in records if record["error"]),
        "cases": [
            {
                "case_id": record["case_id"],
                "kind": record["kind"],
                "run_index": record["run_index"],
                "turn_count": len(record["turns"]),
                "actual_tool_sequence": record["actual_tool_sequence"],
                "final_answer": record["final_answer"],
                "duration_ms": record["duration_ms"],
                "error": record["error"],
            }
            for record in records
        ],
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _run_scenario(
    *,
    model: str,
    provider: str,
    scenario: AgentEvalScenario,
    run_index: int,
    traces_dir: Path,
    session_factory: SessionFactory,
) -> dict:
    started_at = time.perf_counter()
    turn_records: list[dict] = []
    error_message: str | None = None
    session = session_factory(scenario.enable_robot_tools, traces_dir)

    for turn_index, prompt in enumerate(scenario.turns, start=1):
        try:
            result = session.send(prompt)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            turn_records.append(
                {
                    "turn_index": turn_index,
                    "prompt": prompt,
                    "answer": "",
                    "tool_calls": [],
                    "tool_results": [],
                    "trace_path": None,
                    "error": error_message,
                }
            )
            break
        turn_records.append(
            {
                "turn_index": turn_index,
                "prompt": prompt,
                "answer": result.answer,
                "tool_calls": result.tool_calls,
                "tool_results": result.tool_results,
                "trace_path": str(result.trace_path) if result.trace_path else None,
                "error": None,
            }
        )

    return {
        "case_id": scenario.id,
        "kind": scenario.kind,
        "run_index": run_index,
        "model": model,
        "provider": provider,
        "enable_robot_tools": scenario.enable_robot_tools,
        "expected_behavior": scenario.expected_behavior,
        "review_focus": scenario.review_focus,
        "turns": turn_records,
        "actual_tool_sequence": [
            tool_call.get("function", {}).get("name", "")
            for turn in turn_records
            for tool_call in turn["tool_calls"]
        ],
        "final_answer": turn_records[-1]["answer"] if turn_records else "",
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "error": error_message,
        "robot_tools_are_mock": scenario.enable_robot_tools,
    }


def _parse_scenario(payload: object, *, path: Path, line_number: int) -> AgentEvalScenario:
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario must be an object at {path}:{line_number}")
    scenario_id = str(payload.get("id", "")).strip()
    turns = payload.get("turns")
    if not scenario_id:
        raise ValueError(f"Missing scenario id at {path}:{line_number}")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"turns must be a non-empty string list at {path}:{line_number}")
    normalized_turns = tuple(str(turn).strip() for turn in turns)
    if not all(normalized_turns):
        raise ValueError(f"turns must be a non-empty string list at {path}:{line_number}")
    return AgentEvalScenario(
        id=scenario_id,
        turns=normalized_turns,
        enable_robot_tools=bool(payload.get("enable_robot_tools", False)),
        kind=str(payload.get("kind", "home_scenario")).strip() or "home_scenario",
        expected_behavior=str(payload.get("expected_behavior", "")).strip(),
        review_focus=str(payload.get("review_focus", "")).strip(),
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
