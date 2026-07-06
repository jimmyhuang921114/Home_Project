#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GDINO_MODEL="${PROJECT_ROOT}/models/hf/grounding-dino-tiny"
RAM_REPO="${PROJECT_ROOT}/src/recognize-anything"
RAM_CKPT="${PROJECT_ROOT}/models/ram/ram_plus_swin_large_14m.pth"

IMAGE_TOPIC="${IMAGE_TOPIC:-/realsense/rgb}"
DEPTH_TOPIC="${DEPTH_TOPIC:-/realsense/depth}"
CAMERA_INFO_TOPIC="${CAMERA_INFO_TOPIC:-/realsense/camera_info}"
TARGET_FRAME="${TARGET_FRAME:-map}"
CAMERA_FRAME_OVERRIDE="${CAMERA_FRAME_OVERRIDE:-Camera_OmniVision_OV9782_Color}"

if [ ! -d "${GDINO_MODEL}" ]; then
  echo "[ERROR] GroundingDINO local model not found:"
  echo "        ${GDINO_MODEL}"
  echo
  echo "Run:"
  echo "  ${PROJECT_ROOT}/scripts/download_models.sh"
  exit 1
fi

if [ ! -f "${GDINO_MODEL}/config.json" ]; then
  echo "[ERROR] GroundingDINO config.json not found:"
  echo "        ${GDINO_MODEL}/config.json"
  echo
  echo "Run:"
  echo "  ${PROJECT_ROOT}/scripts/download_models.sh --force"
  exit 1
fi

if ! find "${GDINO_MODEL}" -maxdepth 2 -type f \( -name "*.safetensors" -o -name "*.bin" \) | grep -q .; then
  echo "[ERROR] GroundingDINO weight file not found in:"
  echo "        ${GDINO_MODEL}"
  echo
  echo "Run:"
  echo "  ${PROJECT_ROOT}/scripts/download_models.sh --force"
  exit 1
fi

if [ ! -d "${RAM_REPO}/ram" ]; then
  echo "[ERROR] RAM repo not found:"
  echo "        ${RAM_REPO}/ram"
  exit 1
fi

if [ ! -f "${RAM_CKPT}" ]; then
  echo "[ERROR] RAM++ checkpoint not found:"
  echo "        ${RAM_CKPT}"
  echo
  echo "Run:"
  echo "  ${PROJECT_ROOT}/scripts/download_models.sh"
  exit 1
fi

# ROS setup scripts may reference unset variables.
# Temporarily disable nounset around source.
set +u
source /opt/ros/humble/setup.bash
source "${PROJECT_ROOT}/install/setup.bash"
set -u

export PYTHONPATH="${RAM_REPO}:${PYTHONPATH:-}"

# 強制 Hugging Face / Transformers 離線使用。
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "[INFO] PROJECT_ROOT          = ${PROJECT_ROOT}"
echo "[INFO] GDINO_MODEL           = ${GDINO_MODEL}"
echo "[INFO] RAM_REPO              = ${RAM_REPO}"
echo "[INFO] RAM_CKPT              = ${RAM_CKPT}"
echo "[INFO] IMAGE_TOPIC           = ${IMAGE_TOPIC}"
echo "[INFO] DEPTH_TOPIC           = ${DEPTH_TOPIC}"
echo "[INFO] CAMERA_INFO_TOPIC     = ${CAMERA_INFO_TOPIC}"
echo "[INFO] TARGET_FRAME          = ${TARGET_FRAME}"
echo "[INFO] CAMERA_FRAME_OVERRIDE = ${CAMERA_FRAME_OVERRIDE}"
echo

ros2 launch main_policy vision_mapping.launch.py \
  image_topic:="${IMAGE_TOPIC}" \
  depth_topic:="${DEPTH_TOPIC}" \
  camera_info_topic:="${CAMERA_INFO_TOPIC}" \
  target_frame:="${TARGET_FRAME}" \
  camera_frame_override:="${CAMERA_FRAME_OVERRIDE}" \
  hf_model_name:="${GDINO_MODEL}" \
  ram_repo_path:="${RAM_REPO}" \
  pretrained_path:="${RAM_CKPT}" \
  use_ram_tags:=true \
  trigger_ram_before_det:=true
