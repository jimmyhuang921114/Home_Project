#!/usr/bin/env python3
"""Safe mock runtime.  Action names are isolated from real robot names."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory("main_policy")
    mock_nav = "/mock_navigate_to_pose"
    mock_arm = "/mock_arm_controller/follow_joint_trajectory"
    mock_vla = "/mock_pickplace_segment"
    return LaunchDescription([
        DeclareLaunchArgument("api_port", default_value="18020"),
        DeclareLaunchArgument("api_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("api_token", default_value=""),
        Node(
            package="main_policy",
            executable="mock_motion_servers",
            name="mock_motion_servers_node",
            output="screen",
            parameters=[{
                "nav_action": mock_nav,
                "arm_action": mock_arm,
                "vla_action": mock_vla,
            }],
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg, "launch", "robot_flow_bringup.launch.py")
            ),
            launch_arguments={
                "api_port": LaunchConfiguration("api_port"),
                "api_host": LaunchConfiguration("api_host"),
                "api_token": LaunchConfiguration("api_token"),
                "nav_action": mock_nav,
                "vla_action": mock_vla,
                "arm_enabled": "true",
                "arm_action": mock_arm,
                "arm_joint_names": "[joint_1, joint_2]",
                "default_mode": "IDLE",
                "start_mapping_orchestrator": "false",
                "initial_holding_state": "empty",
                "initial_base_motion_permission": "allowed",
            }.items(),
        ),
    ])
