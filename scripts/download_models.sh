#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

MODEL_ROOT="${PROJECT_ROOT}/models"

HF_DIR="${MODEL_ROOT}/hf"
GDINO_DIR="${HF_DIR}/grounding-dino-tiny"
BERT_DIR="${HF_DIR}/bert-base-uncased"

RAM_DIR="${MODEL_ROOT}/ram"
RAM_CKPT="${RAM_DIR}/ram_plus_swin_large_14m.pth"

GDINO_REPO="IDEA-Research/grounding-dino-tiny"
BERT_REPO="bert-base-uncased"

RAM_REPO="xinyu1205/recognize-anything-plus-model"
RAM_FILE="ram_plus_swin_large_14m.pth"

RAM_UTILS_PY="${PROJECT_ROOT}/src/recognize-anything/ram/models/utils.py"

FORCE=0
SKIP_GDINO=0
SKIP_BERT=0
SKIP_RAM=0
PATCH_RAM=1

for arg in "$@"; do
  case "$arg" in
    --force)
      FORCE=1
      ;;
    --skip-gdino)
      SKIP_GDINO=1
      ;;
    --skip-bert)
      SKIP_BERT=1
      ;;
    --skip-ram)
      SKIP_RAM=1
      ;;
    --no-patch-ram)
      PATCH_RAM=0
      ;;
    -h|--help)
      echo "Usage: $0 [--force] [--skip-gdino] [--skip-bert] [--skip-ram] [--no-patch-ram]"
      echo
      echo "Env:"
      echo "  PYTHON_BIN=/usr/bin/python3"
      echo "  HF_TOKEN=xxxx optional"
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $arg"
      echo "Usage: $0 [--force] [--skip-gdino] [--skip-bert] [--skip-ram] [--no-patch-ram]"
      exit 1
      ;;
  esac
done

mkdir -p "${GDINO_DIR}"
mkdir -p "${BERT_DIR}"
mkdir -p "${RAM_DIR}"

# 用暫時 cache，下載完會刪掉，避免模型只存在 Hugging Face cache。
TMP_HF_CACHE="${MODEL_ROOT}/.hf_cache_tmp"
mkdir -p "${TMP_HF_CACHE}"

export HF_HOME="${TMP_HF_CACHE}"
export HF_HUB_CACHE="${TMP_HF_CACHE}/hub"
export HUGGINGFACE_HUB_CACHE="${TMP_HF_CACHE}/hub"
export TRANSFORMERS_CACHE="${TMP_HF_CACHE}/transformers"

echo "[INFO] PROJECT_ROOT = ${PROJECT_ROOT}"
echo "[INFO] PYTHON_BIN    = ${PYTHON_BIN}"
echo "[INFO] MODEL_ROOT    = ${MODEL_ROOT}"
echo "[INFO] GDINO_DIR     = ${GDINO_DIR}"
echo "[INFO] BERT_DIR      = ${BERT_DIR}"
echo "[INFO] RAM_DIR       = ${RAM_DIR}"
echo "[INFO] TMP_HF_CACHE  = ${TMP_HF_CACHE}"
echo "[INFO] PATCH_RAM     = ${PATCH_RAM}"
echo

"${PYTHON_BIN}" - <<'PY'
import importlib.util
import subprocess
import sys

pkgs = [
    ("huggingface_hub", "huggingface_hub[hf_xet]"),
]

for import_name, pip_name in pkgs:
    if importlib.util.find_spec(import_name) is None:
        print(f"[INFO] {import_name} not found. Installing {pip_name}...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--user", "-U", pip_name
        ])
    else:
        print(f"[INFO] {import_name} already installed.")
PY

download_gdino=1
if [ "${FORCE}" -eq 0 ]; then
  if [ -f "${GDINO_DIR}/config.json" ] && \
     find "${GDINO_DIR}" -maxdepth 2 -type f \( -name "*.safetensors" -o -name "*.bin" \) | grep -q .; then
    download_gdino=0
  fi
fi

if [ "${SKIP_GDINO}" -eq 1 ]; then
  echo "[WARN] Skip GroundingDINO download because --skip-gdino was given."
else
  if [ "${download_gdino}" -eq 1 ]; then
    echo "[INFO] Downloading GroundingDINO:"
    echo "       repo: ${GDINO_REPO}"
    echo "       to  : ${GDINO_DIR}"

    if [ "${FORCE}" -eq 1 ]; then
      rm -rf "${GDINO_DIR}"
      mkdir -p "${GDINO_DIR}"
    fi

    "${PYTHON_BIN}" - <<PY
from pathlib import Path
import os
from huggingface_hub import snapshot_download

local_dir = Path("${GDINO_DIR}")
token = os.environ.get("HF_TOKEN") or None

snapshot_download(
    repo_id="${GDINO_REPO}",
    local_dir=str(local_dir),
    token=token,
)

print("[OK] GroundingDINO downloaded to:", local_dir)
PY
  else
    echo "[OK] GroundingDINO already exists. Use --force to re-download."
  fi

  # 有些 transformers / AutoProcessor 會找 processor_config.json。
  # 如果 repo 只有 preprocessor_config.json，就複製一份。
  if [ -f "${GDINO_DIR}/preprocessor_config.json" ] && [ ! -f "${GDINO_DIR}/processor_config.json" ]; then
    cp "${GDINO_DIR}/preprocessor_config.json" "${GDINO_DIR}/processor_config.json"
    echo "[OK] Created processor_config.json from preprocessor_config.json"
  fi
fi

echo

download_bert=1
if [ "${FORCE}" -eq 0 ]; then
  if [ -f "${BERT_DIR}/vocab.txt" ] && [ -f "${BERT_DIR}/tokenizer_config.json" ]; then
    download_bert=0
  fi
fi

if [ "${SKIP_BERT}" -eq 1 ]; then
  echo "[WARN] Skip bert-base-uncased download because --skip-bert was given."
else
  if [ "${download_bert}" -eq 1 ]; then
    echo "[INFO] Downloading BERT tokenizer for RAM:"
    echo "       repo: ${BERT_REPO}"
    echo "       to  : ${BERT_DIR}"

    if [ "${FORCE}" -eq 1 ]; then
      rm -rf "${BERT_DIR}"
      mkdir -p "${BERT_DIR}"
    fi

    "${PYTHON_BIN}" - <<PY
from pathlib import Path
import os
from huggingface_hub import snapshot_download

local_dir = Path("${BERT_DIR}")
token = os.environ.get("HF_TOKEN") or None

snapshot_download(
    repo_id="${BERT_REPO}",
    local_dir=str(local_dir),
    token=token,
    allow_patterns=[
        "config.json",
        "vocab.txt",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    ],
)

print("[OK] bert-base-uncased tokenizer downloaded to:", local_dir)
PY
  else
    echo "[OK] bert-base-uncased already exists. Use --force to re-download."
  fi
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

    "${PYTHON_BIN}" - <<PY
from pathlib import Path
from huggingface_hub import hf_hub_download
import os
import shutil

ram_dir = Path("${RAM_DIR}")
ram_dir.mkdir(parents=True, exist_ok=True)

token = os.environ.get("HF_TOKEN") or None

src = hf_hub_download(
    repo_id="${RAM_REPO}",
    filename="${RAM_FILE}",
    token=token,
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

echo

if [ "${PATCH_RAM}" -eq 1 ]; then
  echo "[INFO] Patching RAM to use local bert-base-uncased tokenizer..."

  if [ ! -f "${RAM_UTILS_PY}" ]; then
    echo "[WARN] RAM utils.py not found:"
    echo "       ${RAM_UTILS_PY}"
    echo "       Skip RAM patch."
  else
    "${PYTHON_BIN}" - <<PY
from pathlib import Path
import re

path = Path("${RAM_UTILS_PY}")
bert_dir = "${BERT_DIR}"

text = path.read_text()

backup = path.with_suffix(path.suffix + ".bak_local_bert")
if not backup.exists():
    backup.write_text(text)
    print("[OK] Backup created:", backup)

pattern = r'BertTokenizer\\.from_pretrained\\((.*?)\\)'
replacement = f'BertTokenizer.from_pretrained("{bert_dir}", local_files_only=True)'

new_text, n = re.subn(pattern, replacement, text, count=1)

if n == 0:
    print("[WARN] Could not patch automatically. Current BertTokenizer lines:")
    for i, line in enumerate(text.splitlines(), 1):
        if "BertTokenizer.from_pretrained" in line:
            print(f"{i}: {line}")
else:
    path.write_text(new_text)
    print("[OK] Patched:", path)
    for i, line in enumerate(new_text.splitlines(), 1):
        if "BertTokenizer.from_pretrained" in line:
            print(f"[CHECK] {i}: {line}")
PY
  fi
else
  echo "[WARN] Skip RAM patch because --no-patch-ram was given."
fi

echo

# 清掉 local_dir 裡 Hugging Face 產生的 metadata cache。
find "${MODEL_ROOT}" -type d -name ".cache" -prune -exec rm -rf {} + 2>/dev/null || true

# 清掉暫時 HF cache，真正模型已經在 models/hf 和 models/ram。
rm -rf "${TMP_HF_CACHE}"

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
  | head -120

echo
echo "[INFO] Quick checks:"
if [ -f "${GDINO_DIR}/config.json" ]; then
  echo "[OK] GroundingDINO config exists."
else
  echo "[WARN] GroundingDINO config missing."
fi

if [ -f "${GDINO_DIR}/processor_config.json" ]; then
  echo "[OK] GroundingDINO processor_config.json exists."
else
  echo "[WARN] GroundingDINO processor_config.json missing."
fi

if [ -f "${BERT_DIR}/vocab.txt" ]; then
  echo "[OK] BERT vocab.txt exists."
else
  echo "[WARN] BERT vocab.txt missing."
fi

if [ -f "${RAM_CKPT}" ]; then
  echo "[OK] RAM++ checkpoint exists."
else
  echo "[WARN] RAM++ checkpoint missing."
fi

echo
echo "[OK] Done."