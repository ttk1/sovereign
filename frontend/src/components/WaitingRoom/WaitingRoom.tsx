import type { GameState } from '../../types'
import styles from './WaitingRoom.module.css'

interface WaitingRoomProps {
  gameState: GameState
  playerId: string | null
  onStart: () => void
}

export function WaitingRoom({ gameState, playerId, onStart }: WaitingRoomProps) {
  return (
    <div className={styles.waiting}>
      <div className={styles.card}>
        <h2>待機中...</h2>
        <div className={styles.roomCode}>{gameState.game_id}</div>
        <p className={styles.hint}>このコードを友人に共有してください</p>
        <ul className={styles.playerList}>
          {gameState.players.map((p) => (
            <li key={p.id}>
              {p.name}{p.id === playerId ? ' (あなた)' : ''}
            </li>
          ))}
        </ul>
        <div className="btn-row" style={{ justifyContent: 'center' }}>
          <button className="btn btn-primary" onClick={onStart}>
            ゲーム開始
          </button>
        </div>
      </div>
    </div>
  )
}
