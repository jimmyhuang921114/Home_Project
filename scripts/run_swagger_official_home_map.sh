#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOME_WS="${HOME_PROJECT_ROOT:-${PROJECT_ROOT}}"
SWAGGER_WS="${SWAGGER_WS:-${PROJECT_ROOT}/../SWAGGER}"

MAP_YAML="${HOME_WS}/config/map.yaml"
OUT_DIR="${HOME_WS}/config/generated/swagger_official"

mkdir -p "${OUT_DIR}"

if [ ! -f "${MAP_YAML}" ]; then
  echo "[ERROR] map yaml not found: ${MAP_YAML}"
  exit 1
fi

if [ ! -f "${SWAGGER_WS}/scripts/generate_graph.py" ]; then
  echo "[ERROR] SWAGGER generate_graph.py not found:"
  echo "        ${SWAGGER_WS}/scripts/generate_graph.py"
  exit 1
fi

python3 - <<PY
import sys
try:
    import swagger
    print("[OK] swagger import success")
except Exception as e:
    print("[ERROR] cannot import swagger")
    print(e)
    print("")
    print("Run this inside docker first:")
    print("  cd ${SWAGGER_WS}")
    print("  python3 -m pip install -e .")
    sys.exit(1)
PY

readarray -t MAP_INFO < <(python3 - <<PY
from pathlib import Path
import yaml

map_yaml = Path("${MAP_YAML}")
data = yaml.safe_load(map_yaml.read_text())

image = Path(data["image"])
if not image.is_absolute():
    image = map_yaml.parent / image

resolution = float(data["resolution"])
origin = data.get("origin", [0.0, 0.0, 0.0])

print(str(image.resolve()))
print(resolution)
print(float(origin[0]))
print(float(origin[1]))
print(float(origin[2]) if len(origin) >= 3 else 0.0)
PY
)

MAP_IMAGE="${MAP_INFO[0]}"
RESOLUTION="${MAP_INFO[1]}"
X_OFFSET="${MAP_INFO[2]}"
Y_OFFSET="${MAP_INFO[3]}"
ROTATION="${MAP_INFO[4]}"

if [ ! -f "${MAP_IMAGE}" ]; then
  echo "[ERROR] map image not found: ${MAP_IMAGE}"
  exit 1
fi

echo "[INFO] map yaml:   ${MAP_YAML}"
echo "[INFO] map image:  ${MAP_IMAGE}"
echo "[INFO] resolution: ${RESOLUTION}"
echo "[INFO] x_offset:   ${X_OFFSET}"
echo "[INFO] y_offset:   ${Y_OFFSET}"
echo "[INFO] rotation:   ${ROTATION}"
echo "[INFO] output dir: ${OUT_DIR}"

cd "${SWAGGER_WS}"

# 根據你目前 SWAGGER 的 generate_graph.py --help 自動判斷支援哪些參數。
# 有些版本只支援官方 README 的四個基本參數；
# 有些版本支援 x-offset / y-offset / rotation / occupancy-threshold。
python3 - <<PY
import subprocess
import sys
from pathlib import Path

swagger_ws = Path("${SWAGGER_WS}")
map_image = "${MAP_IMAGE}"
resolution = "${RESOLUTION}"
x_offset = "${X_OFFSET}"
y_offset = "${Y_OFFSET}"
rotation = "${ROTATION}"
out_dir = "${OUT_DIR}"

script = swagger_ws / "scripts" / "generate_graph.py"

help_text = subprocess.run(
    [sys.executable, str(script), "--help"],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
).stdout

cmd = [
    sys.executable,
    str(script),
    "--map-path", map_image,
    "--resolution", resolution,
    "--safety-distance", "0.30",
    "--output-dir", out_dir,
]

optional_args = {
    "--occupancy-threshold": "220",
    "--x-offset": x_offset,
    "--y-offset": y_offset,
    "--rotation": rotation,
}

for key, value in optional_args.items():
    if key in help_text:
        cmd.extend([key, value])

print("[INFO] running:")
print(" ".join(cmd))

subprocess.check_call(cmd)
PY

echo "[OK] SWAGGER graph generated"

if [ -f "${OUT_DIR}/graph.gml" ]; then
  echo "[OK] graph.gml exists"
else
  echo "[ERROR] graph.gml not generated"
  exit 1
fi

if [ -f "${OUT_DIR}/waypoint_graph.png" ]; then
  echo "[OK] waypoint_graph.png exists"
else
  echo "[WARN] waypoint_graph.png not found"
fi

echo "[DONE]"
echo "  ${OUT_DIR}/graph.gml"
echo "  ${OUT_DIR}/waypoint_graph.png"
