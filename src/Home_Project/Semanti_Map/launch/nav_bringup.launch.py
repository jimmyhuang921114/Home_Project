import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg = get_package_share_directory('Semanti_Map')
    nav2_bringup = get_package_share_directory('nav2_bringup')

    # ── 參數宣告 ──────────────────────────────────────────────────────────────
    declare_map = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(pkg, 'map', 'map.yaml'),
        description='Map YAML path',
    )

    declare_localization_params = DeclareLaunchArgument(
        'localization_params_file',
        default_value=os.path.join(pkg, 'config', 'localization.yaml'),
        description='AMCL / map_server localization params YAML path',
    )

    declare_nav2_params = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=os.path.join(pkg, 'config', 'nav2_params.yaml'),
        description='Nav2 navigation params YAML path',
    )

    declare_sem_params = DeclareLaunchArgument(
        'sem_params_file',
        default_value=os.path.join(pkg, 'config', 'params.yaml'),
        description='Semantic map node params YAML path',
    )

    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation clock',
    )

    declare_rviz_config = DeclareLaunchArgument(
        'rviz_config',
        default_value=os.path.join(nav2_bringup, 'rviz', 'nav2_default_view.rviz'),
        description='RViz2 config path',
    )

    declare_use_rviz = DeclareLaunchArgument(
        'use_rviz',
        default_value='true',
        description='Set false to skip RViz2',
    )

    declare_use_nav2 = DeclareLaunchArgument(
        'use_nav2',
        default_value='true',
        description='Set false to skip Nav2',
    )

    declare_use_semantic_projection = DeclareLaunchArgument(
        'use_semantic_projection',
        default_value='true',
        description='Set false to skip Semanti_Map semantic_map_node',
    )

    declare_use_nav_service = DeclareLaunchArgument(
        'use_nav_service',
        default_value='true',
        description='Set false to skip main_policy nav_service_node',
    )

    declare_use_waypoint_node = DeclareLaunchArgument(
        'use_waypoint_node',
        default_value='false',
        description='Set true to start main_policy sementic_map_node waypoint runner',
    )

    # ── Nav2 Localization：map_server + AMCL ────────────────────────────────
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup, 'launch', 'localization_launch.py')
        ),
        launch_arguments={
            'map': LaunchConfiguration('map'),
            'params_file': LaunchConfiguration('localization_params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('use_nav2')),
    )

    # ── Nav2 Navigation：planner / controller / costmaps / behavior ─────────
    # 延遲一點啟動，讓 Isaac Sim 的 /clock、/odom、/tf 先進來
    navigation = TimerAction(
        period=3.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(nav2_bringup, 'launch', 'navigation_launch.py')
                ),
                launch_arguments={
                    'params_file': LaunchConfiguration('nav2_params_file'),
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                }.items(),
                condition=IfCondition(LaunchConfiguration('use_nav2')),
            )
        ],
    )

    # ── /nav_to_point service ───────────────────────────────────────────────
    # main_policy 的 nav_service_node 會提供 /nav_to_point
    nav_service_node = TimerAction(
        period=5.0,
        actions=[
            Node(
                package='main_policy',
                executable='nav_service_node',
                name='nav_service_node',
                output='screen',
                parameters=[
                    {'use_sim_time': LaunchConfiguration('use_sim_time')},
                ],
                condition=IfCondition(LaunchConfiguration('use_nav_service')),
            )
        ],
    )

    # ── Semanti_Map 的語意投影節點 ───────────────────────────────────────────
    # 這個是 /semantic_map/raw_detections 那個 node，不是 waypoint runner
    semantic_projection_node = Node(
        package='Semanti_Map',
        executable='semantic_map_node',
        name='semantic_map_node',
        output='screen',
        parameters=[
            LaunchConfiguration('sem_params_file'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')},
        ],
        condition=IfCondition(LaunchConfiguration('use_semantic_projection')),
    )

    # ── main_policy waypoint runner ─────────────────────────────────────────
    # 這個才是你手動跑的：ros2 run main_policy sementic_map_node
    # 預設 false，避免 launch 一開就自動巡點
    waypoint_node = TimerAction(
        period=8.0,
        actions=[
            Node(
                package='main_policy',
                executable='sementic_map_node',
                name='waypoint_nav_to_point_step_service',
                output='screen',
                parameters=[
                    {'use_sim_time': LaunchConfiguration('use_sim_time')},
                ],
                condition=IfCondition(LaunchConfiguration('use_waypoint_node')),
            )
        ],
    )

    # ── RViz2 ────────────────────────────────────────────────────────────────
    rviz2 = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        condition=IfCondition(LaunchConfiguration('use_rviz')),
    )

    return LaunchDescription([
        declare_map,
        declare_localization_params,
        declare_nav2_params,
        declare_sem_params,
        declare_use_sim_time,
        declare_rviz_config,
        declare_use_rviz,
        declare_use_nav2,
        declare_use_semantic_projection,
        declare_use_nav_service,
        declare_use_waypoint_node,

        localization,
        navigation,
        nav_service_node,
        semantic_projection_node,
        waypoint_node,
        rviz2,
    ])