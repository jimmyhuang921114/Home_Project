import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'main_policy'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hungyu',
    maintainer_email='doubleradiate@gmail.com',
    description='Semantic map integrator node',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'map_builder_node = main_policy.map_builder_node:main',
            'nav_service_node = main_policy.nav_service_node:main',
            'sementic_map_node = main_policy.sementic_map_node:main',
            'robot_task_orchestrator_node = main_policy.robot_task_orchestrator_node:main',
            'robot_mode_manager = main_policy.robot_mode_manager_node:main',
            'robot_task_executor = main_policy.robot_task_executor_node:main',
            'robot_state = main_policy.robot_state_node:main',
            'robot_api_server = main_policy.robot_api_server_node:main',
            'mock_motion_servers = main_policy.mock_motion_servers_node:main',
        ],
    },
)
