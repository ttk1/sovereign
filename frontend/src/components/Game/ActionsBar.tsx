import type { GameState } from '../../types'
import styles from './GameBoard.module.css'

interface ActionsBarProps {
  gameState: GameState
  playerId: string | null
  onSkipAction: () => void
  onPlayAllTreasures: () => void
  onEndTurn: () => void
}

export function ActionsBar({
  gameState,
  playerId,
  onSkipAction,
  onPlayAllTreasures,
  onEndTurn,
}: ActionsBarProps) {
  const myTurn = gameState.current_player === playerId
  if (!myTurn) return null

  const phase = gameState.phase

  return (
    <div className={styles.actionsBar}>
      {phase === 'action' && (
        <button className="btn btn-small btn-secondary" onClick={onSkipAction}>
          アクション終了
        </button>
      )}
      {(phase === 'action' || phase === 'buy') && (
        <button className="btn btn-small btn-sigil" onClick={onPlayAllTreasures}>
          💰 全財宝を出す
        </button>
      )}
      {(phase === 'buy' || phase === 'action') && (
        <button className="btn btn-small btn-secondary" onClick={onEndTurn}>
          ターン終了
        </button>
      )}
    </div>
  )
}
