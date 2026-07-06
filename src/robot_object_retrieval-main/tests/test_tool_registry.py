from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.tool_registry import ToolRegistry, ToolSchema, ToolSpec


class ToolRegistryTests(unittest.TestCase):
    def test_dispatches_registered_fake_tool(self) -> None:
        registry = ToolRegistry(
            [
                ToolSpec(
                    schema=ToolSchema(
                        name="fake_tool",
                        description="Fake test tool",
                        parameters={"type": "object", "properties": {}},
                    ),
                    handler=lambda arguments: json.dumps(
                        {"ok": True, "value": arguments["value"]},
                        ensure_ascii=False,
                    ),
                )
            ]
        )

        payload = json.loads(registry.dispatch("fake_tool", {"value": "done"}))

        self.assertTrue(registry.has_tool("fake_tool"))
        self.assertEqual(payload, {"ok": True, "value": "done"})
        self.assertEqual(registry.tool_definitions()[0]["function"]["name"], "fake_tool")

    def test_tool_schema_builds_openai_compatible_definition(self) -> None:
        schema = ToolSchema(
            name="fake_tool",
            description="Fake test tool",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        )

        self.assertEqual(
            schema.definition(),
            {
                "type": "function",
                "function": {
                    "name": "fake_tool",
                    "description": "Fake test tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                },
            },
        )

    def test_unknown_tool_returns_stable_error(self) -> None:
        registry = ToolRegistry([])

        payload = json.loads(registry.dispatch("missing_tool", {}))

        self.assertEqual(payload, {"error": "Unknown tool: missing_tool"})


if __name__ == "__main__":
    unittest.main()
