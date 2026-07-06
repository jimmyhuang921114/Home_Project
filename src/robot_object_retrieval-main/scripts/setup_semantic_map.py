from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.infrastructure.db.semantic_map_schema_store import (
    get_default_semantic_map_schema_store,
)
from robot_object_retrieval.infrastructure.embedding_providers import (
    get_default_embedding_provider,
)


def main() -> None:
    embedding_provider = get_default_embedding_provider()
    dimension = embedding_provider.dimension()
    get_default_semantic_map_schema_store().setup_schema(embedding_dimension=dimension)
    print(f"Semantic map schema is ready. Embedding dimension: {dimension}.")


if __name__ == "__main__":
    main()
