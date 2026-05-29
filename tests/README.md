# Testing conventions

How tests are written in this repo. The goal is a suite that **exercises real
behavior and surfaces regressions** — not one that merely goes green. Every test
should be able to fail for a real reason.

## Running

```bash
.venv/bin/pytest tests -n 8 -q                 # fast local loop
.venv/bin/pytest tests -n auto -q              # match CI before pushing
.venv/bin/pytest tests/test_san.py -v          # one file
.venv/bin/pytest "tests/test_clock.py::test_add_time_caps[at_initial]" -v   # one case
.venv/bin/pytest tests -n auto --cov --cov-report=term:skip-covered          # coverage (informational)
.venv/bin/pylama backend frontend server main.py paths.py tests             # lint (≤100 cols)
```

Do **not** run the suite while a chess server is live on `:8000` (the per-process
reconnect probe floods its rate limit). `perft(3)` must read `8902` — it is the
strongest single regression for the move engine.

## Naming

`test_<subject>_<scenario>_<expected>` — e.g. `test_en_passant_capture_clears_target`,
`test_add_time_caps_at_initial`. Avoid generic names (`test_smoke`, `test_feature`)
and names that describe the call rather than the outcome.

## When to parametrize

Collapse **2+** tests whose bodies are structurally identical and differ only in
input data and/or expected output into one `@pytest.mark.parametrize`.

Keep tests **separate** when:
- the setup differs (not just the data),
- they assert different *kinds* of things,
- the test is a multi-step narrative (a real game replay, an interaction flow),
- they take the `server` fixture — **never parametrize a real-server test** (it
  changes xdist worker placement and the shared uvicorn lifecycle).

Convert ad-hoc `for x in [...]: assert f(x)` loops into `parametrize` so each case
is its own node and a failure reports which input broke.

## Parametrize ids

Use explicit `pytest.param(..., id="...")`, snake_case, ≤ ~50 chars. The id is where
a stripped rationale comment goes. Wrap to respect the 100-col limit:

```python
@pytest.mark.parametrize(
    "pieces, expected",
    [
        pytest.param(KN_VS_KN, "draw_insufficient_material", id="knight_vs_knight_auto_draws"),
        pytest.param(KBB_VS_K, None, id="two_bishops_can_mate_not_drawn"),
    ],
)
def test_insufficient_material(pieces, expected):
    assert make_backend(pieces).game_result() == expected
```

Keep the case table inline above the test; hoist it to a module-level constant only
when it is long or reused.

## Comments and docstrings

- **No comments** in test bodies — strip them, including `# ---- section ----`
  dividers. Structure comes from grouping and parametrize ids.
- Real rationale (FIDE citations, regression reasons, non-obvious timing) goes in a
  **function docstring** and/or the **parametrize id**. When unsure whether a comment
  is load-bearing, preserve it as a docstring.
- Strip pure-title module docstrings; **keep** module docstrings that document test
  *strategy* or a non-obvious invariant (tighten them).
- `helpers.py` keeps its docstrings.

Type hints and full docstrings everywhere are a separate later pass — not required here.

## Fixtures and helpers

- Pure data / builders → `tests/helpers.py` (imported explicitly, e.g. `make_backend`,
  `sq`, `play_*`). Assertion helpers are named `assert_*` / `expect_*` (or `_assert_*`)
  so the weak-test guard recognizes them.
- Stateful resources → fixtures in `tests/conftest.py` (e.g. the real-uvicorn `server`,
  a headless pygame display, a temp PGN file).
- Don't duplicate a builder across files — add it to `helpers.py` once.

## Weak-test ban

A test must exercise real behavior: a non-trivial `assert`, a `pytest.raises/warns`,
or a call to an assertion helper. Banned (the `test_no_weak_tests.py` guard fails on
these):
- `assert True` / `assert <literal>`,
- `assert X == X` (identical operands),
- a test with no assertion and no behavior check (a bare `draw()` "doesn't crash").

A render path still worth guarding should assert something real about the result
(rects produced, expected colors/state), not just "didn't raise". Tests being
migrated are listed in `_weak_allowlist.py`; that list self-prunes to empty.
