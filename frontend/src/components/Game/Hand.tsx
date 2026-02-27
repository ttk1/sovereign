import type { GameState, PlayerState, Card } from '../../types'
import { buildEffectLines } from './effectLabels'
import styles from './GameBoard.module.css'

interface HandProps {
  gameState: GameState
  playerId: string | null
  me: PlayerState | undefined
  getCard: (id: string) => Card
  discardMode: boolean
  selectedDiscards: Set<number>
  onToggleDiscard: (idx: number) => void
  onPlayAction: (cardId: string) => void
  onPlayTreasure: (cardId: string) => void
}

const TYPE_CLASS: Record<string, string> = {
  treasure: styles.typeTreasure,
  victory: styles.typeVictory,
  action: styles.typeAction,
}

export function Hand({
  gameState, playerId, me, getCard,
  discardMode, selectedDiscards,
  onToggleDiscard, onPlayAction, onPlayTreasure,
}: HandProps) {
  const myTurn = gameState.current_player === playerId
  const hand = me?.hand || []

  return (
    <div className={styles.handCards}>
      {hand.map((cid, idx) => {
        const c = getCard(cid)
        const isSelected = selectedDiscards.has(idx)
        const handEffects = buildEffectLines(c).join(' / ')

        const handleClick = () => {
          if (discardMode) {
            onToggleDiscard(idx)
          } else if (myTurn && c.type === 'action' && gameState.phase === 'action' && (me?.actions || 0) > 0) {
            onPlayAction(cid)
          } else if (myTurn && c.type === 'treasure' && (gameState.phase === 'action' || gameState.phase === 'buy')) {
            onPlayTreasure(cid)
          }
        }

        const cardClasses = [
          styles.handCard,
          TYPE_CLASS[c.type] || '',
          isSelected ? styles.handCardSelected : '',
        ].filter(Boolean).join(' ')

        return (
          <div key={`${cid}-${idx}`} className={cardClasses} onClick={handleClick}>
            <div className={styles.cardIcon}>{c.icon || '🃏'}</div>
            <div className={styles.cardNameSmall}>{c.name}</div>
            {handEffects && <div className={styles.cardEffectsSmall}>{handEffects}</div>}
          </div>
        )
      })}
    </div>
  )
}
