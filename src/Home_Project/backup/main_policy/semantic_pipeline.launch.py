"""
Semantic Pipeline — 不啟動 YOLO 版本

啟動順序：
  1. semantic_map_node  (Semanti_Map)  — TF 投影，發布 /semantic_map/raw_detections
  2. map_builder_node   (main_policy)  — 停站觀測聚合，發布 /semantic_map、/semantic_objects

觸發建圖：
  ros2 topic pub /semantic_map/trigger std_msgs/msg/String "data: 'start'" --once

使用範例：
  ros2 launch main_policy semantic_pipeline.launch.py
  ros2 launch main_policy semantic_pipeline.launch.py use_sim_time:=true
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    sem_pkg = get_package_share_directory('Semanti_Map')
    policy_pkg = get_package_share_directory('main_policy')

    sem_config = os.path.join(sem_pkg, 'config', 'params.yaml')
    map_builder_config = os.path.join(policy_pkg, 'config', 'map_builder_params.yaml')

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='使用模擬時鐘時設為 true（Gazebo / ROS bag）',
    )

    declare_sem_params = DeclareLaunchArgument(
        'sem_params_file',
        default_value=sem_config,
        description='SemanticMap 節點參數 YAML 路徑',
    )

    declare_map_builder_params = DeclareLaunchArgument(
        'map_builder_params_file',
        default_value=map_builder_config,
        description='MapBuilder 節點參數 YAML 路徑',
    )

    sim_time_override = {
        'use_sim_time': LaunchConfiguration('use_sim_time')
    }

    semantic_map_node = Node(
        package='Semanti_Map',
        executable='semantic_map_node',
        name='semantic_map_node',
        output='screen',
        parameters=[
            LaunchConfiguration('sem_params_file'),
            sim_time_override,
        ],
    )

    map_builder_node = Node(
        package='main_policy',
        executable='map_builder_node',
        name='map_builder_node',
        output='screen',
        parameters=[
            LaunchConfiguration('map_builder_params_file'),
            sim_time_override,
        ],
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_sem_params,
        declare_map_builder_params,
        semantic_map_node,
        map_builder_node,
    ])