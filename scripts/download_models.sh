#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODEL_ROOT="${PROJECT_ROOT}/models"
GDINO_DIR="${MODEL_ROOT}/hf/grounding-dino-tiny"
RAM_DIR="${MODEL_ROOT}/ram"
RAM_CKPT="${RAM_DIR}/ram_plus_swin_large_14m.pth"

GDINO_REPO="IDEA-Research/grounding-dino-tiny"
RAM_REPO="xinyu1205/recognize-anything-plus-model"
RAM_FILE="ram_plus_swin_large_14m.pth"

FORCE=0
SKIP_RAM=0

for arg in "$@"; do
  case "$arg" in
    --force)
      FORCE=1
      ;;
    --skip-ram)
      SKIP_RAM=1
      ;;
    *)
      echo "[ERROR] Unknown argument: $arg"
      echo "Usage: $0 [--force] [--skip-ram]"
      exit 1
      ;;
  esac
done

mkdir -p "${GDINO_DIR}"
mkdir -p "${RAM_DIR}"

# 用暫時 cache，下載完會刪掉，避免模型只存在 HF cache。
TMP_HF_CACHE="${MODEL_ROOT}/.hf_cache_tmp"
mkdir -p "${TMP_HF_CACHE}"

export HF_HOME="${TMP_HF_CACHE}"
export HF_HUB_CACHE="${TMP_HF_CACHE}/hub"
export TRANSFORMERS_CACHE="${TMP_HF_CACHE}/transformers"

echo "[INFO] PROJECT_ROOT = ${PROJECT_ROOT}"
echo "[INFO] MODEL_ROOT   = ${MODEL_ROOT}"
echo "[INFO] GDINO_DIR    = ${GDINO_DIR}"
echo "[INFO] RAM_DIR      = ${RAM_DIR}"
echo "[INFO] TMP_HF_CACHE = ${TMP_HF_CACHE}"
echo

python3 - <<'PY'
import importlib.util
import subprocess
import sys

pkg = "huggingface_hub"
if importlib.util.find_spec(pkg) is None:
    print("[INFO] huggingface_hub not found. Installing...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--user", "-U",
        "huggingface_hub[hf_xet]"
    ])
else:
    print("[INFO] huggingface_hub already installed.")
PY

download_gdino=1
if [ "${FORCE}" -eq 0 ]; then
  if [ -f "${GDINO_DIR}/config.json" ] && \
     find "${GDINO_DIR}" -maxdepth 2 -type f \( -name "*.safetensors" -o -name "*.bin" \) | grep -q .; then
    download_gdino=0
  fi
fi

if [ "${download_gdino}" -eq 1 ]; then
  echo "[INFO] Downloading GroundingDINO:"
  echo "       repo: ${GDINO_REPO}"
  echo "       to  : ${GDINO_DIR}"

  if [ "${FORCE}" -eq 1 ]; then
    rm -rf "${GDINO_DIR}"
    mkdir -p "${GDINO_DIR}"
  fi

  python3 - <<PY
from pathlib import Path
from huggingface_hub import snapshot_download

local_dir = Path("${GDINO_DIR}")
snapshot_download(
    repo_id="${GDINO_REPO}",
    local_dir=str(local_dir),
    token=False,
)
print("[OK] GroundingDINO downloaded to:", local_dir)
PY
else
  echo "[OK] GroundingDINO already exists. Use --force to re-download."
fi

echo

if [ "${SKIP_RAM}" -eq 1 ]; then
  echo "[WARN] Skip RAM++ download because --skip-ram was given."
else
  download_ram=1
  if [ "${FORCE}" -eq 0 ] && [ -f "${RAM_CKPT}" ]; then
    download_ram=0
  fi

  if [ "${download_ram}" -eq 1 ]; then
    echo "[INFO] Downloading RAM++ checkpoint:"
    echo "       repo: ${RAM_REPO}"
    echo "       file: ${RAM_FILE}"
    echo "       to  : ${RAM_CKPT}"

    if [ "${FORCE}" -eq 1 ]; then
      rm -f "${RAM_CKPT}"
    fi

    python3 - <<PY
from pathlib import Path
from huggingface_hub import hf_hub_download
import shutil

ram_dir = Path("${RAM_DIR}")
ram_dir.mkdir(parents=True, exist_ok=True)

src = hf_hub_download(
    repo_id="${RAM_REPO}",
    filename="${RAM_FILE}",
    token=False,
)

dst = ram_dir / "${RAM_FILE}"
if Path(src).resolve() != dst.resolve():
    shutil.copy2(src, dst)

print("[OK] RAM++ checkpoint saved to:", dst)
PY
  else
    echo "[OK] RAM++ checkpoint already exists. Use --force to re-download."
  fi
fi

# 清掉 local_dir 裡 Hugging Face 產生的 metadata cache。
find "${MODEL_ROOT}" -type d -name ".cache" -prune -exec rm -rf {} + 2>/dev/null || true

# 清掉暫時 HF cache，真正模型已經在 models/hf 和 models/ram。
rm -rf "${TMP_HF_CACHE}"

echo
echo "[INFO] Final model files:"
find "${MODEL_ROOT}" -type f \( \
  -name "*.pth" -o \
  -name "*.pt" -o \
  -name "*.bin" -o \
  -name "*.safetensors" -o \
  -name "*.json" -o \
  -name "*.txt" \
\) -printf "%s\t%p\n" 2>/dev/null \
  | sort -nr \
  | awk '{printf "%.2f GB\t%s\n", $1/1024/1024/1024, $2}' \
  | head -80

echo
echo "[OK] Done."
