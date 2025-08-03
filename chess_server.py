import socket
import threading
import chess
import uuid

HOST = "127.0.0.1"  # Standard loopback interface address (localhost)
PORT = 65432  # Port to listen on
MAX_SPECTATORS_PER_GAME = 5

active_games = {}  # Stores game_id: {board, players: {white, black}, spectators, turn}
waiting_players = []  # Queue for players looking for a game
lock = (
    threading.Lock()
)  # To protect shared resources like waiting_players and active_games


def generate_game_id():
    return str(uuid.uuid4())[:8]  # Short unique ID


def broadcast(game_id, message, exclude_conn=None):
    """Sends a message to all players and spectators in a game, optionally excluding one connection."""
    game = active_games.get(game_id)
    if not game:
        return

    # Send to players
    for color, player_conn in game["players"].items():
        if player_conn and player_conn != exclude_conn:
            try:
                player_conn.sendall(message.encode())
            except:  # Handle broken connections
                # Potentially remove player or end game if critical
                pass

    # Send to spectators
    for spec_conn in game["spectators"]:
        if spec_conn != exclude_conn:
            try:
                spec_conn.sendall(message.encode())
            except:  # Handle broken connections
                # Potentially remove spectator
                pass


def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.")
    player_game_id = None
    player_color = None
    is_spectator = False

    try:
        # Ask if player or spectator
        conn.sendall("Welcome! Play (P) or Spectate (S)? ".encode())
        choice = conn.recv(1024).decode().strip().upper()

        with lock:  # Protect access to waiting_players and active_games
            if choice == "P":
                if not waiting_players:
                    # This is the first player for a new game
                    game_id = generate_game_id()
                    player_game_id = game_id
                    player_color = "white"

                    active_games[game_id] = {
                        "board": chess.Board(),
                        "players": {"white": conn, "black": None},
                        "spectators": [],
                        "turn": "white",
                        "player_addrs": {"white": addr, "black": None},
                    }
                    waiting_players.append(game_id)
                    conn.sendall(
                        f"INFO:You are White. Game ID: {game_id}. Waiting for an opponent...\n".encode()
                    )
                    print(
                        f"[GAME {game_id}] Player {addr} is White. Waiting for Black."
                    )
                else:
                    # Join an existing waiting game
                    game_id = waiting_players.pop(0)
                    player_game_id = game_id
                    player_color = "black"

                    game = active_games[game_id]
                    game["players"]["black"] = conn
                    game["player_addrs"]["black"] = addr

                    conn.sendall(
                        f"INFO:You are Black. Game ID: {game_id}. Game starting with {game['player_addrs']['white']}!\n".encode()
                    )
                    if game["players"]["white"]:
                        game["players"]["white"].sendall(
                            f"INFO:Player {addr} (Black) has joined. Game starts!\n".encode()
                        )

                    print(
                        f"[GAME {game_id}] Player {addr} is Black. Game starts with {game['player_addrs']['white']}."
                    )
                    broadcast(game_id, f"BOARD:{game['board'].fen()}\n")
                    broadcast(game_id, f"TURN:{game['turn']}\n")

            elif choice == "S":
                is_spectator = True
                if not active_games:
                    conn.sendall(
                        "INFO:No active games to spectate. Try again later.\n".encode()
                    )
                    return

                games_list_str = "INFO:Active Games:\n"
                for gid, g_data in active_games.items():
                    white_player = g_data["player_addrs"]["white"]
                    black_player = g_data["player_addrs"]["black"]
                    status = "Waiting for Black" if not black_player else "In Progress"
                    games_list_str += f"  ID: {gid} - White: {white_player} vs Black: {black_player if black_player else 'N/A'} ({status})\n"
                games_list_str += "Enter Game ID to spectate: "
                conn.sendall(games_list_str.encode())

                spec_game_id_choice = conn.recv(1024).decode().strip()

                if spec_game_id_choice in active_games:
                    game = active_games[spec_game_id_choice]
                    if len(game["spectators"]) < MAX_SPECTATORS_PER_GAME:
                        game["spectators"].append(conn)
                        player_game_id = (
                            spec_game_id_choice  # Track which game they are watching
                        )
                        conn.sendall(
                            f"INFO:Spectating Game ID {spec_game_id_choice}. Board updates will follow.\n".encode()
                        )
                        conn.sendall(f"BOARD:{game['board'].fen()}\n")
                        conn.sendall(f"TURN:{game['turn']}\n")
                        print(
                            f"[SPECTATOR] {addr} is now spectating game {spec_game_id_choice}"
                        )
                    else:
                        conn.sendall(
                            "INFO:Spectator limit reached for this game.\n".encode()
                        )
                        return
                else:
                    conn.sendall("INFO:Invalid Game ID.\n".encode())
                    return
            else:
                conn.sendall("INFO:Invalid choice.\n".encode())
                return

        # Main game loop for the connected client
        while True:
            if player_game_id and player_game_id in active_games:
                game = active_games[player_game_id]
                if is_spectator:
                    # Spectators just receive, server doesn't expect input from them after initial setup
                    # However, we need to keep the connection alive or handle their disconnects
                    try:
                        # A simple way to check if spectator is still connected.
                        # Could send periodic pings or rely on recv to error out on disconnect.
                        conn.settimeout(60)  # Check every 60s
                        data = conn.recv(
                            1, socket.MSG_PEEK | socket.MSG_DONTWAIT
                        )  # Non-blocking peek
                        if not data and conn.fileno() == -1:  # Socket closed
                            break
                        conn.settimeout(None)  # Reset timeout
                    except socket.timeout:
                        continue  # No data, just timed out, continue spectating
                    except (
                        BlockingIOError
                    ):  # No data, not an error for non-blocking peek
                        pass
                    except Exception:  # Any other error, assume disconnect
                        break
                    threading.Event().wait(5)  # Wait a bit before checking again
                    continue

                # If it's this player's turn
                if (
                    game["players"].get(player_color) == conn
                    and game["turn"] == player_color
                ):
                    conn.sendall("YOUR_TURN:\n".encode())  # Prompt client

                data = conn.recv(1024).decode().strip()
                if not data:
                    print(
                        f"[DISCONNECTED] {addr} (Player: {player_color}, Game: {player_game_id})"
                    )
                    break  # Connection closed by client

                print(
                    f"[GAME {player_game_id}] Received from {addr} ({player_color}): {data}"
                )

                if data.startswith("MOVE:"):
                    if game["turn"] != player_color:
                        conn.sendall("INVALID_MOVE:Not your turn.\n".encode())
                        continue
                    if not game["players"]["white"] or not game["players"]["black"]:
                        conn.sendall(
                            "INVALID_MOVE:Opponent not connected yet.\n".encode()
                        )
                        continue

                    move_uci = data.split(":")[1]
                    try:
                        move = game["board"].parse_uci(move_uci)
                        if move in game["board"].legal_moves:
                            game["board"].push(move)
                            game["turn"] = (
                                "black" if player_color == "white" else "white"
                            )

                            broadcast(player_game_id, f"BOARD:{game['board'].fen()}\n")

                            game_over = False
                            result_message = ""
                            if game["board"].is_checkmate():
                                result_message = (
                                    f"GAME_OVER:Checkmate! Winner: {player_color}\n"
                                )
                                game_over = True
                            elif game["board"].is_stalemate():
                                result_message = "GAME_OVER:Stalemate! It's a draw.\n"
                                game_over = True
                            elif game["board"].is_insufficient_material():
                                result_message = (
                                    "GAME_OVER:Insufficient material! It's a draw.\n"
                                )
                                game_over = True
                            elif game["board"].is_seventyfive_moves():
                                result_message = (
                                    "GAME_OVER:75-move rule! It's a draw.\n"
                                )
                                game_over = True
                            elif game["board"].is_fivefold_repetition():
                                result_message = (
                                    "GAME_OVER:Fivefold repetition! It's a draw.\n"
                                )
                                game_over = True

                            if game_over:
                                broadcast(player_game_id, result_message)
                                print(
                                    f"[GAME {player_game_id}] Game Over. {result_message.strip()}"
                                )
                                # Clean up game after it ends
                                with lock:
                                    if player_game_id in active_games:
                                        del active_games[player_game_id]
                                break  # End client handler loop
                            else:
                                broadcast(
                                    player_game_id,
                                    f"INFO:Move {move_uci} by {player_color} was valid.\n",
                                )
                                broadcast(player_game_id, f"TURN:{game['turn']}\n")
                        else:
                            conn.sendall("INVALID_MOVE:Illegal move.\n".encode())
                    except ValueError:  # Invalid UCI
                        conn.sendall(
                            "INVALID_MOVE:Invalid move format (use UCI e.g., e2e4).\n".encode()
                        )
                    except Exception as e:
                        print(f"Error processing move: {e}")
                        conn.sendall("ERROR:Could not process move.\n".encode())

                elif data.startswith("CHAT:"):
                    chat_msg = data.split(":", 1)[1]
                    broadcast(
                        player_game_id,
                        f"CHAT:{player_color if player_color else 'Spectator'}({addr}): {chat_msg}\n",
                        exclude_conn=conn,
                    )
                    conn.sendall(f"CHAT:You: {chat_msg}\n".encode())  # Echo to self

                elif data.upper() == "QUIT":
                    conn.sendall("INFO:You have quit the game.\n".encode())
                    break

                else:
                    # Handle non-turn commands or just ignore
                    if game["turn"] != player_color:
                        conn.sendall(
                            "INFO:It's not your turn. Type 'CHAT:<your message>' to chat or 'QUIT'.\n".encode()
                        )

            elif player_game_id and player_game_id not in active_games:
                # Game might have ended and been cleaned up
                conn.sendall("INFO:The game session has ended.\n".encode())
                break
            elif not player_game_id and not is_spectator:
                # Player was waiting but game didn't start (e.g. server restarted before match)
                conn.sendall(
                    "INFO:Disconnected from lobby. Please try connecting again.\n".encode()
                )
                break

    except socket.error as e:
        print(f"[SOCKET ERROR] {addr}: {e}")
    except Exception as e:
        print(f"[ERROR] {addr}: {e}")
    finally:
        with lock:
            if player_game_id and player_game_id in active_games:
                game = active_games[player_game_id]
                if is_spectator:
                    if conn in game["spectators"]:
                        game["spectators"].remove(conn)
                        print(f"[SPECTATOR] {addr} left game {player_game_id}")
                else:  # It's a player
                    # Notify opponent about disconnection
                    opponent_color = "black" if player_color == "white" else "white"
                    opponent_conn = game["players"].get(opponent_color)
                    if opponent_conn:
                        try:
                            opponent_conn.sendall(
                                f"INFO:Opponent ({player_color}) disconnected. Game ended.\n".encode()
                            )
                        except:
                            pass  # Opponent might also be disconnected

                    # If a player disconnects, the game is typically over or forfeited
                    print(
                        f"[GAME END DUE TO DISCONNECT] Game {player_game_id} ended because {player_color} ({addr}) disconnected."
                    )
                    if (
                        player_game_id in active_games
                    ):  # Check again as it might be deleted by game_over
                        del active_games[player_game_id]

            # If the player was waiting and disconnected before game started
            for i, waiting_gid in enumerate(waiting_players):
                # Check if the disconnected player was the one waiting in this game_id slot
                if (
                    waiting_gid == player_game_id
                    and active_games.get(waiting_gid)
                    and active_games[waiting_gid]["players"]["white"] == conn
                ):
                    del waiting_players[i]
                    if (
                        waiting_gid in active_games
                    ):  # Also remove the partial game entry
                        del active_games[waiting_gid]
                    print(
                        f"[LOBBY] Player {addr} removed from waiting queue for game {waiting_gid}."
                    )
                    break

        conn.close()
        print(f"[CONNECTION CLOSED] {addr}")


def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(
        socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
    )  # Allow reuse of address
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"Chess server listening on {HOST}:{PORT}")

    while True:
        conn, addr = server_socket.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.daemon = True  # Allow main program to exit even if threads are running
        thread.start()


if __name__ == "__main__":
    start_server()
