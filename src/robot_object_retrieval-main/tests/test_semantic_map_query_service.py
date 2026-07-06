from __future__ import annotations

from pathlib import Path
import sys
import unittest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.semantic_map_query_service import query_semantic_map
from robot_object_retrieval.application.tools.semantic_map import SEMANTIC_MAP_NOT_LOADED_ERROR
from robot_object_retrieval.models import (
    SemanticMapObjectCandidate,
    SemanticMapRegion,
    SemanticMapSearchFilters,
    SemanticMapSearchResult,
)


class SemanticMapQueryServiceTests(unittest.TestCase):
    def test_query_returns_similarity_for_direct_debugging(self) -> None:
        calls = []
        region = SemanticMapRegion(
            region_id="seating_area",
            frame_id="map",
            name="座位區",
            aliases=("椅子區",),
            geometry_type="aabb",
            min_x=0.0,
            max_x=2.0,
            min_y=0.0,
            max_y=2.0,
        )

        def search(query, limit, filters=None):
            calls.append((query, limit, filters))
            return SemanticMapSearchResult(
                frame_id="map",
                candidates=(
                    SemanticMapObjectCandidate(
                        source_id="book_12",
                        frame_id="map",
                        class_name="book",
                        x=1.0,
                        y=2.0,
                        z=3.0,
                        confidence=0.8,
                        similarity=0.9,
                    ),
                ),
                snapshot_loaded=True,
                filter_status="location_applied",
                resolved_location=region,
            )

        filters = SemanticMapSearchFilters(location="座位區")
        payload = query_semantic_map(" book ", 5, candidate_search=search, filters=filters)

        self.assertEqual(payload["query"], "book")
        self.assertEqual(payload["limit"], 5)
        self.assertEqual(calls, [("book", 5, filters)])
        self.assertEqual(payload["filter_status"], "location_applied")
        self.assertEqual(payload["resolved_location"]["id"], "seating_area")
        self.assertEqual(payload["results"][0]["id"], "book_12")
        self.assertEqual(payload["results"][0]["similarity"], 0.9)

    def test_query_returns_structured_error_when_snapshot_is_not_loaded(self) -> None:
        def search(query, limit, filters=None):
            return SemanticMapSearchResult(
                frame_id=None,
                candidates=(),
                snapshot_loaded=False,
            )

        payload = query_semantic_map("book", 5, candidate_search=search)

        self.assertEqual(payload, {"error": SEMANTIC_MAP_NOT_LOADED_ERROR})

    def test_query_rejects_empty_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "query must not be empty"):
            query_semantic_map(" ", 5, candidate_search=lambda query, limit, filters=None: None)


if __name__ == "__main__":
    unittest.main()
