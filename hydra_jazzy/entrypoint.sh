#!/usr/bin/env bash
set -Eeo pipefail
source /opt/ros/jazzy/setup.bash
if [[ -f /workspace/Hydra_Ws/install/setup.bash ]]; then
  source /workspace/Hydra_Ws/install/setup.bash
fi
set -u
exec "$@"
