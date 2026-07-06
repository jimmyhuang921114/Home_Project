from __future__ import annotations

import json

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from robot_object_retrieval.application.semantic_map_import_service import (
    import_semantic_map_incremental,
    import_semantic_map_regions,
    import_semantic_map_snapshot,
    parse_semantic_map_snapshot,
)
from robot_object_retrieval.infrastructure.db.semantic_map_repository import (
    get_default_semantic_map_repository,
)
from robot_object_retrieval.infrastructure.embedding_providers import (
    get_default_embedding_provider,
)
from robot_object_retrieval_ros.srv import ImportSemanticMap


DEFAULT_SERVICE_NAME = "/semantic_map/import"
DEFAULT_MODE = "incremental"
VALID_MODES = {"incremental", "replace", "regions"}


class SemanticMapImportServiceNode(Node):
    def __init__(self) -> None:
        super().__init__("semantic_map_import_service_node")
        self.declare_parameter("service_name", DEFAULT_SERVICE_NAME)
        service_name = (
            self.get_parameter("service_name").get_parameter_value().string_value
        )
        self._embedding_provider = get_default_embedding_provider()
        self._semantic_map_repository = get_default_semantic_map_repository()
        self.create_service(
            ImportSemanticMap,
            service_name,
            self._handle_request,
        )
        self.get_logger().info(
            f"Serving semantic-map JSON imports on {service_name!r}."
        )

    def _handle_request(
        self,
        request: ImportSemanticMap.Request,
        response: ImportSemanticMap.Response,
    ) -> ImportSemanticMap.Response:
        mode = request.mode.strip() or DEFAULT_MODE
        if mode not in VALID_MODES:
            return _failure(
                response,
                "invalid_mode",
                "mode must be one of: incremental, replace, regions",
            )

        try:
            payload = json.loads(request.json_payload)
            snapshot = parse_semantic_map_snapshot(payload)
            if mode == "regions":
                result = import_semantic_map_regions(
                    snapshot,
                    semantic_map_repository=self._semantic_map_repository,
                )
            elif mode == "replace":
                result = import_semantic_map_snapshot(
                    snapshot,
                    embedding_provider=self._embedding_provider,
                    semantic_map_repository=self._semantic_map_repository,
                )
            else:
                result = import_semantic_map_incremental(
                    snapshot,
                    embedding_provider=self._embedding_provider,
                    semantic_map_repository=self._semantic_map_repository,
                )
        except json.JSONDecodeError as error:
            return _failure(response, "invalid_json", str(error))
        except ValueError as error:
            return _failure(response, "invalid_payload", str(error))
        except Exception as error:
            self.get_logger().error(f"Semantic-map import failed: {error}")
            return _failure(response, "import_failed", str(error))

        response.success = True
        response.frame_id = result.frame_id
        response.source_next_id = result.source_next_id
        response.object_count = result.object_count
        response.error_type = ""
        response.message = "imported"
        self.get_logger().info(
            "Semantic map imported. "
            f"mode={mode} frame_id={result.frame_id} "
            f"next_id={result.source_next_id} objects={result.object_count}"
        )
        return response


def _failure(
    response: ImportSemanticMap.Response,
    error_type: str,
    message: str,
) -> ImportSemanticMap.Response:
    response.success = False
    response.frame_id = ""
    response.source_next_id = 0
    response.object_count = 0
    response.error_type = error_type
    response.message = message
    return response


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SemanticMapImportServiceNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
