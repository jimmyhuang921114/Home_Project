#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
touch /tmp/.docker.xauth
export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
docker compose up -d
