import type { GameState, Card } from '../../types'
import styles from './GameBoard.module.css'

interface OpponentCardsProps {
  gameState: GameState
  playerId: string | null
  getCard: (id: string) => Card
}

export function OpponentCards({ gameState, playerId, getCard }: OpponentCardsProps) {
  const opponents = gameState.players.filter(p => p.id !== playerId)

  return (
    <div className={styles.opponentsRow}>
      {opponents.map(p => (
        <div
          key={p.id}
          className={`${styles.opponentCard} ${p.id === gameState.current_player ? styles.opponentCurrent : ''}`}
        >
          <div className={styles.oppName}>
            {p.name}{!p.connected ? ' (切断)' : ''}
          </div>
          <div className={styles.oppStats}>
            <span>手札:{p.hand_count}</span>
            <span>山:{p.deck_count}</span>
            <span>捨:{p.discard_count}</span>
          </div>
          <div className={styles.opponentPlayArea}>
            {(p.play_area || []).map((cid, i) => {
              const c = getCard(cid)
              return (
                <span key={`${cid}-${i}`} className={styles.miniCard}>
                  {c.icon || ''} {c.name}
                </span>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
