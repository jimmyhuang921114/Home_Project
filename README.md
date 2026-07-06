# ARM64 Jetson/Thor Docker package

這包是從你原本的 x86 `hf-vision-cu128` Docker 思路改出來的 ARM64 版本，重點是：

- ARM64 / aarch64
- ROS 2 Humble + Nav2，預設給 JetPack 6 / Ubuntu 22.04
- 加入 robot_object_retrieval 常用依賴：`psycopg[binary]==3.2.9`、`python-dotenv==1.0.1`、`PyYAML>=6,<7`、`textual>=0.89.1,<2.0`
- 加入 `ollama` Python client
- 可選擇把 Ollama ARM64 server binary 裝進 container
- 保留 PostgreSQL / pgvector 的 `DATABASE_URL`
- 保留 GUI / RViz / X11 / host network / persistent container 行為

## 先確認你的機器

在 Thor/Jetson 上先跑：

```bash
uname -m
cat /etc/nv_tegra_release || true
cat /etc/os-release
```

如果是 JetPack 6 / L4T r36 / Ubuntu 22.04，用預設 Humble 版：

```bash
./build_arm64_humble.sh
./run_db_arm64.sh
./run_arm64.sh
```

如果是 Thor JetPack 7 / L4T r38 / Ubuntu 24.04，ROS Humble 不建議直接 apt 裝。請改用 Jazzy 實驗版：

```bash
./build_thor_jp7_jazzy.sh
IMAGE_NAME=robot-thor-jp7-jazzy-ollama:latest ROS_DISTRO=jazzy ./run_arm64.sh
```

## 預設 Humble build

```bash
cd ~/work_ws/docker_arm64_thor
./build_arm64_humble.sh
```

可覆蓋 base image：

```bash
BASE_IMAGE=nvcr.io/nvidia/l4t-jetpack:r36.4.0 ./build_arm64_humble.sh
```

不想在 container 裝 Ollama server，只保留 Python client：

```bash
INSTALL_OLLAMA_SERVER=0 ./build_arm64_humble.sh
```

## Run container

```bash
./run_arm64.sh
```

預設不在同一個 container 啟動 `ollama serve`。如果你的 Ollama 是裝在 host 或另一個 container，保持：

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
./run_arm64.sh
```

如果你想讓這個 container 自己啟動 Ollama server：

```bash
OLLAMA_IN_CONTAINER=1 ./run_arm64.sh
```

進 container 後測試：

```bash
./check_inside_container.sh
```

## PostgreSQL + pgvector

```bash
./run_db_arm64.sh
```

會使用：

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/semantic_map
```

## 注意：PyTorch / CUDA

這包沒有用 x86 的：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

原因是 ARM64 Jetson/Thor 的 PyTorch CUDA wheel 需要對應 JetPack/L4T 版本。若你之後要跑 GroundingDINO/RAM/YOLO 之類的大模型，建議用 NVIDIA/Jetson 對應的 PyTorch container 當 base，或另外安裝 Jetson 對應 wheel。

## 檔案說明

```text
Dockerfile.arm64-humble      # JetPack 6 / Ubuntu 22.04 / ROS Humble 預設版
Dockerfile.thor-jp7-jazzy    # Thor JetPack 7 / Ubuntu 24.04 / ROS Jazzy 實驗版
requirements.robot_object.txt
build_arm64_humble.sh
build_thor_jp7_jazzy.sh
run_arm64.sh
run_db_arm64.sh
check_inside_container.sh
```
