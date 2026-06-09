import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg = get_package_share_directory('yolo')
    config = os.path.join(pkg, 'config', 'params.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='true',
            description='使用模擬時鐘時設為 true',
        ),
        DeclareLaunchArgument(
            'model_path',
            default_value='yolov8n.pt',
            description='YOLO 模型路徑（相對路徑由 ultralytics 自動下載）',
        ),

        Node(
            package='yolo',
            executable='yolo_detect_node',
            name='yolo_detect_node',
            output='screen',
            parameters=[
                config,
                {
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'model_path': LaunchConfiguration('model_path'),
                },
            ],
        ),
    ])
