#!/usr/bin/env bash
set -e
cd /home/jimmy/work_ws/home_project_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run web_nav_control web_nav_api
