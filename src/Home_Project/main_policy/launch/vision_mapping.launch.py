#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    vision_pkg = get_package_share_directory("vision_package")

    use_sim_time = LaunchConfiguration("use_sim_time")
    use_vision = LaunchConfiguration("use_vision")

    image_topic = LaunchConfiguration("image_topic")
    depth_topic = LaunchConfiguration("depth_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")
    target_frame = LaunchConfiguration("target_frame")
    camera_frame_override = LaunchConfiguration("camera_frame_override")

    enable_ram = LaunchConfiguration("enable_ram")
    enable_grounding_dino = LaunchConfiguration("enable_grounding_dino")
    enable_bbox_filter = LaunchConfiguration("enable_bbox_filter")
    enable_bbox_center_3d = LaunchConfiguration("enable_bbox_center_3d")
    enable_bbox_all_3d_marker = LaunchConfiguration("enable_bbox_all_3d_marker")

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
            "use_vision",
            default_value="true",
            description="是否啟動 vision pipeline",
        ),

        # ============================================================
        # Input topics
        # ============================================================
        DeclareLaunchArgument(
            "image_topic",
            default_value="/realsense/rgb",
            description="RGB image topic",
        ),

        DeclareLaunchArgument(
            "depth_topic",
            default_value="/realsense/depth",
            description="Depth image topic，建議使用 aligned depth to color",
        ),

        DeclareLaunchArgument(
            "camera_info_topic",
            default_value="/realsense/camera_info",
            description="Camera info topic，建議使用 color camera info",
        ),

        # ============================================================
        # Frame
        # ============================================================
        DeclareLaunchArgument(
            "target_frame",
            default_value="map",
            description="3D object 輸出座標系。建圖建議 map；若 map->odom 不穩，改 odom",
        ),

        DeclareLaunchArgument(
            "camera_frame_override",
            default_value="Camera_OmniVision_OV9782_Color",
            description="相機 frame override，依你的 TF frame 修改",
        ),

        # ============================================================
        # Node switches
        # ============================================================
        DeclareLaunchArgument(
            "enable_ram",
            default_value="true",
            description="是否啟動 RAM node",
        ),

        DeclareLaunchArgument(
            "enable_grounding_dino",
            default_value="true",
            description="是否啟動 GroundingDINO node",
        ),

        DeclareLaunchArgument(
            "enable_bbox_filter",
            default_value="true",
            description="是否啟動 bbox filter fusion node",
        ),

        DeclareLaunchArgument(
            "enable_bbox_center_3d",
            default_value="true",
            description="是否啟動 bbox center 3D node",
        ),

        DeclareLaunchArgument(
            "enable_bbox_all_3d_marker",
            default_value="true",
            description="是否啟動 bbox all 3D marker node",
        ),

        # ============================================================
        # Include original vision.launch.py
        #
        # 原本的 vision.launch.py 已經包含：
        # - ram_node
        # - grounding_dino_node
        # - bbox_filter_fusion_node
        # - bbox_center_3d_node
        # - bbox_all_3d_marker_node
        #
        # 最重要輸出：
        # /grounding_dino/objects_3d_json
        # ============================================================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(vision_pkg, "launch", "vision.launch.py")
            ),
            launch_arguments={
                "use_sim_time": use_sim_time,

                "image_topic": image_topic,
                "depth_topic": depth_topic,
                "camera_info_topic": camera_info_topic,

                "target_frame": target_frame,
                "camera_frame_override": camera_frame_override,

                "enable_ram": enable_ram,
                "enable_grounding_dino": enable_grounding_dino,
                "enable_bbox_filter": enable_bbox_filter,
                "enable_bbox_center_3d": enable_bbox_center_3d,
                "enable_bbox_all_3d_marker": enable_bbox_all_3d_marker,
            }.items(),
            condition=IfCondition(use_vision),
        ),
    ])

