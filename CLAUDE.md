# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

A virtualenv lives at `.venv/`. Use it directly:

- **Run the game:** `.venv/bin/python main.py`
- **Run all tests:** `.venv/bin/pytest tests -n 8 -q` (~5s under xdist; ~17s serial). `pytest-xdist` is in `requirements-dev.txt`.
- **Run one file or test:** `.venv/bin/pytest tests/test_castling.py -v`, `.venv/bin/pytest tests/test_san.py::test_user_promotion_game_disambiguation -v`
- **Smoke-test the frontend headlessly:** prefix with `SDL_VIDEODRIVER=dummy` and call `Frontend(w, h).draw_frame()`

`pytest.ini` sets `pythonpath = .` and `testpaths = tests`, so absolute imports (`from backend.backend import Backend`) work from anywhere.

## Architecture

Three layers, top-down:

1. **`pieces/`** — pure data. `PieceType`, `PieceColor`, `Piece`, `BACK_RANK`. No logic.
2. **`backend/`** — chess rules engine. `Backend` class + supporting dataclasses. No pygame, no UI.
3. **`frontend/`** — pygame UI. Owns a `Backend`, drives the event loop, renders.

`Frontend` and `Board` consume a `Match` (`backend/match.py`), which wraps a `Backend`. `Match` delegates the engine API and exposes `local_color` for player-color gating. Tests and direct mutations go through `match.backend.X` (or the `backend` property as an escape hatch on `Frontend`/`Board`/`RightMenu`). Production code reads/calls via `self.match.X`.

### Backend contract (the "public API" the frontend depends on)

`Backend` exposes: `new_game()`, `try_move(from, to)`, `promote(square, type)`, `undo()`, `is_game_over()`, `game_result()`, `legal_moves_from(square)`, `is_in_check(color)`, `current_turn()`, `piece_at(square)`. State fields: `state` (8×8), `turn`, `move_history`, `castling_rights`, `en_passant_target`, `halfmove_clock`, `position_counts`.

`game_result()` returns one of: `'white_wins'`, `'black_wins'`, `'draw_stalemate'`, `'draw_repetition'`, `'draw_fifty_move'`, `'draw_insufficient_material'`, or `None`. `'draw_agreement'` is frontend-only (set as `Frontend.manual_result`, not produced by the engine).

### The single per-ply transition: `_finalize_move`

This is the load-bearing helper. It runs **exactly once per completed ply**, called from either `try_move` (non-promotion path) or `promote()` — never both. It snapshots pre-move state into the `HistoryEntry`, advances castling rights / EP target / halfmove clock, switches the turn, hashes the new position into `position_counts`, computes `gives_check`/`gives_checkmate`, and appends `+`/`#` to `entry.san`. Anything that needs to happen "after a ply lands" goes here. **Hashing in two places will double-count the promotion ply** — don't.

### `HistoryEntry` & undo

`move_history: list[HistoryEntry]` (NOT `list[Move]`). Each entry stores the `Move` plus everything needed to undo it: pre-ply castling rights, EP target, halfmove clock, plus the `position_key_added` (so undo can decrement the repetition counter). A pending-promotion entry has `position_key_added = None` — that's the marker for "the ply hasn't been finalized yet."

`Move` is `@dataclass(frozen=True)`. `promote()` cannot mutate `entry.move.promoted_to` — it constructs a fresh `Move` and assigns to `entry.move` (the entry itself is mutable).

### SAN is built at move-time

Disambiguation (`Qdxg4`, `Q1d4`, …) requires the **pre-move** board state — once a move is applied, the rivals are gone. `_apply_*` methods compute SAN before any state mutation; `_finalize_move` appends `+`/`#` afterward. `frontend/pgn.py` is a thin reader of `entry.san`; it does NOT recompute SAN.

### Recursion guard in `_is_square_attacked`

Castling generation calls `_is_square_attacked` (path checks). Without care, that would walk back into `_pseudo_legal_moves` → `_castling_moves` → `_is_square_attacked` infinitely. The guard: `_is_square_attacked` special-cases KING attackers (direct `KING_OFFSETS` adjacency check), so it never calls `_pseudo_legal_moves` for a king. PAWN gets the same special-case treatment for a different reason (pawn forward-pushes are pseudo-legal but aren't attacks). **Don't simplify `_is_square_attacked` to "just call `_pseudo_legal_moves`" — it will recurse.**

### Frontend orchestration

`Frontend` owns: `Match`, `Board`, `RightMenu`, `ResultMenu`, `ConfirmModal`, `FilePicker`, `AudioPanel`, `StartMenu`. `_compute_layout` runs at startup and on `pg.VIDEORESIZE`; it computes rects + calls `set_rect` on each child. Each child's `set_rect` rebuilds its fonts (scale with rect width via `_factor` attributes). `Frontend.draw_frame` is called every frame; click events flow `file_picker` → `start_menu` → `confirm_modal` → `result_menu` → `right_menu` → `board`, in that priority. `pgn_review` and `Board.read_only` lock the board when a saved PGN is being reviewed (only the Menu and Flip right-menu buttons remain active).

`Frontend.manual_result` (resign / draw_agreement) lives separately from `backend.game_result()`. `current_result()` is the union; `result_text()` maps to `(title, reason)` for the modal.

### FIDE deviations to know about

- **EP target is included in the repetition key unconditionally** (FIDE-strict only includes it when an EP capture is actually legal). At most defers a threefold claim by one ply. Documented in `tests/test_repetition.py`.
- **K+B+B vs K is "sufficient"** in our auto-draw set — KBB v K can mate, so we don't auto-draw it (consistent with FIDE Article 5.2.2). Pinned in `tests/test_insufficient_material.py`.
- **`game_result()` ordering: mate/stalemate first**, then insufficient material, then repetition, then 50-move. Otherwise a checkmate that happens to leave insufficient material would be misreported as a draw.

### Test layout

`tests/helpers.py` exports `make_backend(piece_map, turn=WHITE, castling_rights=None, ep_target=None, halfmove_clock=0)` — bypasses `new_game()` and seeds `position_counts` with the constructed position. Single-letter shorthands (`K Q R B N P`, `WHITE BLACK`) and a `sq(row, col)` factory are also exported. `NO_CASTLING` is a shared all-False dict.

`test_perft.py` is the strongest single regression: `perft(3) == 8902` from the initial position validates move-gen + undo + finalize all round-trip cleanly across thousands of plies.

## Conventions

- **No comments in `backend/`, `frontend/`, `pieces/`, `main.py`, `paths.py`.** Names carry meaning. Comments are allowed (and welcomed) only in `tests/`.
- **Double quotes for all strings.** Single quotes only when the string contains `"`.
- **No docstrings outside tests/helpers.** The codebase does not use them.
- **Don't add fields/flags/branches "for future use."** Add them when the use lands.
- **`self.backend` is an escape hatch only.** Production code on `Frontend`/`Board`/`RightMenu` reads via `self.match.X`. The `backend` property exists for tests and direct engine mutations (`app.match.backend.turn = X` / `app.backend.X` work identically).
- **Esc only closes the window.** Don't bind Esc to dismiss modals, exit review mode, or any other in-game action.
- **In-app pygame modals only.** Don't use `tkinter` or system file dialogs — they're broken on the user's KDE/Wayland setup. Mirror `frontend/file_picker.py` / `frontend/confirm_modal.py`.

## Online plan

Pre-online architectural prereqs are **done** (commit `b6683c3`):

- ✅ `Match` layer (`backend/match.py`). The seam where `try_move` will become "send over WS, await ack, commit on ack."
- ✅ Player-color gating (`Match.local_color`, applied in `Board._try_select` / `_try_select_for_premove`).
- ✅ FEN serialization (`backend/fen.py` — `export_fen` / `apply_fen`).
- ✅ Game timer (`backend/clock.py`, integrated since earlier).
- ✅ PGN round-trip (`frontend/pgn.py` exporter + `frontend/pgn_load.py` parser + `Backend.apply_san`).

Remaining: clean-code skill pass, then **FastAPI + WebSockets** server (REST for matchmaking + WebSocket per game, tested locally with `httpx.AsyncClient` + `pytest-asyncio`).

## Repo hygiene

`.gitignore` ignores `__pycache__/`, `.venv/`, `.idea/`, `games/`. The user is in **undercover mode**: commits never reference AI/Claude/Anthropic, and `Co-Authored-By` lines are forbidden. Prefer one-line commit messages for small changes.
