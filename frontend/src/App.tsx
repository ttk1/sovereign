import { useGameState } from './hooks/useGameState'
import { Lobby } from './components/Lobby/Lobby'
import { WaitingRoom } from './components/WaitingRoom/WaitingRoom'
import { GameBoard } from './components/Game/GameBoard'

export function App() {
  const {
    screen,
    gameState,
    playerId,
    toast,
    playerName,
    setPlayerName,
    getCard,
    joinGame,
    send,
  } = useGameState()

  return (
    <>
      {screen === 'lobby' && (
        <Lobby
          playerName={playerName}
          onNameChange={setPlayerName}
          onJoinGame={joinGame}
        />
      )}

      {screen === 'waiting' && gameState && (
        <WaitingRoom
          gameState={gameState}
          playerId={playerId}
          onStart={() => send({ action: 'start' })}
        />
      )}

      {screen === 'game' && gameState && (
        <GameBoard
          gameState={gameState}
          playerId={playerId}
          getCard={getCard}
          send={send}
        />
      )}

      <div className={`toast ${toast ? 'show' : ''}`}>
        {toast}
      </div>
    </>
  )
}
