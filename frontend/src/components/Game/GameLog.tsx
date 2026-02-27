import styles from './GameBoard.module.css'

interface GameLogProps {
  log: string[]
}

export function GameLog({ log }: GameLogProps) {
  const reversed = [...(log || [])].reverse()

  return (
    <div className={styles.logSection}>
      <h3>ログ</h3>
      {reversed.map((entry, i) => (
        <div key={`log-${log.length - 1 - i}`} className={styles.logEntry}>{entry}</div>
      ))}
    </div>
  )
}
