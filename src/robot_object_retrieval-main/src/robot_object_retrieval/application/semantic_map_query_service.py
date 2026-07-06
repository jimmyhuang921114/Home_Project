from __future__ import annotations

from typing import Any

from robot_object_retrieval.application.tools.semantic_map import (
    SEMANTIC_MAP_NOT_LOADED_ERROR,
    SemanticMapSearch,
)
from robot_object_retrieval.models import SemanticMapSearchFilters


def query_semantic_map(
    query_text: str,
    limit: int,
    *,
    candidate_search: SemanticMapSearch,
    filters: SemanticMapSearchFilters | None = None,
) -> dict[str, Any]:
    query = query_text.strip()
    if not query:
        raise ValueError("query must not be empty")

    result = candidate_search(query, limit, filters=filters or SemanticMapSearchFilters())
    if not result.snapshot_loaded:
        return {"error": SEMANTIC_MAP_NOT_LOADED_ERROR}

    return {
        "query": query,
        "limit": limit,
        "frame_id": result.frame_id,
        "filter_status": result.filter_status,
        "message": result.message,
        "resolved_location": (
            {
                "id": result.resolved_location.region_id,
                "name": result.resolved_location.name,
                "aliases": list(result.resolved_location.aliases),
            }
            if result.resolved_location
            else None
        ),
        "near_object": (
            {
                "id": result.near_object.source_id,
                "class": result.near_object.class_name,
                "position": {
                    "x": result.near_object.x,
                    "y": result.near_object.y,
                    "z": result.near_object.z,
                },
            }
            if result.near_object
            else None
        ),
        "results": [
            {
                "id": candidate.source_id,
                "class": candidate.class_name,
                "position": {
                    "x": candidate.x,
                    "y": candidate.y,
                    "z": candidate.z,
                },
                "confidence": candidate.confidence,
                "similarity": candidate.similarity,
            }
            for candidate in result.candidates
        ],
    }
