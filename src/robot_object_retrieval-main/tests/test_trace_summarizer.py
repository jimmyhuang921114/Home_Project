from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / ".codex"
    / "skills"
    / "robot-object-eval"
    / "scripts"
    / "summarize_agent_trace.py"
)


def load_summarizer_module():
    spec = importlib.util.spec_from_file_location("summarize_agent_trace", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load summarizer: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TraceSummarizerTests(unittest.TestCase):
    def test_summarizes_search_results_without_debug_payload(self) -> None:
        module = load_summarizer_module()
        trace = {
            "model": "test-model",
            "prompt_profile": {"profile_id": "semantic_map_agent_v2"},
            "user_input": "幫我找一本書",
            "final_answer": "找到書",
            "steps": [
                {
                    "step": 1,
                    "request_messages": [{"role": "system", "content": "large prompt"}],
                    "raw_response": {"debug": "large response"},
                    "assistant_message": {"content": ""},
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_semantic_map_object",
                                "arguments": {"query": "book", "limit": 5},
                            }
                        }
                    ],
                    "tool_results": [
                        {
                            "tool_name": "search_semantic_map_object",
                            "result": {
                                "query": "book",
                                "limit": 5,
                                "results": [
                                    {
                                        "id": "book_1",
                                        "class": "book",
                                        "position": {"x": 1},
                                        "confidence": 0.8,
                                    },
                                    {"id": "book_2", "class": "book"},
                                    {"id": "table_1", "class": "table"},
                                ],
                            },
                            "debug_result": {
                                "results": [{"id": "book_1", "similarity": 0.99}]
                            },
                        }
                    ],
                }
            ],
        }

        summary = module.summarize_trace_payload(
            trace,
            trace_path="trace.json",
            top_results=2,
        )

        self.assertEqual(summary["prompt_profile"]["profile_id"], "semantic_map_agent_v2")
        step = summary["steps"][0]
        self.assertEqual(
            step["tool_calls"],
            [{"name": "search_semantic_map_object", "arguments": {"query": "book", "limit": 5}}],
        )
        result = step["tool_results"][0]
        self.assertEqual(result["result_count"], 3)
        self.assertEqual(
            result["top_results"],
            [{"id": "book_1", "class": "book"}, {"id": "book_2", "class": "book"}],
        )
        self.assert_no_forbidden_keys(summary)

    def test_preserves_robot_state_and_next_action(self) -> None:
        module = load_summarizer_module()
        trace = {
            "model": "test-model",
            "prompt_profile": {"profile_id": "semantic_map_agent_v2"},
            "user_input": "把書放到桌上",
            "final_answer": "完成",
            "steps": [
                {
                    "step": 4,
                    "assistant_message": {"content": ""},
                    "tool_calls": [
                        {
                            "function": {
                                "name": "use_vla",
                                "arguments": {
                                    "action": "pickup_to_platform",
                                    "instruction": "把書放到 AMR 暫存平台",
                                },
                            }
                        }
                    ],
                    "tool_results": [
                        {
                            "tool_name": "use_vla",
                            "result": {
                                "success": True,
                                "vla_action": "pickup_to_platform",
                                "task_complete": False,
                                "next_required_tool": "move_platform",
                                "next_required_action": "move_to_destination",
                                "state": {
                                    "current_x": 1.0,
                                    "current_y": 2.0,
                                    "carried_object": "書",
                                    "object_on_platform": True,
                                },
                            },
                        }
                    ],
                },
                {
                    "step": 5,
                    "assistant_message": {"content": "搬運完成"},
                    "tool_calls": [],
                    "tool_results": [],
                },
            ],
        }

        summary = module.summarize_trace_payload(trace, trace_path="trace.json")

        result = summary["steps"][0]["tool_results"][0]
        self.assertEqual(result["tool_name"], "use_vla")
        self.assertFalse(result["task_complete"])
        self.assertEqual(result["next_required_tool"], "move_platform")
        self.assertEqual(result["next_required_action"], "move_to_destination")
        self.assertTrue(result["state"]["object_on_platform"])
        self.assertEqual(summary["steps"][1]["assistant_text"], "搬運完成")

    def assert_no_forbidden_keys(self, payload) -> None:
        forbidden = {
            "request_messages",
            "raw_response",
            "debug_result",
            "confidence",
            "similarity",
            "position",
        }
        if isinstance(payload, dict):
            for key, value in payload.items():
                self.assertNotIn(key, forbidden)
                self.assert_no_forbidden_keys(value)
        elif isinstance(payload, list):
            for item in payload:
                self.assert_no_forbidden_keys(item)


if __name__ == "__main__":
    unittest.main()
