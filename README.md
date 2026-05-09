# chess-pygame

A full-featured local chess game built with [pygame](https://www.pygame.org/).
Hot-seat play, drag-and-drop or click-to-move, premoves, annotations, clocks,
PGN export and review.

## Features

- Complete chess rules engine (castling, en passant, promotion, threefold
  repetition, fifty-move rule, insufficient material)
- Drag-and-drop or click-to-move input
- Premove queueing (chess.com-style) with auto-fire on turn flip
- Right-click annotations: square highlights and arrows
- Time controls with increment, board flip, undo, resign, draw agreement
- PGN save and click-through review with arrow-key stepping
- Captured-piece graveyard and material balance per side
- Heartbeat audio when low on time

## Requirements

- Python 3.10 – 3.13 (3.14 has a pygame import bug; avoid)
- [`ffmpeg`](https://ffmpeg.org/) on `$PATH` (used by `pydub` for MP3 capture
  sounds)

## Launch guide

### Linux

```bash
# Arch
sudo pacman -S python ffmpeg
# Debian / Ubuntu
sudo apt install python3 python3-venv ffmpeg

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### macOS

```bash
brew install python ffmpeg

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Windows (PowerShell)

```powershell
# Install Python 3.12 from python.org (tick "Add to PATH")
# Install ffmpeg, e.g. via winget:
winget install Gyan.FFmpeg

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Online play

Two players, one server. The server is authoritative — it runs the same
engine code as the client and validates every move.

### Quick start (local)

```bash
# Terminal 1 — server (default port 8000)
python -m server

# Terminal 2 — first client
python main.py --client-uuid alice --nickname Alice

# Terminal 3 — second client
python main.py --client-uuid bob --nickname Bob
```

Both clients pick **Online** mode in the start menu, choose time control and
side preference, click **Start Game**, accept `localhost:8000` in the address
modal. As soon as the second player connects with the same time control,
both clients land in the game with the player's color at the bottom.

### Settings (`.env`)

The client reads a `.env` at the repo root (gitignored). Copy `.env.example`
and fill in:

```
CHESS_SERVER_ADDR=localhost:8000
CHESS_NICKNAME=YourName
CHESS_CLIENT_UUID=          # auto-generated on first launch
CHESS_LAST_MODE=             # auto-saved
```

CLI flags `--client-uuid` and `--nickname` override `.env` for the running
process — handy for testing two clients on the same machine.

### In-game actions

- **Resign** at any time → opponent wins.
- **Draw** while it's your turn → opponent gets an Accept/Decline prompt;
  mutual draws auto-agree.
- **Undo** (= takeback) only directly after your own move (while the
  opponent is on the clock) → opponent prompted; on accept, one ply rolls
  back and the clock is restored.
- **Rematch** from the result modal → opponent prompted; on accept, the
  same room restarts with swapped colors.

### Reconnection

WS drops mid-game (e.g., transient WiFi blip) trigger an automatic
`/resume` retry every 2 s for up to 60 s. The opponent sees a yellow status
dot. On success the game continues from the exact ply. Closing the client
process drops the in-memory session token — reconnection only handles
network blips, not crashes.

### Deployment

See [deploy/README.md](deploy/README.md) for VPS setup with Caddy + systemd.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests -n 8 -q
```

## License

MIT — see [LICENSE](LICENSE).
