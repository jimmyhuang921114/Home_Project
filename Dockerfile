# syntax=docker/dockerfile:1

FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG USERNAME=work
ARG UID=1000
ARG GID=1000

ARG ROS_DISTRO=humble
ARG ROS_INSTALL=desktop
ARG INSTALL_PIP_OPENCV=0

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Taipei

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

ENV HF_HOME=/workspace/.cache/huggingface
ENV TRANSFORMERS_CACHE=/workspace/.cache/huggingface
ENV HF_HUB_ENABLE_HF_TRANSFER=1

ENV QT_X11_NO_MITSHM=1
ENV XDG_RUNTIME_DIR=/tmp/runtime-${USERNAME}

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display

ENV ROS_DISTRO=${ROS_DISTRO}

# ------------------------------------------------------------
# Basic Ubuntu packages + OpenCV GUI dependencies
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
# Install ROS 2 Humble + common ROS packages
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
    python3-colcon-common-extensions \
    python3-vcstool \
    python3-rosdep \
    python3-argcomplete \
    python3-flake8 \
    python3-pytest-cov \
    python3-pytest \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# rosdep init
# ------------------------------------------------------------
RUN rosdep init || true \
    && rosdep update --rosdistro ${ROS_DISTRO}

# ------------------------------------------------------------
# Python AI packages
# ------------------------------------------------------------
RUN python3 -m pip install --upgrade pip setuptools wheel

# CUDA 12.8 PyTorch wheel
# 加 --ignore-installed，避免 pip 嘗試移除 apt/distutils 裝的 sympy
RUN python3 -m pip install --ignore-installed \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu128
# Important:
# 使用 apt python3-opencv，不要讓 ultralytics/supervision 自動拉 pip opencv-python
RUN python3 -m pip install \
    "numpy<2.0" \
    "transformers>=4.47.0" \
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
    scikit-image \
    scikit-learn \
    onnx \
    onnxruntime-gpu \
    pycocotools

# Install YOLO / supervision without forcing pip OpenCV
RUN python3 -m pip install --no-deps \
    ultralytics \
    supervision

# Optional pip OpenCV, only when explicitly enabled
RUN if [[ "${INSTALL_PIP_OPENCV}" == "1" ]]; then \
        python3 -m pip install opencv-python ; \
    fi

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
    mkdir -p /workspace/src /workspace/work_ws/src /workspace/.cache/huggingface "${XDG_RUNTIME_DIR}"; \
    chown -R "${USERNAME}:${GID}" /workspace "${XDG_RUNTIME_DIR}"; \
    chmod 700 "${XDG_RUNTIME_DIR}"

# ------------------------------------------------------------
# Auto source ROS and workspace
# ------------------------------------------------------------
# RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /home/${USERNAME}/.bashrc \
#     && echo "if [ -f /workspace/work_ws/install/setup.bash ]; then source /workspace/work_ws/install/setup.bash; fi" >> /home/${USERNAME}/.bashrc \
#     && echo "export ROS_DISTRO=${ROS_DISTRO}" >> /home/${USERNAME}/.bashrc \
#     && echo "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" >> /home/${USERNAME}/.bashrc \
#     && echo "export HF_HOME=/workspace/.cache/huggingface" >> /home/${USERNAME}/.bashrc \
#     && echo "export TRANSFORMERS_CACHE=/workspace/.cache/huggingface" >> /home/${USERNAME}/.bashrc \
#     && echo "export QT_X11_NO_MITSHM=1" >> /home/${USERNAME}/.bashrc \
#     && chown ${USERNAME}:${USERNAME} /home/${USERNAME}/.bashrc

# ------------------------------------------------------------
# Build-time checks
# ------------------------------------------------------------
RUN source /opt/ros/${ROS_DISTRO}/setup.bash && \
    python3 -c "import sys, torch, cv2, numpy as np; \
print('Python:', sys.version); \
print('Torch:', torch.__version__); \
print('Torch CUDA build:', torch.version.cuda); \
print('OpenCV:', cv2.__version__); \
print('cv2 path:', cv2.__file__); \
print('NumPy:', np.__version__)" && \
    ros2 --help > /tmp/ros2_help.txt && \
    ros2 pkg list | grep cv_bridge && \
    ros2 pkg list | grep image_transport && \
    ros2 pkg list | grep rosbridge_suite && \
    nvcc --version

USER ${USERNAME}
WORKDIR /workspace/work_ws

CMD ["/bin/bash"]