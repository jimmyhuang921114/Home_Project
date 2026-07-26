"""Contract-faithful HTTP v1 adapter for Nav2 and OpenArm actions."""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from action_msgs.msg import GoalStatus
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from pydantic import BaseModel, Field
from rclpy.action import ActionClient

try:
    from openarm_interfaces.action import PickPlaceSegment
except ImportError:  # OpenArm is an optional runtime overlay.
    PickPlaceSegment = None


TERMINAL = {"succeeded", "canceled", "aborted"}
STAGE_NAMES = {0: "OPENING", 1: "GRASPED", 2: "LIFTING", 3: "CARRYING", 4: "RELEASED", 5: "HOMING"}


class HeaderModel(BaseModel):
    frame_id: str = "map"
    stamp: Optional[dict[str, int]] = None


class PositionModel(BaseModel):
    x: float
    y: float
    z: float = 0.0


class QuaternionModel(BaseModel):
    x: float
    y: float
    z: float
    w: float


class PoseModel(BaseModel):
    position: PositionModel
    orientation: QuaternionModel


class PoseStampedModel(BaseModel):
    header: HeaderModel = Field(default_factory=HeaderModel)
    pose: PoseModel


class NavigationRequest(BaseModel):
    request_id: str
    pose: PoseStampedModel
    behavior_tree: str = ""


class VlaRequest(BaseModel):
    request_id: str
    task_key: str
    segment: int
    execute: bool
    timeout_sec: float


def dump(model: BaseModel) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class V1ActionApi:
    """A bounded, thread-safe goal registry exposed by FastAPI routes."""

    def __init__(self, node) -> None:
        self.node = node
        p = node.get_parameter
        self.host = str(p("api_host").value)
        self.token = str(p("api_token").value) or os.environ.get("MAIN_POLICY_API_TOKEN", "")
        self.vla_server_execute_enabled = bool(p("vla_server_execute_enabled").value)
        self.hardware = bool(p("hardware_execution_enabled").value) and self.vla_server_execute_enabled
        if self.host not in {"127.0.0.1", "::1", "localhost"} and not self.token:
            raise RuntimeError("api_token is required for a non-loopback API bind")
        if self.hardware and not self.token:
            raise RuntimeError("api_token is required when hardware execution is enabled")
        self.timeout = float(p("action_server_timeout_s").value)
        try:
            allowlist = p("nav_behavior_tree_allowlist").value
        except Exception:  # ROS 2 treats an empty YAML sequence as uninitialized.
            allowlist = []
        self.allowlist = {str(v) for v in (allowlist or []) if str(v)}
        self.nav_name, self.vla_name = str(p("nav_action").value), str(p("vla_action").value)
        self.nav = ActionClient(node, NavigateToPose, self.nav_name, callback_group=node._cbg)
        self.vla = ActionClient(node, PickPlaceSegment, self.vla_name, callback_group=node._cbg) if PickPlaceSegment else None
        self.catalog, self.catalog_version = self._catalog(str(p("vla_tasks_json").value), str(p("vla_catalog_version").value))
        self.lock = threading.RLock()
        self.goals: dict[str, dict] = {}
        self.request_ids: dict[str, tuple[str, str]] = {}
        self.active = {"navigate_to_pose": None, "pickplace_segment": None}
        self.holding_state = str(p("initial_holding_state").value)
        self.holding_task_key = None
        self.base_permission = str(p("initial_base_motion_permission").value)
        self.recovery_required = False

    @staticmethod
    def _catalog(raw: str, version: str) -> tuple[dict[str, bool], str]:
        try: items = json.loads(raw)
        except json.JSONDecodeError as exc: raise RuntimeError("vla_tasks_json must be JSON") from exc
        if not isinstance(items, list): raise RuntimeError("vla_tasks_json must be a JSON list")
        return ({str(v["task_key"]): bool(v.get("enabled", False)) for v in items if isinstance(v, dict) and isinstance(v.get("task_key"), str)}, version)

    def mount(self, app: FastAPI) -> None:
        @app.get("/api/v1/health")
        async def health():
            nav_ready, vla_ready = self.nav.server_is_ready(), bool(self.vla and self.vla.server_is_ready())
            return {"status": "ready" if nav_ready and vla_ready else "degraded", "api_version": "v1", "ros_distro": os.environ.get("ROS_DISTRO", "unknown"), "nav2": {"ready": nav_ready, "action_name": self.nav_name, "action_type": "nav2_msgs/action/NavigateToPose", "contract_commit": "3c3db59d6969d8ecee8e68468693d006397f4a0c"}, "vla": {"ready": vla_ready, "action_name": self.vla_name, "action_type": "openarm_interfaces/action/PickPlaceSegment", "contract_commit": "bb5cffe882e7ee450225b7df5d03d6d700a02826"}, "hardware_execution_enabled": self.hardware}

        @app.get("/api/v1/capabilities/vla-tasks")
        async def capabilities():
            return {"catalog_version": self.catalog_version, "tasks": [{"task_key": k, "enabled": enabled} for k, enabled in sorted(self.catalog.items())]}

        @app.get("/api/v1/robot/state")
        async def state(): return self.state()

        @app.post("/api/v1/navigation/goals", status_code=202)
        async def navigation(body: NavigationRequest, authorization: Optional[str] = Header(default=None)):
            self.auth(authorization); return await self.submit_nav(dump(body))

        @app.get("/api/v1/navigation/goals/{goal_id}")
        async def navigation_goal(goal_id: str): return self.goal(goal_id, "navigate_to_pose")

        @app.post("/api/v1/navigation/goals/{goal_id}/cancel")
        async def navigation_cancel(goal_id: str, authorization: Optional[str] = Header(default=None)):
            self.auth(authorization); return self.cancel(goal_id, "navigate_to_pose")

        @app.post("/api/v1/vla/goals", status_code=202)
        async def vla(body: VlaRequest, authorization: Optional[str] = Header(default=None)):
            self.auth(authorization); return await self.submit_vla(dump(body))

        @app.get("/api/v1/vla/goals/{goal_id}")
        async def vla_goal(goal_id: str): return self.goal(goal_id, "pickplace_segment")

        @app.post("/api/v1/vla/goals/{goal_id}/cancel")
        async def vla_cancel(goal_id: str, authorization: Optional[str] = Header(default=None)):
            self.auth(authorization); return self.cancel(goal_id, "pickplace_segment")

    def auth(self, value: Optional[str]) -> None:
        if self.token and value != f"Bearer {self.token}": raise HTTPException(401, "Bearer token is required")

    def state(self) -> dict:
        with self.lock:
            return {"observed_at": now(), "hardware_execution_enabled": self.hardware, "navigation": {"active_goal_id": self.active["navigate_to_pose"], "status": self._active_status("navigate_to_pose")}, "manipulation": {"active_goal_id": self.active["pickplace_segment"], "status": self._active_status("pickplace_segment"), "holding_state": self.holding_state, "holding_task_key": self.holding_task_key, "base_motion_permission": self.base_permission, "recovery_required": self.recovery_required}}

    def _active_status(self, action: str) -> str:
        goal_id = self.active[action]
        return "idle" if goal_id is None else self.goals[goal_id]["status"]

    def existing(self, payload: dict):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        old = self.request_ids.get(payload["request_id"])
        if not old: return None
        if old[0] != raw: return self.error(409, "idempotency_conflict", "request_id was used with a different body")
        return JSONResponse(status_code=200, content=self.accepted(self.goals[old[1]]))

    async def submit_nav(self, payload: dict):
        existing = self.existing(payload)
        if existing: return existing
        if self.recovery_required: return self.error(409, "recovery_required", "Robot recovery is required")
        if self.base_permission != "allowed": return self.error(409, "unsafe_state", "Base motion is not permitted")
        if self.active["pickplace_segment"]: return self.error(409, "goal_rejected", "VLA goal is active")
        if self.active["navigate_to_pose"]: return self.error(409, "goal_already_active", "Navigation goal is active")
        try: self.validate_pose(payload["pose"])
        except ValueError as exc: return self.error(422, "validation_failed", str(exc))
        if payload["behavior_tree"] and payload["behavior_tree"] not in self.allowlist: return self.error(422, "validation_failed", "behavior_tree is not allowlisted")
        if not await self.wait(self.nav): return self.error(503, "action_server_unavailable", "Nav2 action server is unavailable")
        record = self.create(payload, "navigate_to_pose")
        future = self.nav.send_goal_async(self.nav_goal(payload), feedback_callback=lambda msg: self.nav_feedback(record["goal_id"], msg))
        return await self.accept(record, future)

    async def submit_vla(self, payload: dict):
        existing = self.existing(payload)
        if existing: return existing
        task, segment = payload["task_key"], payload["segment"]
        if task not in self.catalog or not self.catalog[task]: return self.error(409, "goal_rejected", "task_key is not enabled")
        if segment not in {1, 2} or not math.isfinite(float(payload["timeout_sec"])): return self.error(422, "validation_failed", "invalid segment or timeout_sec")
        if payload["execute"] and not (self.hardware and self.vla_server_execute_enabled):
            return self.error(409, "unsafe_state", "Hardware execution is not armed by both main_policy and VLA server")
        if self.recovery_required: return self.error(409, "recovery_required", "Robot recovery is required")
        if self.active["pickplace_segment"]: return self.error(409, "goal_already_active", "VLA goal is active")
        if self.active["navigate_to_pose"]: return self.error(409, "goal_rejected", "Navigation goal is active")
        if self.holding_state == "unknown": return self.error(503, "state_unavailable", "Holding state is unknown")
        if segment == 1 and self.holding_state != "empty": return self.error(409, "unsafe_state", "PICK requires empty gripper")
        if segment == 2 and (self.holding_state != "holding" or self.holding_task_key != task): return self.error(409, "unsafe_state", "PLACE task_key does not match held object", {"holding_task_key": self.holding_task_key})
        if not self.vla or not await self.wait(self.vla): return self.error(503, "action_server_unavailable", "VLA action server is unavailable")
        record = self.create(payload, "pickplace_segment")
        goal = PickPlaceSegment.Goal(); goal.task_key, goal.segment, goal.execute, goal.timeout_sec = task, segment, payload["execute"], float(payload["timeout_sec"])
        return await self.accept(record, self.vla.send_goal_async(goal, feedback_callback=lambda msg: self.vla_feedback(record["goal_id"], msg)))

    def create(self, payload: dict, action: str) -> dict:
        goal_id = str(uuid.uuid4()); raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        record = {"request_id": payload["request_id"], "goal_id": goal_id, "action": action, "status": "accepted", "accepted_at": now(), "started_at": None, "finished_at": None, "payload": payload, "latest_feedback": None, "result": None, "handle": None}
        with self.lock: self.goals[goal_id] = record; self.request_ids[payload["request_id"]] = (raw, goal_id); self.active[action] = goal_id
        return record

    async def accept(self, record: dict, future):
        deadline = time.monotonic() + self.timeout
        while not future.done() and time.monotonic() < deadline: await asyncio.sleep(.02)
        if not future.done() or future.result() is None: return self.fail_accept(record, 503, "action_server_unavailable", "Goal acceptance timed out")
        handle = future.result()
        if not handle.accepted: return self.fail_accept(record, 409, "goal_rejected", "ROS action server rejected goal")
        with self.lock: record["handle"], record["status"], record["started_at"] = handle, "executing", now()
        handle.get_result_async().add_done_callback(lambda f, gid=record["goal_id"]: self.finish(gid, f))
        return JSONResponse(status_code=202, content=self.accepted(record))

    def fail_accept(self, record: dict, status: int, code: str, message: str):
        with self.lock: self.goals.pop(record["goal_id"], None); self.request_ids.pop(record["request_id"], None); self.active[record["action"]] = None
        return self.error(status, code, message)

    def accepted(self, record: dict) -> dict:
        prefix = "navigation" if record["action"] == "navigate_to_pose" else "vla"
        return {"request_id": record["request_id"], "goal_id": record["goal_id"], "action": record["action"], "status": record["status"], "accepted_at": record["accepted_at"], "status_url": f"/api/v1/{prefix}/goals/{record['goal_id']}"}

    def goal(self, goal_id: str, action: str):
        with self.lock:
            record = self.goals.get(goal_id)
            if not record or record["action"] != action: return self.error(404, "goal_not_found", "Goal does not exist")
            result = {k: record[k] for k in ("request_id", "goal_id", "action", "status", "accepted_at", "started_at", "finished_at", "latest_feedback", "result")}
            if action == "pickplace_segment": result["goal"] = {k: record["payload"][k] for k in ("task_key", "segment", "execute", "timeout_sec")}
            return result

    def cancel(self, goal_id: str, action: str):
        with self.lock:
            record = self.goals.get(goal_id)
            if not record or record["action"] != action: return self.error(404, "goal_not_found", "Goal does not exist")
            if record["status"] in TERMINAL: return {"goal_id": goal_id, "status": record["status"]}
            record["status"] = "canceling"; handle = record["handle"]
            if action == "pickplace_segment": self.holding_state, self.holding_task_key, self.recovery_required = "unknown", None, True
        if handle: handle.cancel_goal_async()
        return {"goal_id": goal_id, "status": "canceling"}

    def finish(self, goal_id: str, future) -> None:
        with self.lock: record = self.goals.get(goal_id)
        if not record: return
        try:
            wrapped = future.result(); status = {GoalStatus.STATUS_SUCCEEDED: "succeeded", GoalStatus.STATUS_CANCELED: "canceled"}.get(wrapped.status, "aborted")
            result = self.vla_result(wrapped.result) if record["action"] == "pickplace_segment" else {"result": {}}
            if record["action"] == "pickplace_segment" and (not result["success"] or result["result_code"] != 0): status = "aborted" if status == "succeeded" else status
        except Exception as exc: status, result = "aborted", {"error": {"code": "action_result_unavailable", "message": str(exc)}}
        with self.lock:
            record["status"], record["finished_at"], record["result"] = status, now(), result
            if self.active[record["action"]] == goal_id: self.active[record["action"]] = None
            if record["action"] == "pickplace_segment":
                if status == "succeeded": self.holding_state, self.holding_task_key = ("holding", record["payload"]["task_key"]) if record["payload"]["segment"] == 1 else ("empty", None)
                else: self.holding_state, self.holding_task_key, self.recovery_required = "unknown", None, True

    def nav_feedback(self, goal_id: str, msg) -> None:
        f = msg.feedback; self.feedback(goal_id, {"current_pose": self.pose_json(f.current_pose), "navigation_time": self.duration(f.navigation_time), "estimated_time_remaining": self.duration(f.estimated_time_remaining), "number_of_recoveries": int(f.number_of_recoveries), "distance_remaining": float(f.distance_remaining)})

    def vla_feedback(self, goal_id: str, msg) -> None:
        f = msg.feedback; stage = int(f.stage); self.feedback(goal_id, {"stage": stage, "stage_name": STAGE_NAMES.get(stage, "UNKNOWN"), "detail": str(f.detail), "grip_rad": float(f.grip_rad), "lift_delta": float(f.lift_delta), "home_dist": float(f.home_dist), "elapsed_sec": float(f.elapsed_sec)})

    def feedback(self, goal_id: str, value: dict) -> None:
        with self.lock:
            if goal_id in self.goals: self.goals[goal_id]["latest_feedback"] = value

    async def wait(self, client) -> bool:
        deadline = time.monotonic() + self.timeout
        while not client.server_is_ready():
            if time.monotonic() >= deadline: return False
            await asyncio.sleep(.05)
        return True

    def nav_goal(self, payload: dict):
        pose = payload["pose"]; stamped = PoseStamped(); header, p = pose["header"], pose["pose"]
        stamped.header.frame_id = header["frame_id"]
        if header["stamp"] is None: stamped.header.stamp = self.node.get_clock().now().to_msg()
        else: stamped.header.stamp.sec, stamped.header.stamp.nanosec = int(header["stamp"]["sec"]), int(header["stamp"]["nanosec"])
        for k, v in p["position"].items(): setattr(stamped.pose.position, k, float(v))
        for k, v in p["orientation"].items(): setattr(stamped.pose.orientation, k, float(v))
        goal = NavigateToPose.Goal(); goal.pose, goal.behavior_tree = stamped, payload["behavior_tree"]
        return goal

    @staticmethod
    def validate_pose(pose: dict) -> None:
        if pose["header"]["frame_id"] != "map": raise ValueError("frame_id must be map")
        values = list(pose["pose"]["position"].values()) + list(pose["pose"]["orientation"].values())
        if not all(math.isfinite(float(v)) for v in values): raise ValueError("pose values must be finite")
        q = pose["pose"]["orientation"]; norm = math.sqrt(sum(float(q[k]) ** 2 for k in ("x", "y", "z", "w")))
        if not math.isclose(norm, 1.0, rel_tol=1e-4, abs_tol=1e-4): raise ValueError("orientation must be normalized")

    @staticmethod
    def vla_result(result) -> dict:
        code = int(result.result_code)
        return {"success": bool(result.success), "result_code": code, "result_name": {0: "DETECTED", 1: "CANCELED", 2: "TIMEOUT"}.get(code, "UNKNOWN"), "message": str(result.message), "final_state": [float(v) for v in result.final_state], "elapsed_sec": float(result.elapsed_sec)}
    @staticmethod
    def duration(value) -> dict: return {"sec": int(value.sec), "nanosec": int(value.nanosec)}
    @staticmethod
    def pose_json(value) -> dict:
        p = value.pose; return {"header": {"frame_id": value.header.frame_id, "stamp": {"sec": int(value.header.stamp.sec), "nanosec": int(value.header.stamp.nanosec)}}, "pose": {"position": {"x": p.position.x, "y": p.position.y, "z": p.position.z}, "orientation": {"x": p.orientation.x, "y": p.orientation.y, "z": p.orientation.z, "w": p.orientation.w}}}
    @staticmethod
    def error(status: int, code: str, message: str, details: Optional[dict] = None):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "retryable": status >= 500, "details": details or {}}})
