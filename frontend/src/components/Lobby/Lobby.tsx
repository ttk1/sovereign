import { useState, useEffect, useCallback } from 'react'
import { createGame, listGames } from '../../api'
import type { RoomInfo } from '../../types'
import styles from './Lobby.module.css'

interface LobbyProps {
  playerName: string
  onNameChange: (name: string) => void
  onJoinGame: (gameId: string) => void
}

export function Lobby({ playerName, onNameChange, onJoinGame }: LobbyProps) {
  const [roomId, setRoomId] = useState('')
  const [rooms, setRooms] = useState<RoomInfo[]>([])

  const refreshRooms = useCallback(async () => {
    try {
      const data = await listGames()
      setRooms(data)
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    refreshRooms()
  }, [refreshRooms])

  const handleJoinOrCreate = async () => {
    const name = playerName.trim() || 'Player'
    onNameChange(name)
    let rid = roomId.trim()

    if (!rid) {
      const data = await createGame()
      rid = data.game_id
    }

    onJoinGame(rid)
  }

  return (
    <div className={styles.lobby}>
      <div className={styles.card}>
        <h1 className={styles.title}>👑 Sovereign</h1>
        <p className={styles.subtitle}>デッキ構築型カードゲーム</p>

        <div className={styles.formGroup}>
          <label className={styles.label}>プレイヤー名</label>
          <input
            type="text"
            className={styles.input}
            value={playerName}
            onChange={(e) => onNameChange(e.target.value)}
            placeholder="名前を入力"
            maxLength={20}
          />
        </div>

        <div className={styles.formGroup}>
          <label className={styles.label}>ルームID（参加する場合）</label>
          <input
            type="text"
            className={styles.input}
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
            placeholder="空欄で新規作成"
          />
        </div>

        <div className="btn-row">
          <button className="btn btn-primary" onClick={handleJoinOrCreate}>
            参加 / 作成
          </button>
          <button className="btn btn-secondary" onClick={refreshRooms}>
            ルーム一覧を更新
          </button>
        </div>

        <div className={styles.roomList}>
          <h3 className={styles.roomListTitle}>公開ルーム</h3>
          {rooms.length === 0 ? (
            <span className={styles.dimText}>ルームがありません</span>
          ) : (
            rooms.map((r) => (
              <div key={r.game_id} className={styles.roomItem}>
                <span>
                  <span className={styles.roomId}>{r.game_id}</span>
                  {' '}({r.players.length}人{r.started ? ' - 進行中' : ''})
                </span>
                {!r.started && (
                  <button
                    className="btn btn-small btn-primary"
                    onClick={() => {
                      setRoomId(r.game_id)
                      onJoinGame(r.game_id)
                    }}
                  >
                    参加
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
