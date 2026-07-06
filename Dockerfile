# syntax=docker/dockerfile:1

FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG USERNAME=work
ARG UID=1000
ARG GID=1000

ARG ROS_DISTRO=humble
ARG ROS_INSTALL=desktop
ARG INSTALL_PIP_OPENCV=0

ARG NUMPY_VERSION=1.26.4
ARG TRANSFORMERS_VERSION=4.47.1
ARG FAIRSCALE_VERSION=0.4.13

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Taipei

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

ENV USERNAME=${USERNAME}

ENV HF_HOME=/workspace/.cache/huggingface
ENV HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface
ENV TRANSFORMERS_CACHE=/workspace/.cache/huggingface
ENV HF_HUB_ENABLE_HF_TRANSFER=1

ENV QT_X11_NO_MITSHM=1
ENV XDG_RUNTIME_DIR=/tmp/runtime-${USERNAME}

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display

ENV ROS_DISTRO=${ROS_DISTRO}
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# ------------------------------------------------------------
# Basic Ubuntu packages + GUI + DB client
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales \
    tzdata \
    sudo \
    curl \
    wget \
    git \
    vim \
    nano \
    gnupg \
    lsb-release \
    ca-certificates \
    software-properties-common \
    build-essential \
    pkg-config \
    cmake \
    ninja-build \
    ffmpeg \
    x11-apps \
    mesa-utils \
    iputils-ping \
    net-tools \
    dnsutils \
    postgresql-client \
    libpq-dev \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    python-is-python3 \
    python3-opencv \
    libopencv-dev \
    libgl1 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libdbus-1-3 \
    libxkbcommon-x11-0 \
    libx11-xcb1 \
    libxcb1 \
    libxcb-glx0 \
    libxcb-shm0 \
    libxcb-render0 \
    libxcb-render-util0 \
    libxcb-randr0 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-icccm4 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libgtk2.0-0 \
    libgtk-3-0 \
    qtbase5-dev \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
    && add-apt-repository universe \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Add ROS 2 apt source
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}') \
    && curl -fsSL -o /tmp/ros2-apt-source.deb \
        "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb" \
    && dpkg -i /tmp/ros2-apt-source.deb \
    && rm /tmp/ros2-apt-source.deb \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Install ROS 2 Humble + Nav2
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-${ROS_DISTRO}-${ROS_INSTALL} \
    ros-${ROS_DISTRO}-cv-bridge \
    ros-${ROS_DISTRO}-vision-opencv \
    ros-${ROS_DISTRO}-image-transport \
    ros-${ROS_DISTRO}-image-transport-plugins \
    ros-${ROS_DISTRO}-image-geometry \
    ros-${ROS_DISTRO}-tf2 \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-tf2-tools \
    ros-${ROS_DISTRO}-tf-transformations \
    ros-${ROS_DISTRO}-robot-state-publisher \
    ros-${ROS_DISTRO}-joint-state-publisher \
    ros-${ROS_DISTRO}-xacro \
    ros-${ROS_DISTRO}-rqt-image-view \
    ros-${ROS_DISTRO}-rqt-graph \
    ros-${ROS_DISTRO}-rqt-tf-tree \
    ros-${ROS_DISTRO}-rviz2 \
    ros-${ROS_DISTRO}-rosbridge-suite \
    ros-${ROS_DISTRO}-teleop-twist-keyboard \
    ros-${ROS_DISTRO}-demo-nodes-py \
    ros-${ROS_DISTRO}-demo-nodes-cpp \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-navigation2 \
    ros-${ROS_DISTRO}-nav2-bringup \
    ros-${ROS_DISTRO}-nav2-msgs \
    ros-${ROS_DISTRO}-nav2-common \
    ros-${ROS_DISTRO}-nav2-util \
    ros-${ROS_DISTRO}-nav2-map-server \
    ros-${ROS_DISTRO}-nav2-amcl \
    ros-${ROS_DISTRO}-nav2-lifecycle-manager \
    ros-${ROS_DISTRO}-nav2-planner \
    ros-${ROS_DISTRO}-nav2-controller \
    ros-${ROS_DISTRO}-nav2-behaviors \
    ros-${ROS_DISTRO}-nav2-bt-navigator \
    ros-${ROS_DISTRO}-nav2-waypoint-follower \
    ros-${ROS_DISTRO}-nav2-smoother \
    ros-${ROS_DISTRO}-nav2-costmap-2d \
    ros-${ROS_DISTRO}-nav2-voxel-grid \
    ros-${ROS_DISTRO}-nav2-regulated-pure-pursuit-controller \
    ros-${ROS_DISTRO}-nav2-smac-planner \
    ros-${ROS_DISTRO}-nav2-theta-star-planner \
    ros-${ROS_DISTRO}-nav2-dwb-controller \
    ros-${ROS_DISTRO}-nav2-simple-commander \
    ros-${ROS_DISTRO}-slam-toolbox \
    ros-${ROS_DISTRO}-map-msgs \
    ros-${ROS_DISTRO}-diagnostic-updater \
    python3-colcon-common-extensions \
    python3-vcstool \
    python3-rosdep \
    python3-argcomplete \
    python3-flake8 \
    python3-pytest-cov \
    python3-pytest \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# rosdep
# ------------------------------------------------------------
RUN rosdep init || true \
    && rosdep update --rosdistro ${ROS_DISTRO}

# ------------------------------------------------------------
# Python base
# ------------------------------------------------------------
RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install backports.tarfile

# ------------------------------------------------------------
# CUDA 12.8 PyTorch
# ------------------------------------------------------------
RUN python3 -m pip install --ignore-installed \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128

# ------------------------------------------------------------
# Python AI + robot_object_retrieval dependencies
# ------------------------------------------------------------
RUN python3 -m pip install \
    "numpy==${NUMPY_VERSION}" \
    "transformers==${TRANSFORMERS_VERSION}" \
    "fairscale==${FAIRSCALE_VERSION}" \
    accelerate \
    safetensors \
    sentencepiece \
    protobuf \
    pillow \
    matplotlib \
    scipy \
    requests \
    pyyaml \
    tqdm \
    pandas \
    psutil \
    py-cpuinfo \
    huggingface_hub \
    hf_transfer \
    timm \
    einops \
    thop \
    ultralytics-thop \
    scikit-image \
    scikit-learn \
    onnx \
    onnxruntime-gpu \
    pycocotools \
    defusedxml \
    python-dotenv \
    pydantic \
    textual \
    rich \
    psycopg[binary] \
    pgvector \
    sqlalchemy \
    asyncpg \
    httpx \
    ollama

# YOLO / supervision without forcing pip OpenCV
RUN python3 -m pip install --no-deps \
    ultralytics \
    supervision

# Optional pip OpenCV
RUN if [[ "${INSTALL_PIP_OPENCV}" == "1" ]]; then \
        python3 -m pip install opencv-python ; \
    fi

# ------------------------------------------------------------
# RAM / Transformers compatibility patch helper
# ------------------------------------------------------------
RUN cat > /usr/local/bin/patch_ram_bert_compat.py <<'PY'
#!/usr/bin/env python3
from pathlib import Path
import sys

def patch_repo(repo: Path) -> bool:
    bert = repo / "ram" / "models" / "bert.py"
    if not bert.exists():
        return False

    text = bert.read_text()
    original = text

    bak = bert.with_suffix(".py.bak_transformers_compat")
    if not bak.exists():
        bak.write_text(text)

    if "all_tied_weights_keys = []  # docker transformers compatibility patch" not in text:
        needle = "class BertPreTrainedModel(PreTrainedModel):\n"
        if needle in text:
            insert = (
                needle
                + "    # docker transformers compatibility patch\n"
                + "    # Newer transformers PreTrainedModel.tie_weights() may expect this attr.\n"
                + "    all_tied_weights_keys = []  # docker transformers compatibility patch\n"
                + "    _tied_weights_keys = []\n"
            )
            text = text.replace(needle, insert, 1)

    bottom_patch = """
# docker transformers compatibility patch
try:
    BertModel.all_tied_weights_keys = []
    BertModel._tied_weights_keys = []
except NameError:
    pass
"""
    if "BertModel.all_tied_weights_keys = []" not in text:
        text += bottom_patch

    if text != original:
        bert.write_text(text)
        print(f"[patch_ram_bert_compat] patched: {bert}")
    else:
        print(f"[patch_ram_bert_compat] already compatible: {bert}")

    return True

def main():
    candidates = [Path(p) for p in sys.argv[1:] if p]

    candidates += [
        Path("/workspace/work_ws/src/recognize-anything"),
        Path("/workspace/src/recognize-anything"),
        Path("/home/jimmy/work_ws/visual/src/recognize-anything"),
        Path("/home/work/work_ws/visual/src/recognize-anything"),
    ]

    seen = set()
    found = False

    for c in candidates:
        c = c.expanduser()
        if str(c) in seen:
            continue
        seen.add(str(c))

        try:
            if patch_repo(c):
                found = True
        except Exception as e:
            print(f"[patch_ram_bert_compat] warning: failed to patch {c}: {e}")

    if not found:
        print("[patch_ram_bert_compat] no recognize-anything repo found; skip")

if __name__ == "__main__":
    main()
PY

RUN chmod +x /usr/local/bin/patch_ram_bert_compat.py

# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
RUN cat > /usr/local/bin/vision_entrypoint.sh <<'SH'
#!/usr/bin/env bash
set -e

if command -v python3 >/dev/null 2>&1; then
    python3 /usr/local/bin/patch_ram_bert_compat.py \
        "${RAM_REPO_PATH:-}" \
        "/workspace/work_ws/src/recognize-anything" \
        "/workspace/src/recognize-anything" \
        "/home/jimmy/work_ws/visual/src/recognize-anything" \
        "/home/work/work_ws/visual/src/recognize-anything" || true
fi

if [ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
    source "/opt/ros/${ROS_DISTRO}/setup.bash"
fi

if [ -f "/workspace/work_ws/install/setup.bash" ]; then
    source "/workspace/work_ws/install/setup.bash"
fi

if [ -f "/home/jimmy/work_ws/visual/install/setup.bash" ]; then
    source "/home/jimmy/work_ws/visual/install/setup.bash"
fi

exec "$@"
SH

RUN chmod +x /usr/local/bin/vision_entrypoint.sh

# ------------------------------------------------------------
# Create non-root user
# ------------------------------------------------------------
RUN set -eux; \
    groupadd -f render; \
    groupadd -f video; \
    groupadd -f dialout; \
    groupadd -f plugdev; \
    \
    if ! getent group "${GID}" >/dev/null; then \
        groupadd -g "${GID}" "${USERNAME}"; \
    fi; \
    \
    if ! id -u "${USERNAME}" >/dev/null 2>&1; then \
        if getent passwd "${UID}" >/dev/null; then \
            EXISTING_USER="$(getent passwd "${UID}" | cut -d: -f1)"; \
            usermod -l "${USERNAME}" "${EXISTING_USER}" || true; \
            usermod -d "/home/${USERNAME}" -m "${USERNAME}" || true; \
        else \
            useradd -m -u "${UID}" -g "${GID}" -s /bin/bash "${USERNAME}"; \
        fi; \
    fi; \
    \
    usermod -aG sudo,video,render,dialout,plugdev "${USERNAME}"; \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}"; \
    chmod 0440 "/etc/sudoers.d/${USERNAME}"; \
    mkdir -p \
        /workspace \
        /workspace/work_ws \
        /workspace/work_ws/src \
        /workspace/.cache/huggingface \
        /home/jimmy/work_ws \
        "${XDG_RUNTIME_DIR}"; \
    chown -R "${USERNAME}:${GID}" /workspace "${XDG_RUNTIME_DIR}"; \
    chmod 700 "${XDG_RUNTIME_DIR}"

# ------------------------------------------------------------
# Auto source ROS and workspace
# ------------------------------------------------------------
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /home/${USERNAME}/.bashrc \
    && echo "if [ -f /workspace/work_ws/install/setup.bash ]; then source /workspace/work_ws/install/setup.bash; fi" >> /home/${USERNAME}/.bashrc \
    && echo "if [ -f /home/jimmy/work_ws/visual/install/setup.bash ]; then source /home/jimmy/work_ws/visual/install/setup.bash; fi" >> /home/${USERNAME}/.bashrc \
    && echo "export ROS_DISTRO=${ROS_DISTRO}" >> /home/${USERNAME}/.bashrc \
    && echo "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" >> /home/${USERNAME}/.bashrc \
    && echo "export HF_HOME=/workspace/.cache/huggingface" >> /home/${USERNAME}/.bashrc \
    && echo "export HUGGINGFACE_HUB_CACHE=/workspace/.cache/huggingface" >> /home/${USERNAME}/.bashrc \
    && echo "export TRANSFORMERS_CACHE=/workspace/.cache/huggingface" >> /home/${USERNAME}/.bashrc \
    && echo "export QT_X11_NO_MITSHM=1" >> /home/${USERNAME}/.bashrc \
    && chown ${USERNAME}:${GID} /home/${USERNAME}/.bashrc

# ------------------------------------------------------------
# Build-time checks
# ------------------------------------------------------------
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && \
    python3 - <<'PY'
import sys
import torch
import cv2
import numpy as np
import transformers
import fairscale

from fairscale.nn.checkpoint.checkpoint_activations import checkpoint_wrapper
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

print("Python:", sys.version)
print("Torch:", torch.__version__)
print("Torch CUDA build:", torch.version.cuda)
print("CUDA available at build:", torch.cuda.is_available())
print("OpenCV:", cv2.__version__)
print("cv2 path:", cv2.__file__)
print("NumPy:", np.__version__)
print("Transformers:", transformers.__version__)
print("FairScale:", fairscale.__version__)
print("GroundingDINO HF import: OK")
print("FairScale checkpoint_wrapper import: OK")
PY

RUN source /opt/ros/${ROS_DISTRO}/setup.bash && \
    ros2 --help > /tmp/ros2_help.txt && \
    ros2 pkg list | grep cv_bridge && \
    ros2 pkg list | grep image_transport && \
    ros2 pkg list | grep rosbridge_suite && \
    ros2 pkg list | grep nav2_msgs && \
    ros2 pkg list | grep nav2_bringup && \
    ros2 pkg list | grep nav2_map_server && \
    ros2 pkg list | grep nav2_amcl && \
    nvcc --version

USER ${USERNAME}
WORKDIR /home/jimmy/work_ws/docker

ENTRYPOINT ["/usr/local/bin/vision_entrypoint.sh"]
CMD ["/bin/bash"]
