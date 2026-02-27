"""
戦略ボット。状況を判断してアクションカードを使い、本気で勝ちに行く。

Usage (コンテナ内から):
    python scripts/bot.py <game_id> [--name NAME] [--start] [--ai]

    --start  このボットがゲームを開始する（2人目のプレイヤーが使う）
    --ai     Claude AI を使って戦略を判断する（ANTHROPIC_API_KEY 必須）

Examples:
    docker compose exec app python scripts/bot.py abc12345 --name Claude --start --ai
"""

import asyncio
import json
import argparse
import urllib.request
import websockets
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from card_utils import build_effect_text


def fetch_cards(base_url: str) -> dict[str, dict]:
    """カード定義を全フィールド込みで取得する。"""
    with urllib.request.urlopen(f"{base_url}/api/cards") as resp:
        data = json.loads(resp.read())
    return {c["id"]: c for c in data.get("cards", [])}


def log(name: str, msg: dict):
    t = msg.get("type")
    if t == "state":
        st = msg["state"]
        me = next((p for p in st["players"] if p["name"] == name), None)
        hand = me.get("hand", []) if me else []
        coins = me.get("coins", 0) if me else 0
        print(
            f"[{name}] phase={st['phase']:12s} "
            f"turn={st.get('current_player_name', '?'):10s} "
            f"hand={hand} coins={coins}"
        )
    elif t == "error":
        print(f"[{name}] ERROR: {msg['message']}")
    elif t == "joined":
        print(f"[{name}] joined  player_id={msg['player_id']}")
    else:
        print(f"[{name}] {msg}")


# ---- カード属性ヘルパー ----

def card_type(cid: str, cards: dict[str, dict]) -> str:
    return cards.get(cid, {}).get("type", "")


def has_effect(cid: str, effect_type: str, cards: dict[str, dict]) -> bool:
    return any(e["type"] == effect_type for e in cards.get(cid, {}).get("effects", []))


def effect_amount(cid: str, effect_type: str, cards: dict[str, dict]) -> int:
    for e in cards.get(cid, {}).get("effects", []):
        if e["type"] == effect_type:
            return e.get("amount", 0)
    return 0


def is_basic_treasure(cid: str, cards: dict[str, dict]) -> bool:
    """coin_value が最小（=1）の財宝かどうか。"""
    c = cards.get(cid, {})
    if c.get("type") != "treasure":
        return False
    min_cv = min((c2.get("coin_value", 999) for c2 in cards.values() if c2.get("type") == "treasure"), default=1)
    return c.get("coin_value", 0) <= min_cv


def province_card_id(supply: dict, cards: dict[str, dict]) -> str | None:
    """最高コストの勝利点カードID（終了条件判定用）を返す。"""
    vids = [cid for cid in supply if cards.get(cid, {}).get("type") == "victory"]
    if not vids:
        return None
    return max(vids, key=lambda cid: cards[cid].get("cost", 0))


def province_remaining(supply: dict, cards: dict[str, dict]) -> int:
    pid = province_card_id(supply, cards)
    return supply.get(pid, 0) if pid else 0


def empty_piles(supply: dict) -> int:
    return sum(1 for v in supply.values() if v <= 0)


def is_endgame(supply: dict, cards: dict[str, dict]) -> bool:
    """終盤判定：最高VP山が4枚以下 or 空き山が2つ以上。"""
    return province_remaining(supply, cards) <= 4 or empty_piles(supply) >= 2


# ---- 戦略ロジック ----

def _action_priority(cid: str, cards: dict[str, dict], hand: list[str], supply: dict) -> float:
    """
    アクションカードの優先度をエフェクトの内容から計算する。
    ハードコードIDは使わず、effectsとtypeで判断する。
    """
    c = cards.get(cid, {})
    if c.get("type") != "action":
        return 0

    score = 0.0

    # 攻撃 (attack_discard_to)：コイン生産も兼ねるので最優先
    if has_effect(cid, "attack_discard_to", cards):
        score += 10

    # +3ドロー以上 かつ +アクション → スミシー系は高評価
    draw_amt = effect_amount(cid, "draw", cards)
    action_amt = effect_amount(cid, "action", cards)
    coin_amt = effect_amount(cid, "coin", cards)
    buy_amt = effect_amount(cid, "buy", cards)

    score += draw_amt * 1.5
    score += action_amt * 2.0
    score += coin_amt * 1.2
    score += buy_amt * 1.0

    # カード獲得効果は中優先
    if has_effect(cid, "gain_card_up_to", cards):
        can_gain = any(
            cnt > 0 and cards.get(cid2, {}).get("cost", 0) <= effect_amount(cid, "gain_card_up_to", cards)
            and cards.get(cid2, {}).get("type") not in ("action",)
            for cid2, cnt in supply.items()
        )
        score += 5 if can_gain else 0

    # 捨て引き効果（discard_draw）は手札改善として中程度
    if has_effect(cid, "discard_draw", cards):
        score += 4

    # リアクション持ちは他にアクションがある場合は後回し
    if c.get("reaction") == "block_attack":
        other_actions = [c2 for c2 in hand if cards.get(c2, {}).get("type") == "action" and c2 != cid]
        if other_actions:
            score -= 3

    # +2アクション以上の村系：他にアクションカードがあるとき優先
    if action_amt >= 2:
        other_actions = [c2 for c2 in hand if cards.get(c2, {}).get("type") == "action" and c2 != cid]
        if other_actions:
            score += 4

    return score


def choose_action(hand: list[str], cards: dict[str, dict], state: dict, me: dict) -> str | None:
    supply = state.get("supply", {})
    action_cards = [c for c in hand if cards.get(c, {}).get("type") == "action"]
    if not action_cards:
        return None

    best = max(action_cards, key=lambda c: _action_priority(c, cards, hand, supply))
    if _action_priority(best, cards, hand, supply) > 0:
        return best
    return None


def _buy_score(cid: str, coins: int, supply: dict, cards: dict[str, dict], endgame: bool) -> float:
    """
    購入スコアをカード属性から計算する。IDハードコードなし。
    """
    c = cards.get(cid, {})
    cost = c.get("cost", 0)
    if cost > coins or supply.get(cid, 0) <= 0:
        return -1

    ctype = c.get("type", "")
    vp = c.get("victory_points", 0)
    coin_val = c.get("coin_value", 0)

    # 最高コストの勝利点カード（省）
    pid = province_card_id(supply, cards)
    is_province = (cid == pid)

    # 2番目に高い勝利点カード（duchy相当）
    vids_sorted = sorted(
        [cid2 for cid2, c2 in cards.items() if c2.get("type") == "victory"],
        key=lambda cid2: cards[cid2].get("cost", 0),
        reverse=True
    )
    is_duchy = (len(vids_sorted) >= 2 and cid == vids_sorted[1])

    # 最も安い勝利点カード（estate相当）—— 基本的に買わない
    is_estate = (ctype == "victory" and not is_province and not is_duchy)

    # 最も安い財宝カード（copper相当）—— 買わない
    if is_basic_treasure(cid, cards):
        return -1

    if endgame:
        if is_province:
            return 1000
        if is_duchy:
            return 500
        if is_estate:
            prem = province_remaining(supply, cards)
            return 100 if prem <= 2 else 50
        if ctype == "treasure":
            # 終盤でも高コイン財宝は価値あり
            max_cv = max((c2.get("coin_value", 0) for c2 in cards.values() if c2.get("type") == "treasure"), default=1)
            return 80 if coin_val >= max_cv else 30
        # アクションは終盤基本不要
        return 10

    else:
        if is_province:
            return 900 if coins >= cost else -1
        if is_duchy:
            return 600 if province_remaining(supply, cards) <= 4 else -1
        if is_estate:
            return -1

        if ctype == "treasure":
            # コイン値が高いほど評価
            return 400 + coin_val * 100

        if ctype == "action":
            # エフェクトの内容でスコア算出
            score = 300.0
            if has_effect(cid, "attack_discard_to", cards):
                score += 250
            score += effect_amount(cid, "draw", cards) * 30
            score += effect_amount(cid, "action", cards) * 40
            score += effect_amount(cid, "coin", cards) * 25
            score += effect_amount(cid, "buy", cards) * 20
            if has_effect(cid, "gain_card_up_to", cards):
                score += 120
            if has_effect(cid, "discard_draw", cards):
                score += 20
            if cards.get(cid, {}).get("reaction") == "block_attack":
                score -= 50  # リアクションは防御用なので少し下げる
            return score

    return 0


def choose_buy(coins: int, supply: dict, cards: dict[str, dict], me: dict, state: dict) -> str | None:
    endgame = is_endgame(supply, cards)
    candidates = [
        (cid, score) for cid in supply
        if (score := _buy_score(cid, coins, supply, cards, endgame)) > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1])[0]


def choose_cellar_discards(hand: list[str], cards: dict[str, dict]) -> list[str]:
    """
    discard_draw 効果のカードを使ったとき、捨てるカードを選ぶ。
    勝利点カードと最低財宝を優先して捨てる。
    """
    discard = []
    for cid in hand:
        c = cards.get(cid, {})
        if c.get("type") == "victory":
            discard.append(cid)
        elif is_basic_treasure(cid, cards):
            discard.append(cid)
    return discard


def choose_militia_discards(hand: list[str], discard_to: int, cards: dict[str, dict]) -> list[str]:
    """
    attack_discard_to 効果を受けたとき、捨てるカードを選ぶ。
    価値の低いものから捨てる（最低財宝→勝利点→アクション→高コイン財宝の順）。
    """
    needed = max(0, len(hand) - discard_to)
    if needed == 0:
        return []

    def discard_priority(cid: str) -> int:
        c = cards.get(cid, {})
        ctype = c.get("type", "")
        if is_basic_treasure(cid, cards):
            return 0   # 最初に捨てる
        if ctype == "victory":
            return 1
        if ctype == "action":
            return 2
        # 財宝はコイン値が低いほど先に捨てる
        if ctype == "treasure":
            return 3 + c.get("coin_value", 0)
        return 10

    sorted_hand = sorted(hand, key=discard_priority)
    return sorted_hand[:needed]


def _gain_score(cid: str, supply: dict, cards: dict[str, dict], endgame: bool) -> float:
    """gain_card_up_to で獲得するカードのスコア。"""
    c = cards.get(cid, {})
    ctype = c.get("type", "")

    pid = province_card_id(supply, cards)
    vids_sorted = sorted(
        [cid2 for cid2, c2 in cards.items() if c2.get("type") == "victory"],
        key=lambda cid2: cards[cid2].get("cost", 0),
        reverse=True
    )
    is_province = (cid == pid)
    is_duchy = (len(vids_sorted) >= 2 and cid == vids_sorted[1])

    if endgame:
        if is_duchy:
            return 1000
        if ctype == "victory":
            return 500
        if ctype == "treasure":
            return 200 + c.get("coin_value", 0) * 50
    else:
        if ctype == "treasure":
            return 500 + c.get("coin_value", 0) * 100
        if ctype == "action":
            score = 200.0
            if has_effect(cid, "attack_discard_to", cards):
                score += 300
            score += effect_amount(cid, "draw", cards) * 25
            score += effect_amount(cid, "action", cards) * 30
            score += effect_amount(cid, "coin", cards) * 20
            if has_effect(cid, "gain_card_up_to", cards):
                score += 100
            return score
        if is_duchy:
            return 300

    return c.get("cost", 0) * 10


def choose_gain_card(supply: dict, cards: dict[str, dict], max_cost: int) -> str | None:
    endgame = is_endgame(supply, cards)
    candidates = [
        cid for cid, cnt in supply.items()
        if cnt > 0 and cards.get(cid, {}).get("cost", 0) <= max_cost
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda cid: _gain_score(cid, supply, cards, endgame))


# ---- Claude AI 意思決定インターフェース ----

def build_state_prompt(state: dict, me: dict, cards: dict[str, dict], phase: str, pa: dict) -> str:
    supply = state.get("supply", {})
    hand = me.get("hand", [])
    coins = me.get("coins", 0)
    actions_left = me.get("actions", 0)
    buys_left = me.get("buys", 0)
    my_deck_count = me.get("deck_count", 0)
    my_discard_count = me.get("discard_count", 0)

    hand_info = []
    for cid in hand:
        c = cards.get(cid, {})
        hand_info.append(f"  - {cid} ({c.get('name', cid)}): {build_effect_text(c)}")

    supply_info = []
    for cid, cnt in supply.items():
        if cnt > 0:
            c = cards.get(cid, {})
            supply_info.append(
                f"  - {cid} ({c.get('name', cid)}): 残{cnt}枚, "
                f"コスト{c.get('cost', '?')}, {build_effect_text(c)}"
            )

    opponents = [p for p in state.get("players", []) if p["id"] != me["id"]]
    opp_info = []
    for p in opponents:
        opp_info.append(
            f"  - {p['name']}: デッキ{p.get('deck_count',0)}枚, "
            f"捨て札{p.get('discard_count',0)}枚, VP約{p.get('vp',0)}"
        )

    endgame = is_endgame(supply, cards)
    province_left = province_remaining(supply, cards)
    empty = empty_piles(supply)

    prompt = f"""あなたはデッキ構築カードゲーム「Sovereign」のAIプレイヤーです。
本気で勝ちに行く戦略を選んでください。

【現在の状況】
フェーズ: {phase}
終盤判定: {"終盤（積極的に得点を狙え）" if endgame else "序盤〜中盤（デッキを強化せよ）"}
最高VP山残枚数: {province_left}
空きサプライ山: {empty}個

【自分の状態】
手札 (actions_left={actions_left}, coins={coins}, buys={buys_left}):
{chr(10).join(hand_info) if hand_info else "  (なし)"}
デッキ残り: {my_deck_count}枚, 捨て札: {my_discard_count}枚

【対戦相手】
{chr(10).join(opp_info) if opp_info else "  (なし)"}

【サプライ（購入可能カード）】
{chr(10).join(supply_info) if supply_info else "  (なし)"}
"""

    if phase == "action":
        action_cards = [cid for cid in hand if cards.get(cid, {}).get("type") == "action"]
        prompt += f"""
【タスク: アクションフェーズ】
手札のアクションカード: {action_cards}
残りアクション数: {actions_left}

どのアクションカードを使うか、またはスキップするかを決めてください。

以下のJSON形式のみで回答してください（説明不要）:
{{"action": "play_action", "card_id": "<card_id>"}}
または
{{"action": "skip_action"}}
"""

    elif phase == "buy":
        treasure_cards = [cid for cid in hand if cards.get(cid, {}).get("type") == "treasure"]
        prompt += f"""
【タスク: 購入フェーズ】
手札の財宝カード: {treasure_cards}
現在のコイン: {coins}
残り購入回数: {buys_left}

財宝を出す場合は play_all_treasures、購入する場合は buy、ターン終了は end_turn を選んでください。

以下のJSON形式のみで回答してください（説明不要）:
{{"action": "play_all_treasures"}}
または
{{"action": "buy", "card_id": "<card_id>"}}
または
{{"action": "end_turn"}}
"""

    elif phase == "discard":
        discard_to = pa.get("discard_to", 3)
        prompt += f"""
【タスク: 攻撃による強制捨て札】
相手の攻撃により手札を{discard_to}枚になるまで捨てる必要があります。
現在の手札枚数: {len(hand)}枚 → {discard_to}枚まで減らす（{max(0, len(hand) - discard_to)}枚捨てる）

価値の低いカードから捨ててください。

以下のJSON形式のみで回答してください（説明不要）:
{{"action": "discard_selection", "card_ids": ["<card_id>", ...]}}
"""

    elif phase == "discard_draw":
        prompt += """
【タスク: 任意捨て札（引き直し）】
任意の枚数を捨てて、同じ枚数だけ引けます。
不要なカード（勝利点、最低財宝など）を捨てて手札を改善してください。
捨てたくない場合は空リストを返してください。

以下のJSON形式のみで回答してください（説明不要）:
{{"action": "discard_selection", "card_ids": ["<card_id>", ...]}}
または
{{"action": "discard_selection", "card_ids": []}}
"""

    elif phase == "gain":
        max_cost = pa.get("max_cost", 4)
        prompt += f"""
【タスク: カード獲得】
コスト{max_cost}以下のカードを1枚獲得できます。

以下のJSON形式のみで回答してください（説明不要）:
{{"action": "gain_selection", "card_id": "<card_id>"}}
"""

    return prompt


async def ai_decide(state: dict, me: dict, cards: dict[str, dict], phase: str, pa: dict) -> dict | None:
    try:
        import anthropic
    except ImportError:
        print("[AI] anthropic パッケージが見つかりません。pip install anthropic してください。")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[AI] ANTHROPIC_API_KEY が設定されていません。")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_state_prompt(state, me, cards, phase, pa)

    print(f"[AI] Claude に判断を委ねます... (phase={phase})")

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text.strip()
        print(f"[AI] Claude の回答: {response_text}")

        json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        return json.loads(response_text)

    except Exception as e:
        print(f"[AI] Claude API エラー: {e}")
        return None


def fallback_decide(phase: str, pa: dict, state: dict, me: dict, cards: dict[str, dict]) -> dict | None:
    hand = me.get("hand", [])
    supply = state.get("supply", {})
    coins = me.get("coins", 0)

    if phase == "action":
        actions_left = me.get("actions", 0)
        if actions_left > 0:
            card_id = choose_action(hand, cards, state, me)
            if card_id:
                return {"action": "play_action", "card_id": card_id}
        return {"action": "skip_action"}

    elif phase == "buy":
        has_treasures = any(cards.get(c, {}).get("type") == "treasure" for c in hand)
        if has_treasures:
            return {"action": "play_all_treasures"}
        card_id = choose_buy(coins, supply, cards, me, state)
        if card_id:
            return {"action": "buy", "card_id": card_id}
        return {"action": "end_turn"}

    elif phase == "discard":
        discard_to = pa.get("discard_to", 3)
        card_ids = choose_militia_discards(hand, discard_to, cards)
        return {"action": "discard_selection", "card_ids": card_ids}

    elif phase == "discard_draw":
        card_ids = choose_cellar_discards(hand, cards)
        return {"action": "discard_selection", "card_ids": card_ids}

    elif phase == "gain":
        max_cost = pa.get("max_cost", 4)
        card_id = choose_gain_card(supply, cards, max_cost)
        if card_id:
            return {"action": "gain_selection", "card_id": card_id}

    elif phase == "trash":
        pa_type = pa.get("type", "")
        if pa_type == "trash":
            # 低コストカード（銅貨・低勝利点）を廃棄
            copper_count = sum(1 for c in hand if cards.get(c, {}).get("cost", 0) == 0 and cards.get(c, {}).get("type") == "treasure")
            trash_ids = []
            coppers_trashed = 0
            max_cards = pa.get("max_cards", 4)
            for cid in hand:
                if len(trash_ids) >= max_cards:
                    break
                c = cards.get(cid, {})
                if c.get("type") == "victory" and c.get("victory_points", 0) <= 1:
                    trash_ids.append(cid)
                elif c.get("cost", 0) == 0 and c.get("type") == "treasure" and copper_count - coppers_trashed > 3:
                    trash_ids.append(cid)
                    coppers_trashed += 1
            return {"action": "trash_selection", "card_ids": trash_ids}
        elif pa_type == "trash_and_gain":
            # 最安カードを廃棄してアップグレード
            best = min(hand, key=lambda c: cards.get(c, {}).get("cost", 0))
            return {"action": "trash_selection", "card_ids": [best]}
        elif pa_type == "trash_treasure_gain_treasure":
            # 最安財宝を廃棄してアップグレード
            treasures = [c for c in hand if cards.get(c, {}).get("type") == "treasure"]
            if treasures:
                cheapest = min(treasures, key=lambda c: cards.get(c, {}).get("cost", 0))
                return {"action": "trash_selection", "card_ids": [cheapest]}
            return {"action": "trash_selection", "card_ids": []}

    elif phase == "topdeck":
        pa_type = pa.get("type", "")
        if pa_type == "topdeck_from_hand":
            # 勝利点カード優先、なければ最安カードをデッキトップに
            victories = [c for c in hand if cards.get(c, {}).get("type") == "victory"]
            if victories:
                chosen = min(victories, key=lambda c: cards.get(c, {}).get("cost", 0))
            else:
                chosen = min(hand, key=lambda c: cards.get(c, {}).get("cost", 0))
            return {"action": "topdeck_selection", "card_id": chosen}
        elif pa_type == "topdeck_from_discard":
            # 捨て札からコスト3以上の最高コストカードをデッキトップに
            discard_pile = me.get("discard_pile", [])
            if discard_pile:
                best = max(discard_pile, key=lambda c: cards.get(c, {}).get("cost", 0))
                if cards.get(best, {}).get("cost", 0) >= 3:
                    return {"action": "topdeck_selection", "card_id": best}
            return {"action": "topdeck_selection", "card_id": None}
        elif pa_type == "play_revealed_action":
            # Always play the revealed action
            return {"action": "vassal_decision", "play": True}
        elif pa_type == "reveal_trash_discard_topdeck":
            # Trash estates/coppers, topdeck good cards, discard rest
            revealed = pa.get("revealed_cards", [])
            decisions = []
            for cid in revealed:
                c = cards.get(cid, {})
                if c.get("type") == "victory" and c.get("victory_points", 0) <= 1:
                    decisions.append({"card_id": cid, "action": "trash"})
                elif c.get("cost", 0) == 0 and c.get("type") == "treasure":
                    decisions.append({"card_id": cid, "action": "trash"})
                elif c.get("cost", 0) >= 5:
                    decisions.append({"card_id": cid, "action": "topdeck"})
                else:
                    decisions.append({"card_id": cid, "action": "discard"})
            return {"action": "sentry_decision", "decisions": decisions}

    return None


# ---- メインボットループ ----

async def bot(game_id: str, name: str, do_start: bool, base_url: str, use_ai: bool):
    cards = fetch_cards(base_url)
    uri = f"ws://localhost:8000/ws/{game_id}"
    print(f"[{name}] connecting → {uri}")
    if use_ai:
        print(f"[{name}] AI モード: Claude が戦略を判断します")

    async with websockets.connect(uri) as ws:

        async def send(data):
            await ws.send(json.dumps(data))

        async def recv():
            msg = json.loads(await ws.recv())
            log(name, msg)
            return msg

        # 参加
        await send({"action": "join", "name": name})
        await recv()  # joined
        await recv()  # state (waiting)

        # ゲーム開始
        if do_start:
            print(f"[{name}] → start")
            await send({"action": "start"})
            await recv()  # state (action)

        # AI またはフォールバックで判断を取得するヘルパー
        async def decide(phase_key: str, pa: dict, state: dict, me: dict) -> dict | None:
            if use_ai:
                decision = await ai_decide(state, me, cards, phase_key, pa)
                if decision is not None:
                    return decision
            return fallback_decide(phase_key, pa, state, me, cards)

        # メインループ
        while True:
            msg = await recv()
            if msg.get("type") != "state":
                continue

            state = msg["state"]

            if state["phase"] == "game_over":
                print(f"\n[{name}] ===== ゲーム終了 =====")
                for s in sorted(state.get("scores", []), key=lambda x: -x["vp"]):
                    print(f"  {s['name']}: {s['vp']} VP")
                break

            me = next((p for p in state["players"] if p["name"] == name), None)
            if not me:
                continue

            phase = state["phase"]
            pa = state.get("pending_action") or {}

            # 自分が応答すべき状況を判定
            is_my_turn = state["current_player"] == me["id"]
            is_my_discard = phase == "discard" and pa.get("target_player_id") == me["id"]
            is_my_pending = pa.get("player_id") == me["id"]

            if not (is_my_turn or is_my_discard or (is_my_pending and phase in ("discard_draw", "gain", "trash", "topdeck"))):
                continue

            # ターン外の応答（攻撃の捨て札、各種選択フェーズ）
            if phase in ("discard", "discard_draw", "gain", "trash", "topdeck") and not (is_my_turn and phase in ("action", "buy")):
                phase_key = phase
                if is_my_discard and not is_my_turn:
                    phase_key = "discard"
                decision = await decide(phase_key, pa, state, me)
                if decision:
                    print(f"[{name}] → {decision}")
                    await send(decision)
                continue

            # 自分のターン（action / buy フェーズ）
            if phase == "action":
                if me.get("actions", 0) > 0:
                    decision = await decide("action", pa, state, me)
                    if decision:
                        print(f"[{name}] → {decision}")
                        await send(decision)
                        continue

                print(f"[{name}] → skip_action")
                await send({"action": "skip_action"})

            elif phase == "buy":
                hand = me.get("hand", [])
                has_treasures = any(cards.get(c, {}).get("type") == "treasure" for c in hand)

                if has_treasures:
                    print(f"[{name}] → play_all_treasures")
                    await send({"action": "play_all_treasures"})
                    continue

                decision = await decide("buy", pa, state, me)
                if decision:
                    print(f"[{name}] → {decision}")
                    await send(decision)
                else:
                    print(f"[{name}] → end_turn")
                    await send({"action": "end_turn"})


async def main():
    parser = argparse.ArgumentParser(description="Sovereign 戦略ボット")
    parser.add_argument("game_id", help="参加するゲームID")
    parser.add_argument("--name", default="Claude", help="プレイヤー名")
    parser.add_argument("--start", action="store_true", help="ゲームを開始する")
    parser.add_argument("--url", default="http://localhost:8000", help="サーバーURL")
    parser.add_argument("--ai", action="store_true", help="Claude AI で戦略判断する（ANTHROPIC_API_KEY 必須）")
    args = parser.parse_args()

    await bot(args.game_id, args.name, do_start=args.start, base_url=args.url, use_ai=args.ai)


if __name__ == "__main__":
    asyncio.run(main())
