from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from robot_object_retrieval.application.tool_registry import ToolSchema, ToolSpec
from robot_object_retrieval.ports import ChatToolDefinition


@dataclass
class RobotMockState:
    current_x: float | None = None
    current_y: float | None = None
    carried_object: str | None = None
    object_on_platform: bool = False
    phase: str = "idle"
    selected_source_object_id: str | None = None
    selected_destination_kind: str | None = None
    selected_destination_label: str | None = None
    pickup_x: float | None = None
    pickup_y: float | None = None
    last_move_label: str | None = None
    last_error: str | None = None


def build_robot_mock_tool_specs(state: RobotMockState) -> list[ToolSpec]:
    return [
        ToolSpec(
            schema=_move_platform_schema(),
            handler=lambda arguments: _call_move_platform(arguments, state),
        ),
        ToolSpec(
            schema=_use_vla_schema(),
            handler=lambda arguments: _call_use_vla(arguments, state),
        ),
    ]


def build_robot_mock_tools(state: RobotMockState) -> list[ToolSpec]:
    return build_robot_mock_tool_specs(state)


def make_robot_mock_tool_definitions() -> list[ChatToolDefinition]:
    return [_move_platform_schema().definition(), _use_vla_schema().definition()]


def _move_platform_schema() -> ToolSchema:
    return ToolSchema(
        name="move_platform",
        description=(
            "假的 AMR 移動平台工具，用來測試任務規劃。"
            "輸入目標 x/y 座標，工具會回報平台已移動到該座標。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "平台要移動到的目標 x 座標",
                },
                "y": {
                    "type": "number",
                    "description": "平台要移動到的目標 y 座標",
                },
                "label": {
                    "type": "string",
                    "description": "可選，高層位置說明，例如 蘋果附近、床邊",
                },
            },
            "required": ["x", "y"],
        },
    )


def _use_vla_schema() -> ToolSchema:
    return ToolSchema(
        name="use_vla",
        description=(
            "假的 VLA 工具，用自然語言 prompt 測試操作規劃。"
            "每次呼叫只能執行一個動作。"
            "action=pickup_to_platform 只代表把來源物體放到 AMR 暫存平台，任務尚未完成。"
            "action=place_from_platform 代表從 AMR 暫存平台取下物體並放到目的地；"
            "只有這一步成功後才可以宣稱搬運完成。"
            "若上一個 use_vla 回傳 object_on_platform=true，"
            "下一個完成搬運的 VLA 動作應是 place_from_platform。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["pickup_to_platform", "place_from_platform"],
                    "description": (
                        "VLA 動作類型。pickup_to_platform=把來源物體拿起並放到 AMR 暫存平台；"
                        "place_from_platform=從 AMR 暫存平台取下物體並放到目的地。"
                    ),
                },
                "instruction": {
                    "type": "string",
                    "description": (
                        "給 VLA 的高層操作指令，例如："
                        "把蘋果拿起來並放到 AMR 暫存平台；"
                        "從 AMR 暫存平台拿起蘋果並放到床上"
                    ),
                },
            },
            "required": ["action", "instruction"],
        },
    )


def _call_move_platform(arguments: dict[str, Any], state: RobotMockState) -> str:
    x, error = _required_float(arguments, "x")
    if error is not None:
        return _error(error)
    y, error = _required_float(arguments, "y")
    if error is not None:
        return _error(error)
    label = str(arguments.get("label", "")).strip() or None

    state.current_x = x
    state.current_y = y
    state.last_move_label = label
    state.last_error = None
    if state.object_on_platform:
        state.phase = "at_destination"
    elif state.selected_source_object_id:
        state.phase = "at_source"
    else:
        state.phase = "source_ready"
    return _json_state(
        {
            "action": "move_platform",
            "success": True,
            "target": {"x": x, "y": y, "label": label},
            "message": f"fake platform moved to x={x}, y={y}",
        },
        state,
    )


def _call_use_vla(arguments: dict[str, Any], state: RobotMockState) -> str:
    instruction = str(arguments.get("instruction", "")).strip()
    if not instruction:
        return _error("Missing instruction")

    action = str(arguments.get("action", "")).strip()
    object_name = _extract_object_name(instruction)
    task_complete: bool | None = None
    next_required_tool: str | None = None
    next_required_action: str | None = None
    message = "fake VLA instruction accepted"
    if action == "place_from_platform":
        if not state.object_on_platform:
            return _error(
                "platform_has_no_object",
                state=state,
                message="Cannot place from platform before pickup_to_platform succeeds.",
            )
        if state.pickup_x is not None and state.pickup_y is not None:
            same_x = state.current_x == state.pickup_x
            same_y = state.current_y == state.pickup_y
            if same_x and same_y:
                return _error(
                    "destination_not_reached",
                    state=state,
                    message="Move the platform to a destination before place_from_platform.",
                )
        state.object_on_platform = False
        state.last_error = None
        state.selected_destination_kind = "placed"
        task_complete = True
        state.phase = "placed"
        message = "place complete; object has been placed at destination"
    elif action == "pickup_to_platform":
        if state.current_x is None or state.current_y is None:
            return _error(
                "platform_not_at_source",
                state=state,
                message="Move the platform near the source object before pickup_to_platform.",
            )
        if state.object_on_platform:
            return _error(
                "platform_already_loaded",
                state=state,
                message="The AMR platform already has an object; place it before another pickup.",
            )
        state.object_on_platform = True
        state.pickup_x = state.current_x
        state.pickup_y = state.current_y
        state.carried_object = object_name or state.selected_source_object_id
        state.last_error = None
        state.phase = "picked"
        task_complete = False
        next_required_tool = "move_platform"
        next_required_action = "move_to_destination"
        message = "pickup complete; object is on AMR platform; transport is not complete"
    elif action:
        return _error(
            "invalid_action",
            state=state,
            message="action must be pickup_to_platform or place_from_platform",
        )
    elif _looks_like_place_from_platform(instruction):
        if not state.object_on_platform:
            return _error(
                "platform_has_no_object",
                state=state,
                message="Cannot place from platform before pickup_to_platform succeeds.",
            )
        state.object_on_platform = False
        state.last_error = None
        task_complete = True
        state.phase = "placed"
        message = "place complete; object has been placed at destination"
    elif _looks_like_put_on_platform(instruction):
        if state.current_x is None or state.current_y is None:
            return _error(
                "platform_not_at_source",
                state=state,
                message="Move the platform near the source object before pickup_to_platform.",
            )
        state.object_on_platform = True
        state.pickup_x = state.current_x
        state.pickup_y = state.current_y
        state.carried_object = object_name or state.selected_source_object_id
        state.last_error = None
        state.phase = "picked"
        task_complete = False
        next_required_tool = "move_platform"
        next_required_action = "move_to_destination"
        message = "pickup complete; object is on AMR platform; transport is not complete"

    return _json_state(
        {
            "action": "use_vla",
            "vla_action": action or None,
            "success": True,
            "task_complete": task_complete,
            "next_required_tool": next_required_tool,
            "next_required_action": next_required_action,
            "instruction": instruction,
            "message": message,
        },
        state,
    )


def _looks_like_put_on_platform(instruction: str) -> bool:
    has_pick = any(keyword in instruction for keyword in ("拿", "抓", "取", "夾", "撿"))
    has_platform = any(keyword in instruction for keyword in ("平台", "AMR", "暫存"))
    return has_pick and has_platform


def _looks_like_place_from_platform(instruction: str) -> bool:
    has_platform = any(keyword in instruction for keyword in ("平台", "AMR", "暫存"))
    has_place = any(keyword in instruction for keyword in ("放到", "放在", "放置", "放下"))
    has_source = any(keyword in instruction for keyword in ("從", "取下"))
    return has_platform and has_place and has_source


def _extract_object_name(instruction: str) -> str | None:
    patterns = [
        r"把(.+?)(?:拿|抓|取|夾|撿)",
        r"(?:拿起|拿取|抓取|夾起|撿起)(.+?)(?:並|到|放|$)",
        r"從.*?(?:拿起|拿取|取下)(.+?)(?:並|到|放|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction)
        if match:
            value = match.group(1).strip(" 。.!?，,、")
            if value:
                return value
    return None


def _json_state(payload: dict[str, Any], state: RobotMockState) -> str:
    payload.setdefault("error", None)
    payload["state"] = {
        "current_x": state.current_x,
        "current_y": state.current_y,
        "carried_object": state.carried_object,
        "object_on_platform": state.object_on_platform,
        "phase": state.phase,
        "selected_source_object_id": state.selected_source_object_id,
        "selected_destination_kind": state.selected_destination_kind,
        "selected_destination_label": state.selected_destination_label,
        "pickup_x": state.pickup_x,
        "pickup_y": state.pickup_y,
        "last_move_label": state.last_move_label,
        "last_error": state.last_error,
    }
    return json.dumps(payload, ensure_ascii=False)


def _required_float(arguments: dict[str, Any], field_name: str) -> tuple[float, str | None]:
    if field_name not in arguments:
        return 0.0, f"Missing {field_name}"
    try:
        return float(arguments[field_name]), None
    except (TypeError, ValueError):
        return 0.0, f"{field_name} must be a number"


def _error(error: str, *, state: RobotMockState | None = None, message: str | None = None) -> str:
    if state is None:
        return json.dumps({"success": False, "error": error, "message": message or error}, ensure_ascii=False)
    state.last_error = error
    payload = {
        "success": False,
        "error": error,
        "message": message or error,
        "task_complete": False,
        "next_required_tool": None,
        "next_required_action": None,
    }
    return _json_state(payload, state)
