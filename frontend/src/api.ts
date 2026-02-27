import type { CardData, RoomInfo } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export async function fetchCards(): Promise<CardData> {
  const res = await fetch(`${BASE}/api/cards`)
  return res.json()
}

export async function createGame(): Promise<{ game_id: string }> {
  const res = await fetch(`${BASE}/api/games`, { method: 'POST' })
  return res.json()
}

export async function listGames(): Promise<RoomInfo[]> {
  const res = await fetch(`${BASE}/api/games`)
  return res.json()
}
