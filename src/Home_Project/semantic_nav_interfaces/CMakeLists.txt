cmake_minimum_required(VERSION 3.8)
project(semantic_nav_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/ExecuteRobotTask.action"
  "action/DetectSemanticObjects.action"
  "msg/RobotFlowStatus.msg"
  "msg/SemanticDetection2D.msg"
  "srv/NavToPoint.srv"
  "srv/SetRobotMode.srv"
  DEPENDENCIES builtin_interfaces sensor_msgs
)

ament_package()
