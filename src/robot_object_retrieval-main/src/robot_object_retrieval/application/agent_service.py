from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable

from robot_object_retrieval.application.agent_instructions import AgentInstructionBuilder
from robot_object_retrieval.application.agent_instructions import AgentPromptProfile
from robot_object_retrieval.application.tool_registry import ToolDispatchResult, ToolRegistry
from robot_object_retrieval.application.tools.robot_mock import RobotMockState
from robot_object_retrieval.application.tools.robot_mock import build_robot_mock_tool_specs
from robot_object_retrieval.application.tools.robot_mock import make_robot_mock_tool_definitions
from robot_object_retrieval.application.tools.semantic_map import SemanticMapSearch
from robot_object_retrieval.application.tools.semantic_map import build_semantic_map_tool_specs
from robot_object_retrieval.application.tools.semantic_map import make_semantic_map_tool_definitions
from robot_object_retrieval.application.tools.semantic_map import model_visible_candidates
from robot_object_retrieval.models import SemanticMapRegion
from robot_object_retrieval.ports import ChatMessage, ChatModel, ChatToolDefinition


AgentEventHandler = Callable[[dict[str, Any]], None]
SemanticMapRegionsLoader = Callable[[], tuple[SemanticMapRegion, ...]]
ARGUMENT_PARSE_ERROR_KEY = "_argument_parse_error"
RAW_ARGUMENTS_KEY = "_raw_arguments"
PRESEARCH_LIMIT = 3
MAX_AGENT_STEPS = 8


def make_tool_definitions(*, enable_robot_tools: bool = False) -> list[ChatToolDefinition]:
    definitions = make_semantic_map_tool_definitions()
    if enable_robot_tools:
        definitions.extend(make_robot_mock_tool_definitions())
    return definitions


def call_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    semantic_map_search: SemanticMapSearch,
    enable_robot_tools: bool = False,
    robot_state: RobotMockState | None = None,
) -> str:
    registry = build_tool_registry(
        semantic_map_search=semantic_map_search,
        enable_robot_tools=enable_robot_tools,
        robot_state=robot_state,
    )
    return registry.dispatch(tool_name, arguments)


def build_tool_registry(
    *,
    semantic_map_search: SemanticMapSearch,
    enable_robot_tools: bool = False,
    robot_state: RobotMockState | None = None,
) -> ToolRegistry:
    tools = build_semantic_map_tool_specs(candidate_search=semantic_map_search)
    if enable_robot_tools:
        tools.extend(build_robot_mock_tool_specs(robot_state or RobotMockState()))
    return ToolRegistry(tools)


def write_debug_trace(debug_dir: Path, trace: dict[str, Any]) -> Path:
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    trace_path = debug_dir / f"trace_{timestamp}.json"
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return trace_path


@dataclass(frozen=True)
class AgentTurnResult:
    answer: str
    trace_path: Path | None
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]


@dataclass
class AgentSession:
    model: str
    chat_model: ChatModel
    semantic_map_search: SemanticMapSearch
    prompt_profile: AgentPromptProfile
    debug_dir: Path | None = None
    enable_robot_tools: bool = False
    semantic_map_regions: SemanticMapRegionsLoader | None = None

    def __post_init__(self) -> None:
        self.robot_state = RobotMockState() if self.enable_robot_tools else None
        self.tool_registry = build_tool_registry(
            semantic_map_search=self.semantic_map_search,
            enable_robot_tools=self.enable_robot_tools,
            robot_state=self.robot_state,
        )
        self.tools = self.tool_registry.tool_definitions()
        self.instruction_builder = AgentInstructionBuilder(
            prompt_profile=self.prompt_profile,
            enable_robot_tools=self.enable_robot_tools,
        )
        self.messages: list[ChatMessage] = []
        self.presearch_context: str | None = None
        self.presearch_evidence: dict[str, Any] | None = None

    def send(
        self,
        user_input: str,
        *,
        on_event: AgentEventHandler | None = None,
    ) -> AgentTurnResult:
        if self.presearch_evidence is None:
            self.presearch_evidence, self.presearch_context = self._run_presearch(user_input)
        self.messages.append({"role": "user", "content": user_input})
        if on_event is not None:
            on_event({"type": "user_message", "content": user_input})
        trace: dict[str, Any] = {
            "model": self.model,
            "user_input": user_input,
            "tools": self.tools,
            "prompt_profile": {
                "profile_id": self.prompt_profile.profile_id,
                "source_path": self.prompt_profile.source_path,
            },
            "presearch": self.presearch_evidence,
            "steps": [],
        }

        all_tool_calls: list[dict[str, Any]] = []
        all_tool_results: list[dict[str, Any]] = []
        for step_index in range(1, MAX_AGENT_STEPS + 1):
            request_messages = self.instruction_builder.build_messages(
                self.messages,
                retrieved_context=self.presearch_context,
            )
            step_trace: dict[str, Any] = {
                "step": step_index,
                "request_messages": list(request_messages),
            }
            response = self.chat_model.create_chat_completion(
                model=self.model,
                messages=request_messages,
                tools=self.tools,
                stream=False,
            )
            assistant_message = extract_assistant_message(response)
            self.messages.append(assistant_message)
            step_trace["raw_response"] = response
            step_trace["assistant_message"] = assistant_message
            reasoning = str(assistant_message.get("reasoning", "")).strip()
            if reasoning and on_event is not None:
                on_event({"type": "reasoning", "content": reasoning, "step": step_index})

            tool_calls = assistant_message.get("tool_calls") or []
            step_trace["tool_calls"] = tool_calls
            all_tool_calls.extend(tool_calls)
            if not tool_calls:
                answer = str(assistant_message.get("content", "")).strip()
                if self._should_continue_after_assistant(answer):
                    self.messages.append(
                        {
                            "role": "system",
                            "content": self._robot_guard_message(answer),
                        }
                    )
                    trace["steps"].append(step_trace)
                    continue
                if on_event is not None:
                    on_event({"type": "assistant_message", "content": answer})
                trace["steps"].append(step_trace)
                trace["final_answer"] = answer
                trace_path = write_debug_trace(self.debug_dir, trace) if self.debug_dir else None
                return AgentTurnResult(
                    answer=answer,
                    trace_path=trace_path,
                    tool_calls=all_tool_calls,
                    tool_results=all_tool_results,
                )

            tool_results: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                function = tool_call["function"]
                tool_name = function["name"]
                arguments = function.get("arguments") or {}
                if on_event is not None:
                    on_event(
                        {
                            "type": "tool_call",
                            "tool_call_id": tool_call["id"],
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "step": step_index,
                        }
                    )
                if ARGUMENT_PARSE_ERROR_KEY in arguments:
                    result = json.dumps(
                        {"error": arguments[ARGUMENT_PARSE_ERROR_KEY]},
                        ensure_ascii=False,
                    )
                    dispatch_result = ToolDispatchResult(
                        model_output=result,
                        debug_output=result,
                    )
                else:
                    dispatch_result = self._dispatch_tool_with_guard(tool_name, arguments)
                result = dispatch_result.model_output
                tool_result = {
                    "tool_call_id": tool_call["id"],
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": json.loads(result),
                    "debug_result": json.loads(dispatch_result.debug_output),
                }
                tool_results.append(tool_result)
                all_tool_results.append(tool_result)
                if on_event is not None:
                    on_event({"type": "tool_result", **tool_result, "step": step_index})
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_name,
                        "content": result,
                    }
                )

            step_trace["tool_results"] = tool_results
            trace["steps"].append(step_trace)

        answer = "找不到合適的物體"
        if on_event is not None:
            on_event({"type": "assistant_message", "content": answer})
        trace["final_answer"] = answer
        trace_path = write_debug_trace(self.debug_dir, trace) if self.debug_dir else None
        return AgentTurnResult(
            answer=answer,
            trace_path=trace_path,
            tool_calls=all_tool_calls,
            tool_results=all_tool_results,
        )

    def _run_presearch(self, user_input: str) -> tuple[dict[str, Any], str]:
        try:
            result = self.semantic_map_search(user_input, PRESEARCH_LIMIT)
        except Exception as exc:
            evidence = {
                "query": user_input,
                "limit": PRESEARCH_LIMIT,
                "error": f"{type(exc).__name__}: {exc}",
            }
            return evidence, _build_presearch_context([], available_regions=self._load_regions())

        evidence = {
            "query": user_input,
            "limit": PRESEARCH_LIMIT,
            "frame_id": result.frame_id,
            "snapshot_loaded": result.snapshot_loaded,
            "results": [_debug_candidate_payload(candidate) for candidate in result.candidates],
        }
        if not result.snapshot_loaded:
            evidence["error"] = "semantic map snapshot is not loaded"
            return evidence, _build_presearch_context([], available_regions=self._load_regions())
        visible_candidates = model_visible_candidates(result.candidates)
        available_regions = self._load_regions()
        evidence["available_regions"] = [_region_context_payload(region) for region in available_regions]
        return evidence, _build_presearch_context(
            [
                {"id": candidate.source_id, "class": candidate.class_name}
                for candidate in visible_candidates[:PRESEARCH_LIMIT]
            ],
            low_confidence=bool(result.candidates and not visible_candidates),
            available_regions=available_regions,
        )

    def _load_regions(self) -> tuple[SemanticMapRegion, ...]:
        if self.semantic_map_regions is None:
            return ()
        try:
            return self.semantic_map_regions()
        except Exception:
            return ()

    def _dispatch_tool_with_guard(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolDispatchResult:
        guard_result = self._guard_robot_tool_call(tool_name, arguments)
        if guard_result is not None:
            return guard_result
        return self.tool_registry.dispatch_with_debug(tool_name, arguments)

    def _guard_robot_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolDispatchResult | None:
        if not self.enable_robot_tools or self.robot_state is None:
            return None
        if tool_name not in {"move_platform", "use_vla"}:
            return None

        search_events = self._successful_search_events()
        source_event = self._source_search_event(search_events)
        destination_event = self._destination_search_event(search_events)
        if destination_event is not None and self._search_has_multiple_candidates(destination_event):
            return self._robot_guard_error(
                "destination_not_confirmed",
                "目的地仍有多個候選，請先向使用者確認目的地。",
            )

        if tool_name == "move_platform" and not self.robot_state.object_on_platform:
            if source_event is None:
                return self._robot_guard_error(
                    "source_not_confirmed",
                    "尚未確認來源物體，請先使用搜尋工具找到合理來源候選。",
                )
            matched_candidate = self._match_candidate_by_position(source_event, arguments)
            if matched_candidate is None:
                return self._robot_guard_error(
                    "platform_not_at_source",
                    "第一次移動平台時必須先移到來源物體附近。",
                )
            self.robot_state.selected_source_object_id = matched_candidate["id"]
            self.robot_state.phase = "at_source"
            return None

        if tool_name == "use_vla":
            action = str(arguments.get("action", "")).strip()
            if action == "pickup_to_platform" and not self.robot_state.selected_source_object_id:
                return self._robot_guard_error(
                    "source_not_confirmed",
                    "尚未選定來源物體，不可直接執行 pickup_to_platform。",
                )
        return None

    def _successful_search_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for message in self.messages:
            if message.get("role") != "tool" or message.get("name") != "search_semantic_map_object":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            if payload.get("error"):
                continue
            if payload.get("match_status") != "found":
                continue
            events.append(payload)
        return events

    def _source_search_event(self, search_events: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not search_events:
            return None
        source_query = str(search_events[0].get("query", "")).strip()
        source_event = search_events[0]
        for event in search_events:
            if str(event.get("query", "")).strip() != source_query:
                break
            source_event = event
        return source_event

    def _destination_search_event(self, search_events: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(search_events) < 2:
            return None
        source_query = str(search_events[0].get("query", "")).strip()
        for event in search_events[1:]:
            if str(event.get("query", "")).strip() != source_query:
                return event
        return None

    @staticmethod
    def _search_has_multiple_candidates(search_event: dict[str, Any]) -> bool:
        results = search_event.get("results")
        return isinstance(results, list) and len(results) > 1

    def _match_candidate_by_position(
        self,
        search_event: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            target_x = float(arguments.get("x"))
            target_y = float(arguments.get("y"))
        except (TypeError, ValueError):
            return None
        results = search_event.get("results")
        if not isinstance(results, list):
            return None
        for candidate in results:
            if not isinstance(candidate, dict):
                continue
            position = candidate.get("position")
            if not isinstance(position, dict):
                continue
            try:
                candidate_x = float(position.get("x"))
                candidate_y = float(position.get("y"))
            except (TypeError, ValueError):
                continue
            if abs(candidate_x - target_x) <= 0.25 and abs(candidate_y - target_y) <= 0.25:
                return {"id": str(candidate.get("id", ""))}
        return None

    def _should_continue_after_assistant(self, answer: str) -> bool:
        if not self.enable_robot_tools or self.robot_state is None:
            return False
        if not answer:
            return bool(self.robot_state.last_error or self.robot_state.object_on_platform)
        if self.robot_state.object_on_platform:
            return self._looks_like_completion_claim(answer)
        if self.robot_state.last_error:
            return self._looks_like_completion_claim(answer)
        return False

    def _robot_guard_message(self, answer: str) -> str:
        if self.robot_state is None:
            return "請根據最近工具結果繼續。"
        if self.robot_state.last_error:
            return (
                "最近一次 robot tool 失敗了。"
                f"error={self.robot_state.last_error}。"
                "請根據失敗原因改成搜尋、澄清，或修正下一次工具呼叫；不可假裝完成。"
            )
        if self.robot_state.object_on_platform:
            return (
                "搬運尚未完成。物體仍在 AMR 暫存平台上，"
                "必須先移動到目的地並成功執行 place_from_platform，才可以宣稱完成。"
            )
        return (
            "上一輪回答不足以完成任務。"
            f"{' 回答不可為空。' if not answer else ''}"
            "請依最近工具結果補上必要的搜尋、澄清或失敗說明。"
        )

    def _robot_guard_error(self, error: str, message: str) -> ToolDispatchResult:
        payload = {
            "success": False,
            "error": error,
            "message": message,
            "task_complete": False,
            "next_required_tool": "search_semantic_map_object",
            "next_required_action": "clarify_or_search",
            "state": {
                "current_x": self.robot_state.current_x if self.robot_state else None,
                "current_y": self.robot_state.current_y if self.robot_state else None,
                "carried_object": self.robot_state.carried_object if self.robot_state else None,
                "object_on_platform": self.robot_state.object_on_platform if self.robot_state else False,
                "phase": self.robot_state.phase if self.robot_state else "idle",
                "selected_source_object_id": self.robot_state.selected_source_object_id if self.robot_state else None,
                "selected_destination_kind": self.robot_state.selected_destination_kind if self.robot_state else None,
                "selected_destination_label": self.robot_state.selected_destination_label if self.robot_state else None,
                "pickup_x": self.robot_state.pickup_x if self.robot_state else None,
                "pickup_y": self.robot_state.pickup_y if self.robot_state else None,
                "last_move_label": self.robot_state.last_move_label if self.robot_state else None,
                "last_error": error,
            },
        }
        if self.robot_state is not None:
            self.robot_state.last_error = error
        output = json.dumps(payload, ensure_ascii=False)
        return ToolDispatchResult(model_output=output, debug_output=output)

    @staticmethod
    def _looks_like_completion_claim(answer: str) -> bool:
        completion_keywords = ("完成", "成功", "已經", "已完成", "done")
        incomplete_keywords = ("尚未", "還沒", "無法", "不能", "失敗", "需要", "請先")
        return any(keyword in answer for keyword in completion_keywords) and not any(
            keyword in answer for keyword in incomplete_keywords
        )
        try:
            return self.semantic_map_regions()
        except Exception:
            return ()


def run_agent(
    model: str,
    user_input: str,
    *,
    chat_model: ChatModel,
    semantic_map_search: SemanticMapSearch,
    prompt_profile: AgentPromptProfile,
    debug_dir: Path | None = None,
    enable_robot_tools: bool = False,
    semantic_map_regions: SemanticMapRegionsLoader | None = None,
) -> tuple[str, Path | None]:
    session = AgentSession(
        model=model,
        debug_dir=debug_dir,
        chat_model=chat_model,
        semantic_map_search=semantic_map_search,
        prompt_profile=prompt_profile,
        enable_robot_tools=enable_robot_tools,
        semantic_map_regions=semantic_map_regions,
    )
    result = session.send(user_input)
    return result.answer, result.trace_path


def _build_presearch_context(
    candidates: list[dict[str, str]],
    *,
    low_confidence: bool = False,
    available_regions: tuple[SemanticMapRegion, ...] = (),
) -> str:
    lines = [
        "[System Retrieved Context]",
        "以下是系統根據使用者第一輪指令預先搜尋出的候選。",
        "候選只用於協助理解意圖，不代表已確認符合需求。",
        "回答位置或執行動作前，仍須使用搜尋工具確認。",
    ]
    if not candidates:
        lines.extend(["", "- 沒有可用的預搜尋候選"])
        if low_confidence:
            lines.append("- 系統找到的向量近鄰可信度不足，不可當成已確認物體。")
    else:
        lines.append("")
        lines.extend(
            f"- object_id={candidate['id']} class={candidate['class']}"
            for candidate in candidates
        )
    lines.extend(_build_region_catalog_lines(available_regions))
    return "\n".join(lines)


def _build_region_catalog_lines(regions: tuple[SemanticMapRegion, ...]) -> list[str]:
    lines = ["", "[Available Regions]"]
    if not regions:
        lines.append("目前 semantic map 沒有 room/zone metadata；不可猜測房間或區域。")
        return lines
    lines.append("以下是 semantic map 已知區域。location 必須優先使用這些 id/name/aliases。")
    for region in regions:
        alias_text = ", ".join(region.aliases)
        line = f"- id={region.region_id} name={region.name}"
        if alias_text:
            line += f" aliases={alias_text}"
        lines.append(line)
    return lines


def _region_context_payload(region: SemanticMapRegion) -> dict[str, Any]:
    return {
        "id": region.region_id,
        "name": region.name,
        "aliases": list(region.aliases),
    }


def _debug_candidate_payload(candidate: Any) -> dict[str, Any]:
    return {
        "id": candidate.source_id,
        "class": candidate.class_name,
        "position": {
            "x": candidate.x,
            "y": candidate.y,
            "z": candidate.z,
        },
        "confidence": candidate.confidence,
        "similarity": candidate.similarity,
    }


def extract_assistant_message(response: dict[str, Any]) -> ChatMessage:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Chat completion response is missing choices.")

    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Chat completion response is missing the assistant message.")

    normalized_message: ChatMessage = {
        "role": str(message.get("role", "assistant")),
        "content": message.get("content") or "",
    }
    reasoning = message.get("reasoning") or message.get("thinking")
    if reasoning:
        normalized_message["reasoning"] = str(reasoning)
    tool_calls = normalize_tool_calls(message.get("tool_calls") or [])
    if tool_calls:
        normalized_message["tool_calls"] = tool_calls
    return normalized_message


def normalize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls, start=1):
        function = tool_call.get("function") or {}
        arguments = normalize_tool_arguments(function.get("arguments"))

        normalized.append(
            {
                "id": str(tool_call.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": str(function.get("name", "")),
                    "arguments": arguments,
                },
            }
        )
    return normalized


def normalize_tool_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        raw_arguments = arguments
        if not raw_arguments.strip():
            return {}
        try:
            parsed_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as error:
            return {
                ARGUMENT_PARSE_ERROR_KEY: f"Invalid tool arguments JSON: {error.msg}",
                RAW_ARGUMENTS_KEY: raw_arguments,
            }
        if isinstance(parsed_arguments, dict):
            return parsed_arguments
        return {
            ARGUMENT_PARSE_ERROR_KEY: "Tool arguments JSON must decode to an object.",
            RAW_ARGUMENTS_KEY: raw_arguments,
        }
    return {
        ARGUMENT_PARSE_ERROR_KEY: "Tool arguments must be a JSON object.",
        RAW_ARGUMENTS_KEY: str(arguments),
    }
