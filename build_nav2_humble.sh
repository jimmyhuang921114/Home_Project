#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${IMAGE_NAME:-home-project-nav2:humble}"

docker build \
  --file "${SCRIPT_DIR}/Dockerfile.nav2-humble" \
  --build-context "retrieval=${SCRIPT_DIR}/../Home_Project/src/robot_object_retrieval" \
  --build-arg "USERNAME=$(id -un)" \
  --build-arg "UID=$(id -u)" \
  --build-arg "GID=$(id -g)" \
  --tag "${IMAGE_NAME}" \
  "${SCRIPT_DIR}"

echo "IMAGE=${IMAGE_NAME}"
