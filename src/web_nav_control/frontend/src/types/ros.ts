export type MapInfo = {
  width: number
  height: number
  resolution: number
  origin: { x: number; y: number; z: number }
}

export type MapPayload = {
  available: boolean
  frame_id?: string
  source?: string
  yaml_path?: string
  image_path?: string
  image_url?: string
  info?: MapInfo
  data?: number[]
}

export type RobotPose = {
  available: boolean
  source_topic?: string
  last_update_time?: number
  frame_id?: string
  x?: number
  y?: number
  z?: number
  yaw?: number
  yaw_degree?: number
}

export type PlanPayload = {
  available: boolean
  frame_id?: string
  points: { x: number; y: number }[]
}

export type Waypoint = {
  id: string
  x: number
  y: number
  yaw: number
  use_yaw: boolean
  source_node_id?: number | null
}

export type WaypointsPayload = {
  available: boolean
  source?: string
  path?: string
  count?: number
  waypoints?: Waypoint[]
  error?: string
  searched_paths?: string[]
}

export type RoomPolygon = {
  name: string
  points: { x: number; y: number }[]
}
