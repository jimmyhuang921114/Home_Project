import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Arrow, Circle, Group, Image as KonvaImage, Label, Layer, Line, Rect, Stage, Tag, Text } from 'react-konva'
import type { MapPayload, PlanPayload, RobotPose, RoomPolygon, Waypoint } from '../types/ros'
import { imageToWorld, worldToImage } from '../utils/mapCoords'

type PointerDebug = {
  imageX: number
  imageY: number
  worldX: number
  worldY: number
} | null

type Props = {
  map: MapPayload | null
  pose?: RobotPose | null
  plan?: PlanPayload | null
  waypoints?: Waypoint[]
  polygon?: [number, number][]
  generated?: Waypoint[]
  rooms?: RoomPolygon[]
  onMapClick?: (x: number, y: number) => void
  selectedWaypointId?: string | null
  selectedRoomName?: string | null
  debugOverlay?: boolean
  onPointerDebug?: (debug: PointerDebug) => void
}

const MIN_SCALE = 0.05
const MAX_SCALE = 10

function clampScale(scale: number) {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale))
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const update = () => {
      const rect = node.getBoundingClientRect()
      setSize({
        width: Math.max(320, Math.floor(rect.width)),
        height: Math.max(320, Math.floor(rect.height)),
      })
    }
    update()

    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return [ref, size] as const
}

function useMapImage(url?: string) {
  const [loaded, setLoaded] = useState<{ url: string; image: HTMLImageElement } | null>(null)

  useEffect(() => {
    if (!url) {
      setLoaded(null)
      return
    }
    setLoaded(null)
    const img = new window.Image()
    img.onload = () => setLoaded({ url, image: img })
    img.onerror = () => setLoaded(null)
    img.src = url
  }, [url])

  if (!loaded || loaded.url !== url) return null
  return loaded.image
}

export default function MapCanvas(props: Props) {
  const {
    map,
    pose,
    plan,
    waypoints = [],
    polygon = [],
    generated = [],
    rooms = [],
    onMapClick,
    selectedWaypointId,
    selectedRoomName,
    debugOverlay = true,
    onPointerDebug,
  } = props

  const [containerRef, size] = useElementSize<HTMLDivElement>()
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const [pointerDebug, setPointerDebug] = useState<PointerDebug>(null)
  const mapImage = useMapImage(map?.image_url)
  const info = map?.info
  const dragRef = useRef<{ active: boolean; x: number; y: number; didDrag: boolean } | null>(null)
  const mapIdentityRef = useRef('')
  const hasFitInitialViewRef = useRef(false)
  const stageWidth = size.width || 900
  const stageHeight = size.height || 640

  const fitMap = useCallback(() => {
    if (!info || size.width <= 0 || size.height <= 0) return
    const scale = clampScale(Math.min(size.width / info.width, size.height / info.height) * 0.95)
    setView({
      scale,
      x: (size.width - info.width * scale) / 2,
      y: (size.height - info.height * scale) / 2,
    })
  }, [info, size.height, size.width])

  useEffect(() => {
    const key = info ? [
      map?.image_url ?? '',
      info.width,
      info.height,
      info.resolution,
      info.origin.x,
      info.origin.y,
    ].join('|') : ''
    if (mapIdentityRef.current === key) return
    mapIdentityRef.current = key
    hasFitInitialViewRef.current = false
  }, [info, map?.image_url])

  useEffect(() => {
    if (!info || !mapImage || hasFitInitialViewRef.current) return
    if (size.width <= 0 || size.height <= 0) return
    fitMap()
    hasFitInitialViewRef.current = true
  }, [fitMap, info, mapImage, size.height, size.width])

  const zoomAt = useCallback((stageX: number, stageY: number, factor: number) => {
    const nextScale = clampScale(view.scale * factor)
    const imageX = (stageX - view.x) / view.scale
    const imageY = (stageY - view.y) / view.scale
    setView({
      scale: nextScale,
      x: stageX - imageX * nextScale,
      y: stageY - imageY * nextScale,
    })
  }, [view.scale, view.x, view.y])

  const zoomAroundCenter = useCallback((factor: number) => {
    zoomAt(stageWidth / 2, stageHeight / 2, factor)
  }, [stageHeight, stageWidth, zoomAt])

  const stageToImage = useCallback((stageX: number, stageY: number): [number, number] => {
    return [(stageX - view.x) / view.scale, (stageY - view.y) / view.scale]
  }, [view.scale, view.x, view.y])

  const updatePointerDebug = useCallback((stageX: number, stageY: number) => {
    if (!info) {
      setPointerDebug(null)
      onPointerDebug?.(null)
      return
    }
    const [imageX, imageY] = stageToImage(stageX, stageY)
    const [worldX, worldY] = imageToWorld(imageX, imageY, info)
    const debug = { imageX, imageY, worldX, worldY }
    setPointerDebug(debug)
    onPointerDebug?.(debug)
  }, [info, onPointerDebug, stageToImage])

  const planPoints = useMemo(() => {
    if (!info) return []
    return plan?.points?.flatMap((p) => worldToImage(p.x, p.y, info)) ?? []
  }, [info, plan?.points])

  const polygonPoints = useMemo(() => {
    if (!info) return []
    return polygon.flatMap((p) => worldToImage(p[0], p[1], info))
  }, [info, polygon])

  return (
    <div className="map-canvas-shell" ref={containerRef}>
      <div className="map-toolbar">
        <button type="button" onClick={() => zoomAroundCenter(1.2)}>Zoom In</button>
        <button type="button" onClick={() => zoomAroundCenter(1 / 1.2)}>Zoom Out</button>
        <button type="button" onClick={fitMap}>Fit Map</button>
        <button type="button" onClick={fitMap}>Reset View</button>
        <span>Zoom {(view.scale * 100).toFixed(1)}%</span>
      </div>

      <Stage
        width={stageWidth}
        height={stageHeight}
        className="map-stage"
        onWheel={(e) => {
          e.evt.preventDefault()
          const pointer = e.target.getStage()?.getPointerPosition()
          if (!pointer) return
          const zoomFactor = e.evt.deltaY > 0 ? 0.9 : 1.1
          zoomAt(pointer.x, pointer.y, zoomFactor)
          updatePointerDebug(pointer.x, pointer.y)
        }}
        onMouseDown={(e) => {
          const pointer = e.target.getStage()?.getPointerPosition()
          if (!pointer) return
          dragRef.current = { active: true, x: pointer.x, y: pointer.y, didDrag: false }
        }}
        onMouseMove={(e) => {
          const pointer = e.target.getStage()?.getPointerPosition()
          if (!pointer) return
          updatePointerDebug(pointer.x, pointer.y)
          const drag = dragRef.current
          if (!drag?.active) return
          const dx = pointer.x - drag.x
          const dy = pointer.y - drag.y
          if (Math.abs(dx) + Math.abs(dy) > 2) drag.didDrag = true
          drag.x = pointer.x
          drag.y = pointer.y
          setView((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }))
        }}
        onMouseLeave={() => {
          dragRef.current = null
          setPointerDebug(null)
          onPointerDebug?.(null)
        }}
        onMouseUp={(e) => {
          const pointer = e.target.getStage()?.getPointerPosition()
          const drag = dragRef.current
          dragRef.current = null
          if (!pointer || drag?.didDrag || !onMapClick || !info) return
          const [imageX, imageY] = stageToImage(pointer.x, pointer.y)
          const [worldX, worldY] = imageToWorld(imageX, imageY, info)
          onMapClick(Number(worldX.toFixed(3)), Number(worldY.toFixed(3)))
        }}
      >
        <Layer>
          <Rect x={0} y={0} width={stageWidth} height={stageHeight} fill="#11151d" />
          {!map?.available && <Text x={24} y={26} fill="#fff" text="Waiting for map ..." fontSize={18} />}
          {map?.available && map?.image_url && !mapImage && (
            <Text x={24} y={26} fill="#fff" text="Loading static map image ..." fontSize={18} />
          )}
          {map?.available && !map?.image_url && (
            <Text x={24} y={26} fill="#fff" text="Static map image unavailable" fontSize={18} />
          )}

          <Group x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale}>
            {info && mapImage && (
              <KonvaImage image={mapImage} x={0} y={0} width={info.width} height={info.height} />
            )}

            {info && planPoints.length > 0 && (
              <Line points={planPoints} stroke="#4da3ff" strokeWidth={4 / view.scale} lineCap="round" lineJoin="round" />
            )}

            {info && waypoints.map((wp) => {
              const [imageX, imageY] = worldToImage(wp.x, wp.y, info)
              const selected = wp.id === selectedWaypointId
              return (
                <Group key={wp.id}>
                  <Circle
                    x={imageX}
                    y={imageY}
                    radius={(selected ? 8 : 5) / view.scale}
                    fill={selected ? '#ffda6b' : '#f97316'}
                    stroke="#111"
                    strokeWidth={1 / view.scale}
                  />
                  {selected && (
                    <Label x={imageX + 10 / view.scale} y={imageY - 10 / view.scale}>
                      <Tag fill="rgba(15,17,21,0.85)" cornerRadius={3 / view.scale} />
                      <Text fill="#fff" text={wp.id} fontSize={13 / view.scale} padding={4 / view.scale} />
                    </Label>
                  )}
                </Group>
              )
            })}

            {info && generated.map((wp) => {
              const [imageX, imageY] = worldToImage(wp.x, wp.y, info)
              return (
                <Circle
                  key={wp.id}
                  x={imageX}
                  y={imageY}
                  radius={4 / view.scale}
                  fill="#22c55e"
                  stroke="#062"
                  strokeWidth={1 / view.scale}
                />
              )
            })}

            {info && polygonPoints.length >= 4 && (
              <Line
                points={polygonPoints}
                closed={polygon.length >= 3}
                stroke="#22c55e"
                strokeWidth={3 / view.scale}
                fill="rgba(34,197,94,0.18)"
              />
            )}

            {info && rooms.map((room) => {
              const points = room.points.flatMap((p) => worldToImage(p.x, p.y, info))
              const selected = room.name === selectedRoomName
              return (
                <Line
                  key={room.name}
                  points={points}
                  closed={room.points.length >= 3}
                  stroke={selected ? '#ffda6b' : '#a78bfa'}
                  strokeWidth={(selected ? 4 : 2) / view.scale}
                  fill={selected ? 'rgba(253,224,71,0.16)' : 'rgba(167,139,250,0.12)'}
                />
              )
            })}

            {info && polygon.map((p, i) => {
              const [imageX, imageY] = worldToImage(p[0], p[1], info)
              return <Circle key={`poly-${i}`} x={imageX} y={imageY} radius={5 / view.scale} fill="#22c55e" />
            })}

            {info && pose?.available && pose.x !== undefined && pose.y !== undefined && (
              <Group>
                {(() => {
                  const [imageX, imageY] = worldToImage(pose.x!, pose.y!, info)
                  const yaw = pose.yaw ?? 0
                  const len = 34 / view.scale
                  return (
                    <>
                      <Circle x={imageX} y={imageY} radius={9 / view.scale} fill="#38bdf8" stroke="#082f49" strokeWidth={2 / view.scale} />
                      <Arrow
                        points={[imageX, imageY, imageX + Math.cos(yaw) * len, imageY - Math.sin(yaw) * len]}
                        stroke="#38bdf8"
                        fill="#38bdf8"
                        strokeWidth={4 / view.scale}
                        pointerLength={9 / view.scale}
                        pointerWidth={9 / view.scale}
                      />
                    </>
                  )
                })()}
              </Group>
            )}
          </Group>

          {debugOverlay && pointerDebug && (
            <Label x={12} y={stageHeight - 116}>
              <Tag fill="rgba(15,17,21,0.88)" cornerRadius={5} />
              <Text
                fill="#dbeafe"
                fontSize={12}
                padding={8}
                text={[
                  `image ${pointerDebug.imageX.toFixed(1)}, ${pointerDebug.imageY.toFixed(1)}`,
                  `world ${pointerDebug.worldX.toFixed(3)}, ${pointerDebug.worldY.toFixed(3)}`,
                  `zoom ${(view.scale * 100).toFixed(1)}%`,
                  `selected waypoint ${selectedWaypointId ?? '-'}`,
                  `selected room ${selectedRoomName ?? '-'}`,
                  `map source ${map?.source ?? '-'}`,
                ].join('\n')}
              />
            </Label>
          )}
        </Layer>
      </Stage>
    </div>
  )
}
