#!/usr/bin/env bash
set -Eeuo pipefail
container="${HYDRA_CONTAINER_NAME:-home_project_hydra_jazzy}"
if (($#)); then
  exec docker exec -it "$container" bash -lc 'source /opt/ros/jazzy/setup.bash; source /workspace/Hydra_Ws/install/setup.bash 2>/dev/null || true; exec "$@"' bash "$@"
fi
exec docker exec -it "$container" bash
