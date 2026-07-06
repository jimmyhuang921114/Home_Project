from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from robot_object_retrieval.application.semantic_map_import_service import (
    import_semantic_map_incremental,
    import_semantic_map_regions,
    import_semantic_map_snapshot,
    load_semantic_map_snapshot,
)
from robot_object_retrieval.infrastructure.db.semantic_map_repository import (
    get_default_semantic_map_repository,
)
from robot_object_retrieval.infrastructure.embedding_providers import (
    get_default_embedding_provider,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a ROS2 semantic map JSON snapshot")
    parser.add_argument("snapshot_path", type=Path, help="Path to semantic_map.json")
    parser.add_argument(
        "--mode",
        choices=("replace", "incremental", "regions"),
        default="replace",
        help=(
            "Import mode. replace swaps objects and regions; incremental inserts or updates "
            "only listed objects; regions replaces room/zone metadata only."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize the snapshot without embedding or writing to PostgreSQL.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    snapshot_path = args.snapshot_path.resolve()
    snapshot = load_semantic_map_snapshot(snapshot_path)
    _print_summary(
        snapshot_path,
        args.mode,
        snapshot.map_id,
        snapshot.map_version,
        snapshot.frame_id,
        snapshot.source_next_id,
        snapshot.objects,
        snapshot.regions,
    )

    if args.dry_run:
        print("Dry run completed. No embeddings were generated and PostgreSQL was not modified.")
        return

    semantic_map_repository = get_default_semantic_map_repository()
    if args.mode == "regions":
        result = import_semantic_map_regions(
            snapshot,
            semantic_map_repository=semantic_map_repository,
        )
    else:
        embedding_provider = get_default_embedding_provider()
        if args.mode == "incremental":
            result = import_semantic_map_incremental(
                snapshot,
                embedding_provider=embedding_provider,
                semantic_map_repository=semantic_map_repository,
            )
        else:
            result = import_semantic_map_snapshot(
                snapshot,
                embedding_provider=embedding_provider,
                semantic_map_repository=semantic_map_repository,
            )
    print(
        "Semantic map imported successfully. "
        f"mode={args.mode} map_id={result.map_id} map_version={result.map_version} "
        f"frame_id={result.frame_id} objects={result.object_count}"
    )


def _print_summary(
    snapshot_path: Path,
    mode: str,
    map_id: str,
    map_version: str,
    frame_id: str,
    source_next_id: int,
    objects,
    regions,
) -> None:
    categories = Counter(obj.class_name for obj in objects)
    print(f"Snapshot: {snapshot_path}")
    print(f"mode: {mode}")
    print(f"map_id: {map_id}")
    print(f"map_version: {map_version}")
    print(f"frame_id: {frame_id}")
    print(f"next_id: {source_next_id}")
    print(f"objects: {len(objects)}")
    print(f"regions: {len(regions)}")
    print("classes:")
    for class_name, count in categories.most_common():
        print(f"  {class_name}: {count}")


if __name__ == "__main__":
    main()
