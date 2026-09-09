#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export HOST_UID="$(id -u)" HOST_GID="$(id -g)"
docker compose build
