import type { PlayerState, Card } from '../../types'
import styles from './GameBoard.module.css'

interface PlayAreaProps {
  me: PlayerState | undefined
  getCard: (id: string) => Card
}

export function PlayArea({ me, getCard }: PlayAreaProps) {
  const cards = me?.play_area || []

  return (
    <div className={styles.playAreaSection}>
      <h3>場に出したカード</h3>
      <div className={styles.playAreaCards}>
        {cards.length === 0 ? (
          <span className={styles.dimText}>なし</span>
        ) : (
          cards.map((cid, i) => {
            const c = getCard(cid)
            return (
              <span key={`${cid}-${i}`} className={styles.playedCard}>
                {c.icon || ''} {c.name}
              </span>
            )
          })
        )}
      </div>
    </div>
  )
}
