from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable

from robot_object_retrieval.application.semantic_map_search_service import (
    search_semantic_map_candidates,
)
from robot_object_retrieval.infrastructure.db.semantic_map_repository import (
    get_default_semantic_map_vector_search_repository,
)
from robot_object_retrieval.infrastructure.embedding_providers import (
    get_default_embedding_provider,
)
from robot_object_retrieval.models import SemanticMapRegion, SemanticMapSearchResult


@dataclass(frozen=True)
class CatalogRuntime:
    semantic_map_search: Callable[..., SemanticMapSearchResult]
    semantic_map_regions: Callable[[], tuple[SemanticMapRegion, ...]]


def get_catalog_runtime() -> CatalogRuntime:
    embedding_provider = get_default_embedding_provider()
    vector_repository = get_default_semantic_map_vector_search_repository()
    return CatalogRuntime(
        semantic_map_search=partial(
            search_semantic_map_candidates,
            embedding_provider=embedding_provider,
            vector_repository=vector_repository,
        ),
        semantic_map_regions=lambda: _list_active_regions(vector_repository),
    )


def _list_active_regions(vector_repository) -> tuple[SemanticMapRegion, ...]:
    frame_id = vector_repository.get_active_frame_id()
    if frame_id is None:
        return ()
    return vector_repository.list_regions(frame_id)
