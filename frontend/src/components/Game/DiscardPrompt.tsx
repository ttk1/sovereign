import { useState, useCallback } from 'react'
import type { GameState, PlayerState, Card } from '../../types'
import styles from './GameBoard.module.css'

interface DiscardPromptProps {
  gameState: GameState
  playerId: string | null
  me: PlayerState | undefined
  getCard: (id: string) => Card
  onSubmitDiscard: () => void
  onTopdeckFromDiscard: (cardId: string | null) => void
  onVassalDecision: (play: boolean) => void
  onSentryDecision: (decisions: { card_id: string; action: string }[]) => void
}

/** Simple prompt with text + 決定 button */
function SimplePrompt({ text, onSubmit }: { text: string; onSubmit: () => void }) {
  return (
    <div className={styles.discardPrompt}>
      <span>{text}</span>
      <button className="btn btn-small btn-red" onClick={onSubmit}>決定</button>
    </div>
  )
}

const SIMPLE_PROMPTS: Record<string, (pa: { max_cards?: number }, handLen: number) => string> = {
  discard_draw:                 () => '捨てるカードを選んでください（0枚でもOK）',
  trash:                        pa => `廃棄するカードを選んでください（${pa.max_cards}枚まで、0枚OK）`,
  trash_and_gain:               () => '廃棄するカードを1枚選んでください',
  trash_treasure_gain_treasure: () => '廃棄する財宝カードを1枚選んでください',
  topdeck_from_hand:            () => 'デッキトップに置くカードを1枚選んでください',
}

export function DiscardPrompt({
  gameState, playerId, me, getCard,
  onSubmitDiscard, onTopdeckFromDiscard, onVassalDecision, onSentryDecision,
}: DiscardPromptProps) {
  const [sentryDecisions, setSentryDecisions] = useState<Record<number, string>>({})
  const pa = gameState.pending_action
  if (!pa) return null

  const isMyPa = pa.player_id === playerId

  // Attack discard (target)
  if (pa.type === 'attack_discard' && pa.target_player_id === playerId) {
    const needed = (me?.hand?.length || 0) - (pa.discard_to ?? 0)
    return <SimplePrompt text={`アタック！ ${needed}枚選んで捨ててください（手札を${pa.discard_to}枚に）`} onSubmit={onSubmitDiscard} />
  }

  // Simple prompt types (player_id match)
  const simplePrompt = SIMPLE_PROMPTS[pa.type]
  if (simplePrompt && isMyPa) {
    return <SimplePrompt text={simplePrompt(pa, me?.hand?.length || 0)} onSubmit={onSubmitDiscard} />
  }

  // Topdeck from discard
  if (pa.type === 'topdeck_from_discard' && isMyPa) {
    const discardPile = me?.discard_pile || []
    if (discardPile.length === 0) return null

    return (
      <div className={styles.discardPrompt}>
        <div>
          <span>デッキトップに置くカードを選んでください（スキップ可）</span>
          <div className={styles.discardPromptCards}>
            {discardPile.map((cid, i) => {
              const c = getCard(cid)
              return (
                <button key={`${cid}-${i}`} className={styles.discardCardBtn} onClick={() => onTopdeckFromDiscard(cid)}>
                  {c.icon || ''} {c.name} ({c.cost})
                </button>
              )
            })}
          </div>
          <button className={`btn btn-small ${styles.skipBtn}`} onClick={() => onTopdeckFromDiscard(null)}>
            スキップ
          </button>
        </div>
      </div>
    )
  }

  // Vassal (play revealed action)
  if (pa.type === 'play_revealed_action' && isMyPa) {
    const vc = getCard(pa.revealed_card!)
    return (
      <div className={styles.discardPrompt}>
        <span>{vc.icon || ''} {vc.name} をプレイしますか？</span>
        <div className={styles.promptBtnGroup}>
          <button className="btn btn-small" onClick={() => onVassalDecision(true)}>プレイする</button>
          <button className="btn btn-small btn-red" onClick={() => onVassalDecision(false)}>しない</button>
        </div>
      </div>
    )
  }

  // Sentry (reveal trash discard topdeck)
  if (pa.type === 'reveal_trash_discard_topdeck' && isMyPa) {
    return <SentryPrompt pa={pa} getCard={getCard} sentryDecisions={sentryDecisions} setSentryDecisions={setSentryDecisions} onSentryDecision={onSentryDecision} />
  }

  return null
}

function SentryPrompt({
  pa, getCard, sentryDecisions, setSentryDecisions, onSentryDecision,
}: {
  pa: NonNullable<GameState['pending_action']>
  getCard: (id: string) => Card
  sentryDecisions: Record<number, string>
  setSentryDecisions: (v: Record<number, string>) => void
  onSentryDecision: (decisions: { card_id: string; action: string }[]) => void
}) {
  const cards = pa.revealed_cards || []

  const handleAction = useCallback((idx: number, action: string) => {
    const updated = { ...sentryDecisions, [idx]: action }
    setSentryDecisions(updated)

    if (cards.every((_, i) => updated[i] != null)) {
      const decisions = cards.map((cid, i) => ({ card_id: cid, action: updated[i] }))
      setSentryDecisions({})
      onSentryDecision(decisions)
    }
  }, [cards, sentryDecisions, setSentryDecisions, onSentryDecision])

  const btnClass = (idx: number, action: string) => {
    const decided = sentryDecisions[idx]
    if (!decided) return ''
    return decided === action ? styles.sentryBtnActive : styles.sentryBtnInactive
  }

  return (
    <div className={styles.discardPrompt}>
      <div>
        <span>各カードの処理を選んでください：</span>
        {cards.map((cid, i) => {
          const c = getCard(cid)
          return (
            <div key={`${cid}-${i}`} className={styles.sentryRow}>
              <span>{c.icon || ''} {c.name} ({c.cost})</span>
              <button className={`btn btn-small btn-red ${btnClass(i, 'trash')}`} onClick={() => handleAction(i, 'trash')}>廃棄</button>
              <button className={`btn btn-small ${btnClass(i, 'discard')}`} onClick={() => handleAction(i, 'discard')}>捨て</button>
              <button className={`btn btn-small ${btnClass(i, 'topdeck')}`} onClick={() => handleAction(i, 'topdeck')}>戻す</button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
