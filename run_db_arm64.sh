#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${PG_CONTAINER_NAME:-robot_object_pg_arm64}"
IMAGE="${PG_IMAGE:-pgvector/pgvector:pg16}"
DB_PORT="${DB_PORT:-5432}"

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "[INFO] container exists, starting: ${CONTAINER_NAME}"
  docker start "${CONTAINER_NAME}" >/dev/null
else
  echo "[INFO] creating PostgreSQL + pgvector container: ${CONTAINER_NAME}"
  docker run -dit \
    --name "${CONTAINER_NAME}" \
    --net=host \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=semantic_map \
    -v "${PWD}/pgdata:/var/lib/postgresql/data" \
    "${IMAGE}"
fi

echo "[INFO] waiting for PostgreSQL..."
for i in $(seq 1 60); do
  if docker exec "${CONTAINER_NAME}" pg_isready -U postgres -d semantic_map >/dev/null 2>&1; then
    echo "[OK] PostgreSQL ready"
    break
  fi
  sleep 1
  if [[ "$i" == "60" ]]; then
    echo "[ERROR] PostgreSQL not ready" >&2
    exit 1
  fi
done

echo "[INFO] enable pgvector extension"
docker exec -i "${CONTAINER_NAME}" psql -U postgres -d semantic_map <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
SQL

echo ""
echo "[OK] PostgreSQL + pgvector ready"
echo "DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:${DB_PORT}/semantic_map"
