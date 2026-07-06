cmake_minimum_required(VERSION 3.8)
project(robot_object_retrieval_ros)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
ament_python_install_package(robot_object_retrieval_ros_nodes)

find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/ImportSemanticMap.srv"
)

install(PROGRAMS
  scripts/semantic_map_import_service_node
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
