#!/usr/bin/env bash
set -e

IMAGE_NAME="hf-vision-cu128:latest"

cd "$(dirname "$0")"

docker build \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  --build-arg USERNAME=work \
  --build-arg ROS_DISTRO=humble \
  --build-arg ROS_INSTALL=desktop \
  -t "${IMAGE_NAME}" .

echo ""
echo "[OK] built image: ${IMAGE_NAME}"
