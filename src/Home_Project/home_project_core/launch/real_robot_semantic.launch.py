#!/usr/bin/env python3
"""Bring up semantic mapping and object navigation on a physical robot.

Hardware drivers, localization, Nav2, and the database are intentionally
external services.  This launch file starts no simulator and uses wall-clock
ROS time by default.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    share = get_package_share_directory("home_project_core")
    build_launch = os.path.join(share, "launch", "build_semantic_map.launch.py")
    navigation_launch = os.path.join(
        share, "launch", "semantic_object_navigation.launch.py"
    )

    use_sim_time = LaunchConfiguration("use_sim_time")
    map_id = LaunchConfiguration("map_id")
    map_version = LaunchConfiguration("map_version")
    runtime_root = LaunchConfiguration("runtime_root")
    map_yaml = LaunchConfiguration("map_yaml")
    waypoint_yaml = LaunchConfiguration("waypoint_yaml")
    vision_backend = LaunchConfiguration("vision_backend")
    rgb_topic = LaunchConfiguration("rgb_topic")
    depth_topic = LaunchConfiguration("depth_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")
    compressed_rgb_topic = LaunchConfiguration("compressed_rgb_topic")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Must remain false on a physical robot.",
            ),
            DeclareLaunchArgument("map_id", default_value="home_robot"),
            DeclareLaunchArgument("map_version", default_value="1"),
            DeclareLaunchArgument(
                "runtime_root", default_value="/tmp/home_project/runtime"
            ),
            DeclareLaunchArgument("map_yaml", default_value=""),
            DeclareLaunchArgument("waypoint_yaml", default_value=""),
            DeclareLaunchArgument(
                "vision_backend",
                default_value="remote",
                description="remote for the typed external vision action; legacy for a local adapter.",
            ),
            DeclareLaunchArgument("rgb_topic", default_value="/realsense/rgb"),
            DeclareLaunchArgument("depth_topic", default_value="/realsense/depth"),
            DeclareLaunchArgument(
                "camera_info_topic", default_value="/realsense/camera_info"
            ),
            DeclareLaunchArgument(
                "compressed_rgb_topic", default_value="/realsense/rgb/compressed"
            ),
            DeclareLaunchArgument("global_frame", default_value="map"),
            DeclareLaunchArgument("camera_frame", default_value=""),
            DeclareLaunchArgument("dry_run", default_value="false"),
            DeclareLaunchArgument("use_database", default_value="true"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(build_launch),
                launch_arguments={
                    "use_sim_time": use_sim_time,
                    "map_id": map_id,
                    "map_version": map_version,
                    "runtime_root": runtime_root,
                    "map_yaml": map_yaml,
                    "waypoint_yaml": waypoint_yaml,
                    "vision_backend": vision_backend,
                    "rgb_topic": rgb_topic,
                    "depth_topic": depth_topic,
                    "camera_info_topic": camera_info_topic,
                    "compressed_rgb_topic": compressed_rgb_topic,
                    "global_frame": LaunchConfiguration("global_frame"),
                    "camera_frame": LaunchConfiguration("camera_frame"),
                    "dry_run": LaunchConfiguration("dry_run"),
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(navigation_launch),
                launch_arguments={
                    "use_sim_time": use_sim_time,
                    "map_id": map_id,
                    "map_version": map_version,
                    "use_database": LaunchConfiguration("use_database"),
                    "dry_run": LaunchConfiguration("dry_run"),
                }.items(),
            ),
        ]
    )
