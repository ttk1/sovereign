# Sovereign

某デッキ構築型カードゲームライクなゲームのサーバーです。

## セットアップ

### 必要なもの

- Docker + Docker Compose

### 起動

```bash
docker compose up --build
```

ブラウザで `http://localhost:8000` にアクセス。

コードを編集するとサーバーがホットリロードされます。

### 停止

```bash
docker compose down
```

## 友人と遊ぶ場合

同一LAN内なら `http://<あなたのIPアドレス>:8000` を共有してください。

インターネット越しにプレイする場合は ngrok や Cloudflare Tunnel などのトンネリングサービスを使います。

```bash
# ngrok の例
ngrok http 8000
```

## ファイル構成

```
sovereign/
├── server.py          # FastAPI サーバー（REST + WebSocket）
├── game_engine.py     # ゲームロジック
├── data/
│   └── cards.json     # カード定義（差し替え可能）
├── static/
│   └── index.html     # プレイ用 UI
├── scripts/
│   ├── bot.py         # ハードコード戦略ボット（--ai フラグで Claude API 使用可）
│   ├── bridge.py      # AI エージェント向け WebSocket↔HTTP 橋渡しサーバー
│   └── claude_play.py # Claude Code がプレイするサンプル実装
├── pyproject.toml
└── docker-compose.yml
```

## カードのカスタマイズ

`data/cards.json` を編集することで、カードの名称・効果・見た目をカスタマイズできます。

### カード定義の例

```json
{
  "id": "smithy",
  "name": "巡察使",
  "name_en": "Inspector General",
  "type": "action",
  "cost": 4,
  "description": "帝国全土を巡察し、広く情報を集める。+3 カードを引く, +1 購入",
  "icon": "🧭",
  "effects": [
    {"type": "draw", "amount": 3},
    {"type": "buy", "amount": 1}
  ]
}
```

### サポートされるエフェクト

| type | 説明 | amount |
|------|------|--------|
| `draw` | カードを引く | 枚数 |
| `action` | アクション追加 | 回数 |
| `buy` | 購入追加 | 回数 |
| `coin` | コイン追加 | 枚数 |
| `attack_discard_to` | 他プレイヤーの手札を減らす | 残す枚数 |
| `discard_draw` | 捨てて同数引く | 0 |
| `gain_card_up_to` | コスト以下のカードを獲得 | 最大コスト |

### リアクション

```json
"reaction": "block_attack"
```

手札にこの属性を持つカードがある場合、攻撃を自動的にブロックします。

## ゲームルール

1. 各プレイヤーは初期デッキ（銅片7枚 + 農地3枚）で開始
2. 毎ターン5枚ドロー
3. **アクションフェーズ**: アクションカードを使用（初期1回）
4. **購入フェーズ**: 財宝カードを出してコインでサプライからカードを購入
5. **クリーンアップ**: 手札・場のカードをすべて捨て札にし、5枚ドロー
6. 王領（province）が無くなるか、サプライの3山が空になったらゲーム終了
7. 勝利点が最も多いプレイヤーの勝ち

---

## AI エージェントでプレイする

ゲームサーバーは WebSocket で通信しますが、AI エージェント（Claude Code、GitHub Copilot、OpenAI Codex など）が扱いやすいよう、**HTTP 長ポーリング**で橋渡しする仕組みを用意しています。

### アーキテクチャ

```
[ゲームサーバー :8000] <--WebSocket--> [bridge.py :8765] <--HTTP--> [AI エージェント]
```

- **bridge.py** がゲームサーバーに WebSocket 接続し、HTTP サーバーを同時に立ち上げます
- AI エージェントは `GET /wait` で自分の手番が来るまでブロック待機し、状態を受け取ります
- `POST /action` でアクションを送信します

### HTTP API リファレンス

| メソッド | エンドポイント | 説明 |
|--------|------------|------|
| `GET` | `/status` | 現在の接続状態・フェーズを返す（ブロックしない） |
| `GET` | `/wait?timeout=300` | 自分の応答が必要になるまでブロック（long-poll）、状態を返す |
| `POST` | `/action` | アクションを送信する |

#### `/wait` のレスポンス形式

```json
{
  "phase": "action",
  "current_player_name": "Claude",
  "context": {
    "reason": "my_turn",
    "phase": "action",
    "description": "自分のターン（actionフェーズ）"
  },
  "me": {
    "name": "Claude",
    "hand": [
      {"id": "copper", "name_en": "Shard", "type": "treasure", "cost": 0, "description": "+1 コイン"},
      {"id": "militia", "name_en": "Dominion Edict", "type": "action", "cost": 5, "description": "..."}
    ],
    "coins": 0,
    "actions": 1,
    "buys": 1,
    "vp": 3
  },
  "opponents": [
    {"name": "Player1", "hand_count": 5, "deck_count": 7, "vp": 0}
  ],
  "supply": {
    "gold": {"name_en": "Sigil", "count": 28, "cost": 6, "type": "treasure"},
    "province": {"name_en": "Realm", "count": 8, "cost": 8, "type": "victory"}
  },
  "endgame": {
    "province_remaining": 8,
    "empty_piles": 0,
    "is_endgame": false
  },
  "log": ["Claude のターンです", "..."]
}
```

`context.reason` の値:

| reason | 説明 |
|--------|------|
| `my_turn` | 自分のターン（action / buy フェーズ） |
| `discard` | 覇権布告（militia）による強制捨て札 |
| `cellar` | 密偵網（cellar）による任意捨て札 |
| `gain` | 勅許工房（workshop）によるカード獲得選択 |

#### `/action` のリクエスト形式

```json
// アクションカードを使う
{"action": "play_action", "card_id": "militia"}

// アクションをスキップ
{"action": "skip_action"}

// 手札の財宝を全て出す
{"action": "play_all_treasures"}

// カードを購入する
{"action": "buy", "card_id": "gold"}

// ターン終了
{"action": "end_turn"}

// 捨て札を選択（militia / cellar）
{"action": "discard_selection", "card_ids": ["copper", "estate"]}

// 獲得カードを選択（workshop）
{"action": "gain_selection", "card_id": "silver"}
```

### セットアップ手順

**1. ゲームサーバーを起動**

```bash
docker compose up
```

**2. ゲームを作成**

```bash
GAME_ID=$(curl -s -X POST http://localhost:8000/api/games | python -c "import sys,json; print(json.load(sys.stdin)['game_id'])")
echo "Game ID: $GAME_ID"
```

**3. bridge.py を起動**（コンテナ内で実行）

```bash
# Claude 側（自分がゲームを開始しない場合）
docker compose exec -d app python scripts/bridge.py $GAME_ID --name Claude --port 8765

# Claude 側（自分がゲームを開始する場合）
docker compose exec -d app python scripts/bridge.py $GAME_ID --name Claude --port 8765 --start
```

**4. 相手が参加してゲームを開始**

ブラウザで `http://localhost:8000` を開き、ゲームIDを入力して参加 → スタート。

**5. AI エージェントがプレイするループを実装**

```python
import urllib.request, json

BRIDGE = "http://127.0.0.1:8765"

def wait():
    with urllib.request.urlopen(f"{BRIDGE}/wait", timeout=310) as r:
        return json.loads(r.read())

def act(body: dict):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BRIDGE}/action", data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

while True:
    state = wait()
    if state.get("game_over"):
        break

    # ここで AI エージェントが state を見て判断する
    action = your_ai_decide(state)   # ← AI の思考ロジック
    act(action)
```

### Claude Code でプレイする例

`scripts/claude_play.py` は Claude Code が `/wait` → 判断 → `/action` をループするサンプルです。

```bash
python scripts/claude_play.py --bridge http://127.0.0.1:8765
```

### GitHub Copilot / OpenAI Codex などでプレイする例

`/wait` エンドポイントの JSON を読み込んで、LLM に渡すプロンプトを構築し、返答をパースして `/action` に送るだけです。

```python
import openai, json, urllib.request

client = openai.OpenAI()

def decide_with_openai(state: dict) -> dict:
    prompt = f"""
You are playing a deck-building card game called Sovereign.
Current state: {json.dumps(state, ensure_ascii=False, indent=2)}

Respond with a single JSON action object only. Examples:
{{"action": "play_action", "card_id": "militia"}}
{{"action": "skip_action"}}
{{"action": "play_all_treasures"}}
{{"action": "buy", "card_id": "gold"}}
{{"action": "end_turn"}}
{{"action": "discard_selection", "card_ids": ["copper"]}}
{{"action": "gain_selection", "card_id": "silver"}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)
```

### Copilot（VS Code 拡張）でインタラクティブにプレイする

Copilot Chat に以下を貼り付けて手番ごとに判断させることもできます：

```
GET http://127.0.0.1:8765/wait の結果が以下です。次の手を JSON で答えてください。
（レスポンスをここに貼り付ける）
```

---

## ハードコード戦略ボット（scripts/bot.py）

AI エージェントを使わずにボット対戦したい場合はこちら。

```bash
# ボット同士で対戦
GAME_ID=$(curl -s -X POST http://localhost:8000/api/games | python -c "import sys,json; print(json.load(sys.stdin)['game_id'])")

docker compose exec -d app python scripts/bot.py $GAME_ID --name BotA
docker compose exec app python scripts/bot.py $GAME_ID --name BotB --start
```

### Claude API を使った戦略判断（--ai フラグ）

`ANTHROPIC_API_KEY` を設定すれば Claude API（Haiku）が各手番を判断します。

```bash
docker compose exec -e ANTHROPIC_API_KEY=sk-ant-... app \
  python scripts/bot.py $GAME_ID --name Claude --ai --start
```
