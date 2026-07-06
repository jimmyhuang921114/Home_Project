from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal


class Point2D(BaseModel):
    x: float
    y: float


class Waypoint(BaseModel):
    id: str
    x: float
    y: float
    yaw: float = 0.0
    use_yaw: bool = False
    source_node_id: Optional[int] = None


class NavToPointRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0
    use_yaw: bool = False


class LoadWaypointsRequest(BaseModel):
    path: str


class GenerateWaypointsRequest(BaseModel):
    polygon: List[List[float]] = Field(..., min_length=3)
    spacing: float = Field(0.75, gt=0.01)
    margin: float = Field(0.60, ge=0.0)
    snake_order: bool = True


class ExportWaypointsRequest(BaseModel):
    waypoints: List[Waypoint]
    format: Literal['yaml', 'json'] = 'yaml'
    frame_id: str = 'map'


class SaveWaypointsRequest(BaseModel):
    waypoints: List[Waypoint]


class ChatRequest(BaseModel):
    message: str
    mode: Literal['text', 'voice'] = 'text'


class ChatResponse(BaseModel):
    ok: bool
    reply: str
    intent: str
    actions: List[Dict[str, Any]] = Field(default_factory=list)
