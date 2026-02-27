import { useRef, useCallback, useEffect } from 'react'
import type { WSMessage } from '../types'

interface UseWebSocketOptions {
  onMessage: (msg: WSMessage) => void
  onClose?: () => void
}

export function useWebSocket({ onMessage, onClose }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)

  const connect = useCallback((gameId: string, playerName: string) => {
    const base = import.meta.env.VITE_API_BASE ?? ''
    let wsUrl: string

    if (base) {
      const url = new URL(base)
      const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      wsUrl = `${protocol}//${url.host}/ws/${gameId}`
    } else {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      wsUrl = `${protocol}//${location.host}/ws/${gameId}`
    }

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      const savedId = sessionStorage.getItem(`pid_${gameId}`)
      ws.send(JSON.stringify({
        action: 'join',
        name: playerName,
        player_id: savedId || undefined,
      }))
    }

    ws.onmessage = (e) => {
      const msg: WSMessage = JSON.parse(e.data)
      onMessage(msg)
    }

    ws.onclose = () => {
      onClose?.()
    }
  }, [onMessage, onClose])

  const send = useCallback((data: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    }
  }, [])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  return { connect, send, disconnect }
}
