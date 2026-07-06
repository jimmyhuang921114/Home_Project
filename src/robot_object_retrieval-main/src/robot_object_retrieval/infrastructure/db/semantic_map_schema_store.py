from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psycopg

from robot_object_retrieval.config import PROJECT_ROOT
from robot_object_retrieval.ports import SemanticMapSchemaStore

from .connection import get_connection


ConnectionFactory = Callable[[], AbstractContextManager[psycopg.Connection]]


@dataclass(frozen=True)
class SqlFileSemanticMapSchemaStore(SemanticMapSchemaStore):
    project_root: Path
    connection_factory: ConnectionFactory = get_connection

    def setup_schema(self, *, embedding_dimension: int) -> None:
        schema_sql = (self.project_root / "sql" / "semantic_map_schema.sql").read_text(
            encoding="utf-8"
        )
        placeholder = "__EMBEDDING_DIMENSION__"
        if placeholder not in schema_sql:
            raise RuntimeError(
                "semantic_map_schema.sql is missing the __EMBEDDING_DIMENSION__ placeholder."
            )

        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema_sql.replace(placeholder, str(embedding_dimension)))
            connection.commit()


def get_default_semantic_map_schema_store() -> SemanticMapSchemaStore:
    return SqlFileSemanticMapSchemaStore(project_root=PROJECT_ROOT)
