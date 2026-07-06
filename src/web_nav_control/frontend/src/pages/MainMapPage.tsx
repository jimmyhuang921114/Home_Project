import { useEffect, useState } from 'react'
import MapCanvas from '../components/MapCanvas'
import { getMap, getPlan, getRobotPose, getWaypoints, uploadMap } from '../api/rosApi'
import type { MapPayload, PlanPayload, RobotPose, Waypoint } from '../types/ros'

export default function MainMapPage() {
  const [map, setMap] = useState<MapPayload | null>(null)
  const [pose, setPose] = useState<RobotPose | null>(null)
  const [plan, setPlan] = useState<PlanPayload | null>(null)
  const [waypoints, setWaypoints] = useState<Waypoint[]>([])
  const [mapImageFile, setMapImageFile] = useState<File | null>(null)
  const [mapYamlFile, setMapYamlFile] = useState<File | null>(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const timer = setInterval(() => {
      getMap().then(setMap).catch(console.error)
      getRobotPose().then(setPose).catch(console.error)
      getPlan().then(setPlan).catch(console.error)
      getWaypoints().then((res) => setWaypoints(res.waypoints ?? [])).catch(console.error)
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  async function handleUploadMap() {
    if (!mapImageFile || !mapYamlFile) {
      setMessage('Select both map.png and map.yaml')
      return
    }
    const res = await uploadMap(mapImageFile, mapYamlFile)
    setMap(res)
    setMessage(res.available ? `Map loaded: ${res.yaml_path}` : 'Map upload failed')
  }

  return (
    <div className="workspace-grid">
      <section className="map-panel">
        <h1>Main Map</h1>
        <MapCanvas map={map} pose={pose} plan={plan} waypoints={waypoints} />
      </section>
      <aside className="right-panel">
        <h2>Robot Status</h2>
        <div className="status-card">
          <div>Map: {map?.available ? 'online' : 'waiting'}</div>
          <div>Map source: {map?.source ?? '-'}</div>
          <div>Map yaml: {map?.yaml_path ?? '-'}</div>
          <div>Pose: {pose?.available ? 'online' : 'Robot pose unavailable'}</div>
          <div>x: {pose?.x?.toFixed(3) ?? '-'}</div>
          <div>y: {pose?.y?.toFixed(3) ?? '-'}</div>
          <div>yaw deg: {pose?.yaw_degree?.toFixed(1) ?? (pose?.yaw !== undefined ? (pose.yaw * 180 / Math.PI).toFixed(1) : '-')}</div>
          <div>frame: {pose?.frame_id ?? '-'}</div>
          <div>topic: {pose?.source_topic ?? '-'}</div>
          <div>updated: {pose?.last_update_time ? new Date(pose.last_update_time * 1000).toLocaleTimeString() : '-'}</div>
          <div>Waypoints: {waypoints.length}</div>
          <div>Plan points: {plan?.points?.length ?? 0}</div>
        </div>
        <h2>Map Import</h2>
        <label>Upload map image</label>
        <input type="file" accept=".png,image/png" onChange={(e) => setMapImageFile(e.target.files?.[0] ?? null)} />
        <label>Upload map yaml</label>
        <input type="file" accept=".yaml,.yml,text/yaml" onChange={(e) => setMapYamlFile(e.target.files?.[0] ?? null)} />
        <button onClick={handleUploadMap}>Apply Map</button>
        <div className="message">{message}</div>
      </aside>
    </div>
  )
}
