#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    semanti_map_pkg = get_package_share_directory("Semanti_Map")
    main_policy_pkg = get_package_share_directory("main_policy")

    use_sim_time = LaunchConfiguration("use_sim_time")
    use_rviz = LaunchConfiguration("use_rviz")

    use_nav2 = LaunchConfiguration("use_nav2")
    use_nav_service = LaunchConfiguration("use_nav_service")
    use_map_builder = LaunchConfiguration("use_map_builder")
    use_waypoint_node = LaunchConfiguration("use_waypoint_node")
    use_tour = LaunchConfiguration("use_tour")
    tour_auto_start = LaunchConfiguration("tour_auto_start")

    return LaunchDescription([
        # ============================================================
        # Common args
        # ============================================================
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="true",
            description="Isaac Sim / Gazebo 用 true；真機通常用 false",
        ),

        DeclareLaunchArgument(
            "use_rviz",
            default_value="true",
            description="是否啟動 RViz2",
        ),

        # ============================================================
        # Main switches
        # ============================================================
        DeclareLaunchArgument(
            "use_nav2",
            default_value="true",
            description="是否啟動 Nav2 localization + navigation",
        ),

        DeclareLaunchArgument(
            "use_nav_service",
            default_value="true",
            description="是否啟動 /nav_to_point service",
        ),

        DeclareLaunchArgument(
            "use_map_builder",
            default_value="true",
            description="是否啟動 map_builder_node",
        ),

        DeclareLaunchArgument(
            "use_waypoint_node",
            default_value="false",
            description="是否啟動 sementic_map_node YAML waypoint runner",
        ),

        DeclareLaunchArgument(
            "use_tour",
            default_value="false",
            description="是否啟動 waypoint_tour_node 固定 6 點巡航建圖",
        ),

        DeclareLaunchArgument(
            "tour_auto_start",
            default_value="false",
            description="waypoint_tour_node 是否一啟動就自動跑",
        ),

        # ============================================================
        # 1. Nav2 + /nav_to_point
        #
        # Include Semanti_Map/nav_bringup.launch.py
        #
        # 注意：
        # use_semantic_projection 這裡固定 false。
        # 因為 vision 要另外用 vision_mapping.launch.py 啟動，
        # 避免 Semanti_Map/semantic_map_node 和 vision pipeline 重複。
        # ============================================================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(semanti_map_pkg, "launch", "nav_bringup.launch.py")
            ),
            launch_arguments={
                "use_sim_time": use_sim_time,
                "use_rviz": use_rviz,
                "use_nav2": use_nav2,
                "use_nav_service": use_nav_service,
                "use_semantic_projection": "false",
                "use_waypoint_node": use_waypoint_node,
            }.items(),
        ),

        # ============================================================
        # 2. Map Builder
        #
        # 啟動 main_policy/map_builder_node
        #
        # 提供：
        # /semantic_map/confirm
        # /semantic_map/finalize
        # /semantic_map/clear_viewpoints
        # /semantic_map/clear_map
        #
        # 預設吃：
        # /grounding_dino/objects_3d_json
        # ============================================================
        TimerAction(
            period=8.0,
            actions=[
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(
                        os.path.join(main_policy_pkg, "launch", "map_builder.launch.py")
                    ),
                    launch_arguments={
                        "use_sim_time": use_sim_time,
                    }.items(),
                    condition=IfCondition(use_map_builder),
                ),
            ],
        ),

        # ============================================================
        # 3. Optional fixed waypoint tour
        #
        # waypoint_tour_node 會做：
        # /nav_to_point
        # /vision/recognize
        # /semantic_map/confirm
        # /semantic_map/finalize
        #
        # 預設不啟動，避免 launch 一開機器人就跑。
        # ============================================================
        TimerAction(
            period=12.0,
            actions=[
                Node(
                    package="main_policy",
                    executable="waypoint_tour_node",
                    name="waypoint_tour_node",
                    output="screen",
                    parameters=[
                        {
                            "use_sim_time": use_sim_time,
                            "auto_start": tour_auto_start,
                        }
                    ],
                    condition=IfCondition(use_tour),
                ),
            ],
        ),
    ])
