from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_eval_service import (
    AgentEvalScenario,
    default_output_dir,
    load_scenarios,
    make_prompt_scenario,
    run_evaluation,
    select_scenarios,
)
from robot_object_retrieval.application.agent_service import AgentTurnResult
from robot_object_retrieval.models import SemanticMapPreflight


class FakeSession:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.prompts = []

    def send(self, prompt: str) -> AgentTurnResult:
        self.prompts.append(prompt)
        if prompt == self.fail_on:
            raise RuntimeError("model unavailable")
        tool_name = "search_semantic_map_object"
        return AgentTurnResult(
            answer=f"answer:{prompt}",
            trace_path=Path("trace.json"),
            tool_calls=[{"function": {"name": tool_name, "arguments": {"query": "book"}}}],
            tool_results=[{"tool_name": tool_name, "result": {"results": []}}],
        )


def fake_preflight() -> SemanticMapPreflight:
    return SemanticMapPreflight(
        snapshot_loaded=True,
        import_id=7,
        frame_id="map",
        source_next_id=20,
        object_count=19,
        imported_at="2026-06-02T10:00:00",
        class_counts=(("book", 4), ("chair", 3)),
    )


class AgentEvalServiceTests(unittest.TestCase):
    def test_default_output_dir_has_subsecond_precision(self) -> None:
        output_dir = default_output_dir(Path("project"))
        self.assertRegex(output_dir.name, r"^\d{8}_\d{6}_\d{6}$")

    def test_load_scenarios_validates_jsonl_and_selects_cases(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cases_path = Path(temp_dir) / "cases.jsonl"
            cases_path.write_text(
                '{"id":"one","turns":["first"],"enable_robot_tools":true}\n'
                '{"id":"two","kind":"diagnostic","turns":["second"]}\n',
                encoding="utf-8",
            )

            scenarios = load_scenarios(cases_path)

        self.assertEqual([scenario.id for scenario in scenarios], ["one", "two"])
        self.assertTrue(scenarios[0].enable_robot_tools)
        self.assertEqual(scenarios[1].kind, "diagnostic")
        self.assertEqual([scenario.id for scenario in select_scenarios(scenarios, ["two"])], ["two"])
        with self.assertRaisesRegex(ValueError, "Unknown case id"):
            select_scenarios(scenarios, ["missing"])

    def test_load_scenarios_rejects_empty_turn(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cases_path = Path(temp_dir) / "cases.jsonl"
            cases_path.write_text('{"id":"bad","turns":[" "]}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "turns must be"):
                load_scenarios(cases_path)

    def test_make_prompt_scenario_builds_adhoc_single_turn(self) -> None:
        scenario = make_prompt_scenario("  幫我找書  ", enable_robot_tools=True)
        self.assertEqual(scenario.id, "adhoc_prompt")
        self.assertEqual(scenario.turns, ("幫我找書",))
        self.assertTrue(scenario.enable_robot_tools)
        self.assertEqual(scenario.kind, "adhoc")

    def test_run_evaluation_keeps_history_within_scenario_and_fresh_sessions_between_cases(self) -> None:
        sessions = []

        def session_factory(enable_robot_tools, traces_dir):
            session = FakeSession()
            sessions.append(session)
            return session

        scenarios = [
            AgentEvalScenario(id="multi", turns=("first", "second"), enable_robot_tools=False),
            AgentEvalScenario(id="single", turns=("third",), enable_robot_tools=True),
        ]
        with TemporaryDirectory() as temp_dir:
            summary = run_evaluation(
                model="test-model",
                provider="test-provider",
                prompt_profile_id="test_profile",
                prompt_profile_path="prompts/test.yaml",
                scenarios=scenarios,
                runs=1,
                output_dir=Path(temp_dir),
                session_factory=session_factory,
                preflight_loader=fake_preflight,
            )
            records = [
                json.loads(line)
                for line in (Path(temp_dir) / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            preflight = json.loads((Path(temp_dir) / "preflight.json").read_text(encoding="utf-8"))

        self.assertEqual([session.prompts for session in sessions], [["first", "second"], ["third"]])
        self.assertEqual(summary["run_count"], 2)
        self.assertEqual(summary["prompt_profile_id"], "test_profile")
        self.assertEqual(records[0]["actual_tool_sequence"], ["search_semantic_map_object"] * 2)
        self.assertEqual(records[0]["turns"][0]["trace_path"], "trace.json")
        self.assertEqual(preflight["object_count"], 19)

    def test_run_evaluation_records_failure_and_continues_next_scenario(self) -> None:
        sessions = []

        def session_factory(enable_robot_tools, traces_dir):
            session = FakeSession(fail_on="fail")
            sessions.append(session)
            return session

        scenarios = [
            AgentEvalScenario(id="broken", turns=("fail", "not-run"), enable_robot_tools=False),
            AgentEvalScenario(id="healthy", turns=("ok",), enable_robot_tools=False),
        ]
        with TemporaryDirectory() as temp_dir:
            summary = run_evaluation(
                model="test-model",
                provider="test-provider",
                prompt_profile_id="test_profile",
                prompt_profile_path="prompts/test.yaml",
                scenarios=scenarios,
                runs=1,
                output_dir=Path(temp_dir),
                session_factory=session_factory,
                preflight_loader=fake_preflight,
            )
            records = [
                json.loads(line)
                for line in (Path(temp_dir) / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(summary["error_count"], 1)
        self.assertIn("model unavailable", records[0]["error"])
        self.assertEqual(sessions[0].prompts, ["fail"])
        self.assertEqual(sessions[1].prompts, ["ok"])


if __name__ == "__main__":
    unittest.main()
