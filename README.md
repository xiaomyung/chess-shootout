# chess-pygame

A full-featured chess game built with [pygame](https://www.pygame.org/).
Hot-seat play, drag-and-drop or click-to-move, premoves, annotations,
clocks, PGN auto-save and review, and an authoritative online server for
two-player matches.

## Features

- Complete chess rules engine (castling, en passant, promotion, threefold
  repetition, fifty-move rule, insufficient material).
- Drag-and-drop or click-to-move input; right-click annotations
  (highlights and arrows).
- Premove queueing (chess.com-style) with pseudo-legal validation,
  bouncing chains, and brighter chain-tip highlight.
- Time controls with increment, board flip, undo, resign, draw
  agreement; clock pocket reddens below 10 % and the heartbeat fades in.
- **PGN auto-save** to `games/<prefix>-YYYYMMDD-HHMMSS.pgn` (`local`,
  `bot`, or `online`); the result modal has an **Open PGN** button that
  launches the file in your OS default editor (`xdg-open` / `open` /
  `os.startfile`).
- **From FEN** start option in the main menu: paste any valid FEN to
  start a single-screen game from that position.
- **Help modal** (right-panel `?` button or `?` hotkey) lists every
  shortcut.
- Captured-piece graveyard and material balance per side.
- Master volume slider with an audio panel — value persisted in `.env`.
- Online play: authoritative FastAPI server, animated reconnect overlay,
  rematch / takeback / draw flows, crash-log capture for bug reports.

## Requirements

- Python `>=3.12,<3.13` (pinned in `pyproject.toml`; pygame's 3.14 wheel
  ships without `pygame.mixer`).
- No external runtime dependencies — every audio asset ships
  pre-encoded as `.ogg`, so `ffmpeg` is **not** required.

## Install

The project uses `pyproject.toml`. Two flavours of install:

| Goal | Command |
|---|---|
| **Just play the game** | `pip install -e .` |
| **Run tests / contribute** | `pip install -e ".[dev]"` |

`-e` means editable: pip installs the dependencies and points at the
cloned source tree, so `python main.py` keeps working as you edit. The
`[dev]` extra adds pytest + xdist + asyncio + httpx — none of which a
player needs.

**You need Python 3.12 specifically.** Newer Python versions ship pygame
wheels without `pygame.mixer` (no audio); older versions miss syntax
the codebase uses. Check with `python3.12 --version` before continuing.

### Linux

The recommended path on any Linux is [`pyenv`](https://github.com/pyenv/pyenv) —
distro Python packages drift between releases, but pyenv guarantees a
matching 3.12.x. Skip to your distro's "native" block only if you know
the package version maps to 3.12.

#### Universal (any Linux, recommended)

```bash
curl https://pyenv.run | bash       # one-time; follow shell-rc instructions printed at the end
pyenv install 3.12
pyenv shell 3.12
python --version                    # Python 3.12.x

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python -m venv .venv
source .venv/bin/activate
python --version                    # Python 3.12.x — confirms the venv inherited it
pip install -e .                    # players
# pip install -e ".[dev]"           # contributors
python main.py
```

#### Native packages (when they happen to ship 3.12)

| Distro | Default version | If 3.12 not the default |
|---|---|---|
| Arch (rolling) | currently `python` *may* be 3.12.x — check `python --version` first | use pyenv |
| Ubuntu 24.04+ | `apt install python3.12 python3.12-venv` | — |
| Ubuntu 22.04 / 23.x | needs deadsnakes PPA (Ubuntu-only): `apt install software-properties-common && add-apt-repository ppa:deadsnakes/ppa && apt update && apt install python3.12 python3.12-venv` | — |
| Debian 12 (bookworm) | enable bookworm-backports, then `apt install -t bookworm-backports python3.12 python3.12-venv` — or use pyenv (simpler) | use pyenv |
| Fedora 39+ | `dnf install python3.12` | — |

Then the same venv steps as above, but with `python3.12 -m venv .venv`
instead of `python -m venv .venv`:

```bash
git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python3.12 -m venv .venv
source .venv/bin/activate
python --version                    # Python 3.12.x
pip install -e .
python main.py
```

### macOS

```bash
brew install python@3.12

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
python3.12 -m venv .venv
source .venv/bin/activate
python --version           # should print Python 3.12.x
pip install -e .
python main.py
```

### Windows (PowerShell)

```powershell
# Download Python 3.12.x from https://www.python.org/downloads/release/
# (tick "Add Python to PATH" during install). Don't use 3.13+.

git clone https://github.com/xiaomyung/chess-pygame.git
cd chess-pygame
py -3.12 -m venv .venv     # the `py` launcher picks 3.12 specifically
.venv\Scripts\Activate.ps1
python --version           # should print Python 3.12.x
pip install -e .
python main.py
```

## Hotkeys

| Key | Action |
|---|---|
| `F` | Flip board |
| `R` | Resign / promote to rook (when a promotion is pending) |
| `D` | Offer draw |
| `Q` / `B` / `N` | Promote (queen / bishop / knight) |
| `Ctrl+Z` | Undo (online: takeback request) |
| `←` / `→` | Step through review |
| `Home` / `End` | Jump to ply 0 / live |
| `?` | Open Help modal |
| `Esc` | Close the window |

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

`--client-uuid alice` is a debug shortcut: non-UUID4 aliases are coerced
into a deterministic UUID4 client-side so the server's UUID4 validator
still accepts them. Real clients get a UUID4 auto-generated on first
launch and persisted in `.env`.

Both clients pick **Online** mode in the start menu, choose time
control and side preference, click **Start Search**, accept
`localhost:8000` in the address modal. As soon as the second player
connects with the same time control, both clients see "Match found!"
for half a second and the game starts with the player's color at the
bottom.

### Settings (`.env`)

The client reads a `.env` at the repo root (gitignored). Copy
`.env.example` and fill in:

```
CHESS_SERVER_ADDR=localhost:8000
CHESS_NICKNAME=YourName
CHESS_CLIENT_UUID=          # auto-generated UUID4 on first launch
CHESS_LAST_MODE=             # auto-saved
CHESS_MASTER_VOLUME=0.70     # 0.0 – 1.0, in-game slider persists here
```

CLI flags `--client-uuid` and `--nickname` override `.env` for the
running process — handy for testing two clients on the same machine.

### In-game actions

- **Resign** at any time → opponent wins.
- **Draw** while it's your turn → opponent gets an Accept/Decline
  prompt; mutual draws auto-agree.
- **Undo** (= takeback) only directly after your own move (while the
  opponent is on the clock) → opponent prompted; on accept, one ply
  rolls back and the clock is restored.
- **Rematch** from the result modal → opponent prompted; on accept, the
  same room restarts with swapped colors. The series score (e.g.
  `1½ – ½`) shows in the right panel.

### Reconnection

Three layered recovery paths:

- **WS drops mid-game** (transient WiFi blip): client retries `/resume`
  every 2 s for up to 60 s. The opponent sees a "Reconnecting…" overlay
  and a yellow status dot. On success the game continues from the exact
  ply.
- **Client app restart** (you closed the window mid-game): on next
  launch the client probes `POST /reclaim {client_uuid}`; if the room
  is still alive the start menu shows a **Reconnect** button between
  Load PGN and Start Search.
- **Server restart** (server killed and brought back): when `/resume`
  fatals but `/healthz` is reachable, the client knows the room is gone
  and surfaces a dedicated modal — **"Server restarted — game ended"**
  with [New Search] / [Cancel]. New Search re-runs matchmake against
  your previous time control without bouncing through the start menu.

Server-side rooms are in-memory only (no DB), so a true server crash
loses the game state — but you go straight to a fresh search on click.

### Crash log capture

Unhandled exceptions write `crashlogs/YYYYMMDD-HHMMSS.txt` with the
traceback, app state, and an in-memory log buffer of the whole session.
`crashlogs/` is gitignored. Attach the file when reporting bugs.

### Deployment

See [deploy/README.md](deploy/README.md) for VPS setup with Caddy +
systemd.

## Running tests

```bash
pip install -e ".[dev]"
pytest tests -n 8 -q
```

~8 s under xdist for 1071 tests; ~25 s serial.

## License

MIT — see [LICENSE](LICENSE).
