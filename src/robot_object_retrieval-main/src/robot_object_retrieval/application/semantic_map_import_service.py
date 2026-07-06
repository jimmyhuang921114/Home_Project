from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robot_object_retrieval.models import (
    SemanticMapImportResult,
    SemanticMapObject,
    SemanticMapRegion,
    SemanticMapSnapshot,
)
from robot_object_retrieval.ports import EmbeddingProvider, SemanticMapRepository


def load_semantic_map_snapshot(path: Path) -> SemanticMapSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    return parse_semantic_map_snapshot(payload)


def parse_semantic_map_snapshot(payload: Any) -> SemanticMapSnapshot:
    root = _required_dict(payload, "snapshot")
    map_id = _required_string(root, "map_id", "snapshot")
    map_version = _required_string(root, "map_version", "snapshot")
    frame_id = _required_string(root, "frame_id", "snapshot")
    source_next_id = _required_int(root, "next_id", "snapshot")
    raw_objects = _required_list(root, "objects", "snapshot")
    raw_regions = _optional_list(root, "regions", "snapshot")

    objects: list[SemanticMapObject] = []
    seen_ids: set[tuple[str, str]] = set()
    for index, raw_object in enumerate(raw_objects):
        path = f"snapshot.objects[{index}]"
        obj = _parse_semantic_map_object(raw_object, frame_id=frame_id, path=path)
        identity = (obj.frame_id, obj.source_id)
        if identity in seen_ids:
            raise ValueError(
                f"{path}.id duplicates source id {obj.source_id!r} in frame {obj.frame_id!r}."
            )
        seen_ids.add(identity)
        objects.append(obj)

    regions: list[SemanticMapRegion] = []
    seen_region_ids: set[tuple[str, str]] = set()
    for index, raw_region in enumerate(raw_regions):
        path = f"snapshot.regions[{index}]"
        region = _parse_semantic_map_region(raw_region, frame_id=frame_id, path=path)
        identity = (region.frame_id, region.region_id)
        if identity in seen_region_ids:
            raise ValueError(
                f"{path}.id duplicates region id {region.region_id!r} in frame {region.frame_id!r}."
            )
        seen_region_ids.add(identity)
        regions.append(region)

    return SemanticMapSnapshot(
        map_id=map_id,
        map_version=map_version,
        frame_id=frame_id,
        source_next_id=source_next_id,
        objects=tuple(objects),
        regions=tuple(regions),
    )


def import_semantic_map_snapshot(
    snapshot: SemanticMapSnapshot,
    *,
    embedding_provider: EmbeddingProvider,
    semantic_map_repository: SemanticMapRepository,
) -> SemanticMapImportResult:
    embeddings = embedding_provider.embed_texts([obj.class_name for obj in snapshot.objects])
    if len(embeddings) != len(snapshot.objects):
        raise RuntimeError(
            "Embedding provider returned an unexpected number of vectors for the semantic map."
        )
    return semantic_map_repository.replace_snapshot(snapshot, embeddings)


def import_semantic_map_incremental(
    snapshot: SemanticMapSnapshot,
    *,
    embedding_provider: EmbeddingProvider,
    semantic_map_repository: SemanticMapRepository,
) -> SemanticMapImportResult:
    if snapshot.regions:
        raise ValueError("incremental import does not accept regions; use mode=regions or mode=replace.")
    embeddings = embedding_provider.embed_texts([obj.class_name for obj in snapshot.objects])
    if len(embeddings) != len(snapshot.objects):
        raise RuntimeError(
            "Embedding provider returned an unexpected number of vectors for the semantic map."
        )
    return semantic_map_repository.upsert_snapshot_objects(snapshot, embeddings)


def import_semantic_map_regions(
    snapshot: SemanticMapSnapshot,
    *,
    semantic_map_repository: SemanticMapRepository,
) -> SemanticMapImportResult:
    return semantic_map_repository.replace_snapshot_regions(snapshot)


def _parse_semantic_map_object(
    payload: Any,
    *,
    frame_id: str,
    path: str,
) -> SemanticMapObject:
    obj = _required_dict(payload, path)
    position = _required_dict(obj.get("position"), f"{path}.position")
    return SemanticMapObject(
        source_id=_required_string(obj, "id", path),
        frame_id=frame_id,
        class_name=_required_string(obj, "class", path),
        x=_required_float(position, "x", f"{path}.position"),
        y=_required_float(position, "y", f"{path}.position"),
        z=_required_float(position, "z", f"{path}.position"),
        confidence=_required_float(obj, "confidence", path),
        observe_count=_required_int(obj, "observe_count", path),
    )


def _parse_semantic_map_region(
    payload: Any,
    *,
    frame_id: str,
    path: str,
) -> SemanticMapRegion:
    region = _required_dict(payload, path)
    geometry = _required_dict(region.get("geometry"), f"{path}.geometry")
    geometry_type = _required_string(geometry, "type", f"{path}.geometry")
    if geometry_type != "aabb":
        raise ValueError(f"{path}.geometry.type must be 'aabb'.")

    min_x = _required_float(geometry, "min_x", f"{path}.geometry")
    max_x = _required_float(geometry, "max_x", f"{path}.geometry")
    min_y = _required_float(geometry, "min_y", f"{path}.geometry")
    max_y = _required_float(geometry, "max_y", f"{path}.geometry")
    if min_x > max_x:
        raise ValueError(f"{path}.geometry.min_x must be less than or equal to max_x.")
    if min_y > max_y:
        raise ValueError(f"{path}.geometry.min_y must be less than or equal to max_y.")

    return SemanticMapRegion(
        region_id=_required_string(region, "id", path),
        frame_id=frame_id,
        name=_required_string(region, "name", path),
        aliases=tuple(_optional_string_list(region, "aliases", path)),
        geometry_type=geometry_type,
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
    )


def _required_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object.")
    return value


def _required_list(payload: dict[str, Any], field_name: str, path: str) -> list[Any]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{path}.{field_name} must be an array.")
    return value


def _optional_list(payload: dict[str, Any], field_name: str, path: str) -> list[Any]:
    value = payload.get(field_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{path}.{field_name} must be an array.")
    return value


def _optional_string_list(payload: dict[str, Any], field_name: str, path: str) -> list[str]:
    value = payload.get(field_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{path}.{field_name} must be an array.")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{path}.{field_name}[{index}] must be a non-empty string.")
        items.append(item.strip())
    return items


def _required_string(payload: dict[str, Any], field_name: str, path: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{field_name} must be a non-empty string.")
    return value.strip()


def _required_float(payload: dict[str, Any], field_name: str, path: str) -> float:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}.{field_name} must be a number.")
    return float(value)


def _required_int(payload: dict[str, Any], field_name: str, path: str) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}.{field_name} must be an integer.")
    return value
