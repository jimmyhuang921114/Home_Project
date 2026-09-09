#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_NAME="${IMAGE_NAME:-hf-vision-cu128:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-hf_vision_nav2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_WS="$(dirname "${SCRIPT_DIR}")"
PROJECT_DIR="${SCRIPT_DIR}"

HF_CACHE="${PROJECT_DIR}/hf_cache"
ENV_FILE="${PROJECT_DIR}/robot_object.env"

ROS_DOMAIN_ID_VALUE="${ROS_DOMAIN_ID:-40}"
ROS_LOCALHOST_ONLY_VALUE="${ROS_LOCALHOST_ONLY:-0}"
RMW_IMPLEMENTATION_VALUE="rmw_cyclonedds_cpp"

CYCLONE_INTERFACE="${CYCLONE_INTERFACE:-wlp130s0f0}"

CYCLONE_CONFIG_HOST="${HOME}/.ros/cyclonedds.xml"
CYCLONE_CONFIG_CONTAINER="/etc/cyclonedds/cyclonedds.xml"
CYCLONEDDS_URI_VALUE="file://${CYCLONE_CONFIG_CONTAINER}"

RECREATE_CONTAINER="${RECREATE_CONTAINER:-0}"

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"
}

write_cyclone_config() {
  mkdir -p "$(dirname "${CYCLONE_CONFIG_HOST}")"

  cat > "${CYCLONE_CONFIG_HOST}" <<XML_EOF
<?xml version="1.0" encoding="UTF-8"?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain Id="any">

    <General>
      <Interfaces>
        <NetworkInterface name="${CYCLONE_INTERFACE}"/>
      </Interfaces>

      <!--
        SPDP discovery uses multicast.
        Actual ROS 2 data traffic uses unicast.
      -->
      <AllowMulticast>spdp</AllowMulticast>
    </General>

    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
    </Discovery>

    <Tracing>
      <Verbosity>warning</Verbosity>
      <OutputFile>stderr</OutputFile>
    </Tracing>

  </Domain>
</CycloneDDS>
XML_EOF

  chmod 0644 "${CYCLONE_CONFIG_HOST}"
}

container_has_required_config() {
  local network_mode
  local cyclone_mount

  network_mode="$(
    docker inspect \
      -f '{{.HostConfig.NetworkMode}}' \
      "${CONTAINER_NAME}" \
      2>/dev/null || true
  )"

  cyclone_mount="$(
    docker inspect \
      -f '{{range .Mounts}}{{if eq .Destination "/etc/cyclonedds/cyclonedds.xml"}}yes{{end}}{{end}}' \
      "${CONTAINER_NAME}" \
      2>/dev/null || true
  )"

  [[ "${network_mode}" == "host" ]] &&
  [[ "${cyclone_mount}" == "yes" ]]
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker not found"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] Docker daemon unavailable"
  exit 1
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/robot_db}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

mkdir -p "${HF_CACHE}"

write_cyclone_config

echo ""
echo "============================================================"
echo "Jimmy ROS 2 / CycloneDDS"
echo "============================================================"
echo "ROS_DOMAIN_ID       = ${ROS_DOMAIN_ID_VALUE}"
echo "ROS_LOCALHOST_ONLY  = ${ROS_LOCALHOST_ONLY_VALUE}"
echo "RMW_IMPLEMENTATION  = ${RMW_IMPLEMENTATION_VALUE}"
echo "CYCLONE_INTERFACE   = ${CYCLONE_INTERFACE}"
echo "CYCLONEDDS_URI      = ${CYCLONEDDS_URI_VALUE}"
echo "CYCLONE_CONFIG      = ${CYCLONE_CONFIG_HOST}"
echo "============================================================"
echo ""

XAUTH="/tmp/.docker.xauth"
touch "${XAUTH}"

xhost +SI:localuser:root >/dev/null 2>&1 || true
xhost +SI:localuser:work >/dev/null 2>&1 || true
xhost +local:root >/dev/null 2>&1 || true

if command -v xauth >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  xauth nlist "${DISPLAY}" 2>/dev/null |
    sed -e 's/^..../ffff/' |
    xauth -f "${XAUTH}" nmerge - 2>/dev/null || true
fi

chmod 644 "${XAUTH}"

if container_exists; then
  if [[ "${RECREATE_CONTAINER}" == "1" ]]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null

  elif ! container_has_required_config; then
    echo "[INFO] old container configuration detected"
    echo "[INFO] recreating container"
    docker rm -f "${CONTAINER_NAME}" >/dev/null
  fi
fi

if ! container_exists; then
  echo "[INFO] creating container"

  docker run -dit \
    --name "${CONTAINER_NAME}" \
    --gpus all \
    --privileged \
    --ipc=host \
    --shm-size=16g \
    --net=host \
    \
    -e "DISPLAY=${DISPLAY:-}" \
    -e "XAUTHORITY=${XAUTH}" \
    -e "QT_X11_NO_MITSHM=1" \
    -e "XDG_RUNTIME_DIR=/tmp/runtime-work" \
    \
    -e "ROS_DISTRO=humble" \
    -e "ROS_DOMAIN_ID=${ROS_DOMAIN_ID_VALUE}" \
    -e "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY_VALUE}" \
    -e "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION_VALUE}" \
    -e "CYCLONEDDS_URI=${CYCLONEDDS_URI_VALUE}" \
    \
    -e "PROJECT_ROOT=${PROJECT_DIR}" \
    -e "PYTHONPATH=${PROJECT_DIR}:${PROJECT_DIR}/src:${PYTHONPATH:-}" \
    \
    -e "DATABASE_URL=${DATABASE_URL}" \
    -e "OLLAMA_BASE_URL=${OLLAMA_BASE_URL}" \
    \
    -e "HF_HOME=${HF_CACHE}" \
    -e "HUGGINGFACE_HUB_CACHE=${HF_CACHE}" \
    -e "TRANSFORMERS_CACHE=${HF_CACHE}" \
    \
    -v "${XAUTH}:${XAUTH}:rw" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v /dev:/dev \
    -v "${HOST_WS}:${HOST_WS}:rw" \
    -v "${CYCLONE_CONFIG_HOST}:${CYCLONE_CONFIG_CONTAINER}:ro" \
    \
    -w "${HOST_WS}" \
    \
    "${IMAGE_NAME}" \
    \
    bash -lc '
      mkdir -p /tmp/runtime-work
      chmod 700 /tmp/runtime-work || true
      exec tail -f /dev/null
    '
else
  if ! container_running; then
    docker start "${CONTAINER_NAME}" >/dev/null
  fi
fi

echo "[INFO] entering container"

docker exec -it \
  -w "${HOST_WS}" \
  \
  -e "DISPLAY=${DISPLAY:-}" \
  -e "XAUTHORITY=${XAUTH}" \
  -e "QT_X11_NO_MITSHM=1" \
  -e "XDG_RUNTIME_DIR=/tmp/runtime-work" \
  \
  -e "ROS_DISTRO=humble" \
  -e "ROS_DOMAIN_ID=${ROS_DOMAIN_ID_VALUE}" \
  -e "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY_VALUE}" \
  -e "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION_VALUE}" \
  -e "CYCLONEDDS_URI=${CYCLONEDDS_URI_VALUE}" \
  \
  "${CONTAINER_NAME}" \
  \
  bash -lc '
    source /opt/ros/humble/setup.bash

    if [[ -f /workspace/work_ws/install/setup.bash ]]; then
      source /workspace/work_ws/install/setup.bash
    fi

    if [[ -f /home/jimmy/work_ws/visual/install/setup.bash ]]; then
      source /home/jimmy/work_ws/visual/install/setup.bash
    fi

    export ROS_DOMAIN_ID=40
    export ROS_LOCALHOST_ONLY=0
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export CYCLONEDDS_URI=file:///etc/cyclonedds/cyclonedds.xml

    unset FASTRTPS_DEFAULT_PROFILES_FILE
    unset FASTDDS_DEFAULT_PROFILES_FILE
    unset ROS_DISCOVERY_SERVER

    echo ""
    echo "============================================"
    echo "Jimmy ROS 2 Environment"
    echo "============================================"
    echo "ROS_DOMAIN_ID       = ${ROS_DOMAIN_ID}"
    echo "ROS_LOCALHOST_ONLY  = ${ROS_LOCALHOST_ONLY}"
    echo "RMW_IMPLEMENTATION  = ${RMW_IMPLEMENTATION}"
    echo "CYCLONEDDS_URI      = ${CYCLONEDDS_URI}"
    echo "============================================"
    echo ""

    exec bash -i
  '
