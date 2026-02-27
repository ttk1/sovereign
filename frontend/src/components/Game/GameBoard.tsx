import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import type { GameState, Card } from '../../types'
import { Header } from './Header'
import { OpponentCards } from './OpponentCards'
import { DiscardPrompt } from './DiscardPrompt'
import { Supply } from './Supply'
import { PlayArea } from './PlayArea'
import { Hand } from './Hand'
import { ActionsBar } from './ActionsBar'
import { GameLog } from './GameLog'
import { GameOverOverlay } from './GameOverOverlay'
import styles from './GameBoard.module.css'

interface GameBoardProps {
  gameState: GameState
  playerId: string | null
  getCard: (id: string) => Card
  send: (data: Record<string, unknown>) => void
}

const DISCARD_TYPES = new Set([
  'attack_discard', 'discard_draw', 'trash', 'trash_and_gain',
  'trash_treasure_gain_treasure', 'topdeck_from_hand',
])
const TRASH_TYPES = new Set(['trash', 'trash_and_gain', 'trash_treasure_gain_treasure'])

export function GameBoard({ gameState, playerId, getCard, send }: GameBoardProps) {
  const [selectedDiscards, setSelectedDiscards] = useState<Set<number>>(new Set())

  const me = gameState.players.find(p => p.id === playerId)
  const pa = gameState.pending_action

  const isMyPa = pa?.player_id === playerId || (pa?.type === 'attack_discard' && pa?.target_player_id === playerId)
  const paType = pa?.type ?? ''

  const discardMode = isMyPa && DISCARD_TYPES.has(paType)
  const trashMode = isMyPa && TRASH_TYPES.has(paType)
  const topdeckMode = isMyPa && paType === 'topdeck_from_hand'

  // Clear selections when discard mode ends
  const prevDiscardMode = useRef(discardMode)
  useEffect(() => {
    if (prevDiscardMode.current && !discardMode) {
      setSelectedDiscards(new Set())
    }
    prevDiscardMode.current = discardMode
  }, [discardMode])

  const toggleDiscard = useCallback((idx: number) => {
    setSelectedDiscards(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }, [])

  const submitDiscard = useCallback(() => {
    if (!me) return
    const cardIds = Array.from(selectedDiscards).map(idx => me.hand?.[idx]).filter(Boolean) as string[]

    if (topdeckMode) {
      send({ action: 'topdeck_selection', card_id: cardIds[0] || null })
    } else if (paType === 'attack_discard' || paType === 'discard_draw') {
      send({ action: 'discard_selection', card_ids: cardIds })
    } else if (trashMode) {
      send({ action: 'trash_selection', card_ids: cardIds })
    }
    setSelectedDiscards(new Set())
  }, [me, selectedDiscards, topdeckMode, trashMode, paType, send])

  const onBuy = useCallback((cardId: string) => send({ action: 'buy', card_id: cardId }), [send])
  const onGain = useCallback((cardId: string) => send({ action: 'gain_selection', card_id: cardId }), [send])
  const onPlayAction = useCallback((cardId: string) => send({ action: 'play_action', card_id: cardId }), [send])
  const onPlayTreasure = useCallback((cardId: string) => send({ action: 'play_treasure', card_id: cardId }), [send])
  const onSkipAction = useCallback(() => send({ action: 'skip_action' }), [send])
  const onPlayAllTreasures = useCallback(() => send({ action: 'play_all_treasures' }), [send])
  const onEndTurn = useCallback(() => send({ action: 'end_turn' }), [send])
  const onTopdeckFromDiscard = useCallback((cardId: string | null) => send({ action: 'topdeck_selection', card_id: cardId }), [send])
  const onVassalDecision = useCallback((play: boolean) => send({ action: 'vassal_decision', play }), [send])
  const onSentryDecision = useCallback(
    (decisions: { card_id: string; action: string }[]) => send({ action: 'sentry_decision', decisions }),
    [send],
  )

  return (
    <div className={styles.game}>
      <Header gameState={gameState} playerId={playerId} me={me} />

      <OpponentCards gameState={gameState} playerId={playerId} getCard={getCard} />

      <DiscardPrompt
        gameState={gameState}
        playerId={playerId}
        me={me}
        getCard={getCard}
        onSubmitDiscard={submitDiscard}
        onTopdeckFromDiscard={onTopdeckFromDiscard}
        onVassalDecision={onVassalDecision}
        onSentryDecision={onSentryDecision}
      />

      <Supply
        gameState={gameState}
        playerId={playerId}
        me={me}
        getCard={getCard}
        onBuy={onBuy}
        onGain={onGain}
      />

      <PlayArea me={me} getCard={getCard} />

      <div className={styles.handSection}>
        <div className={styles.handHeader}>
          <h3>手札</h3>
          <ActionsBar
            gameState={gameState}
            playerId={playerId}
            onSkipAction={onSkipAction}
            onPlayAllTreasures={onPlayAllTreasures}
            onEndTurn={onEndTurn}
          />
        </div>
        <Hand
          gameState={gameState}
          playerId={playerId}
          me={me}
          getCard={getCard}
          discardMode={discardMode}
          selectedDiscards={selectedDiscards}
          onToggleDiscard={toggleDiscard}
          onPlayAction={onPlayAction}
          onPlayTreasure={onPlayTreasure}
        />
      </div>

      <GameLog log={gameState.log} />

      {gameState.phase === 'game_over' && gameState.scores && (
        <GameOverOverlay scores={gameState.scores} playerId={playerId} />
      )}
    </div>
  )
}
