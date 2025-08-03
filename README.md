# Network Chess Game

This is a Python-based multiplayer Chess game with a GUI client and a socket-based server.

## Project Structure

```

Chess
├── chess_server.py               # Server code
├── chess_client_gui
│   ├── assets                    # images 
│   ├── chess_gui_main.py         # Main GUI 
│   ├── gui_board.py              # GUI board 
│   ├── constants.py              # Constants 
│   └── network_handler.py        # Handles

````

## How to Run

### 1. Install Dependencies

Ensure you have Python 3 installed. Then install required packages:

```bash
pip install -r requirements.txt
````

### 2. Run the Server

```bash
python chess_server.py
```

The server will start and listen for client connections.

### 3. Run the Client

In a new terminal:

```bash
python chess_client_gui/chess_gui_main.py
```

You can run two clients to simulate a full 2-player match.

## Notes

* Ensure the server is running before starting any clients.
* The game uses sockets, so all clients and server must be on the same network or properly port-forwarded.
* Ensure you are running on correctly configured version of python, troubleshoot by `Run in dedicated terminal (VS Code)`.
---
Enjoy your game of Chess! ♟️
---