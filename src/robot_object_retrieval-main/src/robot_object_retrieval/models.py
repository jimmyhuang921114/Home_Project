from __future__ import annotations

from dataclasses import dataclass


DEFAULT_OBJECT_SEARCH_LIMIT = 10
MAX_OBJECT_SEARCH_LIMIT = 50
DEFAULT_NEAR_RADIUS_M = 1.5


@dataclass(frozen=True)
class SemanticMapObject:
    source_id: str
    frame_id: str
    class_name: str
    x: float
    y: float
    z: float
    confidence: float
    observe_count: int


@dataclass(frozen=True)
class SemanticMapRegion:
    region_id: str
    frame_id: str
    name: str
    aliases: tuple[str, ...]
    geometry_type: str
    min_x: float
    max_x: float
    min_y: float
    max_y: float


@dataclass(frozen=True)
class SemanticMapSnapshot:
    frame_id: str
    source_next_id: int
    objects: tuple[SemanticMapObject, ...]
    map_id: str = "unknown_map"
    map_version: str = "unknown_version"
    regions: tuple[SemanticMapRegion, ...] = ()


@dataclass(frozen=True)
class SemanticMapObjectCandidate:
    source_id: str
    frame_id: str
    class_name: str
    x: float
    y: float
    z: float
    confidence: float
    similarity: float


@dataclass(frozen=True)
class SemanticMapSearchResult:
    frame_id: str | None
    candidates: tuple[SemanticMapObjectCandidate, ...]
    snapshot_loaded: bool
    filter_status: str = "unfiltered"
    message: str | None = None
    resolved_location: SemanticMapRegion | None = None
    near_object: SemanticMapObjectCandidate | None = None


@dataclass(frozen=True)
class SemanticMapSearchFilters:
    location: str | None = None
    near_object_id: str | None = None
    near_radius_m: float = DEFAULT_NEAR_RADIUS_M


@dataclass(frozen=True)
class SemanticMapImportResult:
    map_id: str
    map_version: str
    frame_id: str
    source_next_id: int
    object_count: int


@dataclass(frozen=True)
class SemanticMapPreflight:
    snapshot_loaded: bool
    import_id: int | None
    map_id: str | None
    map_version: str | None
    frame_id: str | None
    source_next_id: int | None
    object_count: int
    imported_at: str | None
    class_counts: tuple[tuple[str, int], ...]
