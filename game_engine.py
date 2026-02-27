"""
Sovereign - Game Engine
デッキ構築型カードゲーム「Sovereign」のゲームエンジン。
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Phase(str, Enum):
    ACTION = "action"
    BUY = "buy"
    CLEANUP = "cleanup"
    WAITING = "waiting"
    GAME_OVER = "game_over"
    DISCARD = "discard"  # Waiting for discard selection (attack)
    GAIN = "gain"        # Waiting for card gain selection
    DISCARD_DRAW = "discard_draw"  # Waiting for discard-draw selection
    TRASH = "trash"      # Waiting for trash card selection
    TOPDECK = "topdeck"  # Waiting for topdeck card selection


class CardData:
    """Loaded from JSON, immutable card definitions."""

    def __init__(self, data: dict):
        self.cards_by_id: dict[str, dict] = {}
        self.supply_setup = data.get("supply_setup", {})
        self.starting_deck = data.get("starting_deck", {})
        self.game_end_conditions = data.get("game_end_conditions", {})
        for card in data.get("cards", []):
            self.cards_by_id[card["id"]] = card

    def get(self, card_id: str) -> dict:
        return self.cards_by_id.get(card_id, {})

    def victory_card_ids(self) -> list[str]:
        """全勝利点カードのIDリストを返す。"""
        return [cid for cid, c in self.cards_by_id.items() if c.get("type") == "victory"]

    def province_card_id(self) -> str | None:
        """終了条件に使われる最高コストの勝利点カードIDを返す。"""
        vids = self.victory_card_ids()
        if not vids:
            return None
        return max(vids, key=lambda cid: self.cards_by_id[cid].get("cost", 0))


@dataclass
class Player:
    id: str
    name: str
    deck: list[str] = field(default_factory=list)
    hand: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)
    play_area: list[str] = field(default_factory=list)
    actions: int = 1
    buys: int = 1
    coins: int = 0
    connected: bool = True

    def total_cards(self) -> list[str]:
        return self.deck + self.hand + self.discard_pile + self.play_area

    def shuffle_discard_into_deck(self):
        self.deck = self.discard_pile.copy()
        self.discard_pile = []
        random.shuffle(self.deck)

    def draw_cards(self, n: int) -> list[str]:
        drawn = []
        for _ in range(n):
            if not self.deck:
                if not self.discard_pile:
                    break
                self.shuffle_discard_into_deck()
            if self.deck:
                drawn.append(self.deck.pop())
        self.hand.extend(drawn)
        return drawn

    def count_victory_points(self, card_data: CardData) -> int:
        total = 0
        for card_id in self.total_cards():
            card = card_data.get(card_id)
            total += card.get("victory_points", 0)
        return total


class Game:
    def __init__(self, game_id: str, card_data: CardData, kingdom_cards: Optional[list[str]] = None):
        self.id = game_id
        self.card_data = card_data
        self.players: list[Player] = []
        self.supply: dict[str, int] = {}
        self.trash: list[str] = []
        self.current_player_index: int = 0
        self.phase: Phase = Phase.WAITING
        self.started: bool = False
        self.log: list[str] = []
        self.kingdom_cards = kingdom_cards or []
        self.pending_action: Optional[dict] = None  # For multi-step actions

    @property
    def current_player(self) -> Optional[Player]:
        if not self.players:
            return None
        return self.players[self.current_player_index]

    def add_player(self, player_id: str, name: str) -> Optional[Player]:
        if self.started:
            return None
        if len(self.players) >= 4:
            return None
        if any(p.id == player_id for p in self.players):
            return next(p for p in self.players if p.id == player_id)
        player = Player(id=player_id, name=name)
        self.players.append(player)
        self._log(f"{name} がゲームに参加しました")
        return player

    def remove_player(self, player_id: str):
        self.players = [p for p in self.players if p.id != player_id]

    def start_game(self) -> bool:
        if len(self.players) < 2:
            return False
        if self.started:
            return False

        self._setup_supply()

        for player in self.players:
            starting = self.card_data.starting_deck
            for card_id, count in starting.items():
                player.deck.extend([card_id] * count)
            random.shuffle(player.deck)
            player.draw_cards(5)

        self.started = True
        self.current_player_index = 0
        self.phase = Phase.ACTION
        self._log("ゲーム開始！")
        self._log(f"{self.current_player.name} のターンです")
        return True

    def _setup_supply(self):
        setup = self.card_data.supply_setup
        pile_sizes = setup.get("pile_sizes", {})

        for card_id in setup.get("always", []):
            size_key = card_id if card_id in pile_sizes else "default_action"
            self.supply[card_id] = pile_sizes.get(size_key, 10)

        # Adjust victory card piles for 2 players
        if len(self.players) == 2:
            for vid in self.card_data.victory_card_ids():
                if vid in self.supply:
                    self.supply[vid] = 8

        available_kingdom = [
            cid for cid, c in self.card_data.cards_by_id.items()
            if c.get("type") == "action"
        ]

        if self.kingdom_cards:
            chosen = [c for c in self.kingdom_cards if c in available_kingdom]
        else:
            chosen = []

        needed = setup.get("kingdom_count", 10) - len(chosen)
        remaining = [c for c in available_kingdom if c not in chosen]
        if needed > 0 and remaining:
            chosen.extend(random.sample(remaining, min(needed, len(remaining))))

        for card_id in chosen:
            self.supply[card_id] = pile_sizes.get("default_action", 10)

    def play_action(self, player_id: str, card_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}
        if self.phase != Phase.ACTION:
            return {"error": "アクションフェーズではありません"}
        if card_id not in player.hand:
            return {"error": "そのカードは手札にありません"}

        card = self.card_data.get(card_id)
        if card.get("type") != "action":
            return {"error": "アクションカードではありません"}
        if player.actions <= 0:
            return {"error": "アクション回数が残っていません"}

        player.hand.remove(card_id)
        player.play_area.append(card_id)
        player.actions -= 1

        self._log(f"{player.name} が {card.get('name', card_id)} を使用")
        result = self._resolve_effects(player, card)
        return {"ok": True, "card": card_id, **result}

    def _resolve_effects(self, player: Player, card: dict) -> dict:
        result = {}
        effects = card.get("effects", [])

        for effect in effects:
            etype = effect["type"]
            amount = effect.get("amount", 0)

            if etype == "draw":
                drawn = player.draw_cards(amount)
                self._log(f"  → {amount} 枚ドロー")
                result["drawn"] = drawn
            elif etype == "action":
                player.actions += amount
                self._log(f"  → +{amount} アクション")
            elif etype == "buy":
                player.buys += amount
                self._log(f"  → +{amount} 購入")
            elif etype == "coin":
                player.coins += amount
                self._log(f"  → +{amount} コイン")
            elif etype == "attack_discard_to":
                result["attack"] = self._resolve_militia_attack(player, amount)
            elif etype == "discard_draw":
                # Enter discard-draw selection phase
                self.phase = Phase.DISCARD_DRAW
                self.pending_action = {"type": "discard_draw", "player_id": player.id}
                result["awaiting_discard"] = True
            elif etype == "gain_card_up_to":
                # Enter gain selection phase
                self.phase = Phase.GAIN
                self.pending_action = {
                    "type": "gain",
                    "player_id": player.id,
                    "max_cost": amount
                }
                result["awaiting_gain"] = True
            elif etype == "trash":
                # Trash up to N cards from hand
                self.phase = Phase.TRASH
                self.pending_action = {
                    "type": "trash",
                    "player_id": player.id,
                    "max_cards": amount,
                }
                result["awaiting_trash"] = True
            elif etype == "trash_and_gain":
                # Trash 1 card, gain card costing up to trashed + N
                self.phase = Phase.TRASH
                self.pending_action = {
                    "type": "trash_and_gain",
                    "player_id": player.id,
                    "cost_bonus": amount,
                }
                result["awaiting_trash"] = True
            elif etype == "trash_treasure_gain_treasure":
                # Trash a treasure, gain treasure costing up to trashed + N to hand
                self.phase = Phase.TRASH
                self.pending_action = {
                    "type": "trash_treasure_gain_treasure",
                    "player_id": player.id,
                    "cost_bonus": amount,
                }
                result["awaiting_trash"] = True
            elif etype == "trash_copper_for_coin":
                # Auto-trash the cheapest treasure for +N coins
                cheapest_id = self._find_cheapest_treasure_id()
                if cheapest_id and cheapest_id in player.hand:
                    cname = self.card_data.get(cheapest_id).get("name", cheapest_id)
                    player.hand.remove(cheapest_id)
                    self.trash.append(cheapest_id)
                    player.coins += amount
                    self._log(f"  → {cname} を廃棄して +{amount} コイン")
                else:
                    self._log("  → 廃棄できるカードがない")
            elif etype == "opponents_draw":
                # All other players draw N cards
                for p in self.players:
                    if p.id != player.id:
                        drawn = p.draw_cards(amount)
                        self._log(f"  → {p.name} が {len(drawn)} 枚ドロー")
            elif etype == "gain_card_to_hand":
                # Gain a card costing up to N to hand
                self.phase = Phase.GAIN
                self.pending_action = {
                    "type": "gain_to_hand",
                    "player_id": player.id,
                    "max_cost": amount,
                }
                result["awaiting_gain"] = True
            elif etype == "topdeck_from_discard":
                # Put a card from discard pile on top of deck
                if player.discard_pile:
                    self.phase = Phase.TOPDECK
                    self.pending_action = {
                        "type": "topdeck_from_discard",
                        "player_id": player.id,
                    }
                    result["awaiting_topdeck"] = True
            elif etype == "discard_top_play_action":
                # Discard top card, if action may play it
                if not player.deck:
                    player.shuffle_discard_into_deck()
                if player.deck:
                    top = player.deck.pop()
                    top_card = self.card_data.get(top)
                    player.discard_pile.append(top)
                    self._log(f"  → {top_card.get('name', top)} を公開")
                    if top_card.get("type") == "action":
                        self.phase = Phase.TOPDECK
                        self.pending_action = {
                            "type": "play_revealed_action",
                            "player_id": player.id,
                            "revealed_card": top,
                        }
                        result["awaiting_play_revealed"] = True
                    else:
                        self._log(f"  → アクションではないので捨て札に")
            elif etype == "gain_treasure_topdeck_attack_victory":
                # Gain a treasure of the given cost to topdeck, opponents topdeck a victory card
                treasure_id = self._find_treasure_by_cost(amount)
                if treasure_id and self.supply.get(treasure_id, 0) > 0:
                    self.supply[treasure_id] -= 1
                    player.deck.append(treasure_id)
                    tname = self.card_data.get(treasure_id).get("name", treasure_id)
                    self._log(f"  → {tname} をデッキトップに獲得")
                result["attack"] = self._resolve_bureaucrat_attack(player)
            elif etype == "reveal_trash_discard_topdeck":
                # Reveal top N cards, trash/discard/topdeck each
                revealed = []
                for _ in range(amount):
                    if not player.deck:
                        player.shuffle_discard_into_deck()
                    if player.deck:
                        revealed.append(player.deck.pop())
                if revealed:
                    names = [self.card_data.get(c).get("name", c) for c in revealed]
                    self._log(f"  → {', '.join(names)} を公開")
                    self.phase = Phase.TOPDECK
                    self.pending_action = {
                        "type": "reveal_trash_discard_topdeck",
                        "player_id": player.id,
                        "revealed_cards": revealed,
                    }
                    result["awaiting_reveal_process"] = True

        return result

    def _has_block_reaction(self, player: Player) -> bool:
        """手札に攻撃無効化リアクションを持っているか。"""
        return any(
            self.card_data.get(c).get("reaction") == "block_attack"
            for c in player.hand
        )

    def _resolve_militia_attack(self, attacker: Player, discard_to: int) -> dict:
        attacked = {}
        for p in self.players:
            if p.id == attacker.id:
                continue
            if self._has_block_reaction(p):
                self._log(f"  {p.name} はリアクションカードでアタックを防いだ")
                attacked[p.id] = {"blocked": True}
                continue

            if len(p.hand) <= discard_to:
                attacked[p.id] = {"already_under": True}
                continue

            # AI auto-discard for simplicity, or set pending
            self.phase = Phase.DISCARD
            self.pending_action = {
                "type": "attack_discard",
                "target_player_id": p.id,
                "discard_to": discard_to,
                "attacker_id": attacker.id,
                "remaining_targets": [
                    op.id for op in self.players
                    if op.id != attacker.id and op.id != p.id
                    and len(op.hand) > discard_to
                    and not self._has_block_reaction(op)
                ]
            }
            attacked[p.id] = {"must_discard_to": discard_to}
            break  # Handle one at a time

        return attacked


    def _find_cheapest_treasure_id(self) -> Optional[str]:
        """Find the cheapest treasure card ID in the card data."""
        treasures = [
            (cid, c.get("cost", 0))
            for cid, c in self.card_data.cards_by_id.items()
            if c.get("type") == "treasure"
        ]
        if not treasures:
            return None
        return min(treasures, key=lambda x: x[1])[0]

    def _find_treasure_by_cost(self, cost: int) -> Optional[str]:
        """Find a treasure card ID with the given cost."""
        for cid, c in self.card_data.cards_by_id.items():
            if c.get("type") == "treasure" and c.get("cost", 0) == cost:
                return cid
        return None

    def _resolve_bureaucrat_attack(self, attacker: Player) -> dict:
        """Each opponent topdecks a victory card from hand (attack)."""
        attacked = {}
        for p in self.players:
            if p.id == attacker.id:
                continue
            if self._has_block_reaction(p):
                attacked[p.id] = {"blocked": True}
                self._log(f"  → {p.name} はリアクションで防御した")
                continue
            # Find victory cards in hand, pick cheapest
            victory_in_hand = [
                cid for cid in p.hand
                if self.card_data.get(cid).get("type") == "victory"
            ]
            if victory_in_hand:
                # Auto-select cheapest victory card
                chosen = min(victory_in_hand, key=lambda c: self.card_data.get(c).get("cost", 0))
                p.hand.remove(chosen)
                p.deck.append(chosen)
                cname = self.card_data.get(chosen).get("name", chosen)
                attacked[p.id] = {"topdecked": chosen}
                self._log(f"  → {p.name} が {cname} をデッキトップに置いた")
            else:
                attacked[p.id] = {"no_victory": True}
                self._log(f"  → {p.name} は勝利点カードを持っていない（手札公開）")
        return attacked

    def handle_topdeck_selection(self, player_id: str, card_id: Optional[str]) -> dict:
        """Handle topdeck card selection (from hand or discard)."""
        if not self.pending_action:
            return {"error": "待機中のアクションがありません"}
        pa = self.pending_action
        pa_type = pa["type"]
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        player = self._get_player(player_id)

        if pa_type == "topdeck_from_hand":
            if not card_id or card_id not in player.hand:
                return {"error": "手札からカードを選んでください"}
            player.hand.remove(card_id)
            player.deck.append(card_id)

        elif pa_type == "topdeck_from_discard":
            if not card_id:
                self._log(f"{player.name} はスキップした")
                self.pending_action = None
                self.phase = Phase.ACTION
                return {"ok": True}
            if card_id not in player.discard_pile:
                return {"error": "捨て札にないカードです"}
            player.discard_pile.remove(card_id)
            player.deck.append(card_id)

        else:
            return {"error": "不明なアクション"}

        card = self.card_data.get(card_id)
        self._log(f"{player.name} が {card.get('name', card_id)} をデッキトップに置いた")
        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True}

    def handle_vassal_decision(self, player_id: str, play: bool) -> dict:
        """Handle play decision for a revealed action card."""
        if not self.pending_action or self.pending_action.get("type") != "play_revealed_action":
            return {"error": "待機中のアクションがありません"}
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        player = self._get_player(player_id)
        revealed = pa["revealed_card"]
        card = self.card_data.get(revealed)

        if play:
            # Move from discard to play area and resolve
            player.discard_pile.remove(revealed)
            player.play_area.append(revealed)
            self._log(f"{player.name} が {card.get('name', revealed)} をプレイ")
            self.pending_action = None
            self.phase = Phase.ACTION
            self._resolve_effects(player, card)
        else:
            self._log(f"{player.name} はプレイしなかった")
            self.pending_action = None
            self.phase = Phase.ACTION

        return {"ok": True}

    def handle_sentry_decision(self, player_id: str, decisions: list[dict]) -> dict:
        """Handle trash/discard/topdeck decisions for each revealed card."""
        if not self.pending_action or self.pending_action.get("type") != "reveal_trash_discard_topdeck":
            return {"error": "待機中のアクションがありません"}
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        player = self._get_player(player_id)
        revealed = pa["revealed_cards"]

        # Validate all card_ids are in revealed (handle duplicates)
        decision_ids = sorted([d["card_id"] for d in decisions])
        if decision_ids != sorted(revealed):
            return {"error": "公開されたカードと一致しません"}

        topdeck_cards = []
        for d in decisions:
            cid = d["card_id"]
            action = d["action"]
            cname = self.card_data.get(cid).get("name", cid)
            if action == "trash":
                self.trash.append(cid)
                self._log(f"  → {cname} を廃棄")
            elif action == "discard":
                player.discard_pile.append(cid)
                self._log(f"  → {cname} を捨て札に")
            elif action == "topdeck":
                topdeck_cards.append(cid)
            else:
                return {"error": f"不明なアクション: {action}"}

        # Put topdeck cards back (order doesn't matter much for 1-2 cards)
        for cid in topdeck_cards:
            player.deck.append(cid)
            cname = self.card_data.get(cid).get("name", cid)
            self._log(f"  → {cname} をデッキトップに戻した")

        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True}

    def handle_trash_selection(self, player_id: str, card_ids: list[str]) -> dict:
        if not self.pending_action:
            return {"error": "待機中のアクションがありません"}
        pa = self.pending_action
        pa_type = pa["type"]
        if pa_type == "trash":
            return self._handle_trash(player_id, card_ids)
        elif pa_type == "trash_and_gain":
            return self._handle_trash_and_gain(player_id, card_ids)
        elif pa_type == "trash_treasure_gain_treasure":
            return self._handle_trash_treasure(player_id, card_ids)
        return {"error": "不明なアクション"}

    def _handle_trash(self, player_id: str, card_ids: list[str]) -> dict:
        """Trash up to max_cards from hand."""
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        player = self._get_player(player_id)
        max_cards = pa["max_cards"]
        if len(card_ids) > max_cards:
            return {"error": f"最大{max_cards}枚です"}
        for cid in card_ids:
            if cid not in player.hand:
                return {"error": f"{cid} は手札にありません"}
        for cid in card_ids:
            player.hand.remove(cid)
            self.trash.append(cid)
        if card_ids:
            self._log(f"{player.name} が {len(card_ids)} 枚廃棄")
        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True}

    def _handle_trash_and_gain(self, player_id: str, card_ids: list[str]) -> dict:
        """Trash 1 card, then gain card costing up to trashed_cost + bonus."""
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        if len(card_ids) != 1:
            return {"error": "1枚選んでください"}
        player = self._get_player(player_id)
        cid = card_ids[0]
        if cid not in player.hand:
            return {"error": f"{cid} は手札にありません"}
        card = self.card_data.get(cid)
        trashed_cost = card.get("cost", 0)
        player.hand.remove(cid)
        self.trash.append(cid)
        self._log(f"{player.name} が {card.get('name', cid)} を廃棄")
        # Transition to gain phase
        self.phase = Phase.GAIN
        self.pending_action = {
            "type": "gain",
            "player_id": player_id,
            "max_cost": trashed_cost + pa["cost_bonus"],
        }
        return {"ok": True, "awaiting_gain": True}

    def _handle_trash_treasure(self, player_id: str, card_ids: list[str]) -> dict:
        """Trash a treasure, gain treasure costing up to trashed_cost + bonus to hand."""
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}
        if len(card_ids) != 1:
            return {"error": "1枚選んでください"}
        player = self._get_player(player_id)
        cid = card_ids[0]
        if cid not in player.hand:
            return {"error": f"{cid} は手札にありません"}
        card = self.card_data.get(cid)
        if card.get("type") != "treasure":
            return {"error": "財宝カードを選んでください"}
        trashed_cost = card.get("cost", 0)
        player.hand.remove(cid)
        self.trash.append(cid)
        self._log(f"{player.name} が {card.get('name', cid)} を廃棄")
        # Transition to gain phase (treasure only, to hand)
        self.phase = Phase.GAIN
        self.pending_action = {
            "type": "gain_treasure_to_hand",
            "player_id": player_id,
            "max_cost": trashed_cost + pa["cost_bonus"],
        }
        return {"ok": True, "awaiting_gain": True}

    def handle_discard_selection(self, player_id: str, card_ids: list[str]) -> dict:
        if not self.pending_action:
            return {"error": "待機中のアクションがありません"}

        if self.pending_action["type"] == "attack_discard":
            return self._handle_militia_discard(player_id, card_ids)
        elif self.pending_action["type"] == "discard_draw":
            return self._handle_cellar_discard(player_id, card_ids)

        return {"error": "不明なアクション"}

    def _handle_militia_discard(self, player_id: str, card_ids: list[str]) -> dict:
        pa = self.pending_action
        if player_id != pa["target_player_id"]:
            return {"error": "あなたが捨てるターンではありません"}

        player = self._get_player(player_id)
        discard_to = pa["discard_to"]
        needed = len(player.hand) - discard_to

        if len(card_ids) != needed:
            return {"error": f"{needed}枚捨ててください"}

        for cid in card_ids:
            if cid not in player.hand:
                return {"error": f"{cid} は手札にありません"}

        for cid in card_ids:
            player.hand.remove(cid)
            player.discard_pile.append(cid)

        self._log(f"  {player.name} が {needed} 枚捨てた")

        remaining = pa.get("remaining_targets", [])
        if remaining:
            next_target = remaining.pop(0)
            next_player = self._get_player(next_target)
            if next_player and len(next_player.hand) > discard_to:
                self.pending_action = {
                    "type": "attack_discard",
                    "target_player_id": next_target,
                    "discard_to": discard_to,
                    "attacker_id": pa["attacker_id"],
                    "remaining_targets": remaining
                }
                return {"ok": True, "next_target": next_target}

        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True, "resolved": True}

    def _handle_cellar_discard(self, player_id: str, card_ids: list[str]) -> dict:
        pa = self.pending_action
        if player_id != pa["player_id"]:
            return {"error": "あなたのアクションではありません"}

        player = self._get_player(player_id)
        for cid in card_ids:
            if cid not in player.hand:
                return {"error": f"{cid} は手札にありません"}

        count = len(card_ids)
        for cid in card_ids:
            player.hand.remove(cid)
            player.discard_pile.append(cid)

        drawn = player.draw_cards(count)
        self._log(f"{player.name} が {count} 枚捨てて {count} 枚引いた")

        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True, "drawn": drawn, "discarded": count}

    def handle_gain_selection(self, player_id: str, card_id: str) -> dict:
        pa_type = self.pending_action.get("type") if self.pending_action else None
        if pa_type not in ("gain", "gain_treasure_to_hand", "gain_to_hand"):
            return {"error": "獲得待ちではありません"}
        if player_id != self.pending_action["player_id"]:
            return {"error": "あなたのアクションではありません"}

        max_cost = self.pending_action["max_cost"]
        card = self.card_data.get(card_id)
        if not card:
            return {"error": "不明なカードです"}
        if card.get("cost", 0) > max_cost:
            return {"error": f"コスト{max_cost}以下のカードを選んでください"}
        if pa_type == "gain_treasure_to_hand" and card.get("type") != "treasure":
            return {"error": "財宝カードを選んでください"}
        if self.supply.get(card_id, 0) <= 0:
            return {"error": "サプライにありません"}

        player = self._get_player(player_id)
        self.supply[card_id] -= 1

        gain_to_hand = pa_type in ("gain_to_hand", "gain_treasure_to_hand")
        if gain_to_hand:
            player.hand.append(card_id)
            self._log(f"{player.name} が {card.get('name', card_id)} を手札に獲得")
        else:
            player.discard_pile.append(card_id)
            self._log(f"{player.name} が {card.get('name', card_id)} を獲得")

        if pa_type == "gain_to_hand":
            # After gaining to hand, must topdeck a card from hand
            self.phase = Phase.TOPDECK
            self.pending_action = {
                "type": "topdeck_from_hand",
                "player_id": player_id,
            }
            return {"ok": True, "gained": card_id, "awaiting_topdeck": True}

        self.pending_action = None
        self.phase = Phase.ACTION
        return {"ok": True, "gained": card_id}

    def play_treasure(self, player_id: str, card_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}
        if self.phase not in (Phase.BUY, Phase.ACTION):
            return {"error": "財宝カードを出せるフェーズではありません"}

        if card_id not in player.hand:
            return {"error": "そのカードは手札にありません"}

        card = self.card_data.get(card_id)
        if card.get("type") != "treasure":
            return {"error": "財宝カードではありません"}

        # Auto-transition to buy phase
        if self.phase == Phase.ACTION:
            self.phase = Phase.BUY

        player.hand.remove(card_id)
        player.play_area.append(card_id)
        player.coins += card.get("coin_value", 0)

        return {"ok": True, "coins": player.coins}

    def play_all_treasures(self, player_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}

        if self.phase not in (Phase.ACTION, Phase.BUY):
            return {"error": "財宝カードをプレイできるフェーズではありません"}

        if self.phase == Phase.ACTION:
            self.phase = Phase.BUY

        treasures = [c for c in player.hand if self.card_data.get(c).get("type") == "treasure"]
        for cid in treasures:
            player.hand.remove(cid)
            player.play_area.append(cid)
            player.coins += self.card_data.get(cid).get("coin_value", 0)

        return {"ok": True, "coins": player.coins, "played": treasures}

    def skip_action_phase(self, player_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}
        if self.phase != Phase.ACTION:
            return {"error": "アクションフェーズではありません"}

        self.phase = Phase.BUY
        return {"ok": True}

    def buy_card(self, player_id: str, card_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}
        if self.phase != Phase.BUY:
            return {"error": "購入フェーズではありません"}
        if player.buys <= 0:
            return {"error": "購入回数が残っていません"}

        card = self.card_data.get(card_id)
        if not card:
            return {"error": "不明なカードです"}

        cost = card.get("cost", 0)
        if cost > player.coins:
            return {"error": f"コインが足りません（必要: {cost}, 所持: {player.coins}）"}

        if self.supply.get(card_id, 0) <= 0:
            return {"error": "サプライにありません"}

        player.coins -= cost
        player.buys -= 1
        self.supply[card_id] -= 1
        player.discard_pile.append(card_id)

        self._log(f"{player.name} が {card.get('name', card_id)} を購入")

        if player.buys <= 0:
            self._end_turn()

        return {"ok": True, "card": card_id}

    def end_turn(self, player_id: str) -> dict:
        player = self._get_player(player_id)
        if not player or player != self.current_player:
            return {"error": "あなたのターンではありません"}
        if self.phase not in (Phase.ACTION, Phase.BUY):
            return {"error": "ターンを終了できません"}

        self._end_turn()
        return {"ok": True}

    def _end_turn(self):
        player = self.current_player
        # Cleanup: discard hand and play area
        player.discard_pile.extend(player.hand)
        player.discard_pile.extend(player.play_area)
        player.hand = []
        player.play_area = []

        # Draw new hand
        player.draw_cards(5)

        # Reset
        player.actions = 1
        player.buys = 1
        player.coins = 0

        # Check game end
        if self._check_game_end():
            self.phase = Phase.GAME_OVER
            self._log("ゲーム終了！")
            self._log_scores()
            return

        # Next player
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.phase = Phase.ACTION
        self.pending_action = None
        self._log(f"{self.current_player.name} のターンです")

    def _check_game_end(self) -> bool:
        conditions = self.card_data.game_end_conditions

        if conditions.get("province_empty"):
            province_id = self.card_data.province_card_id()
            if province_id and self.supply.get(province_id, 0) <= 0:
                return True

        empty_count = sum(1 for v in self.supply.values() if v <= 0)
        if empty_count >= conditions.get("empty_piles", 3):
            return True

        return False

    def _log_scores(self):
        scores = []
        for p in self.players:
            vp = p.count_victory_points(self.card_data)
            scores.append((p.name, vp))
            self._log(f"  {p.name}: {vp} 勝利点")

        scores.sort(key=lambda x: x[1], reverse=True)
        self._log(f"🏆 {scores[0][0]} の勝利！")

    def get_scores(self) -> list[dict]:
        return [
            {"name": p.name, "id": p.id, "vp": p.count_victory_points(self.card_data)}
            for p in self.players
        ]

    def get_state(self, for_player_id: Optional[str] = None) -> dict:
        """Return game state, hiding other players' hands."""
        state = {
            "game_id": self.id,
            "started": self.started,
            "phase": self.phase.value,
            "current_player": self.current_player.id if self.current_player else None,
            "current_player_name": self.current_player.name if self.current_player else None,
            "supply": self.supply,
            "trash": self.trash,
            "log": self.log[-30:],
            "players": [],
            "pending_action": None,
        }

        if self.pending_action:
            # remaining_targets is internal state, exclude from client
            state["pending_action"] = {
                k: v for k, v in self.pending_action.items()
                if k != "remaining_targets"
            }

        for p in self.players:
            pdata = {
                "id": p.id,
                "name": p.name,
                "hand_count": len(p.hand),
                "deck_count": len(p.deck),
                "discard_count": len(p.discard_pile),
                "play_area": p.play_area,
                "actions": p.actions,
                "buys": p.buys,
                "coins": p.coins,
                "connected": p.connected,
            }
            if p.id == for_player_id:
                pdata["hand"] = p.hand
                # Expose discard pile contents during topdeck_from_discard
                if (self.pending_action
                    and self.pending_action.get("type") == "topdeck_from_discard"
                    and self.pending_action.get("player_id") == p.id):
                    pdata["discard_pile"] = p.discard_pile
            state["players"].append(pdata)

        if self.phase == Phase.GAME_OVER:
            state["scores"] = self.get_scores()

        return state

    def _get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == player_id), None)

    def _log(self, message: str):
        self.log.append(message)
