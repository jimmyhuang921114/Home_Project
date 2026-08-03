# Home_Project Vision Interface Build Report

Date: 2026-08-04 (Asia/Taipei)

- Package: `src/Home_Project/semantic_nav_interfaces`
- Package manifest parse: PASS (`semantic_nav_interfaces`, version `0.1.0`)
- Required dependencies: PASS (`builtin_interfaces`, `sensor_msgs`, `rosidl_default_generators`)
- Isolated package build: PASS
- Build environment available on Thor mirror: ROS 2 Jazzy
- `ros2 interface show` Action: PASS
- `ros2 interface show` message: PASS
- Generated Python imports: PASS
- Goal construction and assignment: PASS
- Result construction and assignment: PASS
- Feedback construction and assignment: PASS
- `SemanticDetection2D` construction and assignment: PASS
- CDR serialization/deserialization round trip: PASS

Build command:

```bash
cd /home/iclab/home_project_ws/Home_Project
source /opt/ros/jazzy/setup.bash
colcon build --packages-select semantic_nav_interfaces
```

Only `build/semantic_nav_interfaces` and `install/semantic_nav_interfaces` were cleaned. Unrelated workspace packages and runtime data were not removed.

Evidence: `interface_build_v11.log`, `home_action_show_v11.txt`, `home_message_show_v11.txt`, and `home_python_fields_v11.json`.
