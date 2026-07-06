from __future__ import annotations

from pathlib import Path

from robot_object_retrieval.application.agent_service import call_tool as _call_tool
from robot_object_retrieval.application.agent_service import run_agent as _run_agent
from robot_object_retrieval.infrastructure.chat_models import get_default_chat_model
from robot_object_retrieval.infrastructure.catalog_runtime import get_catalog_runtime
from robot_object_retrieval.infrastructure.prompt_profiles import load_prompt_profile


def call_tool(tool_name: str, arguments: dict[str, object]) -> str:
    catalog_runtime = get_catalog_runtime()
    return _call_tool(
        tool_name,
        arguments,
        semantic_map_search=catalog_runtime.semantic_map_search,
    )


def run_agent(
    model: str,
    user_input: str,
    debug_dir: Path | None = None,
) -> tuple[str, Path | None]:
    catalog_runtime = get_catalog_runtime()
    return _run_agent(
        model=model,
        user_input=user_input,
        debug_dir=debug_dir,
        chat_model=get_default_chat_model(),
        semantic_map_search=catalog_runtime.semantic_map_search,
        semantic_map_regions=catalog_runtime.semantic_map_regions,
        prompt_profile=load_prompt_profile(),
    )
