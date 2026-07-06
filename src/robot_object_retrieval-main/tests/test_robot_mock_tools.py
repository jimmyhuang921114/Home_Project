from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.tools.robot_mock import (
    RobotMockState,
    build_robot_mock_tools,
)


class RobotMockToolTests(unittest.TestCase):
    def test_move_platform_updates_current_xy(self) -> None:
        state = RobotMockState()
        registry = {tool.name: tool.handler for tool in build_robot_mock_tools(state)}

        payload = json.loads(registry["move_platform"]({"x": 1.5, "y": -2.0, "label": "床邊"}))

        self.assertTrue(payload["success"])
        self.assertEqual(payload["target"], {"x": 1.5, "y": -2.0, "label": "床邊"})
        self.assertEqual(payload["state"]["current_x"], 1.5)
        self.assertEqual(payload["state"]["current_y"], -2.0)
        self.assertEqual(state.current_x, 1.5)
        self.assertEqual(state.current_y, -2.0)

    def test_use_vla_updates_platform_state_from_action(self) -> None:
        state = RobotMockState(
            current_x=1.5,
            current_y=-2.0,
            selected_source_object_id="蘋果",
            phase="at_source",
        )
        registry = {tool.name: tool.handler for tool in build_robot_mock_tools(state)}

        pick_payload = json.loads(
            registry["use_vla"](
                {
                    "action": "pickup_to_platform",
                    "instruction": "把蘋果拿起來並放到 AMR 暫存平台",
                }
            )
        )
        self.assertEqual(pick_payload["vla_action"], "pickup_to_platform")
        self.assertFalse(pick_payload["task_complete"])
        self.assertEqual(pick_payload["next_required_tool"], "move_platform")
        self.assertEqual(pick_payload["next_required_action"], "move_to_destination")
        self.assertTrue(pick_payload["state"]["object_on_platform"])
        self.assertEqual(pick_payload["state"]["carried_object"], "蘋果")
        self.assertEqual(pick_payload["state"]["phase"], "picked")
        registry["move_platform"]({"x": 2.0, "y": -1.0, "label": "床邊"})
        place_payload = json.loads(
            registry["use_vla"](
                {
                    "action": "place_from_platform",
                    "instruction": "從 AMR 暫存平台拿起蘋果並放到床上",
                }
            )
        )
        self.assertEqual(place_payload["vla_action"], "place_from_platform")
        self.assertTrue(place_payload["task_complete"])
        self.assertIsNone(place_payload["next_required_tool"])
        self.assertIsNone(place_payload["next_required_action"])
        self.assertFalse(place_payload["state"]["object_on_platform"])
        self.assertEqual(place_payload["state"]["carried_object"], "蘋果")
        self.assertEqual(place_payload["state"]["phase"], "placed")

    def test_use_vla_keeps_instruction_only_fallback(self) -> None:
        state = RobotMockState(
            current_x=1.5,
            current_y=-2.0,
            selected_source_object_id="蘋果",
            phase="at_source",
        )
        registry = {tool.name: tool.handler for tool in build_robot_mock_tools(state)}

        pick_payload = json.loads(
            registry["use_vla"](
                {"instruction": "把蘋果拿起來並放到 AMR 暫存平台"}
            )
        )
        self.assertIsNone(pick_payload["vla_action"])
        self.assertFalse(pick_payload["task_complete"])
        self.assertEqual(pick_payload["next_required_tool"], "move_platform")
        self.assertEqual(pick_payload["next_required_action"], "move_to_destination")
        self.assertTrue(pick_payload["state"]["object_on_platform"])
        self.assertEqual(pick_payload["state"]["carried_object"], "蘋果")
        registry["move_platform"]({"x": 2.0, "y": -1.0, "label": "床邊"})
        place_payload = json.loads(
            registry["use_vla"](
                {"instruction": "從 AMR 暫存平台拿起蘋果並放到床上"}
            )
        )
        self.assertIsNone(place_payload["vla_action"])
        self.assertTrue(place_payload["task_complete"])
        self.assertIsNone(place_payload["next_required_action"])
        self.assertFalse(place_payload["state"]["object_on_platform"])
        self.assertEqual(place_payload["state"]["carried_object"], "蘋果")

    def test_use_vla_rejects_pickup_without_source_position(self) -> None:
        state = RobotMockState(selected_source_object_id="book_14")
        registry = {tool.name: tool.handler for tool in build_robot_mock_tools(state)}

        payload = json.loads(
            registry["use_vla"](
                {
                    "action": "pickup_to_platform",
                    "instruction": "把書拿起來並放到 AMR 暫存平台",
                }
            )
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "platform_not_at_source")
        self.assertEqual(payload["state"]["last_error"], "platform_not_at_source")

    def test_use_vla_rejects_place_before_destination_move(self) -> None:
        state = RobotMockState(
            current_x=1.5,
            current_y=-2.0,
            selected_source_object_id="book_14",
            phase="at_source",
        )
        registry = {tool.name: tool.handler for tool in build_robot_mock_tools(state)}
        registry["use_vla"](
            {
                "action": "pickup_to_platform",
                "instruction": "把書拿起來並放到 AMR 暫存平台",
            }
        )

        payload = json.loads(
            registry["use_vla"](
                {
                    "action": "place_from_platform",
                    "instruction": "從 AMR 暫存平台拿起書並放到床上",
                }
            )
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "destination_not_reached")
        self.assertEqual(payload["state"]["phase"], "picked")


if __name__ == "__main__":
    unittest.main()
