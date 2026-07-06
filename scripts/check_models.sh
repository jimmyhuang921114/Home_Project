#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GDINO_DIR="${PROJECT_ROOT}/models/hf/grounding-dino-tiny"
RAM_CKPT="${PROJECT_ROOT}/models/ram/ram_plus_swin_large_14m.pth"
RAM_REPO="${PROJECT_ROOT}/src/recognize-anything"

echo "[INFO] PROJECT_ROOT = ${PROJECT_ROOT}"
echo "[INFO] GDINO_DIR    = ${GDINO_DIR}"
echo "[INFO] RAM_CKPT     = ${RAM_CKPT}"
echo "[INFO] RAM_REPO     = ${RAM_REPO}"
echo

ok=1

echo "=== GroundingDINO local files ==="
if [ ! -d "${GDINO_DIR}" ]; then
  echo "[ERROR] Missing directory: ${GDINO_DIR}"
  ok=0
else
  find "${GDINO_DIR}" -maxdepth 2 -type f -printf "%s\t%p\n" \
    | sort -nr \
    | awk '{printf "%.2f GB\t%s\n", $1/1024/1024/1024, $2}' \
    | head -40

  if [ ! -f "${GDINO_DIR}/config.json" ]; then
    echo "[ERROR] Missing GroundingDINO config.json"
    ok=0
  fi

  if ! find "${GDINO_DIR}" -maxdepth 2 -type f \( -name "*.safetensors" -o -name "*.bin" \) | grep -q .; then
    echo "[ERROR] Missing GroundingDINO weight file: *.safetensors or *.bin"
    ok=0
  fi
fi

echo
echo "=== RAM++ checkpoint ==="
if [ ! -f "${RAM_CKPT}" ]; then
  echo "[ERROR] Missing RAM++ checkpoint: ${RAM_CKPT}"
  ok=0
else
  ls -lh "${RAM_CKPT}"
fi

echo
echo "=== RAM Python import ==="
if [ ! -d "${RAM_REPO}/ram" ]; then
  echo "[ERROR] Missing RAM repo package: ${RAM_REPO}/ram"
  ok=0
else
  export PYTHONPATH="${RAM_REPO}:${PYTHONPATH:-}"
  python3 - <<'PY'
from ram import get_transform
print("[OK] RAM import OK")
PY
fi

echo
echo "=== Transformers local load check ==="
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

python3 - <<PY
from transformers import AutoProcessor, AutoModel
path = "${GDINO_DIR}"
processor = AutoProcessor.from_pretrained(path, local_files_only=True)
model = AutoModel.from_pretrained(path, local_files_only=True)
print("[OK] GroundingDINO local load OK")
print("model class:", model.__class__.__name__)
PY

echo
if [ "${ok}" -eq 1 ]; then
  echo "[OK] All checks passed."
else
  echo "[ERROR] Some checks failed."
  exit 1
fi
