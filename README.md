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

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests -n 8 -q
```

## License

MIT — see [LICENSE](LICENSE).
