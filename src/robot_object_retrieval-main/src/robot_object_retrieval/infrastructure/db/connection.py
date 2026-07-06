from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from robot_object_retrieval.config import get_database_config


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    config = get_database_config()
    with psycopg.connect(config.dsn) as connection:
        yield connection
