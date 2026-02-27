"""
Claude Code がインタラクティブにゲームをプレイするためのスクリプト。

モード1: 状態取得（引数なし）
    /wait でブロックして手番を待ち、状態を表示して終了する。
    Claude Code が状態を読んでアクションを決める。

モード2: アクション送信（引数あり）
    決めたアクションを /action に送信して次の手番まで /wait する。
    その後また状態を表示して終了する。

Usage:
    # 最初の手番を待つ
    python scripts/interactive_play.py

    # アクションを送信して次の手番を待つ
    python scripts/interactive_play.py '{"action": "play_all_treasures"}'
    python scripts/interactive_play.py '{"action": "buy", "card_id": "sigil"}'
    python scripts/interactive_play.py '{"action": "skip_action"}'
    python scripts/interactive_play.py '{"action": "end_turn"}'
    python scripts/interactive_play.py '{"action": "discard_selection", "card_ids": ["shard"]}'
    python scripts/interactive_play.py '{"action": "gain_selection", "card_id": "seal"}'
"""

import json
import sys
import urllib.request
import urllib.error
import argparse


BRIDGE = "http://127.0.0.1:8765"


def api_get(path: str, timeout: float = 310.0) -> dict:
    with urllib.request.urlopen(f"{BRIDGE}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def api_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BRIDGE}{path}", data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def print_state(state: dict):
    me = state.get("me", {})
    ctx = state.get("context", {})
    eg = state.get("endgame", {})
    supply = state.get("supply", {})

    print("=" * 60)
    print(f"[PHASE] {state.get('phase')}  "
          f"{'[終盤]' if eg.get('is_endgame') else '[序盤]'}  "
          f"VP山残{eg.get('province_remaining')}  空山{eg.get('empty_piles')}")

    if ctx:
        print(f"[CONTEXT] reason={ctx.get('reason')}  {ctx.get('description', '')}")
        pa = ctx.get("pending_action") or {}
        if pa:
            print(f"[PENDING] {pa}")

    if me:
        print(f"[ME] coins={me.get('coins',0)}  actions={me.get('actions',0)}  "
              f"buys={me.get('buys',0)}  VP={me.get('vp',0)}")
        hand = me.get("hand", [])
        print(f"[HAND] ({len(hand)}枚)")
        for c in hand:
            print(f"  {c['id']:12s} [{c.get('type','?'):7s}] cost={c.get('cost',0)}  "
                  f"{c.get('name_en', c['id'])} - {c.get('effects_text','')[:50]}")

    for opp in state.get("opponents", []):
        print(f"[OPP] {opp['name']}  手札{opp['hand_count']}枚  "
              f"デッキ{opp['deck_count']}枚  VP{opp['vp']}")

    print("[SUPPLY]")
    for cid, info in sorted(supply.items(), key=lambda x: (x[1].get("type",""), x[1].get("cost",0))):
        print(f"  {cid:12s} [{info.get('type','?'):7s}] cost={info.get('cost',0)}  "
              f"残{info['count']:2d}枚  {info.get('effects_text','')[:45]}")

    log = state.get("log", [])
    if log:
        print("[LOG]")
        for entry in log[-5:]:
            print(f"  {entry}")

    print("=" * 60)
    print()
    print("次のコマンド例:")
    print('  python scripts/interactive_play.py \'{"action": "skip_action"}\'')
    print('  python scripts/interactive_play.py \'{"action": "play_all_treasures"}\'')
    print('  python scripts/interactive_play.py \'{"action": "buy", "card_id": "<card_id>"}\'')
    print('  python scripts/interactive_play.py \'{"action": "end_turn"}\'')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", default="http://127.0.0.1:8765")
    parser.add_argument("action_json", nargs="?", default=None,
                        help="送信するアクション JSON（省略時は /wait のみ）")
    args = parser.parse_args()

    global BRIDGE
    BRIDGE = args.bridge

    # ブリッジ接続確認
    try:
        st = api_get("/status", timeout=5)
    except Exception as e:
        print(f"[ERROR] bridge に接続できません: {e}")
        sys.exit(1)

    # ゲーム終了済みチェック
    if st.get("game_over"):
        print("[GAME OVER] ゲームはすでに終了しています")
        sys.exit(0)

    # アクション送信（引数がある場合）
    if args.action_json:
        try:
            action = json.loads(args.action_json)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON パースエラー: {e}")
            sys.exit(1)

        try:
            result = api_post("/action", action)
            print(f"[SENT] {action}")
        except Exception as e:
            print(f"[ERROR] アクション送信失敗: {e}")
            sys.exit(1)

    # /wait で次の手番を待つ
    print("[WAIT] 手番を待機中...")
    try:
        state = api_get("/wait", timeout=310)
    except urllib.error.HTTPError as e:
        if e.code == 408:
            print("[WAIT] タイムアウト。再度実行してください。")
        else:
            print(f"[ERROR] HTTPエラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # ゲーム終了
    if state.get("game_over"):
        print()
        print("=" * 60)
        print("===== GAME OVER =====")
        for s in sorted(state.get("scores", []), key=lambda x: -x["vp"]):
            print(f"  {s['name']}: {s['vp']} VP")
        print("=" * 60)
        sys.exit(0)

    print_state(state)


if __name__ == "__main__":
    main()
