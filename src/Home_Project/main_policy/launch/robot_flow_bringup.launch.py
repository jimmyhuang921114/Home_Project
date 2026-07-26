#!/usr/bin/env python3
"""Bring up only the robot flow layer; Nav2 and databases are external."""

import os
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _nodes(context):
    pkg = get_package_share_directory("main_policy")
    params = LaunchConfiguration("params_file").perform(context)
    common = {"use_sim_time": _as_bool(LaunchConfiguration("use_sim_time").perform(context))}
    arm_enabled = _as_bool(LaunchConfiguration("arm_enabled").perform(context))
    try:
        joint_names = yaml.safe_load(LaunchConfiguration("arm_joint_names").perform(context))
    except yaml.YAMLError:
        joint_names = []
    if not isinstance(joint_names, list):
        joint_names = []

    executor_overrides = {
        **common,
        "nav_action": LaunchConfiguration("nav_action"),
        "arm_enabled": arm_enabled,
        "arm_action": LaunchConfiguration("arm_action"),
    }
    if joint_names:
        executor_overrides["arm_joint_names"] = joint_names

    nodes = [
        Node(
            package="main_policy",
            executable="robot_mode_manager",
            name="robot_mode_manager_node",
            output="screen",
            parameters=[params, common, {
                "default_mode": LaunchConfiguration("default_mode"),
            }],
        ),
        Node(
            package="main_policy",
            executable="robot_task_executor",
            name="robot_task_executor_node",
            output="screen",
            parameters=[params, executor_overrides],
        ),
        Node(
            package="main_policy",
            executable="robot_state",
            name="robot_state_node",
            output="screen",
            parameters=[params, common, {"arm_enabled": arm_enabled}],
        ),
        Node(
            package="main_policy",
            executable="robot_api_server",
            name="robot_api_server_node",
            output="screen",
            parameters=[params, common, {
                "api_host": LaunchConfiguration("api_host"),
                "api_port": int(LaunchConfiguration("api_port").perform(context)),
                "api_token": LaunchConfiguration("api_token"),
                "nav_action": LaunchConfiguration("nav_action"),
                "vla_action": LaunchConfiguration("vla_action"),
                "initial_holding_state": LaunchConfiguration("initial_holding_state"),
                "initial_base_motion_permission": LaunchConfiguration("initial_base_motion_permission"),
            }],
        ),
    ]

    if _as_bool(LaunchConfiguration("start_mapping_orchestrator").perform(context)):
        waypoint = LaunchConfiguration("waypoint_yaml").perform(context)
        nodes.append(Node(
            package="main_policy",
            executable="robot_task_orchestrator_node",
            name="robot_task_orchestrator_node",
            output="screen",
            parameters=[params, common, {
                "waypoint_yaml": waypoint,
                "auto_start": False,
                "prefer_robot_flow": True,
            }],
        ))
    return nodes


def generate_launch_description():
    pkg = get_package_share_directory("main_policy")
    project_root = Path(pkg)
    env_root = os.environ.get("HOME_PROJECT_ROOT")
    if env_root:
        project_root = Path(env_root).expanduser().resolve()
    else:
        for parent in Path(__file__).resolve().parents:
            if (parent / "src").exists():
                project_root = parent
                break
    waypoint = project_root / "src" / "web_nav_control" / "runtime" / "waypoints" / "nav2_waypoints.yaml"
    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=os.path.join(pkg, "config", "robot_flow_params.yaml")),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("api_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("api_port", default_value="8020"),
        DeclareLaunchArgument("api_token", default_value=""),
        DeclareLaunchArgument("nav_action", default_value="/navigate_to_pose"),
        DeclareLaunchArgument("vla_action", default_value="/pickplace_segment"),
        DeclareLaunchArgument("arm_enabled", default_value="false"),
        DeclareLaunchArgument("arm_action", default_value=""),
        DeclareLaunchArgument("arm_joint_names", default_value="[]"),
        DeclareLaunchArgument("default_mode", default_value="IDLE"),
        DeclareLaunchArgument("initial_holding_state", default_value="unknown"),
        DeclareLaunchArgument("initial_base_motion_permission", default_value="unknown"),
        DeclareLaunchArgument("start_mapping_orchestrator", default_value="false"),
        DeclareLaunchArgument("waypoint_yaml", default_value=str(waypoint)),
        OpaqueFunction(function=_nodes),
    ])
