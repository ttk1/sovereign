import type { Card } from '../../types'
import { buildEffectLines } from './effectLabels'
import styles from './Supply.module.css'

interface SupplyCardProps {
  card: Card
  count: number
  onClick?: () => void
  clickable: boolean
}

const subtypeLabels: Record<string, string> = {
  action: 'アクション',
  attack: 'アタック',
  reaction: 'リアクション',
}

const subtypeStyleMap: Record<string, string> = {
  action: styles.stAction,
  attack: styles.stAttack,
  reaction: styles.stReaction,
}

const typeStyleMap: Record<string, string> = {
  treasure: styles.typeTreasure,
  victory: styles.typeVictory,
  action: styles.typeAction,
}

const subtypeBgMap: Record<string, string> = {
  attack: styles.subtypeAttack,
  reaction: styles.subtypeReaction,
}

export function SupplyCardComponent({ card, count, onClick, clickable }: SupplyCardProps) {
  const c = card
  const subtype = c.subtype || (c.type === 'action' ? 'action' : '')
  const lines = buildEffectLines(c)
  const flavorText = c.description || ''

  const cardClasses = [
    styles.supplyCard,
    typeStyleMap[c.type] || '',
    subtypeBgMap[subtype] || '',
    count <= 0 ? styles.empty : '',
    clickable ? styles.clickable : styles.notClickable,
  ].filter(Boolean).join(' ')

  return (
    <div className={cardClasses} onClick={clickable ? onClick : undefined}>
      <div className={styles.cardHeader}>
        <div className={styles.cardCount}>×{count}</div>
        <div className={styles.cardName}>{c.name}</div>
        {subtype && subtypeLabels[subtype] && (
          <div className={`${styles.cardSubtype} ${subtypeStyleMap[subtype] || ''}`}>
            {subtypeLabels[subtype]}
          </div>
        )}
        <div className={styles.cardCost}>{c.cost ?? 0}</div>
      </div>
      <div className={styles.cardArt}>{c.icon || '🃏'}</div>
      <div className={styles.cardBody}>
        {flavorText && (
          <div className={styles.cardFlavor}>{flavorText}</div>
        )}
        {lines.length > 0 && (
          <div className={styles.cardEffects}>
            {lines.map((l, i) => (
              <span key={i} className={styles.effectLine}>{l}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
