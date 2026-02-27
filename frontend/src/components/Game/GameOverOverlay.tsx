import type { ScoreEntry } from '../../types'
import styles from './GameBoard.module.css'

interface GameOverOverlayProps {
  scores: ScoreEntry[]
  playerId: string | null
}

export function GameOverOverlay({ scores, playerId }: GameOverOverlayProps) {
  const sorted = [...scores].sort((a, b) => b.vp - a.vp)

  return (
    <div className={styles.overlay}>
      <div className={styles.overlayCard}>
        <h2>🏆 ゲーム終了</h2>
        <ul className={styles.scoreList}>
          {sorted.map((s, i) => (
            <li key={s.id} className={`${styles.scoreItem} ${i === 0 ? styles.scoreFirst : ''}`}>
              <span>{i === 0 ? '👑 ' : ''}{s.name}{s.id === playerId ? ' (あなた)' : ''}</span>
              <span>{s.vp} VP</span>
            </li>
          ))}
        </ul>
        <button className="btn btn-primary" onClick={() => location.reload()}>
          ロビーに戻る
        </button>
      </div>
    </div>
  )
}
