#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-home-project-nav2}"
exec docker exec --interactive --tty \
  --workdir /workspace \
  --env "DISPLAY=${DISPLAY:-}" \
  "${CONTAINER_NAME}" bash
