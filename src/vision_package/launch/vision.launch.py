#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg = get_package_share_directory("vision_package")

    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")

    enable_ram = LaunchConfiguration("enable_ram")
    enable_grounding_dino = LaunchConfiguration("enable_grounding_dino")
    enable_bbox_filter = LaunchConfiguration("enable_bbox_filter")
    enable_bbox_center_3d = LaunchConfiguration("enable_bbox_center_3d")
    enable_bbox_all_3d_marker = LaunchConfiguration("enable_bbox_all_3d_marker")

    image_topic = LaunchConfiguration("image_topic")
    depth_topic = LaunchConfiguration("depth_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")
    target_frame = LaunchConfiguration("target_frame")
    camera_frame_override = LaunchConfiguration("camera_frame_override")

    default_params = os.path.join(
        pkg,
        "config",
        "vision_stationary_balanced_params.yaml",
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "params_file",
            default_value=default_params,
            description="Vision params yaml",
        ),

        DeclareLaunchArgument(
            "use_sim_time",
            default_value="true",
            description="Use simulation time",
        ),

        DeclareLaunchArgument(
            "enable_ram",
            default_value="true",
        ),

        DeclareLaunchArgument(
            "enable_grounding_dino",
            default_value="true",
        ),

        DeclareLaunchArgument(
            "enable_bbox_filter",
            default_value="true",
        ),

        DeclareLaunchArgument(
            "enable_bbox_center_3d",
            default_value="true",
        ),

        DeclareLaunchArgument(
            "enable_bbox_all_3d_marker",
            default_value="true",
        ),

        DeclareLaunchArgument(
            "image_topic",
            default_value="/realsense/rgb",
        ),

        DeclareLaunchArgument(
            "depth_topic",
            default_value="/realsense/depth",
        ),

        DeclareLaunchArgument(
            "camera_info_topic",
            default_value="/realsense/camera_info",
        ),

        DeclareLaunchArgument(
            "target_frame",
            default_value="map",
        ),

        DeclareLaunchArgument(
            "camera_frame_override",
            default_value="Camera_OmniVision_OV9782_Color",
        ),

        Node(
            package="vision_package",
            executable="ram_node",
            name="ram_node",
            output="screen",
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "image_topic": image_topic,
                },
            ],
            condition=IfCondition(enable_ram),
        ),

        Node(
            package="vision_package",
            executable="grounding_dino_node",
            name="grounding_dino_node",
            output="screen",
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "image_topic": image_topic,
                },
            ],
            condition=IfCondition(enable_grounding_dino),
        ),

        Node(
            package="vision_package",
            executable="bbox_filter_fusion_node",
            name="bbox_filter_fusion_node",
            output="screen",
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                },
            ],
            condition=IfCondition(enable_bbox_filter),
        ),

        Node(
            package="vision_package",
            executable="bbox_center_3d_node",
            name="bbox_center_3d_node",
            output="screen",
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "depth_topic": depth_topic,
                    "camera_info_topic": camera_info_topic,
                },
            ],
            condition=IfCondition(enable_bbox_center_3d),
        ),

        Node(
            package="vision_package",
            executable="bbox_all_3d_marker_node",
            name="bbox_all_3d_marker_node",
            output="screen",
            parameters=[
                params_file,
                {
                    "use_sim_time": use_sim_time,
                    "depth_topic": depth_topic,
                    "camera_info_topic": camera_info_topic,
                    "target_frame": target_frame,
                    "camera_frame_override": camera_frame_override,
                },
            ],
            condition=IfCondition(enable_bbox_all_3d_marker),
        ),
    ])
