"""
Claude Code ↔ Sovereign ゲームサーバー 橋渡しサーバー。

Claude Code（または任意のHTTPクライアント）が長ポーリングで手番を待ち、
アクションを送信できるようにする。

Usage:
    python scripts/bridge.py <game_id> --name <name> [--start] [--port 8765]

Endpoints:
    GET  /status          ブリッジの現在状態を返す
    GET  /wait            自分の応答が必要になるまでブロック（long-poll）、状態を返す
    POST /action          アクションを送信する
         Body: {"action": "play_action", "card_id": "edict"} など
    POST /join_and_start  ゲームに参加し、オプションでスタートする（初期化用）
"""

import asyncio
import json
import argparse
import urllib.request
import websockets
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import threading


# ---- カード定義取得 ----

def fetch_cards(base_url: str) -> dict[str, dict]:
    with urllib.request.urlopen(f"{base_url}/api/cards") as resp:
        data = json.loads(resp.read())
    return {c["id"]: c for c in data.get("cards", [])}


# ---- ブリッジ状態 ----

class Bridge:
    def __init__(self):
        self.state: dict | None = None           # 最新のゲーム状態
        self.my_id: str | None = None            # 自分のプレイヤーID
        self.my_name: str | None = None          # 自分のプレイヤー名
        self.cards: dict[str, dict] = {}         # カード定義
        self.ws = None                           # WebSocket 接続
        self.pending_event = asyncio.Event()     # 応答が必要なとき set される
        self.pending_context: dict | None = None # 何を要求されているか
        self.action_queue: asyncio.Queue = asyncio.Queue()  # HTTP → WS へのアクション
        self.game_over = False
        self.error: str | None = None

    def needs_response(self, state: dict) -> tuple[bool, dict | None]:
        """
        現在の状態で自分が応答すべきかを判定する。
        戻り値: (応答が必要か, コンテキスト情報)
        """
        if not self.my_id:
            return False, None

        phase = state.get("phase")
        pa = state.get("pending_action") or {}
        current_player = state.get("current_player")

        # 覇権布告による強制捨て札（相手ターン中でも発生）
        if phase == "discard" and pa.get("target_player_id") == self.my_id:
            return True, {
                "reason": "discard",
                "phase": phase,
                "pending_action": pa,
                "description": f"覇権布告による強制捨て札（{pa.get('discard_to', 3)}枚まで）",
            }

        # 密偵網による任意捨て札（自分のターン）
        if phase == "cellar" and pa.get("player_id") == self.my_id:
            return True, {
                "reason": "cellar",
                "phase": phase,
                "pending_action": pa,
                "description": "密偵網による任意捨て札（同枚数引き直し）",
            }

        # 勅許工房によるカード獲得（自分のターン）
        if phase == "gain" and pa.get("player_id") == self.my_id:
            return True, {
                "reason": "gain",
                "phase": phase,
                "pending_action": pa,
                "description": f"勅許工房によるカード獲得（コスト{pa.get('max_cost', 4)}以下）",
            }

        # 自分のターン
        if current_player == self.my_id and phase in ("action", "buy"):
            return True, {
                "reason": "my_turn",
                "phase": phase,
                "pending_action": pa,
                "description": f"自分のターン（{phase}フェーズ）",
            }

        return False, None

    def _build_endgame(self, supply: dict) -> dict:
        province_id = self.province_card_id()
        province_remaining = supply.get(province_id, 0) if province_id else 0
        empty_piles = sum(1 for v in supply.values() if v <= 0)
        return {
            "province_remaining": province_remaining,
            "empty_piles": empty_piles,
            "is_endgame": province_remaining <= 4 or empty_piles >= 2,
        }

    def province_card_id(self) -> str | None:
        """最高コストの勝利点カードID（終了条件用）を返す。"""
        vids = [cid for cid, c in self.cards.items() if c.get("type") == "victory"]
        if not vids:
            return None
        return max(vids, key=lambda cid: self.cards[cid].get("cost", 0))

    def build_summary(self) -> dict:
        """Claude Code に渡す状態サマリを構築する。"""
        state = self.state
        if not state:
            return {"error": "状態未取得"}

        me = next((p for p in state.get("players", []) if p["id"] == self.my_id), None)
        opponents = [p for p in state.get("players", []) if p["id"] != self.my_id]
        supply = state.get("supply", {})

        hand_detail = []
        if me:
            for cid in me.get("hand", []):
                c = self.cards.get(cid, {})
                hand_detail.append({
                    "id": cid,
                    "name": c.get("name", cid),
                    "name_en": c.get("name_en", cid),
                    "type": c.get("type", "?"),
                    "cost": c.get("cost", 0),
                    "description": c.get("description", ""),
                })

        supply_detail = {}
        for cid, cnt in supply.items():
            if cnt > 0:
                c = self.cards.get(cid, {})
                supply_detail[cid] = {
                    "name": c.get("name", cid),
                    "name_en": c.get("name_en", cid),
                    "count": cnt,
                    "cost": c.get("cost", 0),
                    "type": c.get("type", "?"),
                    "description": c.get("description", ""),
                }

        opp_summary = []
        for p in opponents:
            opp_summary.append({
                "name": p["name"],
                "deck_count": p.get("deck_count", 0),
                "discard_count": p.get("discard_count", 0),
                "hand_count": p.get("hand_count", 0),
                "vp": p.get("vp", 0),
            })

        _, context = self.needs_response(state)

        return {
            "phase": state.get("phase"),
            "current_player_name": state.get("current_player_name"),
            "context": context,
            "me": {
                "id": me["id"] if me else None,
                "name": me["name"] if me else None,
                "hand": hand_detail,
                "coins": me.get("coins", 0) if me else 0,
                "actions": me.get("actions", 0) if me else 0,
                "buys": me.get("buys", 0) if me else 0,
                "deck_count": me.get("deck_count", 0) if me else 0,
                "discard_count": me.get("discard_count", 0) if me else 0,
                "vp": me.get("vp", 0) if me else 0,
            } if me else None,
            "opponents": opp_summary,
            "supply": supply_detail,
            "endgame": self._build_endgame(supply),
            "log": state.get("log", [])[-10:],
            "game_over": state.get("phase") == "game_over",
            "scores": state.get("scores", []),
        }


bridge = Bridge()
app = FastAPI(title="Sovereign Bridge")


# ---- HTTP エンドポイント ----

@app.get("/status")
async def status():
    """ブリッジの現在状態を返す（ブロックしない）。"""
    return {
        "connected": bridge.ws is not None,
        "my_id": bridge.my_id,
        "my_name": bridge.my_name,
        "game_over": bridge.game_over,
        "error": bridge.error,
        "current_phase": bridge.state.get("phase") if bridge.state else None,
        "current_player": bridge.state.get("current_player_name") if bridge.state else None,
    }


@app.get("/wait")
async def wait(timeout: float = 300.0):
    """
    自分の応答が必要になるまでブロック（long-poll）。
    応答が必要な状態になったら状態サマリを返す。
    """
    if bridge.game_over:
        return JSONResponse({"game_over": True, "scores": bridge.state.get("scores", []) if bridge.state else []})

    if bridge.error:
        raise HTTPException(500, bridge.error)

    # 現在すでに応答が必要な状態かチェック
    if bridge.state:
        needed, _ = bridge.needs_response(bridge.state)
        if needed:
            return JSONResponse(bridge.build_summary())

    # イベントをクリアして待機
    bridge.pending_event.clear()
    try:
        await asyncio.wait_for(bridge.pending_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(408, "タイムアウト：手番が来ませんでした")

    if bridge.game_over:
        return JSONResponse({"game_over": True, "scores": bridge.state.get("scores", []) if bridge.state else []})

    return JSONResponse(bridge.build_summary())


@app.post("/action")
async def post_action(body: dict):
    """
    アクションを送信する。
    例: {"action": "play_action", "card_id": "edict"}
         {"action": "skip_action"}
         {"action": "play_all_treasures"}
         {"action": "buy", "card_id": "sigil"}
         {"action": "end_turn"}
         {"action": "discard_selection", "card_ids": ["shard", "farmland"]}
         {"action": "gain_selection", "card_id": "seal"}
    """
    if not bridge.ws:
        raise HTTPException(503, "WebSocket 未接続")
    if bridge.game_over:
        raise HTTPException(400, "ゲームは終了しています")

    action = body.get("action")
    if not action:
        raise HTTPException(400, "action フィールドが必要です")

    await bridge.action_queue.put(body)
    return {"ok": True, "queued": body}


# ---- WebSocket ループ ----

async def ws_loop(game_id: str, name: str, do_start: bool, base_url: str):
    uri = f"ws://localhost:8000/ws/{game_id}"
    print(f"[bridge] connecting → {uri}")

    bridge.cards = fetch_cards(base_url)

    async with websockets.connect(uri) as ws:
        bridge.ws = ws

        async def send(data):
            await ws.send(json.dumps(data))
            print(f"[bridge] → {data}")

        # 参加
        await send({"action": "join", "name": name})

        # joined メッセージを受け取って player_id を保存
        msg = json.loads(await ws.recv())
        print(f"[bridge] ← {msg}")
        if msg.get("type") == "joined":
            bridge.my_id = msg["player_id"]
            bridge.my_name = name
            print(f"[bridge] joined as {name} (id={bridge.my_id})")

        # waiting state
        msg = json.loads(await ws.recv())
        print(f"[bridge] ← type={msg.get('type')}")
        if msg.get("type") == "state":
            bridge.state = msg["state"]

        # ゲーム開始
        if do_start:
            await send({"action": "start"})
            msg = json.loads(await ws.recv())
            if msg.get("type") == "state":
                bridge.state = msg["state"]
            print(f"[bridge] game started")

        print(f"[bridge] ready. HTTP endpoints available.")

        # メインループ：WS受信とHTTPからのアクション送信を並行処理
        async def recv_loop():
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "state":
                    bridge.state = msg["state"]
                    phase = bridge.state.get("phase")

                    if phase == "game_over":
                        bridge.game_over = True
                        bridge.pending_event.set()
                        print(f"[bridge] game over")
                        scores = bridge.state.get("scores", [])
                        for s in sorted(scores, key=lambda x: -x["vp"]):
                            print(f"  {s['name']}: {s['vp']} VP")
                        return

                    needed, ctx = bridge.needs_response(bridge.state)
                    if needed:
                        print(f"[bridge] 応答待ち: {ctx['description'] if ctx else ''}")
                        bridge.pending_context = ctx
                        bridge.pending_event.set()

                elif t == "error":
                    print(f"[bridge] ERROR: {msg.get('message')}")

        async def send_loop():
            while True:
                action = await bridge.action_queue.get()
                await send(action)

        await asyncio.gather(recv_loop(), send_loop())

        bridge.ws = None


# ---- エントリポイント ----

def run_bridge(game_id: str, name: str, do_start: bool, base_url: str, port: int):
    loop = asyncio.new_event_loop()

    # FastAPI を別スレッドで起動
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", loop="none")
    server = uvicorn.Server(config)

    def run_api():
        # FastAPI 用のイベントループを設定
        import asyncio as _asyncio
        _asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    # WebSocket ループをメインループで実行
    asyncio.set_event_loop(loop)

    # uvicorn を同じループで動かす
    async def run_all():
        ws_task = asyncio.create_task(
            ws_loop(game_id, name, do_start, base_url)
        )
        api_task = asyncio.create_task(server.serve())
        print(f"[bridge] HTTP server: http://0.0.0.0:{port}  (host: http://127.0.0.1:{port})")
        print(f"[bridge]   GET  /wait   → 手番を待つ（long-poll）")
        print(f"[bridge]   POST /action → アクションを送信")
        print(f"[bridge]   GET  /status → 現在状態")
        await asyncio.gather(ws_task, api_task)

    loop.run_until_complete(run_all())


def main():
    parser = argparse.ArgumentParser(description="Sovereign Claude Bridge")
    parser.add_argument("game_id", help="参加するゲームID")
    parser.add_argument("--name", default="Claude", help="プレイヤー名")
    parser.add_argument("--start", action="store_true", help="ゲームを開始する")
    parser.add_argument("--url", default="http://localhost:8000", help="サーバーURL")
    parser.add_argument("--port", type=int, default=8765, help="ブリッジHTTPサーバーのポート")
    args = parser.parse_args()

    run_bridge(args.game_id, args.name, do_start=args.start, base_url=args.url, port=args.port)


if __name__ == "__main__":
    main()
