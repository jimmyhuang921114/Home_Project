#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import math
import os
from pathlib import Path
from typing import Any

import yaml
import networkx as nx

try:
    import cv2
except Exception:
    cv2 = None


def get_project_root() -> Path:
    env = os.environ.get("HOME_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()

    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").exists():
            return parent
    return p.parents[1]


def parse_xy(data: dict[str, Any]) -> tuple[float, float]:
    for kx, ky in [
        ("x", "y"),
        ("world_x", "world_y"),
        ("pos_x", "pos_y"),
    ]:
        if kx in data and ky in data:
            return float(data[kx]), float(data[ky])

    for key in [
        "world",
        "pos",
        "position",
        "point",
        "xy",
        "coord",
        "coords",
        "coordinates",
    ]:
        if key not in data:
            continue

        value = data[key]

        if isinstance(value, str):
            try:
                value = ast.literal_eval(value)
            except Exception:
                parts = (
                    value.replace("[", "")
                    .replace("]", "")
                    .replace("(", "")
                    .replace(")", "")
                    .split(",")
                )
                if len(parts) >= 2:
                    return float(parts[0]), float(parts[1])
                continue

        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return float(value[0]), float(value[1])

    raise RuntimeError(f"Cannot parse xy from node data: {data}")


def edge_weight(graph: nx.Graph, u: str, v: str) -> float:
    data = graph.edges[u, v]

    for key in ("weight", "distance", "length", "cost"):
        if key in data:
            try:
                return float(data[key])
            except Exception:
                pass

    x1, y1 = graph.nodes[u]["_xy"]
    x2, y2 = graph.nodes[v]["_xy"]
    return math.hypot(x2 - x1, y2 - y1)


def world_to_pixel(
    x: float,
    y: float,
    origin: tuple[float, float, float],
    resolution: float,
    height: int,
) -> tuple[int, int] | None:
    ox, oy, oyaw = origin

    if abs(oyaw) > 1e-9:
        return None

    u = int((x - ox) / resolution)
    v = int(height - 1 - ((y - oy) / resolution))
    return u, v


def order_component(graph: nx.Graph, start_node: str) -> list[str]:
    """
    從 start_node 開始，每次找 graph distance 最近的未拜訪節點，
    並把 shortest path 中間點加入序列。
    """
    unvisited = set(graph.nodes())
    sequence: list[str] = []
    current = start_node

    while unvisited:
        if current in unvisited:
            unvisited.remove(current)

        if not sequence or sequence[-1] != current:
            sequence.append(current)

        lengths = nx.single_source_dijkstra_path_length(
            graph,
            current,
            weight="_w",
        )

        candidates = [n for n in unvisited if n in lengths]

        if not candidates:
            break

        next_node = min(candidates, key=lambda n: lengths[n])
        path = nx.shortest_path(graph, current, next_node, weight="_w")

        for n in path:
            if not sequence or sequence[-1] != n:
                sequence.append(n)
            unvisited.discard(n)

        current = next_node

    return sequence


def filter_by_spacing(
    graph: nx.Graph,
    sequence: list[str],
    min_spacing: float,
) -> list[str]:
    filtered: list[str] = []
    last_xy: tuple[float, float] | None = None

    for node in sequence:
        x, y = graph.nodes[node]["_xy"]

        if last_xy is None:
            filtered.append(node)
            last_xy = (x, y)
            continue

        if math.hypot(x - last_xy[0], y - last_xy[1]) >= min_spacing:
            filtered.append(node)
            last_xy = (x, y)

    return filtered


def draw_debug(
    graph: nx.Graph,
    anchors: list[str],
    waypoints: list[dict[str, Any]],
    map_yaml: Path,
    debug_png: Path,
    semantic_scan: bool,
) -> None:
    if cv2 is None:
        print("[WARN] cv2 not found, skip debug image")
        return

    map_data = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    img_path = Path(map_data["image"])

    if not img_path.is_absolute():
        img_path = map_yaml.parent / img_path

    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)

    if img is None:
        print(f"[WARN] cannot read map image: {img_path}")
        return

    resolution = float(map_data["resolution"])
    origin_raw = map_data.get("origin", [0.0, 0.0, 0.0])
    origin = (
        float(origin_raw[0]),
        float(origin_raw[1]),
        float(origin_raw[2]) if len(origin_raw) >= 3 else 0.0,
    )

    height, _ = img.shape[:2]
    debug = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # graph edges: green
    for u, v in graph.edges():
        x1, y1 = graph.nodes[u]["_xy"]
        x2, y2 = graph.nodes[v]["_xy"]

        p1 = world_to_pixel(x1, y1, origin, resolution, height)
        p2 = world_to_pixel(x2, y2, origin, resolution, height)

        if p1 and p2:
            cv2.line(debug, p1, p2, (0, 180, 0), 1)

    if semantic_scan:
        # semantic scan anchors: red dot + cross
        for i, node in enumerate(anchors):
            x, y = graph.nodes[node]["_xy"]
            p = world_to_pixel(x, y, origin, resolution, height)

            if not p:
                continue

            cv2.circle(debug, p, 6, (0, 0, 255), -1)
            cv2.line(debug, (p[0] - 12, p[1]), (p[0] + 12, p[1]), (0, 0, 255), 2)
            cv2.line(debug, (p[0], p[1] - 12), (p[0], p[1] + 12), (0, 0, 255), 2)

            cv2.putText(
                debug,
                str(i),
                (p[0] + 6, p[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
    else:
        # normal waypoint mode
        for i, wp in enumerate(waypoints):
            p = world_to_pixel(
                float(wp["x"]),
                float(wp["y"]),
                origin,
                resolution,
                height,
            )

            if not p:
                continue

            cv2.circle(debug, p, 4, (0, 0, 255), -1)

            if i < 80:
                cv2.putText(
                    debug,
                    str(i),
                    (p[0] + 4, p[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 0, 255),
                    1,
                    cv2.LINE_AA,
                )

    cv2.imwrite(str(debug_png), debug)
    print(f"[OK] wrote debug image: {debug_png}")


def main() -> None:
    project_root = get_project_root()
    parser = argparse.ArgumentParser()

    parser.add_argument("--graph-dir", required=True)
    parser.add_argument(
        "--map-yaml",
        default=str(project_root / "config" / "map.yaml"),
    )
    parser.add_argument("--out-yaml", default="")
    parser.add_argument("--debug-png", default="")

    parser.add_argument("--start-x", type=float, required=True)
    parser.add_argument("--start-y", type=float, required=True)

    # 普通導航點間距
    parser.add_argument("--min-spacing", type=float, default=0.80)

    # semantic scan anchor 間距
    parser.add_argument("--semantic-scan", action="store_true")
    parser.add_argument("--scan-spacing", type=float, default=1.80)
    parser.add_argument(
        "--yaw-deg-list",
        default="0,90,180,-90",
        help="Example: 0,90,180,-90",
    )

    parser.add_argument(
        "--component-mode",
        choices=["reachable", "all", "largest"],
        default="reachable",
    )

    parser.add_argument("--min-component-size", type=int, default=5)

    args = parser.parse_args()

    graph_dir = Path(args.graph_dir)
    map_yaml = Path(args.map_yaml)
    graph_path = graph_dir / "graph.gml"

    if args.out_yaml:
        out_yaml = Path(args.out_yaml)
    else:
        out_yaml = graph_dir / "nav2_waypoints_swagger.yaml"

    if args.debug_png:
        debug_png = Path(args.debug_png)
    else:
        debug_png = graph_dir / "debug_nav2_waypoints.png"

    if not graph_path.exists():
        raise SystemExit(f"[ERROR] graph.gml not found: {graph_path}")

    graph = nx.read_gml(graph_path)

    if graph.is_directed():
        graph = graph.to_undirected()

    print(f"[INFO] raw graph nodes={graph.number_of_nodes()} edges={graph.number_of_edges()}")

    for node, data in graph.nodes(data=True):
        data["_xy"] = parse_xy(data)

    isolates = list(nx.isolates(graph))
    if isolates:
        graph.remove_nodes_from(isolates)
        print(f"[INFO] removed isolates={len(isolates)}")

    for u, v in graph.edges():
        graph.edges[u, v]["_w"] = edge_weight(graph, u, v)

    components = list(nx.connected_components(graph))
    components = [c for c in components if len(c) >= args.min_component_size]

    if not components:
        raise SystemExit("[ERROR] no component remains after filtering")

    components.sort(key=len, reverse=True)
    print("[INFO] component sizes:", [len(c) for c in components[:20]])

    def dist_to_start(node: str) -> float:
        x, y = graph.nodes[node]["_xy"]
        return math.hypot(x - args.start_x, y - args.start_y)

    if args.component_mode == "reachable":
        nearest_start_node = min(graph.nodes(), key=dist_to_start)
        selected_nodes = nx.node_connected_component(graph, nearest_start_node)
        components_to_process = [selected_nodes]
        print(
            f"[INFO] mode=reachable, start_node={nearest_start_node}, "
            f"xy={graph.nodes[nearest_start_node]['_xy']}"
        )

    elif args.component_mode == "largest":
        components_to_process = [components[0]]
        print("[INFO] mode=largest")

    else:
        components_to_process = components
        print("[INFO] mode=all")

    all_sequence: list[str] = []

    last_x = args.start_x
    last_y = args.start_y

    for ci, component in enumerate(components_to_process):
        subgraph = graph.subgraph(component).copy()

        if ci == 0:
            start_node = min(subgraph.nodes(), key=dist_to_start)
        else:
            start_node = min(
                subgraph.nodes(),
                key=lambda n: math.hypot(
                    subgraph.nodes[n]["_xy"][0] - last_x,
                    subgraph.nodes[n]["_xy"][1] - last_y,
                ),
            )

        sequence = order_component(subgraph, start_node)

        if sequence:
            last_x, last_y = graph.nodes[sequence[-1]]["_xy"]

        for node in sequence:
            if not all_sequence or all_sequence[-1] != node:
                all_sequence.append(node)

    selected_node_set = set()
    for component in components_to_process:
        selected_node_set.update(component)
    debug_graph = graph.subgraph(selected_node_set).copy()

    waypoints: list[dict[str, Any]] = []

    if args.semantic_scan:
        anchors = filter_by_spacing(
            graph,
            all_sequence,
            args.scan_spacing,
        )

        yaw_deg_list = [
            float(v.strip())
            for v in args.yaw_deg_list.split(",")
            if v.strip()
        ]

        for anchor_i, node in enumerate(anchors):
            x, y = graph.nodes[node]["_xy"]

            for yaw_deg in yaw_deg_list:
                yaw_rad = math.radians(yaw_deg)

                waypoints.append(
                    {
                        "id": f"scan_{anchor_i:03d}_yaw_{int(yaw_deg):+04d}",
                        "scan_anchor_id": f"scan_{anchor_i:03d}",
                        "source_node_id": str(node),
                        "x": round(float(x), 3),
                        "y": round(float(y), 3),
                        "yaw": round(float(yaw_rad), 6),
                        "yaw_deg": round(float(yaw_deg), 1),
                    }
                )

        output = {
            "frame_id": "map",
            "mode": "semantic_scan_four_directions",
            "scan_anchor_count": len(anchors),
            "yaw_deg_list": yaw_deg_list,
            "waypoints": waypoints,
        }

        print(f"[INFO] semantic scan anchors={len(anchors)}")
        print(f"[INFO] total yaw waypoints={len(waypoints)}")

    else:
        anchors = filter_by_spacing(
            graph,
            all_sequence,
            args.min_spacing,
        )

        for i, node in enumerate(anchors):
            x, y = graph.nodes[node]["_xy"]

            waypoints.append(
                {
                    "id": f"wp_{i:03d}",
                    "source_node_id": str(node),
                    "x": round(float(x), 3),
                    "y": round(float(y), 3),
                    "yaw": 0.0,
                }
            )

        output = {
            "frame_id": "map",
            "mode": "normal_waypoint_navigation",
            "waypoints": waypoints,
        }

        print(f"[INFO] waypoint count={len(waypoints)}")

    out_yaml.write_text(
        yaml.safe_dump(output, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    print(f"[OK] wrote yaml: {out_yaml}")
    print("[INFO] first 12 waypoints:")
    for wp in waypoints[:12]:
        print(wp)

    draw_debug(
        debug_graph,
        anchors,
        waypoints,
        map_yaml,
        debug_png,
        semantic_scan=args.semantic_scan,
    )


if __name__ == "__main__":
    main()
