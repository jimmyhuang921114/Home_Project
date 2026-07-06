from __future__ import annotations

from typing import Any, Protocol, TypeAlias

from robot_object_retrieval.models import (
    DEFAULT_OBJECT_SEARCH_LIMIT,
    SemanticMapImportResult,
    SemanticMapObjectCandidate,
    SemanticMapPreflight,
    SemanticMapRegion,
    SemanticMapSearchFilters,
    SemanticMapSnapshot,
)


ChatCompletionResponse: TypeAlias = dict[str, Any]
ChatMessage: TypeAlias = dict[str, Any]
ChatToolDefinition: TypeAlias = dict[str, Any]


class ChatModel(Protocol):
    def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[ChatToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatCompletionResponse: ...


class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def dimension(self) -> int: ...

    def model_id(self) -> str: ...


class SemanticMapRepository(Protocol):
    def replace_snapshot(
        self,
        snapshot: SemanticMapSnapshot,
        embeddings: list[list[float]],
    ) -> SemanticMapImportResult: ...

    def upsert_snapshot_objects(
        self,
        snapshot: SemanticMapSnapshot,
        embeddings: list[list[float]],
    ) -> SemanticMapImportResult: ...

    def replace_snapshot_regions(
        self,
        snapshot: SemanticMapSnapshot,
    ) -> SemanticMapImportResult: ...


class SemanticMapVectorSearchRepository(Protocol):
    def get_active_frame_id(self) -> str | None: ...

    def get_snapshot_preflight(self) -> SemanticMapPreflight: ...

    def search_objects_by_vector(
        self,
        query_vector: list[float],
        limit: int = DEFAULT_OBJECT_SEARCH_LIMIT,
        filters: SemanticMapSearchFilters | None = None,
    ) -> list[SemanticMapObjectCandidate]: ...

    def list_regions(self, frame_id: str) -> tuple[SemanticMapRegion, ...]: ...

    def find_object_by_source_id(
        self,
        frame_id: str,
        source_id: str,
    ) -> SemanticMapObjectCandidate | None: ...


class SemanticMapSchemaStore(Protocol):
    def setup_schema(self, *, embedding_dimension: int) -> None: ...
