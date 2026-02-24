"""
Claude Code が bridge.py 経由でゲームをプレイするクライアント。

bridge.py が起動済みの状態で実行する。
手番が来るたびに状態を取得し、Claude Code 自身が判断してアクションを送信する。

Usage:
    python scripts/claude_play.py [--bridge http://127.0.0.1:8765]

流れ:
    1. GET /wait で自分の手番までブロック待機
    2. 状態を表示（Claude Code が読む）
    3. 判断してアクションを POST /action で送信
    4. ゲーム終了まで繰り返す
"""

import json
import sys
import urllib.request
import urllib.error
import argparse


BRIDGE = "http://127.0.0.1:8765"


def get(path: str, timeout: float = 310.0) -> dict:
    with urllib.request.urlopen(f"{BRIDGE}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BRIDGE}{path}", data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fmt_hand(hand: list[dict]) -> str:
    parts = []
    for c in hand:
        parts.append(f"{c['id']}({c.get('name_en', c['id'])})")
    return ", ".join(parts)


# ---- カード属性ヘルパー ----

def has_effect(card: dict, effect_type: str) -> bool:
    return any(e["type"] == effect_type for e in card.get("effects", []))


def effect_amount(card: dict, effect_type: str) -> int:
    for e in card.get("effects", []):
        if e["type"] == effect_type:
            return e.get("amount", 0)
    return 0


def is_basic_treasure(card: dict, hand: list[dict]) -> bool:
    """手札内の財宝のうち coin_value が最小のものかどうか。"""
    if card.get("type") != "treasure":
        return False
    treasure_vals = [c.get("coin_value", 0) for c in hand if c.get("type") == "treasure"]
    if not treasure_vals:
        return False
    return card.get("coin_value", 0) <= min(treasure_vals)


def province_card(supply: dict) -> tuple[str, dict] | tuple[None, None]:
    """最高コストの勝利点カード（終了条件判定用）を返す。"""
    vids = [(cid, info) for cid, info in supply.items() if info.get("type") == "victory"]
    if not vids:
        return None, None
    return max(vids, key=lambda x: x[1].get("cost", 0))


def duchy_card(supply: dict) -> tuple[str, dict] | tuple[None, None]:
    """2番目に高コストの勝利点カード。"""
    vids = sorted(
        [(cid, info) for cid, info in supply.items() if info.get("type") == "victory"],
        key=lambda x: x[1].get("cost", 0),
        reverse=True,
    )
    return vids[1] if len(vids) >= 2 else (None, None)


def province_remaining(supply: dict) -> int:
    cid, _ = province_card(supply)
    return supply[cid]["count"] if cid else 0


def is_endgame(supply: dict) -> bool:
    empty_piles = sum(1 for info in supply.values() if info["count"] <= 0)
    return province_remaining(supply) <= 4 or empty_piles >= 2


# ---- 意思決定 ----

def _action_priority(card: dict, hand: list[dict], supply: dict) -> float:
    """アクションカードの優先度をエフェクトの内容から計算する。"""
    if card.get("type") != "action":
        return 0

    score = 0.0

    if has_effect(card, "attack_discard_to"):
        score += 10
    score += effect_amount(card, "draw") * 1.5
    score += effect_amount(card, "action") * 2.0
    score += effect_amount(card, "coin") * 1.2
    score += effect_amount(card, "buy") * 1.0

    if has_effect(card, "gain_card_up_to"):
        max_cost = effect_amount(card, "gain_card_up_to")
        can_gain = any(
            info["count"] > 0 and info["cost"] <= max_cost and info.get("type") != "action"
            for info in supply.values()
        )
        score += 5 if can_gain else 0

    if has_effect(card, "discard_draw"):
        score += 4

    if card.get("reaction") == "block_attack":
        other_actions = [c for c in hand if c.get("type") == "action" and c["id"] != card["id"]]
        if other_actions:
            score -= 3

    if effect_amount(card, "action") >= 2:
        other_actions = [c for c in hand if c.get("type") == "action" and c["id"] != card["id"]]
        if other_actions:
            score += 4

    return score


def _buy_score(cid: str, info: dict, coins: int, supply: dict) -> float:
    """購入スコアをカード属性から計算する。"""
    cost = info["cost"]
    if cost > coins or info["count"] <= 0:
        return -1

    ctype = info.get("type", "")
    endgame = is_endgame(supply)

    pid, _ = province_card(supply)
    did, _ = duchy_card(supply)
    is_province = (cid == pid)
    is_duchy = (cid == did)
    is_estate = (ctype == "victory" and not is_province and not is_duchy)

    # 最低財宝は買わない
    if ctype == "treasure":
        treasure_vals = [v.get("coin_value", 0) for v in supply.values() if v.get("type") == "treasure"]
        min_cv = min(treasure_vals) if treasure_vals else 0
        if info.get("coin_value", 0) <= min_cv:
            return -1

    if endgame:
        if is_province:
            return 1000
        if is_duchy:
            return 500
        if is_estate:
            return 100 if province_remaining(supply) <= 2 else 50
        if ctype == "treasure":
            treasure_vals = [v.get("coin_value", 0) for v in supply.values() if v.get("type") == "treasure"]
            max_cv = max(treasure_vals) if treasure_vals else 0
            return 80 if info.get("coin_value", 0) >= max_cv else 30
        return 10

    else:
        if is_province:
            return 900 if coins >= cost else -1
        if is_duchy:
            return 600 if province_remaining(supply) <= 4 else -1
        if is_estate:
            return -1
        if ctype == "treasure":
            return 400 + info.get("coin_value", 0) * 100
        if ctype == "action":
            score = 300.0
            if has_effect(info, "attack_discard_to"):
                score += 250
            score += effect_amount(info, "draw") * 30
            score += effect_amount(info, "action") * 40
            score += effect_amount(info, "coin") * 25
            score += effect_amount(info, "buy") * 20
            if has_effect(info, "gain_card_up_to"):
                score += 120
            if has_effect(info, "discard_draw"):
                score += 20
            if info.get("reaction") == "block_attack":
                score -= 50
            return score

    return 0


def _gain_score(cid: str, info: dict, supply: dict) -> float:
    """gain_card_up_to 効果で獲得するカードのスコア。"""
    ctype = info.get("type", "")
    endgame = is_endgame(supply)
    pid, _ = province_card(supply)
    did, _ = duchy_card(supply)

    if endgame:
        if cid == did:
            return 1000
        if ctype == "victory":
            return 500
        if ctype == "treasure":
            return 200 + info.get("coin_value", 0) * 50
    else:
        if ctype == "treasure":
            return 500 + info.get("coin_value", 0) * 100
        if ctype == "action":
            score = 200.0
            if has_effect(info, "attack_discard_to"):
                score += 300
            score += effect_amount(info, "draw") * 25
            score += effect_amount(info, "action") * 30
            score += effect_amount(info, "coin") * 20
            if has_effect(info, "gain_card_up_to"):
                score += 100
            return score
        if cid == did:
            return 300

    return info.get("cost", 0) * 10


def decide(state: dict) -> dict | None:
    """
    ゲーム状態を受け取り、次のアクションを決定して返す。
    カードIDをハードコードせず、type/effectsで判断する。
    """
    me = state.get("me", {})
    ctx = state.get("context", {})
    reason = ctx.get("reason") if ctx else None
    phase = ctx.get("phase") if ctx else state.get("phase")
    pa = ctx.get("pending_action", {}) if ctx else {}
    supply = state.get("supply", {})
    hand = me.get("hand", []) if me else []
    coins = me.get("coins", 0) if me else 0
    actions_left = me.get("actions", 0) if me else 0

    # ---- 攻撃による強制捨て札 ----
    if reason == "discard":
        discard_to = pa.get("discard_to", 3)
        needed = max(0, len(hand) - discard_to)

        def discard_prio(card: dict) -> int:
            ctype = card.get("type", "")
            if is_basic_treasure(card, hand):
                return 0
            if ctype == "victory":
                return 1
            if ctype == "action":
                return 2
            # 財宝はコイン値が低いほど先
            if ctype == "treasure":
                return 3 + card.get("coin_value", 0)
            return 10

        to_discard = [c["id"] for c in sorted(hand, key=discard_prio)[:needed]]
        return {"action": "discard_selection", "card_ids": to_discard}

    # ---- 任意捨て引き直し（discard_draw 効果） ----
    if reason == "cellar":
        to_discard = [
            c["id"] for c in hand
            if c.get("type") == "victory" or is_basic_treasure(c, hand)
        ]
        return {"action": "discard_selection", "card_ids": to_discard}

    # ---- カード獲得（gain_card_up_to 効果） ----
    if reason == "gain":
        max_cost = pa.get("max_cost", 4)
        affordable = {cid: info for cid, info in supply.items()
                      if info["cost"] <= max_cost and info["count"] > 0}
        if affordable:
            best = max(affordable.items(), key=lambda x: _gain_score(x[0], x[1], supply))[0]
            return {"action": "gain_selection", "card_id": best}
        return None

    # ---- アクションフェーズ ----
    if phase == "action":
        action_cards = [c for c in hand if c.get("type") == "action"]

        if actions_left > 0 and action_cards:
            best = max(action_cards, key=lambda c: _action_priority(c, hand, supply))
            if _action_priority(best, hand, supply) > 0:
                return {"action": "play_action", "card_id": best["id"]}

        return {"action": "skip_action"}

    # ---- 購入フェーズ ----
    if phase == "buy":
        has_treasures = any(c.get("type") == "treasure" for c in hand)
        if has_treasures:
            return {"action": "play_all_treasures"}

        candidates = [
            (cid, _buy_score(cid, info, coins, supply))
            for cid, info in supply.items()
            if _buy_score(cid, info, coins, supply) > 0
        ]
        if candidates:
            best_cid = max(candidates, key=lambda x: x[1])[0]
            return {"action": "buy", "card_id": best_cid}

        return {"action": "end_turn"}

    return None


def play_loop():
    print(f"[claude_play] bridge: {BRIDGE}")

    try:
        st = get("/status", timeout=5)
        print(f"[claude_play] 接続確認: phase={st.get('current_phase')} "
              f"my_name={st.get('my_name')}")
    except Exception as e:
        print(f"[claude_play] bridge に接続できません: {e}")
        sys.exit(1)

    turn = 0
    while True:
        print(f"\n{'='*60}")
        print(f"[wait] 手番を待機中...")

        try:
            state = get("/wait", timeout=310)
        except urllib.error.HTTPError as e:
            if e.code == 408:
                print("[wait] タイムアウト、再試行")
                continue
            print(f"[wait] HTTPエラー: {e}")
            break
        except Exception as e:
            print(f"[wait] エラー: {e}")
            break

        if state.get("game_over"):
            print("\n===== ゲーム終了 =====")
            for s in sorted(state.get("scores", []), key=lambda x: -x["vp"]):
                print(f"  {s['name']}: {s['vp']} VP")
            break

        turn += 1
        me = state.get("me", {})
        ctx = state.get("context", {})
        eg = state.get("endgame", {})

        # 状態表示
        print(f"ターン{turn} | phase={state['phase']} | "
              f"{'[終盤]' if eg.get('is_endgame') else '[序盤]'} "
              f"province残{eg.get('province_remaining')} 空山{eg.get('empty_piles')}")
        print(f"自分: coins={me.get('coins',0)} actions={me.get('actions',0)} "
              f"buys={me.get('buys',0)} VP={me.get('vp',0)}")
        print(f"手札: {fmt_hand(me.get('hand', []))}")
        for opp in state.get("opponents", []):
            print(f"相手: {opp['name']} 手札{opp['hand_count']}枚 "
                  f"デッキ{opp['deck_count']}枚 VP{opp['vp']}")
        if ctx:
            print(f"状況: {ctx.get('description', '')}")
        print(f"ログ: {' / '.join(state.get('log', [])[-3:])}")

        # 判断
        action = decide(state)
        if action is None:
            print("[decide] アクションなし → end_turn")
            action = {"action": "end_turn"}

        print(f"[decide] → {action}")

        try:
            post("/action", action)
            print(f"[action] 送信完了")
        except Exception as e:
            print(f"[action] 送信エラー: {e}")
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    global BRIDGE
    BRIDGE = args.bridge

    play_loop()


if __name__ == "__main__":
    main()
