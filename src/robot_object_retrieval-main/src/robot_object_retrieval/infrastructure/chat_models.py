from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from robot_object_retrieval.config import get_agent_config
from robot_object_retrieval.ports import (
    ChatCompletionResponse,
    ChatMessage,
    ChatModel,
    ChatToolDefinition,
)


OLLAMA_NATIVE_CHAT_URL = "http://localhost:11434/api/chat"


@dataclass(frozen=True)
class OpenAICompatibleChatModel(ChatModel):
    chat_completions_url: str
    api_key: str = "ollama"

    def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[ChatToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatCompletionResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _normalize_messages_for_chat_completions(messages),
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        response = _post_json(
            url=self.chat_completions_url,
            payload=payload,
            api_key=self.api_key,
        )
        return _normalize_openai_compatible_response(response)


@dataclass(frozen=True)
class OllamaNativeChatModel(ChatModel):
    chat_url: str = OLLAMA_NATIVE_CHAT_URL

    def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[ChatToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatCompletionResponse:
        return _normalize_legacy_ollama_response(
            self._create_chat(
                model=model,
                messages=messages,
                tools=tools or [],
                stream=stream,
            )
        )

    def _create_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[ChatToolDefinition],
        stream: bool,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": _convert_messages_for_legacy_ollama(messages),
            "tools": tools,
            "stream": stream,
            "think": True,
        }
        return _post_json(url=self.chat_url, payload=payload)


@dataclass(frozen=True)
class ChatEndpointError(RuntimeError):
    status_code: int
    url: str
    response_body: str

    def __str__(self) -> str:
        return (
            f"Chat endpoint returned HTTP {self.status_code} for {self.url}. "
            f"Response body: {self.response_body}"
        )


def get_default_chat_model() -> ChatModel:
    config = get_agent_config()
    return OpenAICompatibleChatModel(
        chat_completions_url=config.chat_completions_url,
        api_key=config.api_key,
    )


def get_chat_model(
    *,
    provider: str = "openai-compatible",
    chat_url: str | None = None,
) -> ChatModel:
    config = get_agent_config()
    if provider == "openai-compatible":
        return OpenAICompatibleChatModel(
            chat_completions_url=chat_url or config.chat_completions_url,
            api_key=config.api_key,
        )
    if provider == "ollama-native":
        return OllamaNativeChatModel(chat_url=chat_url or OLLAMA_NATIVE_CHAT_URL)
    raise ValueError(f"Unknown chat provider: {provider}")


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise ChatEndpointError(
            status_code=exc.code,
            url=url,
            response_body=response_body,
        ) from exc
    return json.loads(body)


def _convert_messages_for_legacy_ollama(
    messages: list[ChatMessage],
) -> list[dict[str, Any]]:
    converted_messages: list[dict[str, Any]] = []
    for message in messages:
        converted_message: dict[str, Any] = {
            "role": message["role"],
            "content": message.get("content", ""),
        }

        if message["role"] == "tool":
            converted_message["tool_name"] = message.get("name", "")

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            converted_message["tool_calls"] = [
                {
                    "function": {
                        "name": tool_call.get("function", {}).get("name", ""),
                        "arguments": _decode_function_arguments(
                            tool_call.get("function", {}).get("arguments")
                        ),
                    }
                }
                for tool_call in tool_calls
            ]

        converted_messages.append(converted_message)

    return converted_messages


def _normalize_openai_compatible_response(
    response: dict[str, Any],
) -> ChatCompletionResponse:
    choices = response.get("choices") or []
    normalized_choices: list[dict[str, Any]] = []
    for choice in choices:
        message = choice.get("message") or {}
        normalized_message: dict[str, Any] = {
            "role": message.get("role", "assistant"),
            "content": message.get("content", ""),
        }
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            normalized_message["tool_calls"] = tool_calls
        normalized_choice = dict(choice)
        normalized_choice["message"] = normalized_message
        normalized_choices.append(normalized_choice)

    normalized_response = dict(response)
    normalized_response["choices"] = normalized_choices
    return normalized_response


def _normalize_messages_for_chat_completions(
    messages: list[ChatMessage],
) -> list[dict[str, Any]]:
    normalized_messages: list[dict[str, Any]] = []

    for message in messages:
        normalized_message: dict[str, Any] = {
            "role": message["role"],
            "content": message.get("content", ""),
        }

        if message["role"] == "tool" and "tool_call_id" in message:
            normalized_message["tool_call_id"] = message["tool_call_id"]

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            normalized_message["tool_calls"] = [
                {
                    "id": str(tool_call.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": tool_call.get("function", {}).get("name", ""),
                        "arguments": _encode_function_arguments(
                            tool_call.get("function", {}).get("arguments")
                        ),
                    },
                }
                for tool_call in tool_calls
            ]

        normalized_messages.append(normalized_message)

    return normalized_messages


def _normalize_legacy_ollama_response(response: dict[str, Any]) -> ChatCompletionResponse:
    message = response.get("message") or {}
    normalized_message: dict[str, Any] = {
        "role": message.get("role", "assistant"),
        "content": message.get("content", ""),
    }
    thinking = message.get("thinking") or message.get("reasoning")
    if thinking:
        normalized_message["reasoning"] = thinking

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        normalized_message["tool_calls"] = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": tool_call.get("function", {}).get("name", ""),
                    "arguments": json.dumps(
                        tool_call.get("function", {}).get("arguments") or {},
                        ensure_ascii=False,
                    ),
                },
            }
            for index, tool_call in enumerate(tool_calls, start=1)
        ]

    return {
        "choices": [
            {
                "message": normalized_message,
            }
        ]
    }


def _decode_function_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        return json.loads(arguments) if arguments.strip() else {}
    if isinstance(arguments, dict):
        return arguments
    return {}


def _encode_function_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    if isinstance(arguments, dict):
        return json.dumps(arguments, ensure_ascii=False)
    return "{}"
