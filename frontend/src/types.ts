export interface CardEffect {
  type: string
  amount?: number
}

export interface Card {
  id: string
  name: string
  name_en?: string
  type: 'treasure' | 'victory' | 'action'
  subtype?: 'action' | 'attack' | 'reaction'
  cost: number
  coin_value?: number
  victory_points?: number
  description?: string
  icon?: string
  effects: CardEffect[]
  reaction?: string
}

export interface CardData {
  meta: { game_title: string; version: string }
  card_types: string[]
  cards: Card[]
  supply_setup: {
    always: string[]
    pile_sizes: Record<string, number>
    kingdom_count: number
  }
  starting_deck: Record<string, number>
  game_end_conditions: { empty_piles_trigger: number }
}

export interface PlayerState {
  id: string
  name: string
  hand_count: number
  deck_count: number
  discard_count: number
  play_area: string[]
  actions: number
  buys: number
  coins: number
  connected: boolean
  hand?: string[]
  discard_pile?: string[]
}

export interface PendingAction {
  type: string
  player_id?: string
  target_player_id?: string
  attacker_id?: string
  discard_to?: number
  max_cards?: number
  max_cost?: number
  revealed_card?: string
  revealed_cards?: string[]
}

export interface ScoreEntry {
  id: string
  name: string
  vp: number
}

export interface GameState {
  game_id: string
  started: boolean
  phase: string
  current_player: string | null
  current_player_name: string | null
  supply: Record<string, number>
  trash: string[]
  log: string[]
  players: PlayerState[]
  pending_action: PendingAction | null
  scores?: ScoreEntry[]
}

export interface RoomInfo {
  game_id: string
  players: { id: string; name: string }[]
  started: boolean
  phase: string
}

export type Screen = 'lobby' | 'waiting' | 'game'

export interface WSMessage {
  type: 'joined' | 'state' | 'error'
  player_id?: string
  game_id?: string
  state?: GameState
  message?: string
}
