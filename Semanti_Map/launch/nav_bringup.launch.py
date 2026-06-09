import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    sem_pkg    = get_package_share_directory('Semanti_Map')
    nav2_pkg   = get_package_share_directory('nav2_bringup')
    policy_pkg = get_package_share_directory('main_policy')

    # ── 參數宣告 ──────────────────────────────────────────────────────────────
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='使用模擬時鐘（Isaac Sim / Gazebo）',
    )
    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(sem_pkg, 'map', 'map.yaml'),
        description='地圖 YAML 路徑',
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(sem_pkg, 'config', 'nav2_params.yaml'),
        description='Nav2 參數 YAML 路徑',
    )
    declare_nav_service_params = DeclareLaunchArgument(
        'nav_service_params_file',
        default_value=os.path.join(policy_pkg, 'config', 'nav_service_params.yaml'),
        description='NavService 節點參數 YAML 路徑',
    )
    declare_rviz_config = DeclareLaunchArgument(
        'rviz_config',
        default_value=os.path.join(nav2_pkg, 'rviz', 'nav2_default_view.rviz'),
        description='RViz2 設定檔路徑',
    )
    declare_use_rviz = DeclareLaunchArgument(
        'use_rviz',
        default_value='true',
        description='設為 false 可略過 RViz2',
    )
    declare_use_nav2 = DeclareLaunchArgument(
        'use_nav2',
        default_value='true',
        description='設為 false 可略過 Nav2',
    )

    sim_time = {'use_sim_time': LaunchConfiguration('use_sim_time')}

    # ── Nav2 定位（map_server + AMCL）────────────────────────────────────────
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_pkg, 'launch', 'localization_launch.py')
        ),
        launch_arguments={
            'map':          LaunchConfiguration('map'),
            'params_file':  LaunchConfiguration('nav2_params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('use_nav2')),
    )

    # ── Nav2 導航堆疊 ─────────────────────────────────────────────────────────
    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_pkg, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'params_file':  LaunchConfiguration('nav2_params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('use_nav2')),
    )

    # ── 導航服務節點 ──────────────────────────────────────────────────────────
    nav_service_node = Node(
        package='main_policy',
        executable='nav_service_node',
        name='nav_service_node',
        output='screen',
        parameters=[
            LaunchConfiguration('nav_service_params_file'),
            sim_time,
        ],
    )

    # ── RViz2 ─────────────────────────────────────────────────────────────────
    rviz2 = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        parameters=[sim_time],
        condition=IfCondition(LaunchConfiguration('use_rviz')),
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_map,
        declare_nav2_params,
        declare_nav_service_params,
        declare_rviz_config,
        declare_use_rviz,
        declare_use_nav2,
        localization,
        navigation,
        nav_service_node,
        rviz2,
    ])
