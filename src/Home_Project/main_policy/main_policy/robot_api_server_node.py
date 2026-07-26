#!/usr/bin/env python3
"""FastAPI-to-ROS bridge.  This node never talks to hardware actions directly."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
import uuid
from typing import Any, Optional

import rclpy
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
import uvicorn

from semantic_nav_interfaces.action import ExecuteRobotTask
from semantic_nav_interfaces.msg import RobotFlowStatus
from semantic_nav_interfaces.srv import SetRobotMode

from .v1_action_api import V1ActionApi


def model_data(model: BaseModel) -> dict:
    method = getattr(model, "model_dump", None)
    return method() if method else model.dict()


class NavigationGoal(BaseModel):
    x: float
    y: float
    yaw: float
    frame_id: str = "map"


class ArmJointGoal(BaseModel):
    joint_names: list[str]
    positions: list[float]
    duration_s: float = 4.0


class NamedAction(BaseModel):
    name: str
    duration_s: float = 4.0


class GripperAction(BaseModel):
    action: str
    position: Optional[float] = None


class ModeRequest(BaseModel):
    mode: str


class RobotApiServer(Node):
    def __init__(self) -> None:
        super().__init__("robot_api_server_node")
        self.declare_parameter("api_host", "127.0.0.1")
        self.declare_parameter("api_port", 8020)
        self.declare_parameter("api_token", "")
        self.declare_parameter("hardware_execution_enabled", False)
        self.declare_parameter("vla_server_execute_enabled", False)
        self.declare_parameter("nav_action", "/navigate_to_pose")
        self.declare_parameter("vla_action", "/pickplace_segment")
        self.declare_parameter("vla_tasks_json", "[]")
        self.declare_parameter("vla_catalog_version", "unconfigured")
        self.declare_parameter("nav_behavior_tree_allowlist", [])
        self.declare_parameter("initial_holding_state", "unknown")
        self.declare_parameter("initial_base_motion_permission", "unknown")
        self.declare_parameter("cors_origins", ["http://localhost:3000"])
        self.declare_parameter("action_server_timeout_s", 3.0)
        self.declare_parameter("accept_timeout_s", 5.0)
        self._host = str(self.get_parameter("api_host").value)
        self._port = int(self.get_parameter("api_port").value)
        self._server_timeout = float(self.get_parameter("action_server_timeout_s").value)
        self._accept_timeout = float(self.get_parameter("accept_timeout_s").value)
        self._lock = threading.RLock()
        self._cbg = ReentrantCallbackGroup()
        self._state = self._empty_state()
        self._flow = self._empty_flow()
        self._last_result: dict = {}
        self._current_goal = None
        self._current_task_id = ""
        self._server = None
        self._server_thread = None
        self._v1 = V1ActionApi(self)

        self._flow_client = ActionClient(
            self, ExecuteRobotTask, "/robot_flow/execute", callback_group=self._cbg
        )
        self._mode_client = self.create_client(
            SetRobotMode, "/robot_mode/set", callback_group=self._cbg
        )
        self._mode_reset_client = self.create_client(
            Trigger, "/robot_mode/reset", callback_group=self._cbg
        )
        self.create_subscription(
            String, "/robot/state_json", self._state_cb, 10, callback_group=self._cbg
        )
        self.create_subscription(
            RobotFlowStatus,
            "/robot_flow/status",
            self._flow_cb,
            20,
            callback_group=self._cbg,
        )
        self.app = self._build_app()
        self._start_server()

    @staticmethod
    def _empty_state() -> dict:
        return {
            "timestamp": time.time(), "mode": "IDLE", "busy": False,
            "task": {}, "navigation": {}, "arm": {}, "errors": [],
        }

    @staticmethod
    def _empty_flow() -> dict:
        return {
            "task_id": "", "mode": "IDLE", "task_type": "", "state": "IDLE",
            "step": "WAITING_COMMAND", "progress": 0.0, "busy": False,
            "message": "", "json_detail": {},
        }

    def _state_cb(self, msg: String) -> None:
        try:
            value = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        with self._lock:
            self._state = value

    def _flow_cb(self, msg: RobotFlowStatus) -> None:
        try:
            detail = json.loads(msg.json_detail or "{}")
        except json.JSONDecodeError:
            detail = {}
        value = {
            "task_id": msg.task_id, "mode": msg.mode, "task_type": msg.task_type,
            "state": msg.state, "step": msg.step, "progress": float(msg.progress),
            "busy": bool(msg.busy), "message": msg.message, "json_detail": detail,
        }
        with self._lock:
            self._flow = value

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Home Project Robot API", version="1.0.0")
        origins = list(self.get_parameter("cors_origins").value)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.exception_handler(Exception)
        async def unhandled(request: Request, exc: Exception):
            self.get_logger().error(f"API error: {exc}")
            return self._error(500, "INTERNAL_ERROR", str(exc))

        @app.exception_handler(HTTPException)
        async def http_error(request: Request, exc: HTTPException):
            if request.url.path.startswith("/api/v1/"):
                code = "unauthorized" if exc.status_code == 401 else "invalid_request"
                return self._v1.error(exc.status_code, code, str(exc.detail))
            code = "INVALID_PAYLOAD" if exc.status_code == 422 else "HTTP_ERROR"
            return self._error(exc.status_code, code, str(exc.detail))

        @app.exception_handler(RequestValidationError)
        async def validation_error(request: Request, exc: RequestValidationError):
            if request.url.path.startswith("/api/v1/"):
                return self._v1.error(
                    422, "validation_failed", "Request validation failed",
                    {"errors": exc.errors()},
                )
            return JSONResponse(status_code=422, content={
                "success": False, "request_id": str(uuid.uuid4()), "task_id": None,
                "state": "REJECTED", "error_code": "INVALID_PAYLOAD",
                "message": "Request validation failed", "detail": {"errors": exc.errors()},
            })

        self._v1.mount(app)

        @app.get("/health")
        async def health():
            return {
                "success": True,
                "state": "OK",
                "message": "Robot API is running",
                "data": {"ros_ok": rclpy.ok(), "port": self._port},
            }

        @app.get("/api/robot/status")
        async def robot_status():
            return self._snapshot("_state")

        @app.get("/api/robot/flow")
        async def robot_flow():
            return self._snapshot("_flow")

        @app.get("/api/navigation/status")
        async def nav_status():
            return self._snapshot("_state").get("navigation", {})

        @app.post("/api/navigation/goals", status_code=202)
        async def nav_goal(body: NavigationGoal):
            payload = model_data(body)
            self._validate_finite(payload, ("x", "y", "yaw"))
            if payload["frame_id"] != "map":
                return self._error(422, "INVALID_FRAME", "frame_id must be map")
            return await self._submit("navigate", payload)

        @app.delete("/api/navigation/goals/current", status_code=202)
        async def cancel_nav():
            return await self._cancel_current()

        @app.get("/api/arm/status")
        async def arm_status():
            return self._snapshot("_state").get("arm", {})

        @app.post("/api/arm/joint-goals", status_code=202)
        async def arm_joints(body: ArmJointGoal):
            payload = model_data(body)
            if not payload["joint_names"] or not payload["positions"]:
                return self._error(422, "INVALID_PAYLOAD", "joint arrays cannot be empty")
            if len(payload["joint_names"]) != len(payload["positions"]):
                return self._error(422, "INVALID_PAYLOAD", "joint array lengths differ")
            self._validate_finite_list(payload["positions"])
            self._validate_finite(payload, ("duration_s",))
            if payload["duration_s"] <= 0:
                return self._error(422, "INVALID_DURATION", "duration_s must be positive")
            return await self._submit("arm_joints", payload)

        @app.post("/api/arm/named-actions", status_code=202)
        async def arm_named(body: NamedAction):
            payload = model_data(body)
            self._validate_finite(payload, ("duration_s",))
            return await self._submit("arm_named_pose", payload)

        @app.post("/api/gripper/actions", status_code=202)
        async def gripper(body: GripperAction):
            payload = model_data(body)
            if payload.get("position") is not None:
                self._validate_finite(payload, ("position",))
            return await self._submit("gripper", payload)

        @app.delete("/api/arm/actions/current", status_code=202)
        async def cancel_arm():
            return await self._cancel_current()

        @app.get("/api/mode")
        async def mode():
            state = self._snapshot("_state")
            return {"mode": state.get("mode", "IDLE"), "busy": state.get("busy", False)}

        @app.post("/api/mode")
        async def set_mode(body: ModeRequest):
            return await self._set_mode(body.mode)

        @app.post("/api/mode/reset")
        async def reset_mode():
            return await self._call_trigger(self._mode_reset_client)

        @app.get("/api/tasks/current")
        async def current_task():
            return self._snapshot("_flow")

        @app.get("/api/tasks/last-result")
        async def last_result():
            return self._snapshot("_last_result")

        @app.delete("/api/tasks/current", status_code=202)
        async def cancel_task():
            return await self._cancel_current()

        @app.websocket("/ws/robot/status")
        async def status_ws(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    await websocket.send_json(self._snapshot("_state"))
                    await asyncio.sleep(0.2)
            except (WebSocketDisconnect, RuntimeError):
                return

        return app

    def _snapshot(self, attr: str) -> dict:
        with self._lock:
            return json.loads(json.dumps(getattr(self, attr), allow_nan=False))

    async def _submit(self, task_type: str, payload: dict):
        request_id = str(uuid.uuid4())
        with self._lock:
            busy = bool(self._flow.get("busy") or self._state.get("busy"))
        if busy:
            return self._error(409, "ROBOT_BUSY", "Robot is busy", request_id)
        if not await self._wait_action_server(self._server_timeout):
            return self._error(
                503, "ROBOT_FLOW_UNAVAILABLE", "Robot flow server unavailable", request_id
            )
        payload = dict(payload)
        payload["_requester_mode"] = "USER_TASK"
        goal = ExecuteRobotTask.Goal()
        goal.task_type = task_type
        goal.json_payload = json.dumps(payload, allow_nan=False)
        future = self._flow_client.send_goal_async(goal, feedback_callback=self._feedback_cb)
        deadline = time.monotonic() + self._accept_timeout
        while not future.done():
            if time.monotonic() >= deadline:
                return self._error(504, "ACCEPT_TIMEOUT", "Task acceptance timed out", request_id)
            await asyncio.sleep(0.02)
        handle = future.result()
        if not handle.accepted:
            return self._error(409, "ROBOT_BUSY", "Task rejected by robot flow", request_id)
        task_id = self._goal_id(handle)
        with self._lock:
            self._current_goal = handle
            self._current_task_id = task_id
        handle.get_result_async().add_done_callback(self._result_cb)
        return JSONResponse(
            status_code=202,
            content={
                "success": True, "request_id": request_id, "task_id": task_id,
                "state": "ACCEPTED", "message": "Task accepted", "data": {},
            },
        )

    async def _wait_action_server(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while not self._flow_client.server_is_ready():
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    def _feedback_cb(self, msg) -> None:
        # Canonical flow snapshots come from /robot_flow/status.
        return

    def _result_cb(self, future) -> None:
        try:
            wrapped = future.result()
            result = wrapped.result
            try:
                data = json.loads(result.json_result or "{}")
            except json.JSONDecodeError:
                data = {}
            value = {
                "success": bool(result.success),
                "task_id": self._current_task_id,
                "state": result.final_state,
                "message": result.message,
                "data": data,
            }
        except Exception as exc:
            value = {
                "success": False, "task_id": self._current_task_id,
                "state": "ERROR", "message": str(exc), "data": {},
            }
        with self._lock:
            self._last_result = value
            self._current_goal = None
            self._current_task_id = ""

    async def _cancel_current(self):
        request_id = str(uuid.uuid4())
        with self._lock:
            handle = self._current_goal
            task_id = self._current_task_id
        if handle is None:
            return self._error(409, "NO_ACTIVE_TASK", "No active task", request_id)
        handle.cancel_goal_async()
        return JSONResponse(status_code=202, content={
            "success": True, "request_id": request_id, "task_id": task_id,
            "state": "CANCELING", "message": "Cancellation accepted", "data": {},
        })

    async def _set_mode(self, mode: str):
        request_id = str(uuid.uuid4())
        if not self._mode_client.service_is_ready():
            if not self._mode_client.wait_for_service(timeout_sec=1.0):
                return self._error(503, "MODE_SERVICE_UNAVAILABLE", "Mode service unavailable", request_id)
        req = SetRobotMode.Request()
        req.mode = str(mode)
        future = self._mode_client.call_async(req)
        deadline = time.monotonic() + self._accept_timeout
        while not future.done():
            if time.monotonic() >= deadline:
                return self._error(504, "MODE_TIMEOUT", "Mode request timed out", request_id)
            await asyncio.sleep(0.02)
        response = future.result()
        if not response.success:
            code = "ROBOT_BUSY" if "BUSY" in response.message else "MODE_CHANGE_FAILED"
            return self._error(409, code, response.message, request_id)
        return {
            "success": True, "request_id": request_id, "task_id": None,
            "state": response.current_mode, "message": response.message, "data": {},
        }

    async def _call_trigger(self, client):
        request_id = str(uuid.uuid4())
        if not client.service_is_ready() and not client.wait_for_service(timeout_sec=1.0):
            return self._error(503, "SERVICE_UNAVAILABLE", "Service unavailable", request_id)
        future = client.call_async(Trigger.Request())
        deadline = time.monotonic() + self._accept_timeout
        while not future.done():
            if time.monotonic() >= deadline:
                return self._error(504, "SERVICE_TIMEOUT", "Service timed out", request_id)
            await asyncio.sleep(0.02)
        result = future.result()
        if not result.success:
            return self._error(409, "REQUEST_FAILED", result.message, request_id)
        return {
            "success": True, "request_id": request_id, "task_id": None,
            "state": "IDLE", "message": result.message, "data": {},
        }

    @staticmethod
    def _goal_id(handle) -> str:
        try:
            return str(uuid.UUID(bytes=bytes(handle.goal_id.uuid)))
        except Exception:
            return str(uuid.uuid4())

    @staticmethod
    def _validate_finite(payload: dict, names: tuple[str, ...]) -> None:
        for name in names:
            value = float(payload[name])
            if not math.isfinite(value):
                raise HTTPException(status_code=422, detail=f"{name} must be finite")

    @staticmethod
    def _validate_finite_list(values: list) -> None:
        if not all(math.isfinite(float(value)) for value in values):
            raise HTTPException(status_code=422, detail="positions must be finite")

    @staticmethod
    def _error(status, code, message, request_id=None):
        return JSONResponse(status_code=status, content={
            "success": False, "request_id": request_id or str(uuid.uuid4()),
            "task_id": None, "state": "REJECTED", "error_code": code,
            "message": message, "detail": {},
        })

    def _start_server(self) -> None:
        config = uvicorn.Config(
            self.app, host=self._host, port=self._port, log_level="info", lifespan="off"
        )
        self._server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()

    def destroy_node(self):
        with self._lock:
            handle = self._current_goal
        if handle is not None:
            try:
                handle.cancel_goal_async()
            except Exception:
                pass
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RobotApiServer()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
