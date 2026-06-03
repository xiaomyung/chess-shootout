# Chess Shootout

A full-featured chess game built with [pygame](https://www.pygame.org/) —
local hot-seat play, premoves, clocks, annotations, PGN auto-save and
review, plus an authoritative server for online two-player matches.

## Features

**Gameplay**
- Complete rules engine: castling, en passant, promotion, threefold
  repetition, fifty-move rule, insufficient material.
- Drag-and-drop or click-to-move; right-click highlights and arrows.
- chess.com-style premove queueing (pseudo-legal validation, bouncing chains).
- Time controls with increment, board flip, undo, resign, draw agreement.
- Start from any FEN, or play two-up on a single screen.
- Captured-piece graveyard with running material balance; master-volume
  slider persisted to `.env`.
- Help modal listing every shortcut (`?` or the right-panel button).

**PGN**
- Every game auto-saves to `games/<prefix>-YYYYMMDD-HHMMSS.pgn` (`local`,
  `bot`, or `online`).
- Load and review past games from the **History** menu; step through with
  the arrow keys.
- **Open PGN** in the result modal opens the file in your OS default app.

**Online**
- Authoritative FastAPI + WebSocket server that runs the same engine as the
  client and validates every move.
- Rematch (colors swap; the series score follows the player, not the color),
  takeback, draw offers, and **Give 15 sec** (tops up the opponent's clock,
  capped at the starting time).
- Live abort / abandon / reconnect countdowns in the player strips.
- Layered reconnection for WiFi blips, app restarts, and server restarts
  (see [Reconnection](#reconnection)).
- Crash-log capture for easy bug reports.

## Download

No Python needed — grab the file for your OS from the
[**Releases**](https://github.com/xiaomyung/chess-shootout/releases) page.

| OS | File | First run |
|----|------|-----------|
| **Windows 10/11** | `ChessShootout-<version>-Setup.exe` (installer, no admin) or `ChessShootout-<version>-Portable.exe` (portable) | Unsigned, so SmartScreen warns: **More info → Run anyway**. |
| **macOS** (Apple Silicon) | `ChessShootout-<version>.dmg` | Drag **Chess Shootout** to Applications. Unsigned, so first launch is blocked: **System Settings → Privacy & Security → Open Anyway**, or run `xattr -dr com.apple.quarantine /Applications/ChessShootout.app`. |
| **Linux** (incl. Arch) | `ChessShootout-<version>-x86_64.AppImage` | `chmod +x` it, then run. No install, no FUSE. |

Games, settings, and logs live in a per-user location (`%APPDATA%`,
`~/Library/Application Support`, `~/.local/share`); change the games folder
anytime from the in-app **Options** (gear, top-right of the menu). The Windows
**portable** build is the exception — it keeps everything in a `data/` folder
beside the executable, so the whole app stays self-contained.

> **Tip for the portable build:** since it creates a `data/` folder next to the
> `.exe`, give it its own folder before the first run — make a new directory
> (e.g. `ChessShootout/`, on a USB stick or anywhere), drop
> `ChessShootout-<version>-Portable.exe` inside, and launch it from there. That
> keeps the app and its data tidy in one place instead of scattering a `data/`
> folder into wherever you downloaded it.

## Play from source

Requires **Python 3.12** — and specifically 3.12: newer pygame wheels drop
`pygame.mixer` (no audio) and the code uses 3.12 syntax. There are no other
runtime dependencies — all audio ships as `.ogg`, so `ffmpeg` is not required.

Once you have 3.12:

```bash
git clone https://github.com/xiaomyung/chess-shootout.git
cd chess-shootout
python3.12 -m venv .venv          # Windows: py -3.12 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1
python --version                  # confirm 3.12.x
pip install -e .                  # add ".[dev]" for tests + linting
python -m chessshootout.main      # or just: chess-shootout
```

`-e` is an editable install: pip resolves dependencies but runs against your
working tree, so edits take effect with no reinstall.

### Getting Python 3.12

**Linux** — `pyenv` is the most reliable route, since distro packages drift:

```bash
curl https://pyenv.run | bash     # one-time; follow the shell-rc steps it prints
pyenv install 3.12
pyenv shell 3.12                  # `python3.12` now resolves for the venv step above
```

<details>
<summary>Native distro packages (when they happen to ship 3.12)</summary>

| Distro | Command |
|---|---|
| Arch (rolling) | often already 3.12 — check `python --version`, else use pyenv |
| Ubuntu 24.04+ | `sudo apt install python3.12 python3.12-venv` |
| Ubuntu 22.04 / 23.x | deadsnakes: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update && sudo apt install python3.12 python3.12-venv` |
| Debian 12 | enable bookworm-backports, or use pyenv (simpler) |
| Fedora 39+ | `sudo dnf install python3.12` |

</details>

**macOS** — `brew install python@3.12`

**Windows** — install 3.12.x from [python.org](https://www.python.org/downloads/)
(tick *Add Python to PATH*); the `py -3.12` launcher then selects it.

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

Two players, one server — authoritative, running the same engine as the client.

### Quick start (local)

```bash
python -m chessshootout.server                                      # terminal 1 (port 8000)
python -m chessshootout.main --client-uuid alice --nickname Alice   # terminal 2
python -m chessshootout.main --client-uuid bob   --nickname Bob     # terminal 3
```

`--client-uuid alice` is a debug shortcut: any non-UUID4 alias is coerced to
a deterministic UUID4 client-side so the server's validator accepts it. Real
clients auto-generate and persist a UUID4 on first launch.

In each client pick **Online**, choose time control and side, hit **Start
Search**, and confirm the server address (`<ip>` defaults to port 8000, or
`<ip>:<port>`; `localhost` for local play). When a second player joins with
the same time control, both see "Match found!" and the game begins.

### Settings (`.env`)

The client reads a gitignored `.env` at the repo root — copy `.env.example`:

```
CHESS_SERVER_ADDR=localhost:8000
CHESS_NICKNAME=YourName
CHESS_CLIENT_UUID=          # auto-generated UUID4 on first launch
CHESS_LAST_MODE=            # auto-saved
CHESS_MASTER_VOLUME=0.70    # 0.0–1.0; the in-game slider writes here
```

`--client-uuid` and `--nickname` override `.env` for a single run (handy for
two clients on one machine). The games folder is set from in-app **Options**
and persisted as `CHESS_DATA_DIR`.

### In-game actions

- **Resign** — opponent wins.
- **Draw** (on your turn) — opponent gets Accept/Decline; mutual offers auto-agree.
- **Undo / takeback** — only right after your own move, while the opponent is
  on the clock; on accept, one ply rolls back and the clocks restore.
- **Give 15 sec** — adds 15 s to the opponent's clock, capped at the starting
  time control (debounced against double-clicks).
- **Rematch** (from the result modal) — the same room restarts with swapped
  colors; the series score follows the players, not the colors.

### Reconnection

Three layered recovery paths:

- **WS drops mid-game** (WiFi blip) — the client retries `/resume` every 2 s
  for up to 60 s. The opponent sees a "Reconnecting…" overlay, a yellow status
  dot, and an `Abandon in …` countdown; you see `Reconnect in …`. Desync is
  caught two ways — every move/takeback carries a `ply` counter, and the server
  emits a periodic `state_sync` beacon (~2.5 s) — so even a move lost with no
  follow-up message to react to is detected and resynced via `/resume` within
  seconds. Both players see a resync toast while it resolves.
- **Client app restart** — on next launch the client probes `POST /reclaim`;
  if the room is still alive, a **Reconnect** button appears in the start menu.
- **Server restart** — when `/resume` fails but `/healthz` is reachable, the
  client shows **"Server restarted — game ended"** with New Search / Cancel;
  New Search re-matches against your previous time control directly.

Rooms are in-memory only (no DB), so a true server crash loses game state —
but New Search starts a fresh game in one click.

### Crash logs

Unhandled exceptions write `crashlogs/YYYYMMDD-HHMMSS.txt` (traceback, app
state, and the whole-session log buffer). `crashlogs/` is gitignored — attach
the file when reporting a bug.

### Deployment

See [deploy/README.md](deploy/README.md) for single-VPS systemd setup — the
server listens directly on a public TCP port; no TLS, DNS, or reverse proxy.

## Development

Install the dev extra, then run the same checks CI does:

```bash
pip install -e ".[dev]"
pytest tests -n 8 -q                            # ~12 s for 1331 tests (~25 s serial)
pylama chessshootout tests                      # pycodestyle + pyflakes; exits 0 when clean
```

Both gate merges to `master` (the `test` and `lint` jobs), so a green local
run means the PR checks will pass.

### Releasing

Releases are built by CI on a version tag — merging to `master` builds nothing.

```bash
git tag -a v1.2.0 -m "Chess Shootout 1.2.0"   # v1.2.0-rc1 for a pre-release
git push origin v1.2.0
```

The tagged build runs the test suite, then builds all three OSes and stamps the
version (taken from the tag) into every artifact filename, the Windows
installer, the macOS bundle, and the in-app footer, before assembling a
**draft** GitHub Release. A hyphen in the tag marks it a pre-release. Review the
four artifacts, then **Publish**. No version is hardcoded anywhere — the tag is
the single source of truth.

## License

**Source available, not open source.** Because it forbids commercial use, this
project is *not* an OSI "open source" license — please don't call it that.

- **Code** — [PolyForm Noncommercial License 1.0.0](LICENSE). Read, run, modify,
  fork, and share it for any **non-commercial** purpose. You may **not** sell it
  or use it (or parts of it) commercially.
- **Original assets** (piece art, icons, and any sounds authored for the
  project) — [**CC BY-NC 4.0**](LICENSE-CC-BY-NC-4.0.txt): reuse with credit,
  non-commercial only.
- **Bundled third-party assets** (fonts, sound effects, emoji) keep their own
  licenses — see [ATTRIBUTION.md](ATTRIBUTION.md).
- **v1.0.0** was released under the **MIT License** and stays MIT; the terms
  above apply from **v2.0.0** onward.

"Non-commercial" is meant generously: personal/hobby use, education, clubs,
streaming/videos, and free forks that take donations are all fine — only selling
or charging is off-limits. Running your own server for non-commercial play is
fine; the online service operated by the author is not part of this grant and
access to it is at the author's discretion.

**"Chess Shootout™"** is a trademark of the author — forks and derivatives must
use a different name and not imply endorsement.

Contributions are welcome under the terms in [CONTRIBUTING.md](CONTRIBUTING.md).
