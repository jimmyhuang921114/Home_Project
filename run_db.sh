#!/usr/bin/env bash
set -e

# ─────────────────────────────────────────────
# PostgreSQL + pgvector
# ─────────────────────────────────────────────
PG_CONTAINER_NAME="robot_object_pg"
PG_IMAGE="pgvector/pgvector:pg16"
PG_VOLUME="robot_object_pg_data"

POSTGRES_USER="postgres"
POSTGRES_PASSWORD="postgres"
POSTGRES_DB="robot_db"
POSTGRES_PORT="5432"

# ─────────────────────────────────────────────
# Ollama
# ─────────────────────────────────────────────
OLLAMA_CONTAINER_NAME="robot_object_ollama"
OLLAMA_IMAGE="ollama/ollama:latest"
OLLAMA_VOLUME="robot_object_ollama_data"
OLLAMA_PORT="11434"

echo "[INFO] Start PostgreSQL + pgvector"

if docker ps -a --format '{{.Names}}' | grep -qx "${PG_CONTAINER_NAME}"; then
  echo "[INFO] PostgreSQL container exists, starting: ${PG_CONTAINER_NAME}"
  docker start "${PG_CONTAINER_NAME}" >/dev/null
else
  echo "[INFO] creating PostgreSQL container: ${PG_CONTAINER_NAME}"

  docker run -d \
    --name "${PG_CONTAINER_NAME}" \
    -e POSTGRES_USER="${POSTGRES_USER}" \
    -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
    -e POSTGRES_DB="${POSTGRES_DB}" \
    -p "${POSTGRES_PORT}:5432" \
    -v "${PG_VOLUME}:/var/lib/postgresql/data" \
    "${PG_IMAGE}" >/dev/null
fi

echo "[INFO] waiting for PostgreSQL..."

for i in $(seq 1 40); do
  if docker exec "${PG_CONTAINER_NAME}" \
      pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    echo "[OK] PostgreSQL ready"
    break
  fi

  if [ "$i" = "40" ]; then
    echo "ERROR: PostgreSQL not ready"
    echo "Try:"
    echo "  docker logs ${PG_CONTAINER_NAME}"
    exit 1
  fi

  sleep 1
done

echo "[INFO] enable pgvector extension"

docker exec "${PG_CONTAINER_NAME}" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo ""
echo "[OK] PostgreSQL + pgvector ready"
echo ""

# ─────────────────────────────────────────────
# Start Ollama
# ─────────────────────────────────────────────
echo "[INFO] Start Ollama"

if docker ps -a --format '{{.Names}}' | grep -qx "${OLLAMA_CONTAINER_NAME}"; then
  echo "[INFO] Ollama container exists, starting: ${OLLAMA_CONTAINER_NAME}"
  docker start "${OLLAMA_CONTAINER_NAME}" >/dev/null
else
  echo "[INFO] creating Ollama container: ${OLLAMA_CONTAINER_NAME}"

  docker run -d \
    --name "${OLLAMA_CONTAINER_NAME}" \
    --restart unless-stopped \
    --gpus all \
    --network host \
    -v "${OLLAMA_VOLUME}:/root/.ollama" \
    "${OLLAMA_IMAGE}" >/dev/null
fi

echo "[INFO] waiting for Ollama..."

for i in $(seq 1 40); do
  if docker exec "${OLLAMA_CONTAINER_NAME}" ollama list >/dev/null 2>&1; then
    echo "[OK] Ollama ready"
    break
  fi

  if [ "$i" = "40" ]; then
    echo "ERROR: Ollama not ready"
    echo "Try:"
    echo "  docker logs ${OLLAMA_CONTAINER_NAME}"
    exit 1
  fi

  sleep 1
done

echo ""
echo "[OK] Services ready"
echo ""
echo "DATABASE_URL:"
echo "  postgresql://postgres:postgres@127.0.0.1:5432/robot_db"
echo ""
echo "OLLAMA_BASE_URL:"
echo "  http://127.0.0.1:11434"
echo ""
echo "Ollama models:"
docker exec "${OLLAMA_CONTAINER_NAME}" ollama list || true
