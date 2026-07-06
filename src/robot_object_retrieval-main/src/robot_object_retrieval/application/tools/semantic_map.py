from __future__ import annotations

import json
from typing import Any, Callable

from robot_object_retrieval.application.tool_registry import ToolDispatchResult, ToolSchema, ToolSpec
from robot_object_retrieval.models import (
    DEFAULT_NEAR_RADIUS_M,
    DEFAULT_OBJECT_SEARCH_LIMIT,
    MAX_OBJECT_SEARCH_LIMIT,
    SemanticMapSearchFilters,
    SemanticMapSearchResult,
)
from robot_object_retrieval.ports import ChatToolDefinition


SemanticMapSearch = Callable[..., SemanticMapSearchResult]
SEMANTIC_MAP_NOT_LOADED_ERROR = "semantic map snapshot is not loaded"
MIN_MODEL_VISIBLE_SEARCH_SIMILARITY = 0.60


def build_semantic_map_tool_specs(*, candidate_search: SemanticMapSearch) -> list[ToolSpec]:
    return [
        ToolSpec(
            schema=_search_semantic_map_schema(),
            handler=lambda arguments: _call_search_semantic_map(arguments, candidate_search),
        )
    ]


def build_semantic_map_tools(*, candidate_search: SemanticMapSearch) -> list[ToolSpec]:
    return build_semantic_map_tool_specs(candidate_search=candidate_search)


def make_semantic_map_tool_definitions() -> list[ChatToolDefinition]:
    return [_search_semantic_map_schema().definition()]


def _search_semantic_map_schema() -> ToolSchema:
    return ToolSchema(
        name="search_semantic_map_object",
        description=(
            "搜尋 semantic map 中的物體。"
            "query 只放核心物體詞、品牌詞或名詞，不要放完整句子。"
            "結果包含物體 id、class 與三維座標。"
            "location 只放使用者指定的已知房間或區域。"
            "near_object_id 只放先前工具結果中的物體 id。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要搜尋的物體詞，例如 chair、book、wall lamp",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_OBJECT_SEARCH_LIMIT,
                    "default": DEFAULT_OBJECT_SEARCH_LIMIT,
                    "description": (
                        "回傳候選數量。結果不夠好時可提高 limit 再搜尋，"
                        f"最多 {MAX_OBJECT_SEARCH_LIMIT} 筆。"
                    ),
                },
                "location": {
                    "type": "string",
                    "description": (
                        "可選。使用者指定的房間或區域，例如 入口區、lobby。"
                        "如果使用者沒有指定位置，不要填。"
                    ),
                },
                "near_object_id": {
                    "type": "string",
                    "description": (
                        "可選。已知物體 id，例如 table_10。"
                        "只接受先前搜尋結果中的 id，不接受自然語言描述。"
                    ),
                },
                "near_radius_m": {
                    "type": "number",
                    "minimum": 0.1,
                    "default": DEFAULT_NEAR_RADIUS_M,
                    "description": f"near_object_id 的 2D 搜尋半徑，預設 {DEFAULT_NEAR_RADIUS_M} 公尺。",
                },
            },
            "required": ["query"],
        },
    )


def _call_search_semantic_map(
    arguments: dict[str, Any],
    candidate_search: SemanticMapSearch,
) -> str | ToolDispatchResult:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return _error("Missing query")

    limit = _clamp_search_limit(arguments.get("limit"))
    filters = _parse_search_filters(arguments)
    result = candidate_search(query, limit, filters=filters)
    if not result.snapshot_loaded:
        return _error(SEMANTIC_MAP_NOT_LOADED_ERROR)

    model_payload = build_model_visible_search_payload(query, limit, result, filters)
    debug_payload = {
        "query": query,
        "limit": limit,
        "filters": _filters_payload(filters),
        "frame_id": result.frame_id,
        "filter_status": result.filter_status,
        "message": result.message,
        "resolved_location": _region_payload(result.resolved_location),
        "near_object": _model_candidate_payload(result.near_object) if result.near_object else None,
        "results": [_debug_candidate_payload(candidate) for candidate in result.candidates],
    }
    return ToolDispatchResult(
        model_output=json.dumps(model_payload, ensure_ascii=False),
        debug_output=json.dumps(debug_payload, ensure_ascii=False),
    )


def _debug_candidate_payload(candidate: Any) -> dict[str, Any]:
    return {
        "id": candidate.source_id,
        "class": candidate.class_name,
        "position": {
            "x": candidate.x,
            "y": candidate.y,
            "z": candidate.z,
        },
        "confidence": candidate.confidence,
        "similarity": candidate.similarity,
        "model_visible": is_model_visible_candidate(candidate),
    }


def build_model_visible_search_payload(
    query: str,
    limit: int,
    result: SemanticMapSearchResult,
    filters: SemanticMapSearchFilters | None = None,
) -> dict[str, Any]:
    filters = filters or SemanticMapSearchFilters()
    visible_candidates = model_visible_candidates(result.candidates)
    payload: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "filters": _filters_payload(filters),
        "frame_id": result.frame_id,
        "filter_status": result.filter_status,
        "match_status": _match_status(
            visible_count=len(visible_candidates),
            raw_count=len(result.candidates),
        ),
        "resolved_location": _region_payload(result.resolved_location),
        "near_object": _model_candidate_payload(result.near_object) if result.near_object else None,
        "results": [_model_candidate_payload(candidate) for candidate in visible_candidates],
    }
    if result.message:
        payload["message"] = result.message
    if result.candidates and not visible_candidates:
        payload["message"] = (
            "Only low-confidence vector neighbors were found; "
            "do not treat them as confirmed object matches."
        )
        payload["unreliable_result_count"] = len(result.candidates)
    return payload


def model_visible_candidates(candidates: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(candidate for candidate in candidates if is_model_visible_candidate(candidate))


def is_model_visible_candidate(candidate: Any) -> bool:
    return float(candidate.similarity) >= MIN_MODEL_VISIBLE_SEARCH_SIMILARITY


def _match_status(*, visible_count: int, raw_count: int) -> str:
    if visible_count > 0:
        return "found"
    if raw_count > 0:
        return "low_confidence"
    return "no_results"


def _model_candidate_payload(candidate: Any) -> dict[str, Any]:
    return {
        "id": candidate.source_id,
        "class": candidate.class_name,
        "position": {
            "x": candidate.x,
            "y": candidate.y,
            "z": candidate.z,
        },
    }


def _parse_search_filters(arguments: dict[str, Any]) -> SemanticMapSearchFilters:
    location = _optional_text(arguments.get("location"))
    near_object_id = _optional_text(arguments.get("near_object_id"))
    return SemanticMapSearchFilters(
        location=location,
        near_object_id=near_object_id,
        near_radius_m=_parse_near_radius(arguments.get("near_radius_m")),
    )


def _filters_payload(filters: SemanticMapSearchFilters) -> dict[str, Any]:
    payload: dict[str, Any] = {"near_radius_m": filters.near_radius_m}
    if filters.location:
        payload["location"] = filters.location
    if filters.near_object_id:
        payload["near_object_id"] = filters.near_object_id
    return payload


def _region_payload(region: Any) -> dict[str, Any] | None:
    if region is None:
        return None
    return {
        "id": region.region_id,
        "name": region.name,
        "aliases": list(region.aliases),
    }


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_near_radius(value: Any) -> float:
    try:
        radius = float(value)
    except (TypeError, ValueError):
        return DEFAULT_NEAR_RADIUS_M
    if radius <= 0:
        return DEFAULT_NEAR_RADIUS_M
    return radius


def _clamp_search_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_OBJECT_SEARCH_LIMIT
    if limit < 1:
        return DEFAULT_OBJECT_SEARCH_LIMIT
    return min(limit, MAX_OBJECT_SEARCH_LIMIT)
