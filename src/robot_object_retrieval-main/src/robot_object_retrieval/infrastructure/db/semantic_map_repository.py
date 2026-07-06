from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable

import psycopg

from robot_object_retrieval.models import (
    DEFAULT_OBJECT_SEARCH_LIMIT,
    SemanticMapImportResult,
    SemanticMapObjectCandidate,
    SemanticMapPreflight,
    SemanticMapRegion,
    SemanticMapSearchFilters,
    SemanticMapSnapshot,
)
from robot_object_retrieval.ports import (
    SemanticMapRepository,
    SemanticMapVectorSearchRepository,
)

from .connection import get_connection


ConnectionFactory = Callable[[], AbstractContextManager[psycopg.Connection]]


@dataclass(frozen=True)
class PostgresSemanticMapRepository(SemanticMapRepository):
    connection_factory: ConnectionFactory = get_connection

    def replace_snapshot(
        self,
        snapshot: SemanticMapSnapshot,
        embeddings: list[list[float]],
    ) -> SemanticMapImportResult:
        if len(snapshot.objects) != len(embeddings):
            raise ValueError("Semantic map object and embedding counts must match.")

        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM semantic_map_objects;")
                cursor.execute(
                    """
                    INSERT INTO semantic_map_imports (map_id, map_version, frame_id, source_next_id, object_count)
                    VALUES (%(map_id)s, %(map_version)s, %(frame_id)s, %(source_next_id)s, %(object_count)s)
                    RETURNING id;
                    """,
                    {
                        "map_id": snapshot.map_id,
                        "map_version": snapshot.map_version,
                        "frame_id": snapshot.frame_id,
                        "source_next_id": snapshot.source_next_id,
                        "object_count": len(snapshot.objects),
                    },
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Semantic map import record was not created.")
                import_id = row[0]

                cursor.executemany(
                    """
                    INSERT INTO semantic_map_objects (
                        import_id,
                        source_id,
                        frame_id,
                        class_name,
                        x,
                        y,
                        z,
                        confidence,
                        observe_count,
                        embedding
                    )
                    VALUES (
                        %(import_id)s,
                        %(source_id)s,
                        %(frame_id)s,
                        %(class_name)s,
                        %(x)s,
                        %(y)s,
                        %(z)s,
                        %(confidence)s,
                        %(observe_count)s,
                        %(embedding)s::vector
                    );
                    """,
                    [
                        {
                            "import_id": import_id,
                            "source_id": obj.source_id,
                            "frame_id": obj.frame_id,
                            "class_name": obj.class_name,
                            "x": obj.x,
                            "y": obj.y,
                            "z": obj.z,
                            "confidence": obj.confidence,
                            "observe_count": obj.observe_count,
                            "embedding": self._format_vector(embedding),
                        }
                        for obj, embedding in zip(snapshot.objects, embeddings)
                    ],
                )
                self._replace_regions(cursor, snapshot)
            connection.commit()

        return SemanticMapImportResult(
            map_id=snapshot.map_id,
            map_version=snapshot.map_version,
            frame_id=snapshot.frame_id,
            source_next_id=snapshot.source_next_id,
            object_count=len(snapshot.objects),
        )

    def replace_snapshot_regions(
        self,
        snapshot: SemanticMapSnapshot,
    ) -> SemanticMapImportResult:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                self._replace_regions(cursor, snapshot)
            connection.commit()

        return SemanticMapImportResult(
            map_id=snapshot.map_id,
            map_version=snapshot.map_version,
            frame_id=snapshot.frame_id,
            source_next_id=snapshot.source_next_id,
            object_count=0,
        )

    def _replace_regions(self, cursor, snapshot: SemanticMapSnapshot) -> None:
        cursor.execute(
            "DELETE FROM semantic_map_regions WHERE frame_id = %(frame_id)s;",
            {"frame_id": snapshot.frame_id},
        )
        if not snapshot.regions:
            return
        cursor.executemany(
            """
            INSERT INTO semantic_map_regions (
                frame_id,
                region_id,
                name,
                aliases,
                geometry_type,
                min_x,
                max_x,
                min_y,
                max_y
            )
            VALUES (
                %(frame_id)s,
                %(region_id)s,
                %(name)s,
                %(aliases)s,
                %(geometry_type)s,
                %(min_x)s,
                %(max_x)s,
                %(min_y)s,
                %(max_y)s
            );
            """,
            [
                {
                    "frame_id": region.frame_id,
                    "region_id": region.region_id,
                    "name": region.name,
                    "aliases": list(region.aliases),
                    "geometry_type": region.geometry_type,
                    "min_x": region.min_x,
                    "max_x": region.max_x,
                    "min_y": region.min_y,
                    "max_y": region.max_y,
                }
                for region in snapshot.regions
            ],
        )

    def upsert_snapshot_objects(
        self,
        snapshot: SemanticMapSnapshot,
        embeddings: list[list[float]],
    ) -> SemanticMapImportResult:
        if len(snapshot.objects) != len(embeddings):
            raise ValueError("Semantic map object and embedding counts must match.")

        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO semantic_map_imports (map_id, map_version, frame_id, source_next_id, object_count)
                    VALUES (%(map_id)s, %(map_version)s, %(frame_id)s, %(source_next_id)s, %(object_count)s)
                    RETURNING id;
                    """,
                    {
                        "map_id": snapshot.map_id,
                        "map_version": snapshot.map_version,
                        "frame_id": snapshot.frame_id,
                        "source_next_id": snapshot.source_next_id,
                        "object_count": len(snapshot.objects),
                    },
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Semantic map import record was not created.")
                import_id = row[0]

                cursor.executemany(
                    """
                    INSERT INTO semantic_map_objects (
                        import_id,
                        source_id,
                        frame_id,
                        class_name,
                        x,
                        y,
                        z,
                        confidence,
                        observe_count,
                        embedding
                    )
                    VALUES (
                        %(import_id)s,
                        %(source_id)s,
                        %(frame_id)s,
                        %(class_name)s,
                        %(x)s,
                        %(y)s,
                        %(z)s,
                        %(confidence)s,
                        %(observe_count)s,
                        %(embedding)s::vector
                    )
                    ON CONFLICT (frame_id, source_id) DO UPDATE SET
                        import_id = EXCLUDED.import_id,
                        class_name = EXCLUDED.class_name,
                        x = EXCLUDED.x,
                        y = EXCLUDED.y,
                        z = EXCLUDED.z,
                        confidence = EXCLUDED.confidence,
                        observe_count = EXCLUDED.observe_count,
                        embedding = EXCLUDED.embedding;
                    """,
                    [
                        {
                            "import_id": import_id,
                            "source_id": obj.source_id,
                            "frame_id": obj.frame_id,
                            "class_name": obj.class_name,
                            "x": obj.x,
                            "y": obj.y,
                            "z": obj.z,
                            "confidence": obj.confidence,
                            "observe_count": obj.observe_count,
                            "embedding": self._format_vector(embedding),
                        }
                        for obj, embedding in zip(snapshot.objects, embeddings)
                    ],
                )
            connection.commit()

        return SemanticMapImportResult(
            map_id=snapshot.map_id,
            map_version=snapshot.map_version,
            frame_id=snapshot.frame_id,
            source_next_id=snapshot.source_next_id,
            object_count=len(snapshot.objects),
        )

    @staticmethod
    def _format_vector(vector: list[float]) -> str:
        values = ",".join(f"{value:.8f}" for value in vector)
        return f"[{values}]"


@dataclass(frozen=True)
class PostgresSemanticMapVectorSearchRepository(SemanticMapVectorSearchRepository):
    connection_factory: ConnectionFactory = get_connection

    def get_active_frame_id(self) -> str | None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT frame_id
                    FROM semantic_map_imports
                    ORDER BY id DESC
                    LIMIT 1;
                    """
                )
                row = cursor.fetchone()
        return None if row is None else str(row[0])

    def get_snapshot_preflight(self) -> SemanticMapPreflight:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, map_id, map_version, frame_id, source_next_id, object_count, imported_at
                    FROM semantic_map_imports
                    ORDER BY id DESC
                    LIMIT 1;
                    """
                )
                import_row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT class_name, COUNT(*)
                    FROM semantic_map_objects
                    GROUP BY class_name
                    ORDER BY COUNT(*) DESC, class_name ASC;
                    """
                )
                class_rows = cursor.fetchall()

        if import_row is None:
            return SemanticMapPreflight(
                snapshot_loaded=False,
                import_id=None,
                map_id=None,
                map_version=None,
                frame_id=None,
                source_next_id=None,
                object_count=0,
                imported_at=None,
                class_counts=(),
            )

        imported_at = import_row[6]
        return SemanticMapPreflight(
            snapshot_loaded=True,
            import_id=int(import_row[0]),
            map_id=str(import_row[1]),
            map_version=str(import_row[2]),
            frame_id=str(import_row[3]),
            source_next_id=int(import_row[4]),
            object_count=int(import_row[5]),
            imported_at=(import_row[6].isoformat() if hasattr(import_row[6], "isoformat") else str(import_row[6])),
            class_counts=tuple((str(row[0]), int(row[1])) for row in class_rows),
        )

    def search_objects_by_vector(
        self,
        query_vector: list[float],
        limit: int = DEFAULT_OBJECT_SEARCH_LIMIT,
        filters: SemanticMapSearchFilters | None = None,
    ) -> list[SemanticMapObjectCandidate]:
        filters = filters or SemanticMapSearchFilters()
        frame_id = self.get_active_frame_id()
        if frame_id is None:
            return []

        region = self._resolve_region(frame_id, filters.location) if filters.location else None
        if filters.location and region is None:
            return []
        near_object = (
            self.find_object_by_source_id(frame_id, filters.near_object_id)
            if filters.near_object_id
            else None
        )
        if filters.near_object_id and near_object is None:
            return []

        where_clauses = ["frame_id = %(frame_id)s"]
        params = {
            "frame_id": frame_id,
            "query_vector": PostgresSemanticMapRepository._format_vector(query_vector),
            "limit": limit,
        }
        if region is not None:
            where_clauses.extend(
                [
                    "x >= %(min_x)s",
                    "x <= %(max_x)s",
                    "y >= %(min_y)s",
                    "y <= %(max_y)s",
                ]
            )
            params.update(
                {
                    "min_x": region.min_x,
                    "max_x": region.max_x,
                    "min_y": region.min_y,
                    "max_y": region.max_y,
                }
            )
        if near_object is not None:
            where_clauses.append(
                "((x - %(near_x)s) * (x - %(near_x)s) + "
                "(y - %(near_y)s) * (y - %(near_y)s)) <= "
                "(%(near_radius_m)s * %(near_radius_m)s)"
            )
            params.update(
                {
                    "near_x": near_object.x,
                    "near_y": near_object.y,
                    "near_radius_m": filters.near_radius_m,
                }
            )

        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        source_id,
                        frame_id,
                        class_name,
                        x,
                        y,
                        z,
                        confidence,
                        1 - (embedding <=> %(query_vector)s::vector) AS similarity
                    FROM semantic_map_objects
                    WHERE {" AND ".join(where_clauses)}
                    ORDER BY embedding <=> %(query_vector)s::vector
                    LIMIT %(limit)s;
                    """,
                    params,
                )
                rows = cursor.fetchall()

        return _candidate_rows(rows)

    def list_regions(self, frame_id: str) -> tuple[SemanticMapRegion, ...]:
        try:
            with self.connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT region_id, frame_id, name, aliases, geometry_type, min_x, max_x, min_y, max_y
                        FROM semantic_map_regions
                        WHERE frame_id = %(frame_id)s
                        ORDER BY region_id ASC;
                        """,
                        {"frame_id": frame_id},
                    )
                    rows = cursor.fetchall()
        except psycopg.errors.UndefinedTable:
            return ()

        return tuple(
            SemanticMapRegion(
                region_id=str(row[0]),
                frame_id=str(row[1]),
                name=str(row[2]),
                aliases=tuple(row[3] or ()),
                geometry_type=str(row[4]),
                min_x=float(row[5]),
                max_x=float(row[6]),
                min_y=float(row[7]),
                max_y=float(row[8]),
            )
            for row in rows
        )

    def find_object_by_source_id(
        self,
        frame_id: str,
        source_id: str,
    ) -> SemanticMapObjectCandidate | None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source_id, frame_id, class_name, x, y, z, confidence, 1.0 AS similarity
                    FROM semantic_map_objects
                    WHERE frame_id = %(frame_id)s AND source_id = %(source_id)s
                    LIMIT 1;
                    """,
                    {"frame_id": frame_id, "source_id": source_id},
                )
                row = cursor.fetchone()

        if row is None:
            return None
        return _candidate_rows([row])[0]

    def _resolve_region(self, frame_id: str, location: str) -> SemanticMapRegion | None:
        normalized_location = location.strip().lower()
        if not normalized_location:
            return None
        for region in self.list_regions(frame_id):
            names = [region.region_id, region.name, *region.aliases]
            if any(name.lower() == normalized_location for name in names):
                return region
        return None


def _candidate_rows(rows) -> list[SemanticMapObjectCandidate]:
    return [
        SemanticMapObjectCandidate(
            source_id=row[0],
            frame_id=row[1],
            class_name=row[2],
            x=row[3],
            y=row[4],
            z=row[5],
            confidence=row[6],
            similarity=row[7],
        )
        for row in rows
    ]


def get_default_semantic_map_repository() -> SemanticMapRepository:
    return PostgresSemanticMapRepository()


def get_default_semantic_map_vector_search_repository() -> SemanticMapVectorSearchRepository:
    return PostgresSemanticMapVectorSearchRepository()
