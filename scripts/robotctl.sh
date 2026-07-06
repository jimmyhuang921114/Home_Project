#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS="${HOME_PROJECT_ROOT:-${PROJECT_ROOT}}"
RETRIEVAL="$WS/src/robot_object_retrieval-main"
RECORDS="$WS/data/main_policy_records.jsonl"

source_env() {
  set +u
  source /opt/ros/humble/setup.bash
  source "$WS/install/setup.bash"
  set -u
}

usage() {
  cat <<USAGE
Usage:
  robotctl <command>

Main policy:
  status          Show main_policy status
  start           Start auto waypoint scan
  stop            Stop auto waypoint scan
  next            Run one waypoint + vision
  reset           Reset main_policy index and records
  detect          Trigger vision detect_here
  export          Export main_policy snapshot
  tail            Tail main_policy_records.jsonl

Database:
  db-tree         Show database table tree
  db-classes      Show class count summary
  db-objects      Show objects table
  db-latest       Show latest import objects
  db-psql         Enter PostgreSQL psql
  import-test     Import one test chair through /semantic_map/import
  search <query>  Search semantic map, example: robotctl search chair

Debug:
  services        Show important ROS services
  topics          Show important ROS topics
USAGE
}

cmd="${1:-help}"

case "$cmd" in
  status)
    source_env
    ros2 service call /main_policy/status std_srvs/srv/Trigger "{}"
    ;;

  start)
    source_env
    ros2 service call /main_policy/start std_srvs/srv/Trigger "{}"
    ;;

  stop)
    source_env
    ros2 service call /main_policy/stop std_srvs/srv/Trigger "{}"
    ;;

  next)
    source_env
    ros2 service call /main_policy/next std_srvs/srv/Trigger "{}"
    ;;

  reset)
    source_env
    ros2 service call /main_policy/reset std_srvs/srv/Trigger "{}"
    ;;

  detect)
    source_env
    ros2 service call /task/detect_here std_srvs/srv/Trigger "{}"
    ;;

  export)
    source_env
    ros2 service call /main_policy/export_records std_srvs/srv/Trigger "{}"
    ;;

  tail)
    mkdir -p "$WS/data"
    touch "$RECORDS"
    tail -f "$RECORDS"
    ;;

  services)
    source_env
    ros2 service list | grep -E "main_policy|task|nav_to_point|grounding_dino|semantic_map" || true
    ;;

  topics)
    source_env
    ros2 topic list | grep -E "grounding_dino|ram|realsense|map|tf|plan|amcl" || true
    ;;

  db-tree)
    docker exec -it robot_object_pg psql -U postgres -d robot_db -c "
SELECT 'robot_db' AS tree
UNION ALL
SELECT '├── semantic_map_imports  (' || COUNT(*) || ' rows)' FROM semantic_map_imports
UNION ALL
SELECT '├── semantic_map_objects  (' || COUNT(*) || ' rows)' FROM semantic_map_objects
UNION ALL
SELECT '└── semantic_map_regions  (' || COUNT(*) || ' rows)' FROM semantic_map_regions;
"
    ;;

  db-classes)
    docker exec -it robot_object_pg psql -U postgres -d robot_db -c "
SELECT
  class_name,
  COUNT(*) AS count,
  ROUND(AVG(confidence)::numeric, 2) AS avg_score,
  ROUND(MAX(confidence)::numeric, 2) AS max_score
FROM semantic_map_objects
GROUP BY class_name
ORDER BY count DESC, max_score DESC;
"
    ;;

  db-objects)
    docker exec -it robot_object_pg psql -U postgres -d robot_db -c "
SELECT
  source_id,
  class_name,
  ROUND(confidence::numeric, 2) AS score,
  ROUND(x::numeric, 2) AS x,
  ROUND(y::numeric, 2) AS y,
  ROUND(z::numeric, 2) AS z,
  observe_count
FROM semantic_map_objects
ORDER BY class_name, confidence DESC
LIMIT 50;
"
    ;;

  db-latest)
    docker exec -it robot_object_pg psql -U postgres -d robot_db -c "
SELECT
  o.source_id,
  o.class_name,
  ROUND(o.confidence::numeric, 2) AS score,
  ROUND(o.x::numeric, 2) AS x,
  ROUND(o.y::numeric, 2) AS y,
  ROUND(o.z::numeric, 2) AS z,
  o.observe_count
FROM semantic_map_objects o
WHERE o.import_id = (
  SELECT MAX(id) FROM semantic_map_imports
)
ORDER BY o.class_name, o.confidence DESC
LIMIT 100;
"
    ;;

  db-psql)
    docker exec -it robot_object_pg psql -U postgres -d robot_db
    ;;

  import-test)
    source_env
    ros2 service call /semantic_map/import robot_object_retrieval_ros/srv/ImportSemanticMap \
"{json_payload: '{\"frame_id\":\"map\",\"next_id\":1,\"objects\":[{\"id\":\"test_chair_001\",\"class\":\"chair\",\"confidence\":0.9,\"position\":{\"x\":1.0,\"y\":2.0,\"z\":0.0}}]}', mode: replace}"
    ;;

  search)
    query="${2:-}"
    if [ -z "$query" ]; then
      echo "[ERROR] usage: robotctl search <query>"
      exit 1
    fi
    cd "$RETRIEVAL"
    python3 scripts/search_semantic_map.py "$query" --limit 10
    ;;

  help|-h|--help)
    usage
    ;;

  *)
    echo "[ERROR] unknown command: $cmd"
    usage
    exit 1
    ;;
esac
