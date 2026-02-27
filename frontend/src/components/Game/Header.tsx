import type { GameState, PlayerState, PendingAction } from '../../types'
import styles from './GameBoard.module.css'

interface HeaderProps {
  gameState: GameState
  playerId: string | null
  me: PlayerState | undefined
}

const phaseLabels: Record<string, string> = {
  action: 'アクション',
  buy: '購入',
  cleanup: 'クリーンアップ',
  discard: '捨て札選択',
  gain: '獲得選択',
  discard_draw: '捨て札選択',
  trash: '廃棄選択',
  topdeck: 'デッキトップ選択',
  game_over: '終了',
}

function getTurnAndPhase(
  st: GameState,
  playerId: string | null,
  myTurn: boolean,
): { turnText: string; phaseText: string } {
  const pa = st.pending_action

  const findName = (id: string | undefined) =>
    st.players.find(p => p.id === id)?.name ?? '?'

  const isMilitiaTarget = pa?.type === 'attack_discard' && pa?.target_player_id === playerId
  const isMilitiaAttacker = pa?.type === 'attack_discard' && pa?.attacker_id === playerId
  const isCellarOwner = pa?.type === 'discard_draw' && pa?.player_id === playerId

  if (isMilitiaTarget) {
    return {
      turnText: `${findName(pa!.attacker_id)} のアタック`,
      phaseText: 'あなたが捨て札を選択中',
    }
  }
  if (isMilitiaAttacker) {
    return {
      turnText: 'あなた のターン',
      phaseText: `${findName(pa!.target_player_id)} が捨て札を選択中`,
    }
  }
  if (pa?.type === 'attack_discard') {
    return {
      turnText: `${findName(pa.attacker_id)} のターン`,
      phaseText: `${findName(pa.target_player_id)} が捨て札を選択中`,
    }
  }
  if (isCellarOwner) {
    return {
      turnText: myTurn ? 'あなた のターン' : `${st.current_player_name} のターン`,
      phaseText: '捨て札選択',
    }
  }

  const turnName = myTurn ? 'あなた' : (st.current_player_name ?? '')
  return {
    turnText: `${turnName} のターン`,
    phaseText: phaseLabels[st.phase] ?? st.phase,
  }
}

export function Header({ gameState, playerId, me }: HeaderProps) {
  const myTurn = gameState.current_player === playerId
  const { turnText, phaseText } = getTurnAndPhase(gameState, playerId, myTurn)

  return (
    <div className={styles.gameHeader}>
      <div className={styles.turnInfo}>
        <span>{turnText}</span>
        <span className={styles.phaseBadge}>{phaseText}</span>
      </div>
      {me && (
        <div className={styles.statusBar}>
          <div className={styles.statusItem}><span className={styles.statusLabel}>⚡</span> {me.actions}</div>
          <div className={styles.statusItem}><span className={styles.statusLabel}>🛒</span> {me.buys}</div>
          <div className={styles.statusItem}><span className={styles.statusLabel}>💰</span> {me.coins}</div>
          <div className={styles.statusItem}><span className={styles.statusLabel}>📚</span> {me.deck_count}</div>
          <div className={styles.statusItem}><span className={styles.statusLabel}>🗑️</span> {me.discard_count}</div>
        </div>
      )}
      {me && <div className={styles.myNameBadge}>{me.name}</div>}
    </div>
  )
}
