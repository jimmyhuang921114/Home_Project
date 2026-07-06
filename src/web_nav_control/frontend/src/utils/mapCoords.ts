import type { MapInfo } from '../types/ros'

export function worldToImage(x: number, y: number, mapInfo: MapInfo): [number, number] {
  const mx = (x - mapInfo.origin.x) / mapInfo.resolution
  const my = (y - mapInfo.origin.y) / mapInfo.resolution
  return [mx, mapInfo.height - my]
}

export function imageToWorld(imageX: number, imageY: number, mapInfo: MapInfo): [number, number] {
  const mx = imageX
  const my = mapInfo.height - imageY
  return [
    mx * mapInfo.resolution + mapInfo.origin.x,
    my * mapInfo.resolution + mapInfo.origin.y,
  ]
}

export function isWorldPointInMap(x: number, y: number, mapInfo: MapInfo): boolean {
  const [imageX, imageY] = worldToImage(x, y, mapInfo)
  return imageX >= 0 && imageX <= mapInfo.width && imageY >= 0 && imageY <= mapInfo.height
}

export const isWorldInsideMap = isWorldPointInMap
