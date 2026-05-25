#!/usr/bin/env bash
set -e

IMAGE_NAME="hf-vision-cu128:latest"

HOST_WS="/home/jimmy/work_ws"

if [ ! -d "${HOST_WS}" ]; then
  echo "ERROR: host workspace not found: ${HOST_WS}"
  exit 1
fi

xhost +SI:localuser:root >/dev/null 2>&1 || true
xhost +SI:localuser:work >/dev/null 2>&1 || true
xhost +local:root >/dev/null 2>&1 || true

XAUTH=/tmp/.docker.xauth
touch "${XAUTH}"

if command -v xauth >/dev/null 2>&1; then
  xauth nlist "${DISPLAY}" | sed -e 's/^..../ffff/' | xauth -f "${XAUTH}" nmerge - || true
fi

chmod 644 "${XAUTH}"

docker run --rm -it \
  --gpus all \
  --ipc=host \
  --shm-size=8g \
  --net=host \
  -e DISPLAY="${DISPLAY}" \
  -e XAUTHORITY="${XAUTH}" \
  -e QT_X11_NO_MITSHM=1 \
  -e XDG_RUNTIME_DIR=/tmp/runtime-work \
  -e HF_HOME=/home/hungyu/work_ws/.cache/huggingface \
  -e TRANSFORMERS_CACHE=/home/hungyu/work_ws/.cache/huggingface \
  -v "${XAUTH}:${XAUTH}:rw" \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "${HOST_WS}:${HOST_WS}:rw" \
  -w "${HOST_WS}" \
  "${IMAGE_NAME}"