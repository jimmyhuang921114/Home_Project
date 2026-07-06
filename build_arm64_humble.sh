#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-robot-arm64-humble-ollama:latest}"
BASE_IMAGE="${BASE_IMAGE:-nvcr.io/nvidia/l4t-jetpack:r36.4.0}"
ROS_DISTRO="${ROS_DISTRO:-humble}"
ROS_INSTALL="${ROS_INSTALL:-desktop}"
INSTALL_OLLAMA_SERVER="${INSTALL_OLLAMA_SERVER:-1}"

cd "$(dirname "$0")"

docker build \
  --platform linux/arm64 \
  -f Dockerfile.arm64-humble \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  --build-arg USERNAME=work \
  --build-arg ROS_DISTRO="${ROS_DISTRO}" \
  --build-arg ROS_INSTALL="${ROS_INSTALL}" \
  --build-arg INSTALL_OLLAMA_SERVER="${INSTALL_OLLAMA_SERVER}" \
  -t "${IMAGE_NAME}" .

echo ""
echo "[OK] built ARM64 image: ${IMAGE_NAME}"
echo "[INFO] base image: ${BASE_IMAGE}"
