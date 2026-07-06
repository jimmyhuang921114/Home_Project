#!/usr/bin/env bash
set -euo pipefail

HOME_WS="/home/jimmy/work_ws/home_project_ws"
SWAGGER_DIR="/home/jimmy/work_ws/SWAGGER"

MAP_PNG="${HOME_WS}/config/map.png"
MAP_YAML="${HOME_WS}/config/map.yaml"

# ===== 可調參數 =====
# SAFETY 越大，越遠離牆，但太大會讓門口/房間斷掉
SAFETY="${SAFETY:-0.25}"

# OCC_THR 越大，越嚴格只把白色當 free
OCC_THR="${OCC_THR:-248}"

OUT_DIR="${OUT_DIR:-${HOME_WS}/config/swagger_regen_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUT_DIR"

echo "========== RUN SWAGGER GENERATE =========="
echo "[INFO] HOME_WS     = $HOME_WS"
echo "[INFO] SWAGGER_DIR = $SWAGGER_DIR"
echo "[INFO] MAP_PNG     = $MAP_PNG"
echo "[INFO] MAP_YAML    = $MAP_YAML"
echo "[INFO] SAFETY      = $SAFETY"
echo "[INFO] OCC_THR     = $OCC_THR"
echo "[INFO] OUT_DIR     = $OUT_DIR"
echo "=========================================="

# ===== 修 numba / coverage 衝突 =====
NUMBA_COV="$(
find \
  /home/work/.local/lib/python3.10/site-packages \
  /home/jimmy/.local/lib/python3.10/site-packages \
  /usr/local/lib/python3.10/dist-packages \
  /usr/lib/python3/dist-packages \
  -path "*/numba/misc/coverage_support.py" \
  -print 2>/dev/null | head -n 1 || true
)"

if [ -n "$NUMBA_COV" ]; then
  echo "[INFO] patch numba coverage_support.py: $NUMBA_COV"

  if ! grep -q "Local patch for SWAGGER" "$NUMBA_COV"; then
    cp "$NUMBA_COV" "$NUMBA_COV.bak_$(date +%Y%m%d_%H%M%S)" || true
  fi

  cat > "$NUMBA_COV" <<'PY'
"""
Local patch for SWAGGER:
Disable numba coverage integration because installed coverage package is incompatible.
Return empty iterable, not None.
"""

def get_registered_loc_notify():
    return ()
PY

  find "$(dirname "$NUMBA_COV")" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
else
  echo "[WARN] numba coverage_support.py not found, skip patch"
fi

if [ ! -d "$SWAGGER_DIR" ]; then
  echo "[ERROR] SWAGGER_DIR not found: $SWAGGER_DIR"
  exit 1
fi

if [ ! -f "$MAP_PNG" ]; then
  echo "[ERROR] map image not found: $MAP_PNG"
  exit 1
fi

if [ ! -f "$MAP_YAML" ]; then
  echo "[ERROR] map yaml not found: $MAP_YAML"
  exit 1
fi

# ===== 從 map.yaml 讀 resolution / origin =====
eval "$(
python3 - <<PY
import yaml
data = yaml.safe_load(open("${MAP_YAML}", "r", encoding="utf-8"))
res = float(data["resolution"])
origin = data.get("origin", [0.0, 0.0, 0.0])
ox = float(origin[0])
oy = float(origin[1])
yaw = float(origin[2]) if len(origin) >= 3 else 0.0
print(f"RES={res}")
print(f"OX={ox}")
print(f"OY={oy}")
print(f"OYAW={yaw}")
PY
)"

echo "[INFO] RES    = $RES"
echo "[INFO] ORIGIN = $OX $OY $OYAW"

cd "$SWAGGER_DIR"

python3 scripts/generate_graph.py \
  --map-path "$MAP_PNG" \
  --resolution "$RES" \
  --safety-distance "$SAFETY" \
  --occupancy-threshold "$OCC_THR" \
  --x-offset "$OX" \
  --y-offset "$OY" \
  --rotation "$OYAW" \
  --output-dir "$OUT_DIR"

echo "$OUT_DIR" > /tmp/latest_swagger_out_dir.txt

echo
echo "[OK] SWAGGER output:"
ls -lh "$OUT_DIR"

if [ ! -f "$OUT_DIR/graph.gml" ]; then
  echo "[ERROR] graph.gml not generated"
  exit 1
fi

echo "[OK] graph.gml exists"
echo "[OK] latest output dir saved to /tmp/latest_swagger_out_dir.txt"
