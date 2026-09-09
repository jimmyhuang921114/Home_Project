# ROS 2 / CycloneDDS Diagnostic Report

Audit timestamp: 2026-08-10T16:42:36+08:00  
Host: `jimmy-MS-7E41`, Ubuntu 22.04, ROS 2 Humble  
Audit mode: diagnostic only; no container restart, no process termination, no Isaac termination, and no persistent ROS setting change was intentionally performed.

## Executive result

The reported `ros2 topic list` timeout is caused by a wedged ROS 2 CLI daemon for domain 40, not by `rclpy` import, CycloneDDS participant creation, domain 40 itself, Isaac process count, or host shared-library pollution.

The daemon is PID `1588457`. It was started inside `home-project-nav2`, but because the container uses host networking it owns the host-visible endpoint `127.0.0.1:11551` (`11511 + ROS_DOMAIN_ID 40`). Its TCP listen queue is saturated (`Recv-Q 6`, `Send-Q 5`) and multiple sockets remain in `CLOSE-WAIT`. Consequently, both host and container daemon clients time out. Direct DDS graph access remains operational: `ros2 topic list --no-daemon` and the requested rclpy graph query complete.

There are two additional proven findings:

1. The container deliberately mixes Isaac-bundled compatibility libraries with `/opt/ros/humble`. This is confirmed contamination and an ABI risk, although it is not proven to be the trigger that wedged the daemon.
2. The expected Jimmy address `192.168.0.103` is not currently assigned or reachable. Jimmy is `192.168.0.123/24` on `wlp130s0f0`. This is a separate cross-machine/network assumption failure, not the cause of the local CLI timeout.

## Required status fields

```text
HOST_RCLPY_IMPORT=PASS
HOST_RCLPY_INIT=PASS
HOST_NODE_CREATE=PASS
HOST_GRAPH_QUERY=PASS (get_topic_names_and_types; 98 topics on domain 40)

DOMAIN99_STATUS=PASS (init, node creation, topic graph query, shutdown all completed; 2 topics)
DOMAIN40_STATUS=PASS_FOR_PARTICIPANT_AND_TOPIC_GRAPH; FAIL_FOR_DOMAIN40_CLI_DAEMON; FAIL_FOR_NATIVE_NODE_NAME_QUERY

ROS2_TOPIC_LIST_STATUS=FAIL_WITH_DAEMON_RC124; PASS_WITH_NO_DAEMON_RC0
ROS2_DAEMON_STATUS=FAIL_ON_DOMAIN40_RC124; DOMAIN99_STATUS_COMMAND_PASS_AND_REPORTS_NOT_RUNNING

HOST_LIBRARY_ABI_STATUS=PASS (clean /opt/ros + Ubuntu system resolution; no IsaacLab, Conda, or isaac_ros2_compat paths)
CYCLONEDDS_CONFIG_STATUS=PASS_FOR_LOCAL_DDS_OPERATION; CONFIG_SOURCE_HAS_UNEXPECTED_SHELL_STARTUP_WRITE_SIDE_EFFECT
DOCKER_ROS2_STATUS=PARTIAL_FAIL (rclpy lifecycle and direct graph pass; daemon-backed CLI fails; mixed-library contamination proven)
ISAAC_PROCESS_STATUS=PASS_FOR_SINGLE_INSTANCE_INVENTORY (exactly one active Isaac Sim runtime; no duplicate publisher/runtime found)
NETWORK_STATUS=FAIL_FOR_EXPECTED_ADDRESS_ASSUMPTION (active IP is 192.168.0.123, not 192.168.0.103; .103 did not answer ARP/ping)

ROOT_CAUSE=C. ros2 daemon corruption/unresponsive daemon on domain 40
EVIDENCE=PID 1588457 owns 127.0.0.1:11551 with a saturated accept queue; domain-40 daemon commands time out on host and container; direct no-daemon topic queries pass; domain-99 daemon status responds normally; both domain lifecycle tests pass.
RECOMMENDED_FIX=After approval, stop only the domain-40 ROS CLI daemon, verify the port is released, and rerun the same clean host tests. Then isolate/remove the container's mixed Isaac compatibility overlay only after a controlled native-library A/B test and cross-runtime topic/action verification. Separately correct the Jimmy/Thor IP assumption.

FINAL_DIAGNOSTIC_STATUS=FAIL
```

## Phase 1 — Host ROS runtime

### Baseline environment

```text
which python3=/usr/bin/python3
python3 --version=Python 3.10.12
which ros2=/opt/ros/humble/bin/ros2
ROS_DISTRO=humble
ROS_VERSION=2
ROS_PYTHON_VERSION=3
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ROS_DOMAIN_ID=40
CYCLONEDDS_URI=file:///home/jimmy/.config/cyclonedds/cyclonedds.xml
ROS_LOCALHOST_ONLY=0
LD_LIBRARY_PATH=/opt/ros/humble/opt/rviz_ogre_vendor/lib:/opt/ros/humble/lib/x86_64-linux-gnu:/opt/ros/humble/lib
PYTHONPATH=/opt/ros/humble/lib/python3.10/site-packages:/opt/ros/humble/local/lib/python3.10/dist-packages
AMENT_PREFIX_PATH=/opt/ros/humble
CMAKE_PREFIX_PATH=<UNSET>
COLCON_PREFIX_PATH=<UNSET>
```

The requested clean-shell environment, with `CYCLONEDDS_URI` and `ROS_LOCALHOST_ONLY` unset, imported `rclpy` successfully.

### Loaded library provenance

`/opt/ros/humble/lib/librcl_logging_spdlog.so` resolves:

```text
libspdlog.so.1 -> /lib/x86_64-linux-gnu/libspdlog.so.1
libfmt.so.8    -> /lib/x86_64-linux-gnu/libfmt.so.8
```

The rclpy extension resolves `librcl*`, `librmw.so`, `librmw_implementation.so`, and ROSIDL libraries from `/opt/ros/humble`. The dynamically selected Cyclone RMW resolves:

```text
librmw_cyclonedds_cpp.so -> /opt/ros/humble/lib/librmw_cyclonedds_cpp.so
libddsc.so.0             -> /opt/ros/humble/lib/x86_64-linux-gnu/libddsc.so.0
librmw.so                -> /opt/ros/humble/lib/librmw.so
librmw_dds_common.so     -> /opt/ros/humble/lib/librmw_dds_common.so
ROSIDL runtime and introspection libraries -> /opt/ros/humble/lib
```

No resolved host library came from IsaacLab, Miniconda, or `Home_Project/runtime/isaac_ros2_compat`. The previously reported `librcl_logging_spdlog.so` undefined-symbol condition is not present in the audited host environment.

## Phase 2 — rclpy lifecycle isolation

All calls were bracketed with before/after markers and a 12-second outer timeout.

```text
DOMAIN99_INIT=PASS
DOMAIN99_NODE_CREATE=PASS
DOMAIN99_GRAPH_QUERY=PASS (2 topics)
DOMAIN99_SHUTDOWN=PASS
DOMAIN99_RC=0

DOMAIN40_INIT=PASS
DOMAIN40_NODE_CREATE=PASS
DOMAIN40_GRAPH_QUERY=PASS (98 topics)
DOMAIN40_SHUTDOWN=PASS
DOMAIN40_RC=0
```

Therefore, the symptom is not a CycloneDDS participant-creation hang and is not caused merely by selecting domain 40.

## Phase 3 — ROS CLI and daemon isolation

Clean host environment, domain 40, custom Cyclone URI unset:

```text
ros2 daemon status                  -> timeout, RC=124
ros2 topic list                     -> timeout, RC=124
ros2 node list                      -> timeout, RC=124
ros2 topic list --no-daemon         -> PASS, RC=0, about 1 second
ros2 node list --no-daemon          -> FAIL, RC=1, "empty node name returned by the RMW layer"
repeat topic list --no-daemon       -> PASS, RC=0
repeat node list --no-daemon        -> same empty-node-name failure
domain 99: ros2 daemon status       -> PASS, "The daemon is not running"
```

The persistent native host node-name error is a second graph-compatibility defect, but it does not block topic graph queries and does not explain the daemon TCP behavior by itself.

`ros2 daemon stop` was deliberately not executed because the audit's controlling instruction was READ-ONLY and stopping it would change process state. No daemon or other process was killed.

### Daemon proof

Local ROS 2 CLI source defines the daemon port as `11511 + ROS_DOMAIN_ID`, hence domain 40 uses TCP 11551.

```text
PID=1588457
PPID=1572907 (home-project-nav2 main process)
command=/usr/bin/python3 -c "from ros2cli.daemon.daemonize import main; main()" --name ros2-daemon --ros-domain-id 40 --rmw-implementation rmw_cyclonedds_cpp
started=2026-08-10 16:00:15 +08:00
state=Sl, 8 threads
listener=127.0.0.1:11551
listen_queue=Recv-Q 6 / Send-Q 5
CLOSE-WAIT sockets=multiple
```

Host and container share this endpoint because `home-project-nav2` uses host networking. This fully explains why the same CLI timeout appears in both environments.

## Phase 4 — CycloneDDS configuration and environment sources

### Effective host config

`/home/jimmy/.config/cyclonedds/cyclonedds.xml` is well-formed and selects `wlp130s0f0` with `AllowMulticast=spdp`. Local DDS works both with this normal shell configuration and in the requested clean test where `CYCLONEDDS_URI` was unset.

Effective source chain:

```text
/home/jimmy/.profile
  -> sources /home/jimmy/.bashrc
/home/jimmy/.bashrc:126
  -> sources /opt/ros/humble/setup.bash
/home/jimmy/.bashrc:153
  -> sources /home/jimmy/ros2_cyclonedds_env.sh
```

`ros2_cyclonedds_env.sh` sets:

```text
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-40}
ROS_LOCALHOST_ONLY=0
CYCLONEDDS_URI=file:///home/jimmy/.config/cyclonedds/cyclonedds.xml
```

It also chooses the default-route interface and rewrites the XML with `mkdir -p` plus a heredoc every time it is sourced. This means login-shell initialization itself has a filesystem side effect. The XML observed during the audit had modification time `2026-08-10 16:20:22 +08:00`. This should be made deterministic in a later approved fix, but the generated content itself is not causing the current local DDS failure.

Other relevant sources found:

- `/home/jimmy/IsaacLab/isaac_ros2_cyclone_env.sh` removes `/opt/ros/*` paths, prepends Isaac Sim's bundled Humble bridge libraries, sets domain 40, and uses the same host Cyclone XML. It is not sourced by the normal host shell.
- `run_nav2_humble.sh` sets domain 40, Cyclone RMW, a separate `/home/jimmy/.ros/cyclonedds.xml`, and prepends `/opt/isaac_ros2_humble_compat` in the container.
- `Dockerfile.nav2-humble` supplies matching domain/RMW/URI defaults.
- Numerous archived reports and backup Docker scripts contain historical values but are not effective shell startup sources.

No current evidence supports classification B (CycloneDDS configuration) as the cause of the timeout.

## Phase 5 — Docker audit

```text
container=home-project-nav2
state=running
network_mode=host
ipc_mode=host
ROS_DOMAIN_ID=40
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
CYCLONEDDS_URI=file:///home/jimmy/.ros/cyclonedds.xml
LD_LIBRARY_PATH=/opt/isaac_ros2_humble_compat:/opt/ros/humble/lib:/opt/ros/humble/lib/x86_64-linux-gnu
```

Relevant mounts:

```text
/home/jimmy/work_ws/Home_Project -> /workspace (rw)
/home/jimmy/.ros/cyclonedds.xml -> /home/jimmy/.ros/cyclonedds.xml (ro)
/home/jimmy/work_ws/Home_Project/runtime/isaac_ros2_compat/lib -> /opt/isaac_ros2_humble_compat (ro)
named build/install/log volumes -> /colcon/{build,install,log}
```

After sourcing `/opt/ros/humble/setup.bash` and `/colcon/install/setup.bash`:

```text
container rclpy import=PASS
container rclpy init=PASS
container node create=PASS
container topic graph query=PASS (97 topics)
container shutdown=PASS
container ros2 topic list=FAIL, RC=124
container ros2 topic list --no-daemon=PASS, RC=0
container ros2 node list --no-daemon=PASS, RC=0
container ros2 daemon status=FAIL, RC=124
```

The container's rclpy extension loads a mixture: core `librcl*`, logging, messages, and Python bindings from `/opt/ros/humble`, while `librmw.so`, `libddsc.so.0`, `librmw_dds_common*`, `librosidl_runtime_c.so`, and introspection/type-support libraries resolve from `/opt/isaac_ros2_humble_compat`. The wedged daemon itself has exactly this mixed map. This proves category E as an environment defect/risk, but the successful container lifecycle and direct graph queries mean it is not proven as the daemon hang trigger.

`run_nav2_humble.sh` also copies compatibility libraries into the host workspace before container creation. That script was inspected only and was not executed.

## Phase 6 — Active participant/process inventory

Active ROS-related processes include the Nav2 launch, component container, Nav2 nodes, SWAGGER helper nodes, RViz, one suspended host `ros2 topic hz /realsense/rgb`, and the stuck container-origin ROS 2 daemon.

Exactly one Isaac runtime was found:

```text
PID=1635726
executable=/home/jimmy/IsaacLab/env_isaaclab/bin/python3.11
command=isaacsim ... --enable home_project.camera_restart_guard --enable home_project.localization_sensor_contract
LD_LIBRARY_PATH=.../isaacsim.ros2.bridge/humble/lib
CYCLONEDDS_URI=file:///home/jimmy/.config/cyclonedds/cyclonedds.xml
```

No second Isaac Sim publisher/runtime was found. Isaac was neither stopped nor altered. There is no evidence that duplicate Isaac instances cause this incident.

## Phase 7 — Network validation

```text
active interface=wlp130s0f0
flags=BROADCAST,MULTICAST,UP,LOWER_UP
actual IPv4=192.168.0.123/24 (dynamic)
default route=via 192.168.0.1 dev wlp130s0f0
expected IPv4=192.168.0.103 (not assigned)
ping 192.168.0.103=FAIL, 100% loss
neighbor 192.168.0.103=INCOMPLETE
enx00e04c521538=UP but has no IPv4 address
Cyclone multicast membership=239.255.0.1 present on wlp130s0f0
```

The interface selection is correct and multicast capability/group membership is present. However, the stated `192.168.0.103` assumption is false at audit time. Thor's authoritative IP was not present in the effective local environment files, so Thor-specific unicast reachability cannot be proven from the supplied data. Firewall status could not be read noninteractively because `sudo` requires a password; no firewall change was attempted.

## Phase 8 — Evidence-based classification

| Category | Result | Evidence |
|---|---|---|
| A. Host ROS shared-library ABI pollution | Not present | All audited host resolutions are `/opt/ros/humble` or Ubuntu system libraries. |
| B. CycloneDDS configuration | Not causal | Requested unset-URI lifecycle and graph tests pass; pinned configs select the active interface. |
| C. ros2 daemon corruption | **Proven primary cause** | Domain-40 daemon endpoint is owned by an unresponsive process with saturated backlog; daemon-free topic query passes. |
| D. ROS_DOMAIN_ID=40 participant issue | Disproven for init/topic graph | Domain 40 completes init, node creation, topic graph query, and shutdown. |
| E. Docker environment contamination | **Proven coexisting defect/risk** | Container and daemon maps mix `/opt/ros/humble` with Isaac compatibility RMW/DDS/ROSIDL libraries. Causality for the hang is not proven. |
| F. Isaac bundled ROS compatibility | Not proven as root cause | One Isaac exists; host clean lifecycle and topic graph work while Isaac is active. |
| G. Cross-distro Thor compatibility | No evidence available | No Thor process or authoritative remote runtime details were locally inspectable. |
| H. Network/interface issue | **Proven for expected-address assumption, not local CLI hang** | Jimmy is `.123`, expected `.103` is absent/unreachable; DDS interface and multicast are otherwise operational. |
| I. Other | Persistent malformed node-name graph entry | Native host `ros2 node list --no-daemon` fails while topic queries pass; publisher identity is not proven by this read-only audit. |

Historical host logs contain earlier `rmw_create_node: failed to create domain` records, but current controlled lifecycle tests do not reproduce them. No current exact-match log entry for `serdata`, type-hash warnings, or undefined symbols was found in the searched current host/container ROS logs.

## Proposed fix plan — not applied

1. With explicit approval, attempt a bounded graceful stop of only the domain-40 ROS CLI daemon. If it cannot respond, terminate only verified PID `1588457`; do not touch Isaac or Nav2 nodes.
2. Verify `127.0.0.1:11551` is released, then run clean host domain-40 lifecycle, `ros2 daemon status`, `ros2 topic list`, `ros2 node list`, and their `--no-daemon` equivalents.
3. Start exactly one daemon from a clean `/opt/ros/humble` host environment and verify that host and container clients return without timeout.
4. Run a controlled container A/B test using native Humble libraries versus the compatibility overlay. Check rclpy lifecycle, topic and node graphs, Isaac topics, Thor actions, message exchange, type hashes, and logs. Remove the compatibility overlay from `LD_LIBRARY_PATH` only if the native path passes those checks.
5. Identify the participant responsible for the empty node-name entry using bounded participant/process isolation or Cyclone tracing. Do not attribute it to Isaac or Thor without that evidence.
6. Standardize one CycloneDDS configuration source and remove the shell-startup rewrite side effect after validating the desired interface policy.
7. Confirm whether Jimmy should have a DHCP reservation/static address of `192.168.0.103` or whether documentation/Thor peer configuration must use current `192.168.0.123`; then test the actual Thor IP and multicast/unicast path. Do not change firewall until its read-only state is captured.

No fix in this plan has been applied.
