import { useMemo } from 'react'
import type { GameState, PlayerState, Card } from '../../types'
import { SupplyCardComponent } from './SupplyCard'
import styles from './Supply.module.css'

interface SupplyProps {
  gameState: GameState
  playerId: string | null
  me: PlayerState | undefined
  getCard: (id: string) => Card
  onBuy: (cardId: string) => void
  onGain: (cardId: string) => void
}

export function Supply({ gameState, playerId, me, getCard, onBuy, onGain }: SupplyProps) {
  const st = gameState
  const myTurn = st.current_player === playerId

  const gainType = st.pending_action?.type
  const isGainMode =
    (gainType === 'gain' || gainType === 'gain_to_hand' || gainType === 'gain_treasure_to_hand') &&
    st.pending_action?.player_id === playerId
  const maxCost = st.pending_action?.max_cost ?? 0

  const { victoryEntries, treasureEntries, actionEntries } = useMemo(() => {
    const victory: [string, number][] = []
    const treasure: [string, number][] = []
    const action: [string, number][] = []

    for (const [cid, count] of Object.entries(st.supply || {})) {
      const c = getCard(cid)
      if (c.type === 'victory') victory.push([cid, count])
      else if (c.type === 'treasure') treasure.push([cid, count])
      else action.push([cid, count])
    }

    victory.sort((a, b) => (getCard(b[0]).cost || 0) - (getCard(a[0]).cost || 0))
    treasure.sort((a, b) => (getCard(b[0]).cost || 0) - (getCard(a[0]).cost || 0))
    action.sort((a, b) => (getCard(a[0]).cost || 0) - (getCard(b[0]).cost || 0))

    return { victoryEntries: victory, treasureEntries: treasure, actionEntries: action }
  }, [st.supply, getCard])

  const renderCard = (cid: string, count: number) => {
    const c = getCard(cid)
    const canBuy = myTurn && st.phase === 'buy' && (me?.coins || 0) >= (c.cost || 0) && count > 0 && (me?.buys || 0) > 0
    const canGain = isGainMode && count > 0 && (c.cost || 0) <= maxCost &&
      (gainType !== 'gain_treasure_to_hand' || c.type === 'treasure')

    return (
      <SupplyCardComponent
        key={cid}
        card={c}
        count={count}
        onClick={() => canGain ? onGain(cid) : onBuy(cid)}
        clickable={canBuy || canGain}
      />
    )
  }

  return (
    <div className={styles.supplySection}>
      <h3>サプライ</h3>
      <div className={styles.supplyLayout}>
        <div className={styles.victoryCards}>
          {victoryEntries.map(([cid, count]) => renderCard(cid, count))}
        </div>
        <div className={styles.treasureCards}>
          {treasureEntries.map(([cid, count]) => renderCard(cid, count))}
        </div>
        <div className={styles.actionCards}>
          {actionEntries.map(([cid, count]) => renderCard(cid, count))}
        </div>
      </div>
    </div>
  )
}
