#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-robot-thor-jp7-jazzy-ollama:latest}"
BASE_IMAGE="${BASE_IMAGE:-nvcr.io/nvidia/cuda:13.0.2-devel-ubuntu24.04}"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_INSTALL="${ROS_INSTALL:-desktop}"
INSTALL_OLLAMA_SERVER="${INSTALL_OLLAMA_SERVER:-1}"

cd "$(dirname "$0")"

docker build \
  --platform linux/arm64 \
  -f Dockerfile.thor-jp7-jazzy \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  --build-arg USERNAME=work \
  --build-arg ROS_DISTRO="${ROS_DISTRO}" \
  --build-arg ROS_INSTALL="${ROS_INSTALL}" \
  --build-arg INSTALL_OLLAMA_SERVER="${INSTALL_OLLAMA_SERVER}" \
  -t "${IMAGE_NAME}" .

echo ""
echo "[OK] built Thor JP7/Jazzy ARM64 image: ${IMAGE_NAME}"
echo "[INFO] base image: ${BASE_IMAGE}"
