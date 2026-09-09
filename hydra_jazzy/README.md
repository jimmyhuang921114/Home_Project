# Home_Project Hydra Jazzy container

This is an independent Ubuntu 24.04 / ROS 2 Jazzy environment. It does not
modify or replace `/home/jimmy/work_ws/docker`, `hf-vision-cu128:latest`, or
`hf_vision_nav2`. PostgreSQL and large semantic models are not started.

```bash
./build.sh
./run.sh
./exec.sh
./test_hydra.sh
docker compose stop
```

The host workspaces are mounted at `/workspace/Hydra_Ws` and
`/workspace/home_project_runtime`. Both ROS containers use host networking,
domain 40, and CycloneDDS; the supported first-stage semantic exchange is the
atomic snapshot file in the shared runtime volume.
