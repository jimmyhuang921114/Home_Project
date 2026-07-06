from __future__ import annotations

from pathlib import Path

import yaml

from robot_object_retrieval.application.agent_instructions import AgentPromptProfile


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROMPT_PROFILE_PATH = PROJECT_ROOT / "prompts" / "semantic_map_agent_v1.yaml"


def load_prompt_profile(path: Path = DEFAULT_PROMPT_PROFILE_PATH) -> AgentPromptProfile:
    resolved_path = path.resolve()
    try:
        payload = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read prompt profile: {resolved_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML prompt profile: {resolved_path}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Prompt profile must be a YAML object")
    system = payload.get("system")
    if not isinstance(system, dict):
        raise ValueError("Prompt profile system must be a YAML object")

    return AgentPromptProfile(
        profile_id=_required_text(payload, "profile_id"),
        source_path=str(resolved_path),
        base_assistant=_required_text(system, "base_assistant"),
        search_strategy=_required_text(system, "search_strategy"),
        robot_planning=_required_text(system, "robot_planning"),
        response_style=_required_text(system, "response_style"),
    )


def _required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Prompt profile field must be a non-empty string: {key}")
    return value.strip()
