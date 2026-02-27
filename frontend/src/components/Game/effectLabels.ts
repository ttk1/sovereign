import type { Card } from '../../types'

const effectLabels: Record<string, (n: number) => string> = {
  draw:              n => `+${n} カードを引く`,
  action:            n => `+${n} アクション`,
  buy:               n => `+${n} 購入`,
  coin:              n => `+${n} コイン`,
  coin_value:        n => `+${n} コイン`,
  victory_points:    n => `${n} 勝利点`,
  attack_discard_to: n => `【攻撃】他者は手札${n}枚まで捨てる`,
  discard_draw:      _ => `好きな枚数を捨て、同数引く`,
  gain_card_up_to:   n => `コスト${n}以下を獲得`,
  trash:                         n => `手札${n}枚まで廃棄`,
  trash_and_gain:                n => `1枚廃棄→コスト+${n}以下を獲得`,
  trash_treasure_gain_treasure:  n => `財宝廃棄→コスト+${n}以下の財宝を手札に`,
  trash_copper_for_coin:         n => `最安財宝を廃棄で+${n}コイン`,
  opponents_draw:                n => `他者: +${n} ドロー`,
  gain_card_to_hand:             n => `コスト${n}以下を手札に獲得, 手札1枚をデッキトップに`,
  topdeck_from_discard:          _ => `捨て札1枚をデッキトップに`,
  discard_top_play_action:       _ => `デッキトップ1枚を捨て札に。アクションならプレイ可`,
  gain_treasure_topdeck_attack_victory: n => `コスト${n}の財宝をデッキトップに獲得,【攻撃】他者は勝利点をデッキトップに`,
  reveal_trash_discard_topdeck:  n => `デッキトップ${n}枚を公開し、各々廃棄/捨て/戻す`,
}

export function buildEffectLines(c: Card): string[] {
  let effects = c.effects || []
  if (effects.length === 0) {
    if (c.type === 'treasure' && c.coin_value != null)
      effects = [{ type: 'coin_value', amount: c.coin_value }]
    else if (c.type === 'victory' && c.victory_points != null)
      effects = [{ type: 'victory_points', amount: c.victory_points }]
  }
  const lines = effects.map(ef => {
    const fn = effectLabels[ef.type]
    return fn ? fn(ef.amount ?? 0) : null
  }).filter((l): l is string => l !== null)
  if (c.reaction === 'block_attack') lines.push('攻撃を無効化')
  return lines
}
