from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

from robot_object_retrieval.config import get_embedding_config
from robot_object_retrieval.ports import EmbeddingProvider


@dataclass(frozen=True)
class EmbeddingEndpointError(RuntimeError):
    status_code: int
    url: str
    response_body: str

    def __str__(self) -> str:
        return (
            f"Embedding endpoint returned HTTP {self.status_code} for {self.url}. "
            f"Response body: {self.response_body}"
        )


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    api_url: str
    model_name: str
    api_key: str = ""
    _cached_dimension: int | None = field(default=None, init=False, repr=False, compare=False)

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        normalized_texts = [" ".join(text.split()) for text in texts]
        non_empty_inputs: list[str] = []
        embedding_positions: list[int] = []
        embeddings: list[list[float] | None] = [None] * len(texts)

        for index, normalized in enumerate(normalized_texts):
            if not normalized:
                continue
            embedding_positions.append(index)
            non_empty_inputs.append(normalized)

        if not non_empty_inputs:
            raise ValueError("Cannot embed an empty text list.")

        if non_empty_inputs:
            response = _post_json(
                url=self.api_url,
                payload={
                    "model": self.model_name,
                    "input": non_empty_inputs,
                    "encoding_format": "float",
                },
                api_key=self.api_key,
            )
            batch_embeddings = _extract_embeddings(response, self.api_url)
            if len(batch_embeddings) != len(non_empty_inputs):
                raise RuntimeError(
                    "Embedding endpoint returned an unexpected number of embeddings: "
                    f"expected {len(non_empty_inputs)}, got {len(batch_embeddings)}."
                )

            embedding_dimension = len(batch_embeddings[0])
            for index, embedding in zip(embedding_positions, batch_embeddings):
                if len(embedding) != embedding_dimension:
                    raise RuntimeError(
                        "Embedding dimension mismatch from endpoint: "
                        f"provider '{self.model_name}' returned {len(embedding)} dimensions, "
                        f"but detected dimension is {embedding_dimension}."
                )
                embeddings[index] = embedding

            for index, normalized in enumerate(normalized_texts):
                if not normalized:
                    embeddings[index] = [0.0] * embedding_dimension

        return [embedding if embedding is not None else [0.0] * embedding_dimension for embedding in embeddings]

    def dimension(self) -> int:
        if self._cached_dimension is None:
            object.__setattr__(
                self,
                "_cached_dimension",
                _fetch_embedding_dimension(
                    model_name=self.model_name,
                    api_url=self.api_url,
                    api_key=self.api_key,
                ),
            )
        return self._cached_dimension

    def model_id(self) -> str:
        return self.model_name


def get_default_embedding_provider() -> EmbeddingProvider:
    config = get_embedding_config()
    return OpenAICompatibleEmbeddingProvider(
        api_url=config.api_url,
        model_name=config.model_name,
        api_key=config.api_key,
    )


def _post_json(
    *,
    url: str,
    payload: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise EmbeddingEndpointError(
            status_code=exc.code,
            url=url,
            response_body=response_body,
        ) from exc
    return json.loads(body)


def _fetch_embedding_dimension(*, model_name: str, api_url: str, api_key: str) -> int:
    show_url = _derive_model_show_url(api_url)
    if show_url is not None:
        try:
            response = _post_json(
                url=show_url,
                payload={"model": model_name},
                api_key=api_key,
            )
            dimension = _extract_dimension_from_model_info(response)
            if dimension is not None:
                return dimension
        except EmbeddingEndpointError:
            pass

    embedding = _probe_embedding_dimension(
        model_name=model_name,
        api_url=api_url,
        api_key=api_key,
    )
    return len(embedding)


def _derive_model_show_url(api_url: str) -> str | None:
    if api_url.endswith("/v1/embeddings"):
        return api_url[: -len("/v1/embeddings")] + "/api/show"
    return None


def _extract_dimension_from_model_info(response: dict[str, Any]) -> int | None:
    model_info = response.get("model_info")
    if not isinstance(model_info, dict):
        return None

    for key in ("bert.embedding_length", "embedding_length"):
        value = model_info.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    return None


def _probe_embedding_dimension(*, model_name: str, api_url: str, api_key: str) -> list[float]:
    response = _post_json(
        url=api_url,
        payload={
            "model": model_name,
            "input": "dimension probe",
            "encoding_format": "float",
        },
        api_key=api_key,
    )
    embeddings = _extract_embeddings(response, api_url)
    if not embeddings:
        raise RuntimeError(
            f"Embedding endpoint response from {api_url} is missing data[0].embedding."
        )
    return embeddings[0]


def _extract_embeddings(response: dict[str, Any], url: str) -> list[list[float]]:
    data = response.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(
            f"Embedding endpoint response from {url} is missing data[0].embedding."
        )

    indexed_embeddings: list[tuple[int, list[float]]] = []
    for fallback_index, item in enumerate(data):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"Embedding endpoint response from {url} contains an invalid data item."
            )

        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError(
                f"Embedding endpoint response from {url} is missing an embedding vector."
            )

        try:
            indexed_embeddings.append(
                (
                    int(item.get("index", fallback_index)),
                    [float(value) for value in embedding],
                )
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Embedding endpoint response from {url} contained a non-numeric embedding."
            ) from exc

    indexed_embeddings.sort(key=lambda item: item[0])
    return [embedding for _, embedding in indexed_embeddings]
