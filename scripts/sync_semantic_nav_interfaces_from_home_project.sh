#!/usr/bin/env bash
set -euo pipefail

HOME_PROJECT_ROOT="${HOME_PROJECT_ROOT:-/home/iclab/home_project_ws/Home_Project}"
THOR_ROOT="${THOR_ROOT:-/home/iclab/home_project_ws/Vision_Model_Ws}"
SOURCE_PACKAGE="${HOME_PROJECT_ROOT}/src/Home_Project/semantic_nav_interfaces"
TARGET_PACKAGE="${THOR_ROOT}/src/semantic_nav_interfaces"
FILES=("action/DetectSemanticObjects.action" "msg/SemanticDetection2D.msg")

for relative_path in "${FILES[@]}"; do
  source_path="${SOURCE_PACKAGE}/${relative_path}"
  target_path="${TARGET_PACKAGE}/${relative_path}"
  test -f "${source_path}" || { echo "Missing source: ${source_path}" >&2; exit 2; }
  echo "Diff before sync: ${relative_path}"
  diff -u "${target_path}" "${source_path}" || true
  install -D -m 0644 "${source_path}" "${target_path}"
  source_sha="$(sha256sum "${source_path}" | cut -d' ' -f1)"
  target_sha="$(sha256sum "${target_path}" | cut -d' ' -f1)"
  test "${source_sha}" = "${target_sha}" || { echo "SHA mismatch: ${relative_path}" >&2; exit 3; }
  echo "SHA256 ${relative_path}: ${source_sha}"
done

source_version="$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "${SOURCE_PACKAGE}/package.xml" | head -1)"
target_version="$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "${TARGET_PACKAGE}/package.xml" | head -1)"
test "${source_version}" = "0.1.0" || { echo "Unexpected Home_Project version: ${source_version}" >&2; exit 4; }
test "${target_version}" = "${source_version}" || { echo "Package version mismatch: host=${source_version} thor=${target_version}" >&2; exit 5; }
echo "Home_Project -> Thor contract sync complete; version ${source_version}."
