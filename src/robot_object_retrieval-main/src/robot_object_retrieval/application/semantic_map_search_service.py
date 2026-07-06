from __future__ import annotations

from robot_object_retrieval.models import (
    DEFAULT_OBJECT_SEARCH_LIMIT,
    MAX_OBJECT_SEARCH_LIMIT,
    SemanticMapRegion,
    SemanticMapSearchFilters,
    SemanticMapSearchResult,
)
from robot_object_retrieval.ports import EmbeddingProvider, SemanticMapVectorSearchRepository


def search_semantic_map_candidates(
    query_text: str,
    limit: int = DEFAULT_OBJECT_SEARCH_LIMIT,
    *,
    embedding_provider: EmbeddingProvider,
    vector_repository: SemanticMapVectorSearchRepository,
    filters: SemanticMapSearchFilters | None = None,
) -> SemanticMapSearchResult:
    filters = filters or SemanticMapSearchFilters()
    frame_id = vector_repository.get_active_frame_id()
    if frame_id is None:
        return SemanticMapSearchResult(
            frame_id=None,
            candidates=(),
            snapshot_loaded=False,
        )

    resolved_location: SemanticMapRegion | None = None
    if filters.location:
        regions = vector_repository.list_regions(frame_id)
        if not regions:
            return SemanticMapSearchResult(
                frame_id=frame_id,
                candidates=(),
                snapshot_loaded=True,
                filter_status="location_unavailable",
                message="semantic map has no room or zone metadata",
            )
        resolved_location = _resolve_region(regions, filters.location)
        if resolved_location is None:
            return SemanticMapSearchResult(
                frame_id=frame_id,
                candidates=(),
                snapshot_loaded=True,
                filter_status="unknown_location",
                message="semantic map has no known region matching this location",
            )

    near_object = None
    if filters.near_object_id:
        near_object = vector_repository.find_object_by_source_id(
            frame_id,
            filters.near_object_id,
        )
        if near_object is None:
            return SemanticMapSearchResult(
                frame_id=frame_id,
                candidates=(),
                snapshot_loaded=True,
                filter_status="unknown_near_object",
                message="near_object_id was not found in the active semantic map",
            )

    query_vector = embedding_provider.embed_text(query_text.strip())
    candidates = vector_repository.search_objects_by_vector(
        query_vector=query_vector,
        limit=_clamp_search_limit(limit),
        filters=filters,
    )
    return SemanticMapSearchResult(
        frame_id=frame_id,
        candidates=tuple(candidates),
        snapshot_loaded=True,
        filter_status=_filter_status(filters),
        resolved_location=resolved_location,
        near_object=near_object,
    )


def _clamp_search_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_OBJECT_SEARCH_LIMIT
    if limit < 1:
        return DEFAULT_OBJECT_SEARCH_LIMIT
    return min(limit, MAX_OBJECT_SEARCH_LIMIT)


def _resolve_region(
    regions: tuple[SemanticMapRegion, ...],
    location: str,
) -> SemanticMapRegion | None:
    normalized_location = location.strip().lower()
    for region in regions:
        names = [region.region_id, region.name, *region.aliases]
        if any(name.lower() == normalized_location for name in names):
            return region
    return None


def _filter_status(filters: SemanticMapSearchFilters) -> str:
    if filters.location and filters.near_object_id:
        return "location_and_near_applied"
    if filters.location:
        return "location_applied"
    if filters.near_object_id:
        return "near_applied"
    return "unfiltered"
