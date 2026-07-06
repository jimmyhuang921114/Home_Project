from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from robot_object_retrieval.ports import ChatToolDefinition


@dataclass(frozen=True)
class ToolDispatchResult:
    model_output: str
    debug_output: str


ToolHandler = Callable[[dict[str, Any]], str | ToolDispatchResult]


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]

    def definition(self) -> ChatToolDefinition:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolSpec:
    schema: ToolSchema
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.schema.name

    def definition(self) -> ChatToolDefinition:
        return self.schema.definition()


AgentTool = ToolSpec


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec]) -> None:
        self._tools_by_name: dict[str, ToolSpec] = {}
        for tool in tools:
            if not tool.name:
                raise ValueError("Tool schema is missing name")
            if tool.name in self._tools_by_name:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools_by_name[tool.name] = tool

    def tool_definitions(self) -> list[ChatToolDefinition]:
        return [tool.definition() for tool in self._tools_by_name.values()]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools_by_name

    def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return self.dispatch_with_debug(tool_name, arguments).model_output

    def dispatch_with_debug(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolDispatchResult:
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            output = json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
            return ToolDispatchResult(model_output=output, debug_output=output)
        result = tool.handler(arguments)
        if isinstance(result, ToolDispatchResult):
            return result
        return ToolDispatchResult(model_output=result, debug_output=result)
