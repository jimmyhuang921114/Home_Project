from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib import error


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_service import run_agent
from robot_object_retrieval.config import get_agent_config
from robot_object_retrieval.infrastructure.chat_models import ChatEndpointError
from robot_object_retrieval.infrastructure.chat_models import get_chat_model
from robot_object_retrieval.infrastructure.catalog_runtime import get_catalog_runtime
from robot_object_retrieval.infrastructure.prompt_profiles import (
    DEFAULT_PROMPT_PROFILE_PATH,
    load_prompt_profile,
)


def parse_args() -> argparse.Namespace:
    config = get_agent_config()
    parser = argparse.ArgumentParser(description="Minimal object-retrieval agent")
    parser.add_argument(
        "--model",
        default=config.model_name,
        help="OpenAI-compatible chat model name, e.g. gemma4:e4b",
    )
    parser.add_argument(
        "--provider",
        choices=["openai-compatible", "ollama-native"],
        default="openai-compatible",
        help="Chat provider. Use ollama-native to enable Ollama thinking output in supported clients.",
    )
    parser.add_argument(
        "--chat-url",
        default=None,
        help=(
            "Override chat endpoint URL. Defaults to .env for openai-compatible "
            "and http://localhost:11434/api/chat for ollama-native."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable request/response trace output",
    )
    parser.add_argument(
        "--debug-dir",
        default=".agent_debug",
        help="Directory for saving request/response traces when --debug is enabled",
    )
    parser.add_argument(
        "--enable-robot-tools",
        action="store_true",
        help="Enable fake move_platform/use_vla tools for planning smoke tests",
    )
    parser.add_argument(
        "--prompt-profile",
        type=Path,
        default=DEFAULT_PROMPT_PROFILE_PATH,
        help="YAML prompt profile path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    debug_dir = Path(args.debug_dir).resolve() if args.debug else None
    catalog_runtime = get_catalog_runtime()
    chat_model = get_chat_model(provider=args.provider, chat_url=args.chat_url)
    prompt_profile = load_prompt_profile(args.prompt_profile)

    print(f"Model: {args.model}")
    print(f"Provider: {args.provider}")
    print("Object catalog: semantic_map")
    print(f"Prompt profile: {prompt_profile.profile_id}")
    if args.enable_robot_tools:
        print("Robot tools: fake move_platform/use_vla enabled")
    print("Type 'exit' to quit.")

    while True:
        try:
            user_input = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            return 0

        try:
            answer, trace_path = run_agent(
                model=args.model,
                user_input=user_input,
                debug_dir=debug_dir,
                chat_model=chat_model,
                semantic_map_search=catalog_runtime.semantic_map_search,
                semantic_map_regions=catalog_runtime.semantic_map_regions,
                prompt_profile=prompt_profile,
                enable_robot_tools=args.enable_robot_tools,
            )
        except ChatEndpointError as exc:
            print(f"Chat endpoint error: {exc}")
            print("Check the endpoint URL, model name, and whether tool calling is supported.")
            continue
        except error.URLError as exc:
            print(f"Connection error: {exc}")
            print("Check whether the configured chat endpoint is running and the model has been pulled.")
            continue
        except Exception as exc:
            print(f"Agent error: {exc}")
            continue

        print(f"\nAgent> {answer}")
        if trace_path is not None:
            print(f"Trace> {trace_path}")


if __name__ == "__main__":
    raise SystemExit(main())
