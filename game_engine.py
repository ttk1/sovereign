"""
Sovereign - Game Engine
デッキ構築型カードゲーム「Sovereign」のゲームエンジン。
"""

import random
import json
import copy
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Phase(str, Enum):
    ACTION = "action"
    BUY = "buy"
    CLEANUP = "cleanup"
    WAITING = "waiting"
    GAME_OVER = "game_over"
    DISCARD = "discard"  # Waiting for discard selection (edict etc.)
    GAIN = "gain"        # Waiting for card gain selection (chartered etc.)
    CELLAR = "cellar"    # Waiting for cellar discard selection


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
                # Cellar: enter discard selection phase
                self.phase = Phase.CELLAR
                self.pending_action = {"type": "cellar", "player_id": player.id}
                result["awaiting_discard"] = True
            elif etype == "gain_card_up_to":
                # Workshop: enter gain selection phase
                self.phase = Phase.GAIN
                self.pending_action = {
                    "type": "gain",
                    "player_id": player.id,
                    "max_cost": amount
                }
                result["awaiting_gain"] = True

        return result

    def _resolve_militia_attack(self, attacker: Player, discard_to: int) -> dict:
        attacked = {}
        for p in self.players:
            if p.id == attacker.id:
                continue
            # Check for rampart reaction
            has_moat = any(
                self.card_data.get(c).get("reaction") == "block_attack"
                for c in p.hand
            )
            if has_moat:
                self._log(f"  {p.name} はリアクションカードでアタックを防いだ")
                attacked[p.id] = {"blocked": True}
                continue

            if len(p.hand) <= discard_to:
                attacked[p.id] = {"already_under": True}
                continue

            # AI auto-discard for simplicity, or set pending
            self.phase = Phase.DISCARD
            self.pending_action = {
                "type": "militia_discard",
                "target_player_id": p.id,
                "discard_to": discard_to,
                "attacker_id": attacker.id,
                "remaining_targets": [
                    op.id for op in self.players
                    if op.id != attacker.id and op.id != p.id
                    and len(op.hand) > discard_to
                    and not any(
                        self.card_data.get(c).get("reaction") == "block_attack"
                        for c in op.hand
                    )
                ]
            }
            attacked[p.id] = {"must_discard_to": discard_to}
            break  # Handle one at a time

        return attacked

    def handle_discard_selection(self, player_id: str, card_ids: list[str]) -> dict:
        if not self.pending_action:
            return {"error": "待機中のアクションがありません"}

        if self.pending_action["type"] == "militia_discard":
            return self._handle_militia_discard(player_id, card_ids)
        elif self.pending_action["type"] == "cellar":
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
                    "type": "militia_discard",
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
        if not self.pending_action or self.pending_action["type"] != "gain":
            return {"error": "獲得待ちではありません"}
        if player_id != self.pending_action["player_id"]:
            return {"error": "あなたのアクションではありません"}

        max_cost = self.pending_action["max_cost"]
        card = self.card_data.get(card_id)
        if not card:
            return {"error": "不明なカードです"}
        if card.get("cost", 0) > max_cost:
            return {"error": f"コスト{max_cost}以下のカードを選んでください"}
        if self.supply.get(card_id, 0) <= 0:
            return {"error": "サプライにありません"}

        player = self._get_player(player_id)
        self.supply[card_id] -= 1
        player.discard_pile.append(card_id)
        self._log(f"{player.name} が {card.get('name', card_id)} を獲得")

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
            state["pending_action"] = {
                "type": self.pending_action.get("type"),
                "target_player_id": self.pending_action.get("target_player_id"),
                "player_id": self.pending_action.get("player_id"),
                "max_cost": self.pending_action.get("max_cost"),
                "discard_to": self.pending_action.get("discard_to"),
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
            state["players"].append(pdata)

        if self.phase == Phase.GAME_OVER:
            state["scores"] = self.get_scores()

        return state

    def _get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.id == player_id), None)

    def _log(self, message: str):
        self.log.append(message)
