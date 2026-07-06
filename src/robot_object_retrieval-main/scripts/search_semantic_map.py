from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.semantic_map_query_service import query_semantic_map
from robot_object_retrieval.infrastructure.catalog_runtime import get_catalog_runtime
from robot_object_retrieval.models import (
    DEFAULT_NEAR_RADIUS_M,
    DEFAULT_OBJECT_SEARCH_LIMIT,
    MAX_OBJECT_SEARCH_LIMIT,
    SemanticMapSearchFilters,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query the active semantic-map snapshot without running the agent."
    )
    parser.add_argument("query", help="Object text to embed and search, e.g. book or plate.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_OBJECT_SEARCH_LIMIT,
        help=f"Maximum candidates to return, from 1 to {MAX_OBJECT_SEARCH_LIMIT}.",
    )
    parser.add_argument(
        "--location",
        help="Optional room or region filter, matched by region id, name, or alias.",
    )
    parser.add_argument(
        "--near-object-id",
        help="Optional source object id used as a 2D distance filter anchor.",
    )
    parser.add_argument(
        "--near-radius-m",
        type=float,
        default=DEFAULT_NEAR_RADIUS_M,
        help=f"2D radius in meters for --near-object-id. Defaults to {DEFAULT_NEAR_RADIUS_M}.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit < 1 or args.limit > MAX_OBJECT_SEARCH_LIMIT:
        print(
            f"ERROR: --limit must be between 1 and {MAX_OBJECT_SEARCH_LIMIT}",
            file=sys.stderr,
        )
        return 2
    if args.near_radius_m <= 0:
        print("ERROR: --near-radius-m must be greater than 0", file=sys.stderr)
        return 2

    try:
        payload = query_semantic_map(
            args.query,
            args.limit,
            candidate_search=get_catalog_runtime().semantic_map_search,
            filters=SemanticMapSearchFilters(
                location=args.location,
                near_object_id=args.near_object_id,
                near_radius_m=args.near_radius_m,
            ),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
