import { useEffect, useMemo, useState } from 'react'
import MapCanvas from '../components/MapCanvas'
import {
  exportWaypoints,
  getMap,
  getRobotPose,
  getWaypoints,
  loadWaypoints,
  navToPoint,
  saveWaypoints,
  uploadWaypoints,
} from '../api/rosApi'
import type { MapPayload, RobotPose, Waypoint } from '../types/ros'
import { isWorldInsideMap } from '../utils/mapCoords'

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function nextWaypointId(waypoints: Waypoint[]) {
  const used = new Set(waypoints.map((wp) => wp.id))
  for (let i = 0; i < 100000; i += 1) {
    const id = `wp_${String(i).padStart(3, '0')}`
    if (!used.has(id)) return id
  }
  return `wp_${Date.now()}`
}

function normalizeNumber(value: string, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export default function NavigationPointsPage() {
  const [map, setMap] = useState<MapPayload | null>(null)
  const [pose, setPose] = useState<RobotPose | null>(null)
  const [waypoints, setWaypoints] = useState<Waypoint[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [path, setPath] = useState('/home/jimmy/work_ws/home_project_ws/config/nav2_waypoints.yaml')
  const [sourcePath, setSourcePath] = useState('')
  const [available, setAvailable] = useState(false)
  const [message, setMessage] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [addMode, setAddMode] = useState(false)
  const [manual, setManual] = useState({ x: '0', y: '0', yaw: '0', use_yaw: false })

  useEffect(() => {
    getMap().then(setMap).catch(console.error)
    getRobotPose().then(setPose).catch(console.error)
    getWaypoints().then((res) => {
      setAvailable(res.available)
      setSourcePath(res.path ?? '')
      setWaypoints(res.waypoints ?? [])
      if (!res.available && res.error) setMessage(res.error)
    }).catch(console.error)

    const timer = setInterval(() => {
      getMap().then(setMap).catch(console.error)
      getRobotPose().then(setPose).catch(console.error)
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const selected = useMemo(() => waypoints.find((wp) => wp.id === selectedId) ?? null, [selectedId, waypoints])
  const outsideCount = map?.info ? waypoints.filter((wp) => !isWorldInsideMap(wp.x, wp.y, map.info!)).length : 0

  function replaceWaypoint(next: Waypoint) {
    setWaypoints((prev) => prev.map((wp) => (wp.id === selectedId ? next : wp)))
    setSelectedId(next.id)
  }

  function addWaypointAt(x: number, y: number) {
    const wp = { id: nextWaypointId(waypoints), x, y, yaw: 0, use_yaw: false }
    setWaypoints((prev) => [...prev, wp])
    setSelectedId(wp.id)
    setMessage(`Added ${wp.id}`)
  }

  async function handleLoad() {
    const res = await loadWaypoints(path)
    setAvailable(res.available)
    setSourcePath(res.path ?? path)
    setWaypoints(res.waypoints ?? [])
    setSelectedId(null)
    setMessage(res.available ? `Loaded ${res.count ?? 0} waypoints` : (res.error ?? 'Failed to load waypoints'))
  }

  async function handleUpload() {
    if (!uploadFile) {
      setMessage('Select waypoint YAML first')
      return
    }
    const res = await uploadWaypoints(uploadFile)
    setAvailable(res.available)
    setSourcePath(res.path ?? '')
    setWaypoints(res.waypoints ?? [])
    setSelectedId(null)
    setMessage(res.available ? `Uploaded ${res.count ?? 0} waypoints` : (res.error ?? 'Upload failed'))
  }

  async function handleSave() {
    const res = await saveWaypoints(waypoints)
    setAvailable(res.available)
    setSourcePath(res.path ?? '')
    setMessage(res.available ? `Saved ${res.count ?? 0} waypoints` : (res.error ?? 'Save failed'))
  }

  async function handleExport(format: 'yaml' | 'json') {
    const text = await exportWaypoints(waypoints, format)
    downloadText(`waypoints.${format === 'yaml' ? 'yaml' : 'json'}`, text)
  }

  async function handleNav() {
    if (!selected) return
    const res = await navToPoint(selected)
    setMessage(`${res.success ? 'OK' : 'FAIL'}: ${res.message}`)
  }

  return (
    <div className="workspace-grid">
      <section className="map-panel">
        <h1>Navigation Points</h1>
        <MapCanvas
          map={map}
          pose={pose}
          waypoints={waypoints}
          selectedWaypointId={selectedId}
          onMapClick={(x, y) => {
            if (addMode) addWaypointAt(x, y)
          }}
        />
      </section>
      <aside className="right-panel">
        <h2>Waypoint Import</h2>
        <input value={path} onChange={(e) => setPath(e.target.value)} />
        <button onClick={handleLoad}>Load Waypoint</button>
        <label>Upload waypoint YAML</label>
        <input type="file" accept=".yaml,.yml,text/yaml" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} />
        <button onClick={handleUpload}>Upload Waypoint YAML</button>
        <div className="status-card compact">
          <div>available: {available ? 'true' : 'false'}</div>
          <div>count: {waypoints.length}</div>
          <div>path: {sourcePath || '-'}</div>
          {outsideCount > 0 && <div className="warning">Waypoint outside map bounds: {outsideCount}</div>}
        </div>

        <h2>Waypoint Actions</h2>
        <label className="check-row"><input type="checkbox" checked={addMode} onChange={(e) => setAddMode(e.target.checked)} /> Add waypoint mode</label>
        <div className="form-grid two">
          <label>x<input value={manual.x} onChange={(e) => setManual((p) => ({ ...p, x: e.target.value }))} /></label>
          <label>y<input value={manual.y} onChange={(e) => setManual((p) => ({ ...p, y: e.target.value }))} /></label>
          <label>yaw<input value={manual.yaw} onChange={(e) => setManual((p) => ({ ...p, yaw: e.target.value }))} /></label>
          <label className="check-row"><input type="checkbox" checked={manual.use_yaw} onChange={(e) => setManual((p) => ({ ...p, use_yaw: e.target.checked }))} /> use_yaw</label>
        </div>
        <button onClick={() => {
          const wp = {
            id: nextWaypointId(waypoints),
            x: normalizeNumber(manual.x),
            y: normalizeNumber(manual.y),
            yaw: normalizeNumber(manual.yaw),
            use_yaw: manual.use_yaw,
          }
          setWaypoints((prev) => [...prev, wp])
          setSelectedId(wp.id)
        }}>Add Waypoint</button>
        <button onClick={handleSave}>Save Waypoints</button>
        <button onClick={() => handleExport('yaml')}>Export YAML</button>
        <button onClick={() => handleExport('json')}>Export JSON</button>

        <h2>Waypoint List</h2>
        <div className="list">
          {waypoints.map((wp) => (
            <button key={wp.id} className={selectedId === wp.id ? 'selected row' : 'row'} onClick={() => setSelectedId(wp.id)}>
              {wp.id} | x={wp.x.toFixed(2)} y={wp.y.toFixed(2)}
              {map?.info && !isWorldInsideMap(wp.x, wp.y, map.info) ? ' | outside' : ''}
            </button>
          ))}
        </div>

        <h2>Selected Waypoint</h2>
        {selected ? (
          <div className="form-grid">
            <label>id<input value={selected.id} onChange={(e) => replaceWaypoint({ ...selected, id: e.target.value })} /></label>
            <label>x<input value={String(selected.x)} onChange={(e) => replaceWaypoint({ ...selected, x: normalizeNumber(e.target.value, selected.x) })} /></label>
            <label>y<input value={String(selected.y)} onChange={(e) => replaceWaypoint({ ...selected, y: normalizeNumber(e.target.value, selected.y) })} /></label>
            <label>yaw<input value={String(selected.yaw)} onChange={(e) => replaceWaypoint({ ...selected, yaw: normalizeNumber(e.target.value, selected.yaw) })} /></label>
            <label className="check-row"><input type="checkbox" checked={selected.use_yaw} onChange={(e) => replaceWaypoint({ ...selected, use_yaw: e.target.checked })} /> use_yaw</label>
            <button onClick={handleNav}>Go To Point</button>
            <button className="danger" onClick={() => {
              setWaypoints((prev) => prev.filter((wp) => wp.id !== selected.id))
              setSelectedId(null)
            }}>Delete Waypoint</button>
          </div>
        ) : <pre>none</pre>}

        <h2>First 10 Waypoints</h2>
        <pre>{waypoints.slice(0, 10).map((wp) => `${wp.id}  x=${wp.x.toFixed(3)}  y=${wp.y.toFixed(3)}  yaw=${wp.yaw.toFixed(3)}`).join('\n') || 'none'}</pre>
        <div className="message">{message}</div>
      </aside>
    </div>
  )
}
