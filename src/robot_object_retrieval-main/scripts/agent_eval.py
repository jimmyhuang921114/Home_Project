from __future__ import annotations

import argparse
from functools import partial
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DEFAULT_CASES_PATH = PROJECT_ROOT / "benchmarks" / "semantic_map_agent_cases.jsonl"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_eval_service import (
    default_output_dir,
    load_scenarios,
    make_prompt_scenario,
    run_evaluation,
    select_scenarios,
)
from robot_object_retrieval.application.agent_service import AgentSession
from robot_object_retrieval.config import get_agent_config
from robot_object_retrieval.infrastructure.catalog_runtime import get_catalog_runtime
from robot_object_retrieval.infrastructure.chat_models import get_chat_model
from robot_object_retrieval.infrastructure.prompt_profiles import (
    DEFAULT_PROMPT_PROFILE_PATH,
    load_prompt_profile,
)
from robot_object_retrieval.infrastructure.db.semantic_map_repository import (
    get_default_semantic_map_vector_search_repository,
)


def build_parser() -> argparse.ArgumentParser:
    config = get_agent_config()
    parser = argparse.ArgumentParser(
        description="Run Codex-assisted semantic-map agent evaluation traces."
    )
    parser.add_argument("--model", default=config.model_name)
    parser.add_argument(
        "--provider",
        choices=["openai-compatible", "ollama-native"],
        default="openai-compatible",
    )
    parser.add_argument("--chat-url", default=None)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument("--prompt", default=None, help="Run one ad-hoc single-turn prompt.")
    parser.add_argument("--enable-robot-tools", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--prompt-profile",
        type=Path,
        default=DEFAULT_PROMPT_PROFILE_PATH,
        help="YAML prompt profile path",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.prompt is not None and args.case_id:
        print("ERROR: --prompt cannot be combined with --case-id", file=sys.stderr)
        return 2

    output_dir = (args.output_dir or default_output_dir(PROJECT_ROOT)).resolve()
    runtime = get_catalog_runtime()
    chat_model = get_chat_model(provider=args.provider, chat_url=args.chat_url)
    vector_repository = get_default_semantic_map_vector_search_repository()
    prompt_profile = load_prompt_profile(args.prompt_profile)

    def session_factory(enable_robot_tools: bool, traces_dir: Path) -> AgentSession:
        return AgentSession(
            model=args.model,
            chat_model=chat_model,
            semantic_map_search=runtime.semantic_map_search,
            semantic_map_regions=runtime.semantic_map_regions,
            prompt_profile=prompt_profile,
            debug_dir=traces_dir,
            enable_robot_tools=enable_robot_tools,
        )

    try:
        if args.prompt is not None:
            scenarios = [
                make_prompt_scenario(
                    args.prompt,
                    enable_robot_tools=args.enable_robot_tools,
                )
            ]
        else:
            scenarios = select_scenarios(load_scenarios(args.cases.resolve()), args.case_id)
        summary = run_evaluation(
            model=args.model,
            provider=args.provider,
            prompt_profile_id=prompt_profile.profile_id,
            prompt_profile_path=prompt_profile.source_path,
            scenarios=scenarios,
            runs=args.runs,
            output_dir=output_dir,
            session_factory=session_factory,
            preflight_loader=vector_repository.get_snapshot_preflight,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _print_json(summary)
    return 0


def _print_json(payload: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
