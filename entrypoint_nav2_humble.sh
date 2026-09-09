#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash
if [[ -f /colcon/install/setup.bash ]]; then
  source /colcon/install/setup.bash
fi

echo "ENVIRONMENT=DOCKER"
echo "ROS_DISTRO=humble"
echo "SOURCE_WORKSPACE=/workspace"
echo "BUILD_BASE=/colcon/build"
echo "INSTALL_BASE=/colcon/install"
echo "LOG_BASE=/colcon/log"

exec "$@"
