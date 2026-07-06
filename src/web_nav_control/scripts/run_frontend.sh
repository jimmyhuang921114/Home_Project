#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PROJECT_ROOT="${HOME_PROJECT_ROOT:-${PROJECT_ROOT}}"
cd "${PROJECT_ROOT}/src/web_nav_control/frontend"
npm run dev -- --host 0.0.0.0
