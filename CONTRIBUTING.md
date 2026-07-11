# Contributing to Chess Shootout

Thanks for your interest. A few ground rules before you open a pull request.

## What this project is

Chess Shootout is **source available, non-commercial** — not open source. The
code is under the [PolyForm Noncommercial License 1.0.0](LICENSE) and the
original assets under CC BY-NC 4.0. It may not be sold or used commercially by
anyone other than the author. See the README for the full picture.

## Contributor terms

By submitting a contribution (code, art, sound, docs, or anything else) you
agree to all of the following:

1. **You have the right to contribute it.** You wrote it yourself, or you
   otherwise have the right to submit it, and to your knowledge it does not
   infringe anyone's rights.
2. **You grant the author broad rights.** You keep your copyright, but you grant
   Xiao Myung a perpetual, worldwide, irrevocable, royalty-free, sublicensable,
   and transferable license to use, reproduce, modify, distribute, **relicense,
   and commercially exploit** your contribution as part of Chess Shootout or any
   successor work — including under different license terms and in paid or
   commercial releases.
3. **You won't assert claims that limit that use.** You waive, to the extent the
   law allows, any moral rights or other claims that would prevent the author
   from using your contribution in the ways above.
4. **No ownership stake, no payment.** You receive no ownership share and no
   compensation. Accepted contributors are credited in [CREDITS.md](CREDITS.md).

If you do not agree to these terms, please do not submit a contribution. To
record your agreement, state in your pull request that you have read and accept
this file.

## Logging

Every module gets its own `log = logging.getLogger(__name__)` (or the
matching `chess.*` / `logging_setup.get_logger("chess.server.app")` name used
elsewhere in that package — grep a sibling file before adding a new logger
name). Pick the level by what the line is *for*, not by habit:

- **INFO** — a user action or a state transition: a game starts or ends, a
  move gets undone, an offer is sent/received/resolved, a setting is
  persisted, a room gets created/paired, a result gets finalized. One line
  per event, with the handful of fields that let you reconstruct the story
  (never a value the app also treats as identity or a secret — see below).
- **DEBUG** — per-message wire dispatch and other detail that's only useful
  shoulder-to-shoulder with the code (`ws dispatch`, `ws send`, `ws recv`).
- **WARNING** — degraded but continuing: a save fell back to a second
  directory, a resync kicked in, a reconnect attempt failed and is retrying.
- **ERROR** (`log.exception` inside an `except` block) — a failure the app
  is not going to recover from on its own; always with a traceback.

Never log a skill-check's `room.skillcheck_secret` (the which-fires selector)
or a per-check geometry `seed`, on either the client or the server — logging
either would hand a spectator or opponent the information the anti-cheat
model is built to keep from them. Same spirit for nicknames and client
UUIDs: log the *setting key* that changed, never the value.

Nothing logs on a per-frame cadence — no log call belongs directly inside
`draw_frame`, `draw_board`, or any other function that runs every tick,
whether or not something changed. If a per-frame function needs to report a
failure, wrap it in a state flag so it logs once, or emit at the point the
condition changes rather than at the point it's polled.

The server reads `LOG_LEVEL` (default `INFO`) and, when set, `LOG_FILE` (a
rotating file handler). The desktop client keeps every level-DEBUG-and-up
record in an in-memory ring buffer (`infra/crash_log.py`) regardless of what
the console shows, so a crash report is enriched with the INFO breadcrumbs
that led up to it even though nothing was written to disk along the way.

## Versioning

Every pull request must bump `[project].version` in `pyproject.toml` — a CI
job blocks merges where it's unchanged from the base branch. Run `make bump`
(`uv version --bump patch`) to bump the patch version and update `uv.lock`'s
`chess-shootout` entry together in one atomic step. A version-only bump can
also be done by hand: edit both files' version strings to match; no `uv`
required.
