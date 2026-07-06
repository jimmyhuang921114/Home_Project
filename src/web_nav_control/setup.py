from setuptools import setup, find_packages

package_name = 'web_nav_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jimmy',
    maintainer_email='jimmy@example.com',
    description='ROS2 Nav2 web control dashboard with waypoint and polygon generation tools.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'web_nav_api = web_nav_api.main:main',
        ],
    },
)
