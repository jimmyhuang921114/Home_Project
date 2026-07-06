from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.infrastructure.chat_models import (
    OllamaNativeChatModel,
    OpenAICompatibleChatModel,
    get_chat_model,
)


class ChatModelTests(unittest.TestCase):
    def test_openai_compatible_request_does_not_send_think_or_keep_reasoning(self) -> None:
        captured_payloads = []

        def fake_post_json(*, url, payload, api_key=None):
            captured_payloads.append(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning": "should be stripped",
                        }
                    }
                ]
            }

        model = OpenAICompatibleChatModel(
            chat_completions_url="http://localhost:11434/v1/chat/completions",
            api_key="ollama",
        )

        with patch(
            "robot_object_retrieval.infrastructure.chat_models._post_json",
            side_effect=fake_post_json,
        ):
            response = model.create_chat_completion(
                model="gemma4:e4b",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertNotIn("think", captured_payloads[0])
        message = response["choices"][0]["message"]
        self.assertEqual(message, {"role": "assistant", "content": "answer"})

    def test_ollama_native_request_sends_think_and_normalizes_thinking(self) -> None:
        captured_payloads = []

        def fake_post_json(*, url, payload, api_key=None):
            captured_payloads.append(payload)
            return {
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "thinking": "visible thinking",
                }
            }

        model = OllamaNativeChatModel(chat_url="http://localhost:11434/api/chat")

        with patch(
            "robot_object_retrieval.infrastructure.chat_models._post_json",
            side_effect=fake_post_json,
        ):
            response = model.create_chat_completion(
                model="gemma4:e4b",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertIs(captured_payloads[0]["think"], True)
        message = response["choices"][0]["message"]
        self.assertEqual(message["content"], "answer")
        self.assertEqual(message["reasoning"], "visible thinking")

    def test_get_chat_model_selects_provider(self) -> None:
        self.assertIsInstance(
            get_chat_model(
                provider="openai-compatible",
                chat_url="http://example.test/v1/chat/completions",
            ),
            OpenAICompatibleChatModel,
        )
        self.assertIsInstance(
            get_chat_model(
                provider="ollama-native",
                chat_url="http://localhost:11434/api/chat",
            ),
            OllamaNativeChatModel,
        )


if __name__ == "__main__":
    unittest.main()
