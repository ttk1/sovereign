"""
Sovereign - Server
デッキ構築型カードゲーム「Sovereign」のサーバー。

Usage:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import os
import uuid
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from game_engine import Game, CardData, Phase

# ── Load card data ──────────────────────────────────────────────
ROOT = Path(__file__).parent

def _resolve_card_path() -> Path:
    """
    カードファイルのパスを解決する。
    環境変数 CARDS でファイル名またはフルパスを指定可能。

    例:
        CARDS=cards_decktop.json   → data/cards_decktop.json
        CARDS=/path/to/my.json     → そのまま使用
    """
    env = os.environ.get("CARDS")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = ROOT / "data" / p
        return p
    return ROOT / "data" / "cards.json"

CARD_DATA_PATH = _resolve_card_path()

def load_card_data(path: Path = CARD_DATA_PATH) -> CardData:
    with open(path, "r", encoding="utf-8") as f:
        return CardData(json.load(f))

card_data = load_card_data()
print(f"[server] cards: {CARD_DATA_PATH}")

# ── App ─────────────────────────────────────────────────────────
app = FastAPI(title="Sovereign")

# ── Game rooms ──────────────────────────────────────────────────
games: dict[str, Game] = {}
connections: dict[str, dict[str, WebSocket]] = {}  # game_id -> {player_id: ws}


# ── REST API ────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/cards")
async def get_cards():
    """Return all card definitions (for UI rendering)."""
    with open(CARD_DATA_PATH, encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.post("/api/games")
async def create_game(kingdom: Optional[list[str]] = None):
    """Create a new game room."""
    game_id = uuid.uuid4().hex[:8]
    game = Game(game_id, card_data, kingdom_cards=kingdom)
    games[game_id] = game
    connections[game_id] = {}
    return {"game_id": game_id}


@app.get("/api/games")
async def list_games():
    """List available games."""
    result = []
    for gid, g in games.items():
        result.append({
            "game_id": gid,
            "players": [{"id": p.id, "name": p.name} for p in g.players],
            "started": g.started,
            "phase": g.phase.value,
        })
    return result


@app.get("/api/games/{game_id}")
async def get_game(game_id: str, player_id: Optional[str] = None):
    game = games.get(game_id)
    if not game:
        raise HTTPException(404, "Game not found")
    return game.get_state(for_player_id=player_id)


# ── WebSocket ───────────────────────────────────────────────────

async def broadcast(game_id: str, exclude: Optional[str] = None):
    """Send updated game state to all connected players."""
    game = games.get(game_id)
    if not game:
        return
    conns = connections.get(game_id, {})
    for pid, ws in list(conns.items()):
        if pid == exclude:
            continue
        try:
            state = game.get_state(for_player_id=pid)
            await ws.send_json({"type": "state", "state": state})
        except Exception:
            pass


async def send_state(ws: WebSocket, game: Game, player_id: str):
    state = game.get_state(for_player_id=player_id)
    await ws.send_json({"type": "state", "state": state})


async def send_error(ws: WebSocket, message: str):
    await ws.send_json({"type": "error", "message": message})


@app.websocket("/ws/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await websocket.accept()

    game = games.get(game_id)
    if not game:
        await send_error(websocket, "ゲームが見つかりません")
        await websocket.close()
        return

    player_id = None

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "join":
                name = data.get("name", "Player")
                pid = data.get("player_id")
                if pid and any(p.id == pid for p in game.players):
                    # Reconnect
                    player_id = pid
                    player = next(p for p in game.players if p.id == pid)
                    player.connected = True
                    player.name = name
                else:
                    player_id = uuid.uuid4().hex[:8]
                    player = game.add_player(player_id, name)
                    if not player:
                        await send_error(websocket, "参加できません（満員またはゲーム進行中）")
                        continue

                connections[game_id][player_id] = websocket
                await websocket.send_json({
                    "type": "joined",
                    "player_id": player_id,
                    "game_id": game_id,
                })
                await broadcast(game_id)

            elif action == "start":
                if not player_id:
                    await send_error(websocket, "先にゲームに参加してください")
                    continue
                ok = game.start_game()
                if not ok:
                    await send_error(websocket, "ゲームを開始できません（2人以上必要）")
                    continue
                await broadcast(game_id)

            elif action == "play_action":
                card_id = data.get("card_id")
                result = game.play_action(player_id, card_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "play_treasure":
                card_id = data.get("card_id")
                result = game.play_treasure(player_id, card_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "play_all_treasures":
                result = game.play_all_treasures(player_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "buy":
                card_id = data.get("card_id")
                result = game.buy_card(player_id, card_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "skip_action":
                result = game.skip_action_phase(player_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "end_turn":
                result = game.end_turn(player_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "discard_selection":
                card_ids = data.get("card_ids", [])
                result = game.handle_discard_selection(player_id, card_ids)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

            elif action == "gain_selection":
                card_id = data.get("card_id")
                result = game.handle_gain_selection(player_id, card_id)
                if "error" in result:
                    await send_error(websocket, result["error"])
                else:
                    await broadcast(game_id)

    except WebSocketDisconnect:
        if player_id and game_id in connections:
            connections[game_id].pop(player_id, None)
            player = game._get_player(player_id)
            if player:
                player.connected = False
            await broadcast(game_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if player_id and game_id in connections:
            connections[game_id].pop(player_id, None)


# ── Static files ────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
