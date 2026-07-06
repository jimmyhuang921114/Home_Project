from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.infrastructure.prompt_profiles import load_prompt_profile


class PromptProfileTests(unittest.TestCase):
    def test_loads_default_yaml_profile(self) -> None:
        profile = load_prompt_profile()

        self.assertEqual(profile.profile_id, "semantic_map_agent_v1")
        self.assertIn("search_semantic_map_object", profile.search_strategy)
        self.assertEqual(
            Path(profile.source_path).parts[-2:],
            ("prompts", "semantic_map_agent_v1.yaml"),
        )

    def test_loads_v2_yaml_profile(self) -> None:
        path = Path(__file__).resolve().parents[1] / "prompts" / "semantic_map_agent_v2.yaml"

        profile = load_prompt_profile(path)

        self.assertEqual(profile.profile_id, "semantic_map_agent_v2")
        self.assertIn('use_vla(action="pickup_to_platform")', profile.robot_planning)
        self.assertIn("task_complete=true", profile.robot_planning)

    def test_rejects_missing_required_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.yaml"
            path.write_text(
                "profile_id: bad\nsystem:\n  base_assistant: ok\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "search_strategy"):
                load_prompt_profile(path)

    def test_loads_custom_yaml_profile(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "custom.yaml"
            path.write_text(
                "profile_id: custom_profile\n"
                "system:\n"
                "  base_assistant: base\n"
                "  search_strategy: search\n"
                "  robot_planning: robot\n"
                "  response_style: style\n",
                encoding="utf-8",
            )

            profile = load_prompt_profile(path)

        self.assertEqual(profile.profile_id, "custom_profile")
        self.assertEqual(profile.search_strategy, "search")


if __name__ == "__main__":
    unittest.main()
