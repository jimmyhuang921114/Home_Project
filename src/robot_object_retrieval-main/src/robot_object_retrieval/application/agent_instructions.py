from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from robot_object_retrieval.ports import ChatMessage


@dataclass(frozen=True)
class AgentPromptProfile:
    profile_id: str
    source_path: str
    base_assistant: str
    search_strategy: str
    robot_planning: str
    response_style: str


@dataclass(frozen=True)
class AgentInstructionBuilder:
    prompt_profile: AgentPromptProfile
    enable_robot_tools: bool = False
    recent_tool_result_limit: int = 2
    recent_search_candidate_limit: int = 3

    def build_messages(
        self,
        history: list[ChatMessage],
        *,
        retrieved_context: str | None = None,
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = [self._system_message(self._build_static_prompt())]
        if retrieved_context is not None:
            messages.append(self._system_message(retrieved_context))
        context_message = self._build_context_message(history)
        if context_message is not None:
            messages.append(context_message)
        messages.extend(history)
        return messages

    def _build_static_prompt(self) -> str:
        sections = [
            self.prompt_profile.base_assistant,
            self.prompt_profile.search_strategy,
        ]
        if self.enable_robot_tools:
            sections.append(self.prompt_profile.robot_planning)
        sections.append(self.prompt_profile.response_style)
        return "\n\n".join(sections)

    def _build_context_message(self, history: list[ChatMessage]) -> ChatMessage | None:
        summaries = self._summarize_recent_tool_results(history)
        if not summaries:
            return None
        return self._system_message("\n".join(["[Context]", "最近工具結果：", *summaries]))

    def _summarize_recent_tool_results(self, history: list[ChatMessage]) -> list[str]:
        tool_messages = [message for message in history if message.get("role") == "tool"]
        summaries: list[str] = []
        for message in tool_messages[-self.recent_tool_result_limit :]:
            summaries.extend(self._summarize_tool_message(message))
        return summaries

    def _summarize_tool_message(self, message: ChatMessage) -> list[str]:
        tool_name = str(message.get("name", "tool"))
        content = message.get("content") or ""
        if not isinstance(content, str):
            return [f"- {tool_name}: 無法解析結果"]

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return [f"- {tool_name}: 無法解析結果"]

        if tool_name == "search_semantic_map_object":
            return self._summarize_semantic_map_search_payload(payload)
        if tool_name in {"move_platform", "use_vla"}:
            return [self._summarize_robot_payload(tool_name, payload)]
        return [f"- {tool_name}: 無法識別結果"]

    def _summarize_semantic_map_search_payload(self, payload: dict[str, Any]) -> list[str]:
        if payload.get("error"):
            return [f"- search_semantic_map_object: error={payload.get('error')}"]

        query = payload.get("query", "")
        limit = payload.get("limit", "")
        frame_id = payload.get("frame_id", "")
        rows = [
            f"- search_semantic_map_object: query={query} limit={limit} frame_id={frame_id} "
            f"filter_status={payload.get('filter_status')} match_status={payload.get('match_status')}"
        ]
        if payload.get("message"):
            rows.append(f"  message={payload.get('message')}")
        resolved_location = payload.get("resolved_location")
        if isinstance(resolved_location, dict):
            rows.append(
                "  "
                f"resolved_location id={resolved_location.get('id')} "
                f"name={resolved_location.get('name')}"
            )
        near_object = payload.get("near_object")
        if isinstance(near_object, dict):
            rows.append(
                "  "
                f"near_object id={near_object.get('id')} class={near_object.get('class')}"
            )
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            rows.append("  無候選")
            return rows

        for index, result in enumerate(results[: self.recent_search_candidate_limit], start=1):
            if not isinstance(result, dict):
                continue
            position = result.get("position")
            position_text = json.dumps(position, ensure_ascii=False, separators=(",", ":"))
            rows.append(
                "  "
                f"{index}. id={result.get('id')} class={result.get('class')} "
                f"position={position_text}"
            )
        if len(results) > self.recent_search_candidate_limit:
            rows.append(f"  ... 其餘 {len(results) - self.recent_search_candidate_limit} 筆省略")
        return rows

    def _summarize_robot_payload(self, tool_name: str, payload: dict[str, Any]) -> str:
        state = payload.get("state")
        if not isinstance(state, dict):
            return f"- {tool_name}: success={payload.get('success')}"
        return (
            f"- {tool_name}: success={payload.get('success')} "
            f"error={payload.get('error')} "
            f"task_complete={payload.get('task_complete')} "
            f"next_required_tool={payload.get('next_required_tool')} "
            f"next_required_action={payload.get('next_required_action')} "
            f"phase={state.get('phase')} "
            f"current_x={state.get('current_x')} "
            f"current_y={state.get('current_y')} "
            f"carried_object={state.get('carried_object')} "
            f"object_on_platform={state.get('object_on_platform')}"
        )

    @staticmethod
    def _system_message(content: str) -> ChatMessage:
        return {"role": "system", "content": content}
