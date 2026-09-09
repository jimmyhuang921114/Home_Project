#!/usr/bin/env python3
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
    PythonExpression,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    share = get_package_share_directory("home_project_core")
    params = os.path.join(share, "config", "semantic_mapping.yaml")
    backend = LaunchConfiguration("vision_backend")
    runtime_root = LaunchConfiguration("runtime_root")
    map_id = LaunchConfiguration("map_id")
    map_version = LaunchConfiguration("map_version")
    version_directory = PythonExpression(["'v' + '", map_version, "'"])
    dsg_output = PathJoinSubstitution(
        [runtime_root, "maps", map_id, version_directory, "semantic_dsg"]
    )
    common = {
        "use_sim_time": ParameterValue(
            LaunchConfiguration("use_sim_time"), value_type=bool
        )
    }
    return LaunchDescription(
        [
            DeclareLaunchArgument("map_id", default_value="home_lab"),
            DeclareLaunchArgument("map_version", default_value="1"),
            DeclareLaunchArgument(
                "map_yaml",
                default_value="/home/jimmy/work_ws/Home_Project/config/map.yaml",
            ),
            DeclareLaunchArgument(
                "waypoint_yaml",
                default_value="/home/jimmy/work_ws/Home_Project/config/nav2_waypoints.yaml",
            ),
            DeclareLaunchArgument(
                "runtime_root", default_value="/home/jimmy/work_ws/Home_Project/runtime"
            ),
            DeclareLaunchArgument(
                "swagger_executable",
                default_value="/home/jimmy/work_ws/Home_Project/scripts/swagger_runtime_adapter.py",
            ),
            DeclareLaunchArgument(
                "swagger_root", default_value="/home/jimmy/work_ws/SWAGGER"
            ),
            DeclareLaunchArgument("vision_backend", default_value="remote"),
            DeclareLaunchArgument("use_database", default_value="false"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("max_waypoints", default_value="0"),
            DeclareLaunchArgument("dry_run", default_value="false"),
            DeclareLaunchArgument("start_rgb_compression", default_value="true"),
            DeclareLaunchArgument("rgb_topic", default_value="/realsense/rgb"),
            DeclareLaunchArgument("depth_topic", default_value="/realsense/depth"),
            DeclareLaunchArgument("camera_info_topic", default_value="/realsense/camera_info"),
            DeclareLaunchArgument("compressed_rgb_topic", default_value="/realsense/rgb/compressed"),
            DeclareLaunchArgument("global_frame", default_value="map"),
            DeclareLaunchArgument("camera_frame", default_value=""),
            DeclareLaunchArgument(
                "start_spark_dsg_export_server", default_value="false"
            ),
            DeclareLaunchArgument("start_spark_dsg_visualizer", default_value="false"),
            DeclareLaunchArgument("scene_graph_backend", default_value="hydra"),
            DeclareLaunchArgument("spark_dsg_enabled", default_value="false"),
            DeclareLaunchArgument("spark_dsg_required", default_value="false"),
            DeclareLaunchArgument(
                "spark_dsg_service_timeout_sec", default_value="30.0"
            ),
            Node(
                package="home_project_core",
                executable="semantic_mapping_action_server",
                name="semantic_mapping_action_server",
                output="screen",
                parameters=[
                    params,
                    common,
                    {
                        "configured_map_id": LaunchConfiguration("map_id"),
                        "configured_map_version": ParameterValue(
                            LaunchConfiguration("map_version"), value_type=int
                        ),
                        "configured_map_yaml": LaunchConfiguration("map_yaml"),
                        "configured_waypoint_yaml": LaunchConfiguration(
                            "waypoint_yaml"
                        ),
                        "runtime_root": LaunchConfiguration("runtime_root"),
                        "compressed_image_topic": LaunchConfiguration("compressed_rgb_topic"),
                        "global_frame": LaunchConfiguration("global_frame"),
                        "camera_frame": LaunchConfiguration("camera_frame"),
                        "swagger_executable": LaunchConfiguration("swagger_executable"),
                        "swagger_root": LaunchConfiguration("swagger_root"),
                        "vision_backend": backend,
                        "max_waypoints": ParameterValue(
                            LaunchConfiguration("max_waypoints"), value_type=int
                        ),
                        "dry_run": ParameterValue(
                            LaunchConfiguration("dry_run"), value_type=bool
                        ),
                        "scene_graph_backend": LaunchConfiguration("scene_graph_backend"),
                        "spark_dsg.enabled": ParameterValue(
                            LaunchConfiguration("spark_dsg_enabled"), value_type=bool
                        ),
                        "spark_dsg.required": ParameterValue(
                            LaunchConfiguration("spark_dsg_required"), value_type=bool
                        ),
                        "spark_dsg.service_timeout_sec": ParameterValue(
                            LaunchConfiguration("spark_dsg_service_timeout_sec"),
                            value_type=float,
                        ),
                    },
                ],
            ),
            Node(
                package="home_project_core",
                executable="rgb_compression_node",
                name="rgb_compression_node",
                output="screen",
                parameters=[params, common, {
                    "rgb_topic": LaunchConfiguration("rgb_topic"),
                    "compressed_rgb_topic": LaunchConfiguration("compressed_rgb_topic"),
                }],
                condition=IfCondition(LaunchConfiguration("start_rgb_compression")),
            ),
            Node(
                package="semantic_dsg_bridge",
                executable="dsg_export_server",
                name="semantic_dsg_export_server",
                output="screen",
                parameters=[common],
                condition=IfCondition(
                    LaunchConfiguration("start_spark_dsg_export_server")
                ),
            ),
            Node(
                package="semantic_dsg_bridge",
                executable="dsg_marker_node",
                name="dsg_marker_node",
                output="screen",
                parameters=[
                    common,
                    {
                        "graph_path": PathJoinSubstitution(
                            [dsg_output, "semantic_dsg.json"]
                        ),
                        "metadata_path": PathJoinSubstitution(
                            [dsg_output, "semantic_dsg_metadata.json"]
                        ),
                    },
                ],
                condition=IfCondition(
                    LaunchConfiguration("start_spark_dsg_visualizer")
                ),
            ),
            Node(
                package="home_project_core",
                executable="legacy_vision_action_adapter",
                name="legacy_vision_action_adapter",
                output="screen",
                parameters=[params, common],
                condition=IfCondition(
                    PythonExpression(["'", backend, "' in ['legacy', 'mock']"])
                ),
            ),
            Node(
                package="home_project_core",
                executable="timestamp_semantic_fusion_node",
                name="timestamp_semantic_fusion_node",
                output="screen",
                parameters=[params, common, {
                    "rgb_topic": LaunchConfiguration("rgb_topic"),
                    "depth_topic": LaunchConfiguration("depth_topic"),
                    "camera_info_topic": LaunchConfiguration("camera_info_topic"),
                    "global_frame": LaunchConfiguration("global_frame"),
                    "camera_frame": LaunchConfiguration("camera_frame"),
                }],
                # The exact fusion path receives all three input topic parameters.
                # Legacy latest-data nodes remain outside this formal profile.
                # (The backend condition below controls which path is active.)
                condition=IfCondition(
                    PythonExpression(["'", backend, "' not in ['legacy', 'mock']"])
                ),
            ),
        ]
    )
