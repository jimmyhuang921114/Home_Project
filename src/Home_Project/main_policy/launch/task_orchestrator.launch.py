#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="true",
            description="Isaac Sim / Gazebo 用 true；真機通常 false",
        ),

        DeclareLaunchArgument(
            "waypoint_yaml",
            default_value="/home/jimmy/work_ws/home_project_ws/src/Semanti_Map/config/nav2_waypoints_margin_060.yaml",
            description="Waypoint YAML path",
        ),

        DeclareLaunchArgument(
            "auto_start",
            default_value="false",
            description="是否 launch 後自動開始跑 waypoint",
        ),

        DeclareLaunchArgument(
            "enable_map_confirm",
            default_value="false",
            description="到點 vision 後是否自動 call /semantic_map/confirm",
        ),

        Node(
            package="main_policy",
            executable="robot_task_orchestrator_node",
            name="robot_task_orchestrator_node",
            output="screen",
            parameters=[
                {
                    "use_sim_time": LaunchConfiguration("use_sim_time"),

                    "waypoint_yaml": LaunchConfiguration("waypoint_yaml"),

                    "auto_start": LaunchConfiguration("auto_start"),
                    "start_delay_s": 3.0,

                    "use_yaw": True,
                    "skip_on_fail": True,
                    "pause_after_nav_s": 0.5,
                    "pause_after_vision_s": 0.5,

                    "nav_service": "/nav_to_point",
                    "nav_timeout_s": 180.0,

                    "vision_trigger_service": "/grounding_dino/detect_once",
                    "objects_json_topic": "/grounding_dino/objects_3d_json",
                    "vision_service_timeout_s": 10.0,
                    "objects_wait_timeout_s": 8.0,

                    "enable_map_confirm": LaunchConfiguration("enable_map_confirm"),
                    "map_confirm_service": "/semantic_map/confirm",
                    "map_confirm_timeout_s": 10.0,

                    "records_save_path": "/home/jimmy/work_ws/home_project_ws/data/main_policy_records.jsonl",
                }
            ],
        ),
    ])