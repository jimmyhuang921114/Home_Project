#!/usr/bin/env bash
set -e

IMAGE_NAME="hf-vision-cu128:latest"
CONTAINER_NAME="hf_vision_nav2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_WS="$(dirname "${SCRIPT_DIR}")"
PROJECT_DIR="${SCRIPT_DIR}"
HF_CACHE="${PROJECT_DIR}/hf_cache"
ENV_FILE="${PROJECT_DIR}/robot_object.env"

# Load shared env file
if [ -f "${ENV_FILE}" ]; then
  echo "[INFO] loading env file: ${ENV_FILE}"
  set -a
  source "${ENV_FILE}"
  set +a
else
  echo "[WARN] env file not found: ${ENV_FILE}"
fi

# Defaults if robot_object.env is missing something
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/robot_db}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

mkdir -p "${HF_CACHE}"

echo "[INFO] HOST_WS     = ${HOST_WS}"
echo "[INFO] PROJECT_DIR = ${PROJECT_DIR}"
echo "[INFO] HF_CACHE    = ${HF_CACHE}"
echo "[INFO] IMAGE       = ${IMAGE_NAME}"
echo "[INFO] CONTAINER   = ${CONTAINER_NAME}"
echo "[INFO] DATABASE_URL    = ${DATABASE_URL}"
echo "[INFO] OLLAMA_BASE_URL = ${OLLAMA_BASE_URL}"

# X11 permission for RViz / GUI
xhost +SI:localuser:root >/dev/null 2>&1 || true
xhost +SI:localuser:work >/dev/null 2>&1 || true
xhost +local:root >/dev/null 2>&1 || true

XAUTH=/tmp/.docker.xauth
touch "${XAUTH}"

if command -v xauth >/dev/null 2>&1; then
  xauth nlist "${DISPLAY}" | sed -e 's/^..../ffff/' | xauth -f "${XAUTH}" nmerge - || true
fi

chmod 644 "${XAUTH}"

# 如果 container 已經存在
if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    echo "[INFO] container already running, entering..."
  else
    echo "[INFO] container exists but stopped, starting..."
    docker start "${CONTAINER_NAME}" >/dev/null
  fi
else
  echo "[INFO] creating persistent container..."

  docker run -dit \
    --name "${CONTAINER_NAME}" \
    --gpus all \
    --privileged \
    --ipc=host \
    --shm-size=16g \
    --net=host \
    -e DISPLAY="${DISPLAY}" \
    -e XAUTHORITY="${XAUTH}" \
    -e QT_X11_NO_MITSHM=1 \
    -e XDG_RUNTIME_DIR=/tmp/runtime-work \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display \
    -e ROS_DISTRO=humble \
    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e PROJECT_ROOT="${PROJECT_DIR}" \
    -e PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/src:${PYTHONPATH:-}" \
    -e DATABASE_URL="${DATABASE_URL}" \
    -e OLLAMA_BASE_URL="${OLLAMA_BASE_URL}" \
    -e PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" \
    -e HF_HOME="${HF_CACHE}" \
    -e HUGGINGFACE_HUB_CACHE="${HF_CACHE}" \
    -e TRANSFORMERS_CACHE="${HF_CACHE}" \
    -e RAM_REPO_PATH="${HOST_WS}/visual/src/recognize-anything" \
    -v "${XAUTH}:${XAUTH}:rw" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v /dev:/dev \
    -v "${HOST_WS}:${HOST_WS}:rw" \
    -w "${HOST_WS}" \
    "${IMAGE_NAME}" \
    bash -lc "mkdir -p /tmp/runtime-work && tail -f /dev/null"
fi

echo "[INFO] entering container shell..."
docker exec -it \
  -w "${HOST_WS}" \
  -e DATABASE_URL="${DATABASE_URL}" \
  -e OLLAMA_BASE_URL="${OLLAMA_BASE_URL}" \
  -e PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" \
  "${CONTAINER_NAME}" \
  bash
