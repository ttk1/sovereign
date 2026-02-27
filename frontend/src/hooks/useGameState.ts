import { useState, useCallback, useEffect, useRef } from 'react'
import type { Card, GameState, Screen } from '../types'
import { fetchCards } from '../api'
import { useWebSocket } from './useWebSocket'

const ADJECTIVES = ['勇敢な', '賢い', '素早い', '力強い', '不思議な']
const NOUNS = ['騎士', '魔術師', '商人', '冒険者', '錬金術師']

function randomName(): string {
  const a = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)]
  const n = NOUNS[Math.floor(Math.random() * NOUNS.length)]
  return a + n
}

export function useGameState() {
  const [screen, setScreen] = useState<Screen>('lobby')
  const [gameState, setGameState] = useState<GameState | null>(null)
  const [playerId, setPlayerId] = useState<string | null>(null)
  const [cardDefs, setCardDefs] = useState<Record<string, Card>>({})
  const [toast, setToast] = useState<string | null>(null)
  const [playerName, setPlayerName] = useState(() => randomName())

  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(null), 2500)
  }, [])

  const { connect, send } = useWebSocket({
    onMessage: useCallback((msg) => {
      if (msg.type === 'joined' && msg.player_id && msg.game_id) {
        setPlayerId(msg.player_id)
        sessionStorage.setItem(`pid_${msg.game_id}`, msg.player_id)
      } else if (msg.type === 'state' && msg.state) {
        setGameState(msg.state)
        if (!msg.state.started) {
          setScreen('waiting')
        } else {
          setScreen('game')
        }
      } else if (msg.type === 'error' && msg.message) {
        showToast(msg.message)
      }
    }, [showToast]),
    onClose: useCallback(() => {
      showToast('接続が切断されました。ページをリロードしてください。')
    }, [showToast]),
  })

  // Load card data on mount
  useEffect(() => {
    fetchCards().then((data) => {
      const defs: Record<string, Card> = {}
      for (const card of data.cards) {
        defs[card.id] = card
      }
      setCardDefs(defs)
    })
  }, [])

  const getCard = useCallback((id: string): Card => {
    return cardDefs[id] ?? {
      id,
      name: id,
      icon: '?',
      description: '',
      type: 'action' as const,
      cost: 0,
      effects: [],
    }
  }, [cardDefs])

  const joinGame = useCallback((gid: string) => {
    connect(gid, playerName)
  }, [connect, playerName])

  return {
    screen,
    gameState,
    playerId,
    toast,
    playerName,
    setPlayerName,
    getCard,
    joinGame,
    send,
  }
}
