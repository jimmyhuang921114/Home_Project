from __future__ import annotations

from robot_object_retrieval.infrastructure.embedding_providers import (
    get_default_embedding_provider,
)


def build_embedding(text: str) -> list[float]:
    provider = get_default_embedding_provider()
    return provider.embed_text(text)


def format_vector(vector: list[float]) -> str:
    values = ",".join(f"{value:.8f}" for value in vector)
    return f"[{values}]"


def get_embedding_dimension() -> int:
    provider = get_default_embedding_provider()
    return provider.dimension()


def get_embedding_model_id() -> str:
    provider = get_default_embedding_provider()
    return provider.model_id()
