import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg = get_package_share_directory('main_policy')
    config = os.path.join(pkg, 'config', 'map_builder_params.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='true',
            description='使用模擬時鐘時設為 true',
        ),
        DeclareLaunchArgument(
            'map_builder_params_file',
            default_value=config,
            description='MapBuilder 節點參數 YAML 路徑',
        ),

        Node(
            package='main_policy',
            executable='map_builder_node',
            name='map_builder_node',
            output='screen',
            parameters=[
                LaunchConfiguration('map_builder_params_file'),
                {'use_sim_time': LaunchConfiguration('use_sim_time')},
            ],
        ),
    ])
