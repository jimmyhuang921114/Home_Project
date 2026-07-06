#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-robot-arm64-humble-ollama:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-robot_arm64_runtime}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_WS="$(dirname "${SCRIPT_DIR}")"
PROJECT_DIR="${SCRIPT_DIR}"
HF_CACHE="${PROJECT_DIR}/hf_cache"
OLLAMA_DIR="${PROJECT_DIR}/ollama"

mkdir -p "${HF_CACHE}" "${OLLAMA_DIR}/models"

echo "[INFO] HOST_WS     = ${HOST_WS}"
echo "[INFO] PROJECT_DIR = ${PROJECT_DIR}"
echo "[INFO] HF_CACHE    = ${HF_CACHE}"
echo "[INFO] OLLAMA_DIR  = ${OLLAMA_DIR}"
echo "[INFO] IMAGE       = ${IMAGE_NAME}"
echo "[INFO] CONTAINER   = ${CONTAINER_NAME}"

# X11 permission for RViz / GUI
xhost +SI:localuser:root >/dev/null 2>&1 || true
xhost +SI:localuser:work >/dev/null 2>&1 || true
xhost +local:root >/dev/null 2>&1 || true

XAUTH=/tmp/.docker.xauth
touch "${XAUTH}"
if command -v xauth >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  xauth nlist "${DISPLAY}" | sed -e 's/^..../ffff/' | xauth -f "${XAUTH}" nmerge - || true
fi
chmod 644 "${XAUTH}"

GPU_ARGS=()
if docker info 2>/dev/null | grep -q "Runtimes:.*nvidia"; then
  GPU_ARGS+=(--runtime nvidia)
else
  GPU_ARGS+=(--gpus all)
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    echo "[INFO] container already running, entering..."
  else
    echo "[INFO] container exists but stopped, starting..."
    docker start "${CONTAINER_NAME}" >/dev/null
  fi
else
  echo "[INFO] creating persistent ARM64 container..."
  docker run -dit \
    --name "${CONTAINER_NAME}" \
    "${GPU_ARGS[@]}" \
    --privileged \
    --ipc=host \
    --shm-size=8g \
    --net=host \
    -e DISPLAY="${DISPLAY:-}" \
    -e XAUTHORITY="${XAUTH}" \
    -e QT_X11_NO_MITSHM=1 \
    -e XDG_RUNTIME_DIR=/tmp/runtime-work \
    -e ROS_DISTRO="${ROS_DISTRO:-humble}" \
    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e PROJECT_ROOT="${PROJECT_DIR}" \
    -e PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/src:${PYTHONPATH:-}" \
    -e DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/semantic_map}" \
    -e OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}" \
    -e OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}" \
    -e OLLAMA_MODELS="/workspace/.ollama/models" \
    -e OLLAMA_IN_CONTAINER="${OLLAMA_IN_CONTAINER:-0}" \
    -e HF_HOME="/workspace/.cache/huggingface" \
    -e HUGGINGFACE_HUB_CACHE="/workspace/.cache/huggingface" \
    -e TRANSFORMERS_CACHE="/workspace/.cache/huggingface" \
    -v "${XAUTH}:${XAUTH}:rw" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v /dev:/dev \
    -v "${HOST_WS}:${HOST_WS}:rw" \
    -v "${HF_CACHE}:/workspace/.cache/huggingface:rw" \
    -v "${OLLAMA_DIR}/models:/workspace/.ollama/models:rw" \
    -w "${PROJECT_DIR}" \
    "${IMAGE_NAME}" \
    bash -lc "mkdir -p /tmp/runtime-work && tail -f /dev/null"
fi

echo "[INFO] entering container shell..."
docker exec -it -w "${PROJECT_DIR}" "${CONTAINER_NAME}" bash
