# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.0-devel-ubuntu24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG USERNAME=work
ARG UID=1000
ARG GID=1000
ENV DEBIAN_FRONTEND=noninteractive ROS_DISTRO=jazzy LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
ENV ROS_DOMAIN_ID=40 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV CYCLONEDDS_URI=file:///etc/cyclonedds/cyclonedds.xml
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display

RUN apt-get update && apt-get install -y --no-install-recommends \
    locales curl ca-certificates gnupg lsb-release software-properties-common \
    && locale-gen en_US.UTF-8 \
    && curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu noble main" \
      > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-desktop ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-depth-image-proc \
      ros-jazzy-image-transport-plugins ros-jazzy-rqt-tf-tree \
      ros-jazzy-gtsam \
      ros-dev-tools python3-vcstool python3-colcon-common-extensions python3-rosdep \
      python3-pip python3-pytest python3-yaml python3-numpy python3-opencv \
      build-essential cmake ninja-build git git-lfs curl wget x11-apps x11-utils mesa-utils iproute2 \
      nlohmann-json3-dev libgoogle-glog-dev libcli11-dev libeigen3-dev libzmq5-dev \
      libx11-xcb1 libxcb-xinerama0 libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

# Hydra's C++ workspace builds Spark-DSG as a CMake dependency, but that build
# does not enable/install the Python bindings used by offline graph auditing.
# Keep the binding version locked to the workspace's Spark-DSG 1.1.3 source.
RUN python3 -m pip install --break-system-packages --no-cache-dir \
      spark-dsg==1.1.3

RUN existing_group="$(getent group "${GID}" | cut -d: -f1 || true)" \
    && if [[ -n "${existing_group}" && "${existing_group}" != "${USERNAME}" ]]; then groupmod -n "${USERNAME}" "${existing_group}"; elif [[ -z "${existing_group}" ]]; then groupadd --gid "${GID}" "${USERNAME}"; fi \
    && existing_user="$(getent passwd "${UID}" | cut -d: -f1 || true)" \
    && if [[ -n "${existing_user}" && "${existing_user}" != "${USERNAME}" ]]; then usermod -l "${USERNAME}" -d "/home/${USERNAME}" -m "${existing_user}"; elif [[ -z "${existing_user}" ]]; then useradd --uid "${UID}" --gid "${GID}" --create-home --shell /bin/bash "${USERNAME}"; fi \
    && usermod --gid "${GID}" --shell /bin/bash "${USERNAME}" \
    && mkdir -p /workspace/Hydra_Ws /workspace/home_project_runtime /etc/cyclonedds \
    && chown -R "${UID}:${GID}" /workspace

COPY cyclonedds.xml /etc/cyclonedds/cyclonedds.xml
COPY entrypoint.sh /usr/local/bin/hydra-entrypoint
RUN chmod 0755 /usr/local/bin/hydra-entrypoint && rosdep init || true
USER ${USERNAME}
WORKDIR /workspace/Hydra_Ws
ENTRYPOINT ["/usr/local/bin/hydra-entrypoint"]
CMD ["bash"]
