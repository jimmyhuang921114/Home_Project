import { useEffect, useState } from 'react'
import MapCanvas from '../components/MapCanvas'
import { getMap, getRobotPose } from '../api/rosApi'
import type { MapPayload, RobotPose, RoomPolygon } from '../types/ros'

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function roomsPayload(rooms: RoomPolygon[]) {
  return {
    frame_id: 'map',
    rooms: rooms.map((room) => ({
      name: room.name,
      points: room.points.map((p) => ({ x: Number(p.x.toFixed(6)), y: Number(p.y.toFixed(6)) })),
    })),
  }
}

function roomsToYaml(rooms: RoomPolygon[]) {
  const lines = ['frame_id: map', 'rooms:']
  for (const room of roomsPayload(rooms).rooms) {
    lines.push(`  - name: ${room.name}`)
    lines.push('    points:')
    for (const point of room.points) {
      lines.push(`      - x: ${point.x}`)
      lines.push(`        y: ${point.y}`)
    }
  }
  return `${lines.join('\n')}\n`
}

export default function PolygonWaypointPage() {
  const [map, setMap] = useState<MapPayload | null>(null)
  const [pose, setPose] = useState<RobotPose | null>(null)
  const [polygon, setPolygon] = useState<[number, number][]>([])
  const [rooms, setRooms] = useState<RoomPolygon[]>([])
  const [roomName, setRoomName] = useState('room_001')
  const [selectedRoomName, setSelectedRoomName] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getMap().then(setMap).catch(console.error)
    getRobotPose().then(setPose).catch(console.error)
    const timer = setInterval(() => {
      getMap().then(setMap).catch(console.error)
      getRobotPose().then(setPose).catch(console.error)
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  function saveRoom() {
    const name = roomName.trim()
    if (!name) {
      setMessage('Room name is required')
      return
    }
    if (polygon.length < 3) {
      setMessage('Need at least 3 polygon points')
      return
    }
    const room = {
      name,
      points: polygon.map(([x, y]) => ({ x, y })),
    }
    setRooms((prev) => [...prev.filter((r) => r.name !== name), room])
    setSelectedRoomName(name)
    setPolygon([])
    setMessage(`Saved room ${name}`)
  }

  function exportRooms(format: 'json' | 'yaml') {
    if (format === 'json') {
      downloadText('rooms.json', JSON.stringify(roomsPayload(rooms), null, 2))
      return
    }
    downloadText('rooms.yaml', roomsToYaml(rooms))
  }

  const selectedRoom = rooms.find((room) => room.name === selectedRoomName) ?? null

  return (
    <div className="workspace-grid">
      <section className="map-panel">
        <h1>Room Polygon Tool</h1>
        <MapCanvas
          map={map}
          pose={pose}
          polygon={polygon}
          rooms={rooms}
          selectedRoomName={selectedRoomName}
          onMapClick={(x, y) => setPolygon((prev) => [...prev, [x, y]])}
        />
      </section>
      <aside className="right-panel">
        <h2>Current Polygon</h2>
        <label>Room name</label>
        <input value={roomName} onChange={(e) => setRoomName(e.target.value)} />
        <div className="status-card compact">
          <div>active points: {polygon.length}</div>
          <div>rooms: {rooms.length}</div>
          <div>selected room: {selectedRoomName ?? '-'}</div>
        </div>
        <button onClick={() => setPolygon((p) => p.slice(0, -1))}>Undo Point</button>
        <button onClick={() => setPolygon([])}>Clear Polygon</button>
        <button onClick={saveRoom}>Save Room</button>

        <h2>Rooms</h2>
        <div className="list compact-list">
          {rooms.map((room) => (
            <button key={room.name} className={room.name === selectedRoomName ? 'selected row' : 'row'} onClick={() => setSelectedRoomName(room.name)}>
              {room.name} | points={room.points.length}
            </button>
          ))}
        </div>
        <button disabled={!selectedRoom} className="danger" onClick={() => {
          if (!selectedRoom) return
          setRooms((prev) => prev.filter((room) => room.name !== selectedRoom.name))
          setSelectedRoomName(null)
        }}>Delete Room</button>

        <h2>Selected Room Points</h2>
        <pre>{selectedRoom ? selectedRoom.points.map((p, i) => `${i}: x=${p.x.toFixed(3)} y=${p.y.toFixed(3)}`).join('\n') : 'none'}</pre>

        <h2>Export Rooms</h2>
        <button disabled={rooms.length === 0} onClick={() => exportRooms('json')}>Export Room JSON</button>
        <button disabled={rooms.length === 0} onClick={() => exportRooms('yaml')}>Export Room YAML</button>
        <div className="message">{message}</div>
      </aside>
    </div>
  )
}
