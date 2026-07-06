from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import unittest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.agent_instructions import AgentInstructionBuilder
from robot_object_retrieval.application.agent_service import AgentSession, make_tool_definitions
from robot_object_retrieval.application.semantic_map_import_service import (
    import_semantic_map_incremental,
    import_semantic_map_regions,
    import_semantic_map_snapshot,
    parse_semantic_map_snapshot,
)
from robot_object_retrieval.application.semantic_map_search_service import (
    search_semantic_map_candidates,
)
from robot_object_retrieval.application.tool_registry import ToolRegistry
from robot_object_retrieval.application.tools.semantic_map import (
    build_semantic_map_tool_specs,
    SEMANTIC_MAP_NOT_LOADED_ERROR,
    build_semantic_map_tools,
)
from robot_object_retrieval.infrastructure.prompt_profiles import load_prompt_profile
from robot_object_retrieval.infrastructure.db.semantic_map_repository import (
    PostgresSemanticMapRepository,
    PostgresSemanticMapVectorSearchRepository,
)
from robot_object_retrieval.models import SemanticMapObjectCandidate
from robot_object_retrieval.models import SemanticMapRegion
from robot_object_retrieval.models import SemanticMapSearchFilters


def valid_payload() -> dict:
    return {
        "map_id": "home_demo",
        "map_version": "2026-06-20",
        "frame_id": "map",
        "next_id": 2,
        "objects": [
            {
                "id": "chair_0",
                "class": "chair",
                "position": {"x": 1.0, "y": 2.0, "z": 3.0},
                "confidence": 0.8,
                "observe_count": 4,
            },
            {
                "id": "book_1",
                "class": "book",
                "position": {"x": -1.0, "y": 0.5, "z": 1.2},
                "confidence": 0.6,
                "observe_count": 2,
            },
        ],
    }


def payload_with_regions() -> dict:
    payload = valid_payload()
    payload["regions"] = [
        {
            "id": "lobby",
            "name": "入口區",
            "aliases": ["入口", "門口"],
            "geometry": {
                "type": "aabb",
                "min_x": 0.0,
                "max_x": 2.0,
                "min_y": 0.0,
                "max_y": 3.0,
            },
        }
    ]
    return payload


def make_candidate(source_id: str) -> SemanticMapObjectCandidate:
    return SemanticMapObjectCandidate(
        source_id=source_id,
        frame_id="map",
        class_name="chair",
        x=1.0,
        y=2.0,
        z=0.0,
        confidence=0.8,
        similarity=0.9,
    )


class FakeEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batch_inputs: list[list[str]] = []
        self.query_inputs: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batch_inputs.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[0.1, 0.2] for _ in texts]

    def embed_text(self, text: str) -> list[float]:
        self.query_inputs.append(text)
        return [0.1, 0.2]

    def dimension(self) -> int:
        return 2

    def model_id(self) -> str:
        return "fake"


class FakeSemanticMapRepository:
    def __init__(self) -> None:
        self.calls = []

    def replace_snapshot(self, snapshot, embeddings):
        self.calls.append((snapshot, embeddings))
        return type(
            "ImportResult",
            (),
            {
                "map_id": snapshot.map_id,
                "map_version": snapshot.map_version,
                "frame_id": snapshot.frame_id,
                "source_next_id": snapshot.source_next_id,
                "object_count": len(snapshot.objects),
            },
        )()

    def upsert_snapshot_objects(self, snapshot, embeddings):
        self.calls.append((snapshot, embeddings))
        return type(
            "ImportResult",
            (),
            {
                "map_id": snapshot.map_id,
                "map_version": snapshot.map_version,
                "frame_id": snapshot.frame_id,
                "source_next_id": snapshot.source_next_id,
                "object_count": len(snapshot.objects),
            },
        )()

    def replace_snapshot_regions(self, snapshot):
        self.calls.append((snapshot, "regions"))
        return type(
            "ImportResult",
            (),
            {
                "map_id": snapshot.map_id,
                "map_version": snapshot.map_version,
                "frame_id": snapshot.frame_id,
                "source_next_id": snapshot.source_next_id,
                "object_count": 0,
            },
        )()


class FakeSemanticMapVectorRepository:
    def __init__(self, *, frame_id="map", candidates=(), regions=()) -> None:
        self.frame_id = frame_id
        self.candidates = list(candidates)
        self.regions = tuple(regions)
        self.search_calls = []

    def get_active_frame_id(self):
        return self.frame_id

    def search_objects_by_vector(self, query_vector, limit=10, filters=None):
        self.search_calls.append((query_vector, limit, filters))
        candidates = self.candidates
        if filters and filters.location:
            region = self._resolve_region(filters.location)
            if region is None:
                return []
            candidates = [
                candidate
                for candidate in candidates
                if region.min_x <= candidate.x <= region.max_x
                and region.min_y <= candidate.y <= region.max_y
            ]
        if filters and filters.near_object_id:
            near_object = self.find_object_by_source_id(self.frame_id, filters.near_object_id)
            if near_object is None:
                return []
            radius = filters.near_radius_m
            candidates = [
                candidate
                for candidate in candidates
                if (candidate.x - near_object.x) ** 2 + (candidate.y - near_object.y) ** 2
                <= radius**2
            ]
        return candidates[:limit]

    def list_regions(self, frame_id):
        return self.regions if frame_id == self.frame_id else ()

    def find_object_by_source_id(self, frame_id, source_id):
        if frame_id != self.frame_id:
            return None
        for candidate in self.candidates:
            if candidate.source_id == source_id:
                return candidate
        return None

    def _resolve_region(self, location):
        normalized = location.lower()
        for region in self.regions:
            names = [region.region_id, region.name, *region.aliases]
            if any(name.lower() == normalized for name in names):
                return region
        return None


class RecordingCursor:
    def __init__(self) -> None:
        self.executed = []
        self.executemany_calls = []

    def execute(self, query, params=None) -> None:
        self.executed.append((str(query), params))

    def executemany(self, query, params) -> None:
        self.executemany_calls.append((str(query), list(params)))

    def fetchone(self):
        return (7,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = RecordingCursor()
        self.commit_count = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class PreflightCursor:
    def __init__(self, *, import_row, class_rows) -> None:
        self.import_row = import_row
        self.class_rows = class_rows
        self.executed = []

    def execute(self, query, params=None) -> None:
        self.executed.append((str(query), params))

    def fetchone(self):
        return self.import_row

    def fetchall(self):
        return self.class_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class PreflightConnection:
    def __init__(self, cursor) -> None:
        self.cursor_instance = cursor

    def cursor(self):
        return self.cursor_instance

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class SemanticMapTests(unittest.TestCase):
    def test_parse_snapshot_preserves_ros2_fields(self) -> None:
        snapshot = parse_semantic_map_snapshot(valid_payload())

        self.assertEqual(snapshot.map_id, "home_demo")
        self.assertEqual(snapshot.map_version, "2026-06-20")
        self.assertEqual(snapshot.frame_id, "map")
        self.assertEqual(snapshot.source_next_id, 2)
        self.assertEqual(snapshot.objects[0].source_id, "chair_0")
        self.assertEqual(snapshot.objects[0].class_name, "chair")
        self.assertEqual(snapshot.objects[0].z, 3.0)
        self.assertEqual(snapshot.objects[0].confidence, 0.8)
        self.assertEqual(snapshot.objects[0].observe_count, 4)
        self.assertEqual(snapshot.regions, ())

    def test_parse_snapshot_preserves_aabb_regions(self) -> None:
        snapshot = parse_semantic_map_snapshot(payload_with_regions())

        self.assertEqual(len(snapshot.regions), 1)
        region = snapshot.regions[0]
        self.assertEqual(region.region_id, "lobby")
        self.assertEqual(region.name, "入口區")
        self.assertEqual(region.aliases, ("入口", "門口"))
        self.assertEqual(region.geometry_type, "aabb")
        self.assertEqual(region.min_x, 0.0)
        self.assertEqual(region.max_y, 3.0)

    def test_parse_snapshot_rejects_invalid_or_duplicate_ids(self) -> None:
        cases = []

        missing_class = valid_payload()
        del missing_class["objects"][0]["class"]
        cases.append((missing_class, "snapshot.objects[0].class"))

        empty_id = valid_payload()
        empty_id["objects"][0]["id"] = " "
        cases.append((empty_id, "snapshot.objects[0].id"))

        duplicate = valid_payload()
        duplicate["objects"][1]["id"] = "chair_0"
        cases.append((duplicate, "duplicates source id"))

        invalid_position = valid_payload()
        invalid_position["objects"][0]["position"]["z"] = "3"
        cases.append((invalid_position, "snapshot.objects[0].position.z"))

        duplicate_region = payload_with_regions()
        duplicate_region["regions"].append(dict(duplicate_region["regions"][0]))
        cases.append((duplicate_region, "duplicates region id"))

        invalid_region_bounds = payload_with_regions()
        invalid_region_bounds["regions"][0]["geometry"]["min_x"] = 3.0
        invalid_region_bounds["regions"][0]["geometry"]["max_x"] = 1.0
        cases.append((invalid_region_bounds, "min_x must be less than or equal to max_x"))

        invalid_alias = payload_with_regions()
        invalid_alias["regions"][0]["aliases"] = ["入口", 3]
        cases.append((invalid_alias, "snapshot.regions[0].aliases[1]"))

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    parse_semantic_map_snapshot(payload)

    def test_import_embeds_only_classes_before_replace(self) -> None:
        provider = FakeEmbeddingProvider()
        repository = FakeSemanticMapRepository()
        snapshot = parse_semantic_map_snapshot(valid_payload())

        result = import_semantic_map_snapshot(
            snapshot,
            embedding_provider=provider,
            semantic_map_repository=repository,
        )

        self.assertEqual(provider.batch_inputs, [["chair", "book"]])
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(result.object_count, 2)

    def test_import_does_not_replace_when_embedding_fails(self) -> None:
        provider = FakeEmbeddingProvider(fail=True)
        repository = FakeSemanticMapRepository()

        with self.assertRaisesRegex(RuntimeError, "embedding unavailable"):
            import_semantic_map_snapshot(
                parse_semantic_map_snapshot(valid_payload()),
                embedding_provider=provider,
                semantic_map_repository=repository,
            )

        self.assertEqual(repository.calls, [])

    def test_incremental_import_embeds_classes_before_upsert(self) -> None:
        provider = FakeEmbeddingProvider()
        repository = FakeSemanticMapRepository()
        snapshot = parse_semantic_map_snapshot(valid_payload())

        result = import_semantic_map_incremental(
            snapshot,
            embedding_provider=provider,
            semantic_map_repository=repository,
        )

        self.assertEqual(provider.batch_inputs, [["chair", "book"]])
        self.assertEqual(len(repository.calls), 1)
        self.assertEqual(result.object_count, 2)

    def test_incremental_import_rejects_regions(self) -> None:
        provider = FakeEmbeddingProvider()
        repository = FakeSemanticMapRepository()

        with self.assertRaisesRegex(ValueError, "incremental import does not accept regions"):
            import_semantic_map_incremental(
                parse_semantic_map_snapshot(payload_with_regions()),
                embedding_provider=provider,
                semantic_map_repository=repository,
            )

        self.assertEqual(provider.batch_inputs, [])
        self.assertEqual(repository.calls, [])

    def test_incremental_import_does_not_upsert_when_embedding_fails(self) -> None:
        provider = FakeEmbeddingProvider(fail=True)
        repository = FakeSemanticMapRepository()

        with self.assertRaisesRegex(RuntimeError, "embedding unavailable"):
            import_semantic_map_incremental(
                parse_semantic_map_snapshot(valid_payload()),
                embedding_provider=provider,
                semantic_map_repository=repository,
            )

        self.assertEqual(repository.calls, [])

    def test_postgres_repository_replaces_snapshot_in_one_transaction(self) -> None:
        connection = RecordingConnection()

        @contextmanager
        def connection_factory():
            yield connection

        repository = PostgresSemanticMapRepository(connection_factory=connection_factory)
        snapshot = parse_semantic_map_snapshot(valid_payload())

        result = repository.replace_snapshot(snapshot, [[0.1, 0.2], [0.3, 0.4]])

        self.assertEqual(connection.commit_count, 1)
        self.assertIn("DELETE FROM semantic_map_objects", connection.cursor_instance.executed[0][0])
        object_batches = [
            call for call in connection.cursor_instance.executemany_calls
            if "semantic_map_objects" in call[0]
        ]
        self.assertEqual(len(object_batches), 1)
        rows = object_batches[0][1]
        self.assertEqual(rows[0]["source_id"], "chair_0")
        self.assertEqual(rows[0]["embedding"], "[0.10000000,0.20000000]")
        self.assertEqual(result.object_count, 2)

    def test_postgres_repository_replaces_regions_with_snapshot(self) -> None:
        connection = RecordingConnection()

        @contextmanager
        def connection_factory():
            yield connection

        repository = PostgresSemanticMapRepository(connection_factory=connection_factory)
        snapshot = parse_semantic_map_snapshot(payload_with_regions())

        result = repository.replace_snapshot(snapshot, [[0.1, 0.2], [0.3, 0.4]])

        self.assertEqual(connection.commit_count, 1)
        statements = "\n".join(query for query, _ in connection.cursor_instance.executed)
        self.assertIn("DELETE FROM semantic_map_regions", statements)
        region_batches = [
            call for call in connection.cursor_instance.executemany_calls
            if "semantic_map_regions" in call[0]
        ]
        self.assertEqual(len(region_batches), 1)
        self.assertEqual(region_batches[0][1][0]["region_id"], "lobby")
        self.assertEqual(region_batches[0][1][0]["aliases"], ["入口", "門口"])
        self.assertEqual(result.object_count, 2)

    def test_import_regions_replaces_regions_without_embedding(self) -> None:
        provider = FakeEmbeddingProvider()
        repository = FakeSemanticMapRepository()
        snapshot = parse_semantic_map_snapshot(payload_with_regions())

        result = import_semantic_map_regions(
            snapshot,
            semantic_map_repository=repository,
        )

        self.assertEqual(provider.batch_inputs, [])
        self.assertEqual(repository.calls, [(snapshot, "regions")])
        self.assertEqual(result.object_count, 0)

    def test_postgres_repository_upserts_incremental_objects(self) -> None:
        connection = RecordingConnection()

        @contextmanager
        def connection_factory():
            yield connection

        repository = PostgresSemanticMapRepository(connection_factory=connection_factory)
        snapshot = parse_semantic_map_snapshot(valid_payload())

        result = repository.upsert_snapshot_objects(snapshot, [[0.1, 0.2], [0.3, 0.4]])

        self.assertEqual(connection.commit_count, 1)
        statements = "\n".join(query for query, _ in connection.cursor_instance.executed)
        batch_statement = connection.cursor_instance.executemany_calls[0][0]
        self.assertNotIn("DELETE FROM semantic_map_objects", statements)
        self.assertIn("ON CONFLICT (frame_id, source_id) DO UPDATE", batch_statement)
        self.assertIn("class_name = EXCLUDED.class_name", batch_statement)
        self.assertIn("embedding = EXCLUDED.embedding", batch_statement)
        rows = connection.cursor_instance.executemany_calls[0][1]
        self.assertEqual(rows[0]["source_id"], "chair_0")
        self.assertEqual(rows[0]["embedding"], "[0.10000000,0.20000000]")
        self.assertEqual(result.object_count, 2)

    def test_postgres_repository_reads_snapshot_preflight_without_writes(self) -> None:
        cursor = PreflightCursor(
            import_row=(7, "home_demo", "2026-06-20", "map", 20, 19, datetime(2026, 6, 2, 10, 30)),
            class_rows=[("book", 4), ("chair", 3)],
        )

        @contextmanager
        def connection_factory():
            yield PreflightConnection(cursor)

        repository = PostgresSemanticMapVectorSearchRepository(
            connection_factory=connection_factory
        )
        result = repository.get_snapshot_preflight()

        self.assertTrue(result.snapshot_loaded)
        self.assertEqual(result.map_id, "home_demo")
        self.assertEqual(result.map_version, "2026-06-20")
        self.assertEqual(result.frame_id, "map")
        self.assertEqual(result.object_count, 19)
        self.assertEqual(result.imported_at, "2026-06-02T10:30:00")
        self.assertEqual(result.class_counts, (("book", 4), ("chair", 3)))
        statements = "\n".join(query for query, _ in cursor.executed)
        self.assertIn("FROM semantic_map_imports", statements)
        self.assertIn("FROM semantic_map_objects", statements)
        self.assertNotRegex(statements, r"\b(?:INSERT|UPDATE|DELETE)\b")

    def test_postgres_repository_reads_empty_snapshot_preflight(self) -> None:
        cursor = PreflightCursor(import_row=None, class_rows=[])

        @contextmanager
        def connection_factory():
            yield PreflightConnection(cursor)

        repository = PostgresSemanticMapVectorSearchRepository(
            connection_factory=connection_factory
        )
        result = repository.get_snapshot_preflight()

        self.assertFalse(result.snapshot_loaded)
        self.assertIsNone(result.map_id)
        self.assertIsNone(result.map_version)
        self.assertEqual(result.object_count, 0)
        self.assertEqual(result.class_counts, ())

    def test_semantic_map_search_and_tool_return_ros2_shape(self) -> None:
        candidate = SemanticMapObjectCandidate(
            source_id="chair_0",
            frame_id="map",
            class_name="chair",
            x=1.0,
            y=2.0,
            z=3.0,
            confidence=0.8,
            similarity=0.9,
        )
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(candidates=[candidate])

        search = lambda query, limit, filters=None: search_semantic_map_candidates(
            query,
            limit,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=filters,
        )
        registry = ToolRegistry(build_semantic_map_tools(candidate_search=search))
        dispatch_result = registry.dispatch_with_debug("search_semantic_map_object", {"query": "椅子"})
        payload = json.loads(dispatch_result.model_output)
        debug_payload = json.loads(dispatch_result.debug_output)

        self.assertEqual(provider.query_inputs, ["椅子"])
        self.assertEqual(payload["frame_id"], "map")
        self.assertEqual(payload["match_status"], "found")
        self.assertEqual(payload["results"][0]["id"], "chair_0")
        self.assertEqual(payload["results"][0]["position"], {"x": 1.0, "y": 2.0, "z": 3.0})
        self.assertNotIn("confidence", payload["results"][0])
        self.assertNotIn("similarity", payload["results"][0])
        self.assertEqual(debug_payload["results"][0]["confidence"], 0.8)
        self.assertEqual(debug_payload["results"][0]["similarity"], 0.9)
        self.assertTrue(debug_payload["results"][0]["model_visible"])

    def test_semantic_map_tool_hides_low_confidence_vector_neighbors_from_model(self) -> None:
        candidate = SemanticMapObjectCandidate(
            source_id="tablet_9",
            frame_id="map",
            class_name="tablet",
            x=4.3,
            y=3.35,
            z=0.0,
            confidence=0.9,
            similarity=0.5,
        )
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(candidates=[candidate])

        search = lambda query, limit, filters=None: search_semantic_map_candidates(
            query,
            limit,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=filters,
        )
        registry = ToolRegistry(build_semantic_map_tools(candidate_search=search))
        dispatch_result = registry.dispatch_with_debug(
            "search_semantic_map_object",
            {"query": "book"},
        )
        payload = json.loads(dispatch_result.model_output)
        debug_payload = json.loads(dispatch_result.debug_output)

        self.assertEqual(payload["match_status"], "low_confidence")
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["unreliable_result_count"], 1)
        self.assertIn("low-confidence", payload["message"])
        self.assertEqual(debug_payload["results"][0]["id"], "tablet_9")
        self.assertEqual(debug_payload["results"][0]["similarity"], 0.5)
        self.assertFalse(debug_payload["results"][0]["model_visible"])

    def test_search_filters_by_location_alias(self) -> None:
        candidates = (
            SemanticMapObjectCandidate(
                source_id="chair_0",
                frame_id="map",
                class_name="chair",
                x=1.0,
                y=2.0,
                z=0.0,
                confidence=0.8,
                similarity=0.9,
            ),
            SemanticMapObjectCandidate(
                source_id="chair_1",
                frame_id="map",
                class_name="chair",
                x=5.0,
                y=5.0,
                z=0.0,
                confidence=0.8,
                similarity=0.9,
            ),
        )
        region = SemanticMapRegion(
            region_id="lobby",
            frame_id="map",
            name="入口區",
            aliases=("入口",),
            geometry_type="aabb",
            min_x=0.0,
            max_x=2.0,
            min_y=0.0,
            max_y=3.0,
        )
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(
            candidates=candidates,
            regions=(region,),
        )

        result = search_semantic_map_candidates(
            "chair",
            10,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=SemanticMapSearchFilters(location="入口"),
        )

        self.assertEqual(result.filter_status, "location_applied")
        self.assertEqual(result.resolved_location, region)
        self.assertEqual([candidate.source_id for candidate in result.candidates], ["chair_0"])

    def test_search_rejects_unknown_location_without_global_fallback(self) -> None:
        region = SemanticMapRegion(
            region_id="lobby",
            frame_id="map",
            name="入口區",
            aliases=(),
            geometry_type="aabb",
            min_x=0.0,
            max_x=2.0,
            min_y=0.0,
            max_y=3.0,
        )
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(
            candidates=(make_candidate("chair_0"),),
            regions=(region,),
        )

        result = search_semantic_map_candidates(
            "chair",
            10,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=SemanticMapSearchFilters(location="廚房"),
        )

        self.assertEqual(provider.query_inputs, [])
        self.assertEqual(result.filter_status, "unknown_location")
        self.assertEqual(result.candidates, ())

    def test_search_reports_location_unavailable_when_no_regions_exist(self) -> None:
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(candidates=(make_candidate("chair_0"),))

        result = search_semantic_map_candidates(
            "chair",
            10,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=SemanticMapSearchFilters(location="入口區"),
        )

        self.assertEqual(provider.query_inputs, [])
        self.assertEqual(result.filter_status, "location_unavailable")
        self.assertEqual(result.candidates, ())

    def test_search_filters_by_near_object_id(self) -> None:
        candidates = (
            SemanticMapObjectCandidate(
                source_id="table_0",
                frame_id="map",
                class_name="table",
                x=0.0,
                y=0.0,
                z=0.0,
                confidence=0.8,
                similarity=1.0,
            ),
            SemanticMapObjectCandidate(
                source_id="book_near",
                frame_id="map",
                class_name="book",
                x=1.0,
                y=0.0,
                z=0.0,
                confidence=0.8,
                similarity=0.9,
            ),
            SemanticMapObjectCandidate(
                source_id="book_far",
                frame_id="map",
                class_name="book",
                x=3.0,
                y=0.0,
                z=0.0,
                confidence=0.8,
                similarity=0.9,
            ),
        )
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(candidates=candidates)

        result = search_semantic_map_candidates(
            "book",
            10,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=SemanticMapSearchFilters(near_object_id="table_0"),
        )

        self.assertEqual(result.filter_status, "near_applied")
        self.assertEqual(result.near_object.source_id, "table_0")
        self.assertEqual([candidate.source_id for candidate in result.candidates], ["table_0", "book_near"])

    def test_search_rejects_unknown_near_object_id(self) -> None:
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(candidates=(make_candidate("chair_0"),))

        result = search_semantic_map_candidates(
            "chair",
            10,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=SemanticMapSearchFilters(near_object_id="missing"),
        )

        self.assertEqual(provider.query_inputs, [])
        self.assertEqual(result.filter_status, "unknown_near_object")
        self.assertEqual(result.candidates, ())

    def test_semantic_map_tool_returns_error_when_snapshot_is_not_loaded(self) -> None:
        provider = FakeEmbeddingProvider()
        vector_repository = FakeSemanticMapVectorRepository(frame_id=None)
        search = lambda query, limit, filters=None: search_semantic_map_candidates(
            query,
            limit,
            embedding_provider=provider,
            vector_repository=vector_repository,
            filters=filters,
        )
        registry = ToolRegistry(build_semantic_map_tools(candidate_search=search))

        payload = json.loads(registry.dispatch("search_semantic_map_object", {"query": "chair"}))

        self.assertEqual(payload, {"error": SEMANTIC_MAP_NOT_LOADED_ERROR})
        self.assertEqual(provider.query_inputs, [])

    def test_tool_definitions_include_semantic_map_search(self) -> None:
        names = [tool["function"]["name"] for tool in make_tool_definitions()]
        self.assertEqual(names, ["search_semantic_map_object"])

    def test_semantic_map_tool_specs_expose_schema_from_single_source(self) -> None:
        specs = build_semantic_map_tool_specs(candidate_search=lambda query, limit, filters=None: SemanticMapSearchResult(frame_id="map", candidates=(), snapshot_loaded=True))

        self.assertEqual([spec.name for spec in specs], ["search_semantic_map_object"])
        self.assertEqual(specs[0].definition()["function"]["name"], "search_semantic_map_object")

    def test_agent_session_and_instructions_use_only_semantic_map_tool(self) -> None:
        class FakeChatModel:
            def create_chat_completion(self, *, model, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant", "content": "完成"}}]}

        session = AgentSession(
            model="test",
            chat_model=FakeChatModel(),
            semantic_map_search=lambda query, limit: None,
            prompt_profile=load_prompt_profile(),
        )
        tool_names = [tool["function"]["name"] for tool in session.tools]
        messages = AgentInstructionBuilder(prompt_profile=load_prompt_profile()).build_messages([])
        system_text = "\n".join(message["content"] for message in messages)

        self.assertEqual(tool_names, ["search_semantic_map_object"])
        self.assertIn("search_semantic_map_object", system_text)
        self.assertNotIn("semantic_search_object", system_text)
        self.assertNotIn("Mutation Policy", system_text)


if __name__ == "__main__":
    unittest.main()
