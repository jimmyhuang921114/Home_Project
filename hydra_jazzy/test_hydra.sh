#!/usr/bin/env bash
set -Eeuo pipefail
container="${HYDRA_CONTAINER_NAME:-home_project_hydra_jazzy}"
docker exec "$container" bash -lc '
  source /opt/ros/jazzy/setup.bash
  source /workspace/Hydra_Ws/install/setup.bash
  test "$ROS_DISTRO" = jazzy
  test "$ROS_DOMAIN_ID" = 40
  test "$RMW_IMPLEMENTATION" = rmw_cyclonedds_cpp
  ros2 pkg prefix hydra_ros
  ros2 pkg prefix hydra
  ros2 pkg executables hydra_ros
  nvidia-smi
'
