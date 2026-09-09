#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_NAME="${IMAGE_NAME:-home-project-nav2:humble}"
CONTAINER_NAME="${CONTAINER_NAME:-home-project-nav2}"
HOST_WORKSPACE="${HOST_WORKSPACE:-/home/jimmy/work_ws/Home_Project}"
CYCLONE_CONFIG="${CYCLONE_CONFIG:-/home/jimmy/.ros/cyclonedds.xml}"
CYCLONE_INTERFACE="${CYCLONE_INTERFACE:-wlp130s0f0}"
ISAAC_ROS2_COMPAT_LIB="${ISAAC_ROS2_COMPAT_LIB:-${HOST_WORKSPACE}/runtime/isaac_ros2_compat/lib}"
ISAAC_ROS2_SOURCE_LIB="${ISAAC_ROS2_SOURCE_LIB:-/home/jimmy/IsaacLab/env_isaaclab/lib/python3.11/site-packages/isaacsim/exts/isaacsim.ros2.bridge/humble/lib}"
MAP_IMAGE="${MAP_IMAGE:-${HOST_WORKSPACE}/src/Home_Project/home_project_core/maps/map.png}"

[[ -d "${HOST_WORKSPACE}" ]] || { echo "Missing workspace: ${HOST_WORKSPACE}" >&2; exit 1; }
[[ -f "${CYCLONE_CONFIG}" ]] || { echo "Missing CycloneDDS config: ${CYCLONE_CONFIG}" >&2; exit 1; }
[[ -f "${MAP_IMAGE}" ]] || { echo "Missing map image: ${MAP_IMAGE}" >&2; exit 1; }
compat_libraries=(
  libddsc.so libddsc.so.0 libddsc.so.0.10.5
  librmw_cyclonedds_cpp.so librmw_dds_common.so
  librmw_dds_common__rosidl_generator_c.so
  librmw_dds_common__rosidl_typesupport_c.so
  librmw_dds_common__rosidl_typesupport_cpp.so
  librmw_dds_common__rosidl_typesupport_introspection_c.so
  librmw_dds_common__rosidl_typesupport_introspection_cpp.so
  librmw.so
  librosidl_typesupport_introspection_cpp.so
  librosidl_typesupport_introspection_c.so librosidl_runtime_c.so
  librcutils.so librcpputils.so librosidl_typesupport_cpp.so
)
mkdir -p "${ISAAC_ROS2_COMPAT_LIB}"
for library in "${compat_libraries[@]}"; do
  [[ -f "${ISAAC_ROS2_SOURCE_LIB}/${library}" ]] || {
    echo "Missing Isaac-compatible ROS library: ${ISAAC_ROS2_SOURCE_LIB}/${library}" >&2
    exit 1
  }
  cp -a "${ISAAC_ROS2_SOURCE_LIB}/${library}" "${ISAAC_ROS2_COMPAT_LIB}/${library}"
done
ip -o -4 address show dev "${CYCLONE_INTERFACE}" scope global | grep -q 'inet ' || {
  echo "CycloneDDS interface has no global IPv4: ${CYCLONE_INTERFACE}" >&2
  exit 1
}
grep -Eq "<NetworkInterface[[:space:]]+name=\"${CYCLONE_INTERFACE}\"" "${CYCLONE_CONFIG}" || {
  echo "CycloneDDS config is not pinned to ${CYCLONE_INTERFACE}" >&2
  exit 1
}
[[ "$(ip route show default | awk 'NR == 1 {print $5}')" == "${CYCLONE_INTERFACE}" ]] || {
  echo "Default route is not on ${CYCLONE_INTERFACE}" >&2
  exit 1
}

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Container already exists: ${CONTAINER_NAME}"
  echo "Use ./enter_nav2_humble.sh, or explicitly remove it before recreating." 
  exit 0
fi

docker run --detach --tty \
  --name "${CONTAINER_NAME}" \
  --network host \
  --ipc host \
  --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-40}" \
  --env "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" \
  --env "CYCLONEDDS_URI=file:///home/jimmy/.ros/cyclonedds.xml" \
  --env "LD_LIBRARY_PATH=/opt/isaac_ros2_humble_compat:/opt/ros/humble/lib:/opt/ros/humble/lib/x86_64-linux-gnu" \
  --env "DISPLAY=${DISPLAY:-}" \
  --env "QT_X11_NO_MITSHM=1" \
  --volume "${HOST_WORKSPACE}:/workspace:rw" \
  --volume "${CYCLONE_CONFIG}:/home/jimmy/.ros/cyclonedds.xml:ro" \
  --volume "${ISAAC_ROS2_COMPAT_LIB}:/opt/isaac_ros2_humble_compat:ro" \
  --volume "${MAP_IMAGE}:/workspace/config/map.png:ro" \
  --volume /tmp/.X11-unix:/tmp/.X11-unix:rw \
  --volume home_project_nav2_build:/colcon/build \
  --volume home_project_nav2_install:/colcon/install \
  --volume home_project_nav2_log:/colcon/log \
  --workdir /workspace \
  "${IMAGE_NAME}" tail -f /dev/null

echo "CONTAINER=${CONTAINER_NAME}"
