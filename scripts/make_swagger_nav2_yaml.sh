#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOME_WS="${HOME_PROJECT_ROOT:-${PROJECT_ROOT}}"

# ===== SWAGGER graph 生成參數 =====
SAFETY="${SAFETY:-0.25}"
OCC_THR="${OCC_THR:-248}"

# ===== 起點，建議填 robot 目前 AMCL 附近位置 =====
START_X="${START_X:-1.185}"
START_Y="${START_Y:-6.104}"

# ===== 一般導航模式參數 =====
MIN_SPACING="${MIN_SPACING:-0.80}"

# ===== 語意掃描模式參數 =====
SEMANTIC_SCAN="${SEMANTIC_SCAN:-1}"
SCAN_SPACING="${SCAN_SPACING:-1.80}"
YAW_DEG_LIST="${YAW_DEG_LIST:-0,90,180,-90}"

# ===== component 選擇 =====
COMPONENT_MODE="${COMPONENT_MODE:-reachable}"
MIN_COMPONENT_SIZE="${MIN_COMPONENT_SIZE:-5}"

cd "$HOME_WS"

echo "========== SWAGGER → NAV2 YAML =========="
echo "[INFO] HOME_WS            = $HOME_WS"
echo "[INFO] SAFETY             = $SAFETY"
echo "[INFO] OCC_THR            = $OCC_THR"
echo "[INFO] START_X START_Y    = $START_X $START_Y"
echo "[INFO] COMPONENT_MODE     = $COMPONENT_MODE"
echo "[INFO] MIN_COMPONENT_SIZE = $MIN_COMPONENT_SIZE"
echo "[INFO] SEMANTIC_SCAN      = $SEMANTIC_SCAN"
echo "[INFO] MIN_SPACING        = $MIN_SPACING"
echo "[INFO] SCAN_SPACING       = $SCAN_SPACING"
echo "[INFO] YAW_DEG_LIST       = $YAW_DEG_LIST"
echo "========================================="

if [ ! -f scripts/run_swagger_generate.sh ]; then
  echo "[ERROR] missing scripts/run_swagger_generate.sh"
  exit 1
fi

if [ ! -f scripts/convert_swagger_graph_to_nav2_yaml.py ]; then
  echo "[ERROR] missing scripts/convert_swagger_graph_to_nav2_yaml.py"
  exit 1
fi

SAFETY="$SAFETY" OCC_THR="$OCC_THR" ./scripts/run_swagger_generate.sh

OUT_DIR="$(cat /tmp/latest_swagger_out_dir.txt)"

if [ "$SEMANTIC_SCAN" = "1" ] || [ "$SEMANTIC_SCAN" = "true" ] || [ "$SEMANTIC_SCAN" = "TRUE" ]; then
  echo "[INFO] mode = semantic scan four directions"

  python3 scripts/convert_swagger_graph_to_nav2_yaml.py \
    --graph-dir "$OUT_DIR" \
    --map-yaml config/map.yaml \
    --out-yaml "$OUT_DIR/nav2_waypoints_swagger.yaml" \
    --debug-png "$OUT_DIR/debug_nav2_waypoints.png" \
    --start-x "$START_X" \
    --start-y "$START_Y" \
    --scan-spacing "$SCAN_SPACING" \
    --semantic-scan \
    --yaw-deg-list "$YAW_DEG_LIST" \
    --component-mode "$COMPONENT_MODE" \
    --min-component-size "$MIN_COMPONENT_SIZE"

else
  echo "[INFO] mode = normal waypoint navigation"

  python3 scripts/convert_swagger_graph_to_nav2_yaml.py \
    --graph-dir "$OUT_DIR" \
    --map-yaml config/map.yaml \
    --out-yaml "$OUT_DIR/nav2_waypoints_swagger.yaml" \
    --debug-png "$OUT_DIR/debug_nav2_waypoints.png" \
    --start-x "$START_X" \
    --start-y "$START_Y" \
    --min-spacing "$MIN_SPACING" \
    --component-mode "$COMPONENT_MODE" \
    --min-component-size "$MIN_COMPONENT_SIZE"
fi

echo
echo "[OK] DONE"
echo "[INFO] OUT_DIR:"
echo "$OUT_DIR"

echo
echo "[INFO] Generated files:"
ls -lh "$OUT_DIR"

echo
echo "[NEXT] Open debug image:"
echo "xdg-open \"$OUT_DIR/debug_nav2_waypoints.png\""

echo
echo "[NEXT] Test waypoint node:"
echo "source /opt/ros/humble/setup.bash"
echo "source \"${HOME_WS}/install/setup.bash\""

if [ "$SEMANTIC_SCAN" = "1" ] || [ "$SEMANTIC_SCAN" = "true" ] || [ "$SEMANTIC_SCAN" = "TRUE" ]; then
  echo "ros2 run main_policy sementic_map_node --yaml \"$OUT_DIR/nav2_waypoints_swagger.yaml\" --use-yaw --success-delay 3.0"
else
  echo "ros2 run main_policy sementic_map_node --yaml \"$OUT_DIR/nav2_waypoints_swagger.yaml\" --no-use-yaw"
fi

echo
echo "[NEXT] If OK, replace official YAML:"
echo "cp config/nav2_waypoints_margin_060.yaml config/nav2_waypoints_margin_060.yaml.bak_\$(date +%Y%m%d_%H%M%S)"
echo "cp \"$OUT_DIR/nav2_waypoints_swagger.yaml\" config/nav2_waypoints_margin_060.yaml"
