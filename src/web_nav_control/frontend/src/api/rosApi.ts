import type { MapPayload, PlanPayload, RobotPose, Waypoint, WaypointsPayload } from '../types/ros'

export async function getMap(): Promise<MapPayload> {
  return fetch('/api/map').then((r) => r.json())
}

export async function uploadMap(mapImage: File, mapYaml: File): Promise<MapPayload> {
  const body = new FormData()
  body.append('map_image', mapImage)
  body.append('map_yaml', mapYaml)
  return fetch('/api/upload_map', { method: 'POST', body }).then((r) => r.json())
}

export async function getRobotPose(): Promise<RobotPose> {
  return fetch('/api/robot_pose').then((r) => r.json())
}

export async function getPlan(): Promise<PlanPayload> {
  return fetch('/api/plan').then((r) => r.json())
}

export async function getWaypoints(): Promise<WaypointsPayload> {
  return fetch('/api/waypoints').then((r) => r.json())
}

export async function loadWaypoints(path: string): Promise<WaypointsPayload> {
  return fetch('/api/waypoints/load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  }).then((r) => r.json())
}

export async function uploadWaypoints(file: File): Promise<WaypointsPayload> {
  const body = new FormData()
  body.append('file', file)
  return fetch('/api/upload_waypoints', { method: 'POST', body }).then((r) => r.json())
}

export async function saveWaypoints(waypoints: Waypoint[]): Promise<WaypointsPayload & { success?: boolean }> {
  return fetch('/api/waypoints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ waypoints }),
  }).then((r) => r.json())
}

export async function navToPoint(wp: Waypoint): Promise<{ success: boolean; message: string }> {
  return fetch('/api/nav_to_point', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x: wp.x, y: wp.y, yaw: wp.yaw, use_yaw: wp.use_yaw }),
  }).then((r) => r.json())
}

export async function generateWaypoints(
  polygon: [number, number][],
  spacing: number,
  margin: number,
): Promise<Waypoint[]> {
  const res = await fetch('/api/generate_waypoints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ polygon, spacing, margin, snake_order: true }),
  }).then((r) => r.json())
  return res.waypoints ?? []
}

export async function exportWaypoints(waypoints: Waypoint[], format: 'yaml' | 'json'): Promise<string> {
  return fetch('/api/export_waypoints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ waypoints, format, frame_id: 'map' }),
  }).then((r) => r.text())
}

export async function sendChatMessage(message: string, mode: 'text' | 'voice'): Promise<{
  ok: boolean
  reply: string
  intent: string
  actions: { type: string; target?: string }[]
}> {
  return fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, mode }),
  }).then((r) => r.json())
}
