import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg = get_package_share_directory('Semanti_Map')
    nav2_bringup = get_package_share_directory('nav2_bringup')

    # ── 參數宣告 ──────────────────────────────────────────────────────────────
    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg, 'map', 'map.yaml'),
        description='地圖 YAML 路徑',
    )
    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(pkg, 'config', 'nav2_params.yaml'),
        description='Nav2 參數 YAML 路徑',
    )
    declare_sem_params = DeclareLaunchArgument(
        'sem_params_file',
        default_value=os.path.join(pkg, 'config', 'params.yaml'),
        description='語意地圖節點參數 YAML 路徑',
    )
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='使用模擬時鐘 (Gazebo) 時設為 ',
    )
    declare_rviz_config = DeclareLaunchArgument(
        'rviz_config',
        default_value=os.path.join(nav2_bringup, 'rviz', 'nav2_default_view.rviz'),
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
        description='設為 false 可略過 Nav2 (定位 + 導航)',
    )

    # ── Nav2 定位 (map_server + AMCL) ─────────────────────────────────────────
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup, 'launch', 'localization_launch.py')
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
            os.path.join(nav2_bringup, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'params_file':  LaunchConfiguration('nav2_params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('use_nav2')),
    )

    # ── 語意地圖節點 ──────────────────────────────────────────────────────────
    semantic_map_node = Node(
        package='Semanti_Map',
        executable='semantic_map_node',
        name='semantic_map_node',
        output='screen',
        parameters=[LaunchConfiguration('sem_params_file')],
    )

    # ── RViz2 ─────────────────────────────────────────────────────────────────
    rviz2 = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        condition=IfCondition(LaunchConfiguration('use_rviz')),
    )

    return LaunchDescription([
        declare_map,
        declare_nav2_params,
        declare_sem_params,
        declare_use_sim_time,
        declare_rviz_config,
        declare_use_rviz,
        declare_use_nav2,
        localization,
        navigation,
        semantic_map_node,
        rviz2,
    ])
