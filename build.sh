docker build \
  --build-arg UID=$(id -u) \
  --build-arg GID=$(id -g) \
  -t hf-vision-cu128:latest .