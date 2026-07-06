from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_instructions import AgentInstructionBuilder
from robot_object_retrieval.application.agent_service import (
    AgentSession,
    call_tool,
    make_tool_definitions,
    normalize_tool_calls,
    run_agent,
)
from robot_object_retrieval.infrastructure.prompt_profiles import load_prompt_profile
from robot_object_retrieval.models import (
    SemanticMapRegion,
    SemanticMapObjectCandidate,
    SemanticMapSearchResult,
)


def empty_search(query: str, limit: int, filters=None) -> SemanticMapSearchResult:
    return SemanticMapSearchResult(frame_id="map", candidates=(), snapshot_loaded=True)


def chair_search(query: str, limit: int, filters=None) -> SemanticMapSearchResult:
    return SemanticMapSearchResult(
        frame_id="map",
        candidates=(
            SemanticMapObjectCandidate(
                source_id="chair_5",
                frame_id="map",
                class_name="chair",
                x=1.0,
                y=2.0,
                z=3.0,
                confidence=0.8,
                similarity=0.9,
            ),
        ),
        snapshot_loaded=True,
    )


def weak_tablet_search(query: str, limit: int, filters=None) -> SemanticMapSearchResult:
    return SemanticMapSearchResult(
        frame_id="map",
        candidates=(
            SemanticMapObjectCandidate(
                source_id="tablet_9",
                frame_id="map",
                class_name="tablet",
                x=4.3,
                y=3.35,
                z=0.0,
                confidence=0.9,
                similarity=0.5,
            ),
        ),
        snapshot_loaded=True,
    )


def book_and_table_search(query: str, limit: int, filters=None) -> SemanticMapSearchResult:
    candidates_by_query = {
        "book": (
            SemanticMapObjectCandidate(
                source_id="book_14",
                frame_id="map",
                class_name="book",
                x=1.0,
                y=2.0,
                z=0.0,
                confidence=0.9,
                similarity=0.95,
            ),
        ),
        "table": (
            SemanticMapObjectCandidate(
                source_id="table_10",
                frame_id="map",
                class_name="table",
                x=3.0,
                y=4.0,
                z=0.0,
                confidence=0.9,
                similarity=0.95,
            ),
        ),
    }
    return SemanticMapSearchResult(
        frame_id="map",
        candidates=candidates_by_query.get(query, ()),
        snapshot_loaded=True,
    )


def make_candidate(source_id: str) -> SemanticMapObjectCandidate:
    return SemanticMapObjectCandidate(
        source_id=source_id,
        frame_id="map",
        class_name="chair",
        x=1.0,
        y=2.0,
        z=3.0,
        confidence=0.8,
        similarity=0.9,
    )


PROMPT_PROFILE = load_prompt_profile()


class FakeChatModel:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.requests = []

    def create_chat_completion(self, *, model, messages, tools=None, stream=False):
        self.requests.append(
            {
                "model": model,
                "messages": list(messages),
                "tools": tools,
                "stream": stream,
            }
        )
        return {"choices": [{"message": {"role": "assistant", "content": self.contents.pop(0)}}]}


class ToolCallingChatModel:
    def __init__(self, *, arguments=None) -> None:
        self.arguments = arguments if arguments is not None else {"query": "chair"}
        self.requests = []

    def create_chat_completion(self, *, model, messages, tools=None, stream=False):
        self.requests.append({"messages": list(messages), "tools": tools})
        if len(self.requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_semantic_map_object",
                                        "arguments": self.arguments,
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "找到椅子"}}]}


class AgentServiceTests(unittest.TestCase):
    def test_make_tool_definitions_keeps_only_semantic_map_tool(self) -> None:
        names = [tool["function"]["name"] for tool in make_tool_definitions()]
        self.assertEqual(names, ["search_semantic_map_object"])

    def test_make_tool_definitions_can_include_robot_tools(self) -> None:
        tools = make_tool_definitions(enable_robot_tools=True)
        names = [tool["function"]["name"] for tool in tools]
        self.assertEqual(names, ["search_semantic_map_object", "move_platform", "use_vla"])

    def test_use_vla_tool_definition_requires_action_enum(self) -> None:
        tools = make_tool_definitions(enable_robot_tools=True)
        use_vla = next(tool for tool in tools if tool["function"]["name"] == "use_vla")
        parameters = use_vla["function"]["parameters"]

        self.assertEqual(parameters["required"], ["action", "instruction"])
        self.assertEqual(
            parameters["properties"]["action"]["enum"],
            ["pickup_to_platform", "place_from_platform"],
        )
        self.assertIn("object_on_platform=true", use_vla["function"]["description"])

    def test_agent_session_keeps_history_between_turns(self) -> None:
        chat_model = FakeChatModel(["第一輪回答", "第二輪回答"])
        session = AgentSession(
            model="test-model",
            chat_model=chat_model,
            semantic_map_search=empty_search,
            prompt_profile=PROMPT_PROFILE,
        )

        first = session.send("幫我找椅子")
        second = session.send("剛剛那個在哪裡")

        self.assertEqual(first.answer, "第一輪回答")
        self.assertEqual(second.answer, "第二輪回答")
        self.assertEqual(
            [message["role"] for message in chat_model.requests[1]["messages"][-3:]],
            ["user", "assistant", "user"],
        )

    def test_agent_session_presearches_only_first_turn_and_injects_compact_context(self) -> None:
        queries = []

        def search(query: str, limit: int) -> SemanticMapSearchResult:
            queries.append((query, limit))
            return SemanticMapSearchResult(
                frame_id="map",
                candidates=tuple(make_candidate(f"chair_{index}") for index in range(5)),
                snapshot_loaded=True,
            )

        chat_model = FakeChatModel(["第一輪回答", "第二輪回答"])
        session = AgentSession(
            model="test-model",
            chat_model=chat_model,
            semantic_map_search=search,
            prompt_profile=PROMPT_PROFILE,
        )

        session.send("幫我找椅子")
        session.send("可以")

        self.assertEqual(queries, [("幫我找椅子", 3)])
        retrieved_contexts = [
            message["content"]
            for message in chat_model.requests[1]["messages"]
            if message["role"] == "system"
            and message["content"].startswith("[System Retrieved Context]")
        ]
        self.assertEqual(len(retrieved_contexts), 1)
        self.assertIn("object_id=chair_0 class=chair", retrieved_contexts[0])
        self.assertIn("object_id=chair_2 class=chair", retrieved_contexts[0])
        self.assertNotIn("object_id=chair_3 class=chair", retrieved_contexts[0])
        self.assertNotIn("confidence", retrieved_contexts[0])
        self.assertNotIn("similarity", retrieved_contexts[0])

    def test_agent_session_presearch_hides_low_confidence_candidates(self) -> None:
        chat_model = FakeChatModel(["查不到合適結果"])
        session = AgentSession(
            model="test-model",
            chat_model=chat_model,
            semantic_map_search=weak_tablet_search,
            prompt_profile=PROMPT_PROFILE,
        )

        session.send("找書")

        retrieved_contexts = [
            message["content"]
            for message in chat_model.requests[0]["messages"]
            if message["role"] == "system"
            and message["content"].startswith("[System Retrieved Context]")
        ]
        self.assertEqual(len(retrieved_contexts), 1)
        self.assertIn("沒有可用的預搜尋候選", retrieved_contexts[0])
        self.assertIn("可信度不足", retrieved_contexts[0])
        self.assertNotIn("tablet_9", retrieved_contexts[0])

    def test_agent_session_injects_available_region_catalog(self) -> None:
        chat_model = FakeChatModel(["找到"])
        region = SemanticMapRegion(
            region_id="lobby",
            frame_id="map",
            name="入口區",
            aliases=("入口", "門口"),
            geometry_type="aabb",
            min_x=0.0,
            max_x=2.0,
            min_y=0.0,
            max_y=3.0,
        )
        session = AgentSession(
            model="test-model",
            chat_model=chat_model,
            semantic_map_search=empty_search,
            semantic_map_regions=lambda: (region,),
            prompt_profile=PROMPT_PROFILE,
        )

        session.send("找入口區的椅子")

        retrieved_contexts = [
            message["content"]
            for message in chat_model.requests[0]["messages"]
            if message["role"] == "system"
            and message["content"].startswith("[System Retrieved Context]")
        ]
        self.assertEqual(len(retrieved_contexts), 1)
        self.assertIn("[Available Regions]", retrieved_contexts[0])
        self.assertIn("id=lobby name=入口區 aliases=入口, 門口", retrieved_contexts[0])
        self.assertNotIn("min_x", retrieved_contexts[0])

    def test_trace_keeps_presearch_and_tool_debug_evidence(self) -> None:
        chat_model = ToolCallingChatModel()
        with TemporaryDirectory() as temp_dir:
            session = AgentSession(
                model="test-model",
                chat_model=chat_model,
                semantic_map_search=chair_search,
                prompt_profile=PROMPT_PROFILE,
                debug_dir=Path(temp_dir),
            )

            result = session.send("找椅子")
            trace = json.loads(result.trace_path.read_text(encoding="utf-8"))

        self.assertEqual(trace["prompt_profile"]["profile_id"], "semantic_map_agent_v1")
        self.assertEqual(trace["presearch"]["results"][0]["similarity"], 0.9)
        tool_result = trace["steps"][0]["tool_results"][0]
        self.assertNotIn("similarity", tool_result["result"]["results"][0])
        self.assertEqual(tool_result["debug_result"]["results"][0]["similarity"], 0.9)

    def test_run_agent_remains_single_turn(self) -> None:
        chat_model = FakeChatModel(["第一次", "第二次"])
        first, _ = run_agent(
            model="test-model",
            user_input="第一輪",
            chat_model=chat_model,
            semantic_map_search=empty_search,
            prompt_profile=PROMPT_PROFILE,
        )
        second, _ = run_agent(
            model="test-model",
            user_input="第二輪",
            chat_model=chat_model,
            semantic_map_search=empty_search,
            prompt_profile=PROMPT_PROFILE,
        )
        self.assertEqual((first, second), ("第一次", "第二次"))

    def test_agent_session_emits_tool_events_and_context(self) -> None:
        events = []
        chat_model = ToolCallingChatModel()
        session = AgentSession(
            model="test-model",
            chat_model=chat_model,
            semantic_map_search=chair_search,
            prompt_profile=PROMPT_PROFILE,
        )

        result = session.send("找椅子", on_event=events.append)

        self.assertEqual(result.answer, "找到椅子")
        self.assertEqual(
            [event["type"] for event in events],
            ["user_message", "tool_call", "tool_result", "assistant_message"],
        )
        payload = events[2]["result"]
        self.assertEqual(payload["results"][0]["id"], "chair_5")
        self.assertEqual(payload["results"][0]["position"], {"x": 1.0, "y": 2.0, "z": 3.0})
        context = [
            message["content"]
            for message in chat_model.requests[1]["messages"]
            if message["role"] == "system" and message["content"].startswith("[Context]")
        ]
        self.assertEqual(len(context), 1)
        self.assertIn("id=chair_5 class=chair", context[0])
        self.assertNotIn("similarity", context[0])
        self.assertNotIn("confidence", context[0])
        self.assertEqual(result.tool_results[0]["debug_result"]["results"][0]["similarity"], 0.9)

    def test_instruction_builder_summarizes_robot_next_required_action(self) -> None:
        history = [
            {
                "role": "tool",
                "name": "use_vla",
                "content": json.dumps(
                    {
                        "success": True,
                        "task_complete": False,
                        "next_required_tool": "move_platform",
                        "next_required_action": "move_to_destination",
                        "state": {
                            "current_x": 1.0,
                            "current_y": 2.0,
                            "carried_object": "蘋果",
                            "object_on_platform": True,
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        ]

        messages = AgentInstructionBuilder(
            prompt_profile=PROMPT_PROFILE,
            enable_robot_tools=True,
        ).build_messages(history)
        context = [
            message["content"]
            for message in messages
            if message["role"] == "system" and message["content"].startswith("[Context]")
        ]

        self.assertEqual(len(context), 1)
        self.assertIn("task_complete=False", context[0])
        self.assertIn("next_required_tool=move_platform", context[0])
        self.assertIn("next_required_action=move_to_destination", context[0])

    def test_agent_session_reports_invalid_tool_argument_json(self) -> None:
        events = []

        def fail_search(query: str, limit: int) -> SemanticMapSearchResult:
            raise AssertionError("search should not run for invalid arguments")

        session = AgentSession(
            model="test-model",
            chat_model=ToolCallingChatModel(arguments='{"query":'),
            semantic_map_search=fail_search,
            prompt_profile=PROMPT_PROFILE,
        )
        result = session.send("找椅子", on_event=events.append)

        self.assertEqual(result.answer, "找到椅子")
        self.assertIn("Invalid tool arguments JSON", result.tool_results[0]["result"]["error"])

    def test_agent_session_dispatches_enabled_robot_tool(self) -> None:
        class MoveToolChatModel:
            def __init__(self) -> None:
                self.calls = 0

            def create_chat_completion(self, *, model, messages, tools=None, stream=False):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "search_semantic_map_object",
                                                "arguments": {"query": "chair"},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                if self.calls == 2:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_2",
                                            "type": "function",
                                            "function": {
                                                "name": "move_platform",
                                                "arguments": {"x": 1.0, "y": 2.0},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                return {"choices": [{"message": {"role": "assistant", "content": "已移動"}}]}

        session = AgentSession(
            model="test-model",
            chat_model=MoveToolChatModel(),
            semantic_map_search=chair_search,
            prompt_profile=PROMPT_PROFILE,
            enable_robot_tools=True,
        )
        result = session.send("移動")
        self.assertEqual(result.answer, "已移動")
        self.assertEqual(result.tool_results[-1]["result"]["state"]["current_x"], 1.0)

    def test_agent_session_allows_transport_chain_then_final_answer(self) -> None:
        class TransportChainChatModel:
            def __init__(self) -> None:
                self.calls = 0
                self.tool_calls = [
                    ("search_semantic_map_object", {"query": "book"}),
                    ("search_semantic_map_object", {"query": "table"}),
                    ("move_platform", {"x": 1.0, "y": 2.0}),
                    (
                        "use_vla",
                        {
                            "action": "pickup_to_platform",
                            "instruction": "把書拿起來並放到 AMR 暫存平台",
                        },
                    ),
                    ("move_platform", {"x": 3.0, "y": 4.0}),
                    (
                        "use_vla",
                        {
                            "action": "place_from_platform",
                            "instruction": "從 AMR 暫存平台拿起書並放到桌上",
                        },
                    ),
                ]

            def create_chat_completion(self, *, model, messages, tools=None, stream=False):
                self.calls += 1
                if self.calls <= len(self.tool_calls):
                    tool_name, arguments = self.tool_calls[self.calls - 1]
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": f"call_{self.calls}",
                                            "type": "function",
                                            "function": {
                                                "name": tool_name,
                                                "arguments": arguments,
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                return {"choices": [{"message": {"role": "assistant", "content": "搬運完成"}}]}

        session = AgentSession(
            model="test-model",
            chat_model=TransportChainChatModel(),
            semantic_map_search=book_and_table_search,
            prompt_profile=PROMPT_PROFILE,
            enable_robot_tools=True,
        )

        result = session.send("把書放到桌上")

        self.assertEqual(result.answer, "搬運完成")
        self.assertEqual(len(result.tool_calls), 6)
        self.assertTrue(result.tool_results[-1]["result"]["task_complete"])

    def test_agent_session_blocks_robot_move_until_source_position_is_grounded(self) -> None:
        class PrematureMoveChatModel:
            def __init__(self) -> None:
                self.calls = 0

            def create_chat_completion(self, *, model, messages, tools=None, stream=False):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "search_semantic_map_object",
                                                "arguments": {"query": "book"},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                if self.calls == 2:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_2",
                                            "type": "function",
                                            "function": {
                                                "name": "move_platform",
                                                "arguments": {"x": 4.0, "y": 7.0},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "我需要先移到書本附近，不能直接移到目的地。",
                            }
                        }
                    ]
                }

        session = AgentSession(
            model="test-model",
            chat_model=PrematureMoveChatModel(),
            semantic_map_search=chair_search,
            prompt_profile=PROMPT_PROFILE,
            enable_robot_tools=True,
        )

        result = session.send("把一本書移到 x4 y7")

        self.assertIn("不能直接移到目的地", result.answer)
        self.assertEqual(result.tool_results[-1]["result"]["error"], "platform_not_at_source")

    def test_agent_session_reprompts_when_model_claims_done_before_place(self) -> None:
        class PrematureCompleteChatModel:
            def __init__(self) -> None:
                self.calls = 0

            def create_chat_completion(self, *, model, messages, tools=None, stream=False):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "search_semantic_map_object",
                                                "arguments": {"query": "book"},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                if self.calls == 2:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_2",
                                            "type": "function",
                                            "function": {
                                                "name": "move_platform",
                                                "arguments": {"x": 1.0, "y": 2.0, "label": "到 book_14 附近"},
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                if self.calls == 3:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_3",
                                            "type": "function",
                                            "function": {
                                                "name": "use_vla",
                                                "arguments": {
                                                    "action": "pickup_to_platform",
                                                    "instruction": "把 book_14 拿起來並放到 AMR 暫存平台",
                                                },
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                if self.calls == 4:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "搬運已完成。",
                                }
                            }
                    ]
                }
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "搬運尚未完成，物體還在平台上。",
                            }
                        }
                    ]
                }

        def book_search(query: str, limit: int, filters=None) -> SemanticMapSearchResult:
            return SemanticMapSearchResult(
                frame_id="map",
                candidates=(
                    SemanticMapObjectCandidate(
                        source_id="book_14",
                        frame_id="map",
                        class_name="book",
                        x=1.0,
                        y=2.0,
                        z=0.0,
                        confidence=0.9,
                        similarity=0.95,
                    ),
                ),
                snapshot_loaded=True,
            )

        session = AgentSession(
            model="test-model",
            chat_model=PrematureCompleteChatModel(),
            semantic_map_search=book_search,
            prompt_profile=PROMPT_PROFILE,
            enable_robot_tools=True,
        )

        result = session.send("把一本書搬到目的地")

        self.assertEqual(result.answer, "搬運尚未完成，物體還在平台上。")
        self.assertTrue(result.tool_results[-1]["result"]["state"]["object_on_platform"])

    def test_normalize_tool_calls_parses_argument_strings(self) -> None:
        normalized = normalize_tool_calls(
            [{"function": {"name": "search_semantic_map_object", "arguments": '{"query":"椅子"}'}}]
        )
        self.assertEqual(normalized[0]["function"]["arguments"], {"query": "椅子"})

    def test_call_tool_unknown_tool_returns_stable_error(self) -> None:
        payload = json.loads(
            call_tool("missing_tool", {}, semantic_map_search=empty_search)
        )
        self.assertEqual(payload, {"error": "Unknown tool: missing_tool"})

    def test_instruction_builder_has_no_legacy_guidance(self) -> None:
        messages = AgentInstructionBuilder(prompt_profile=PROMPT_PROFILE).build_messages([])
        text = "\n".join(message["content"] for message in messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("search_semantic_map_object", text)
        self.assertNotIn("semantic_search_object", text)
        self.assertNotIn("Mutation Policy", text)

    def test_robot_instructions_cover_source_destination_and_any_candidate(self) -> None:
        text = "\n".join(
            message["content"]
            for message in AgentInstructionBuilder(
                prompt_profile=PROMPT_PROFILE,
                enable_robot_tools=True,
            ).build_messages([])
        )
        self.assertIn("來源物體與目的地", text)
        self.assertIn("每個角色只能使用該角色專屬 query", text)
        self.assertIn("隨便一個", text)
        self.assertIn("room metadata", text)
        self.assertIn("最後一次 use_vla 成功", text)


if __name__ == "__main__":
    unittest.main()
