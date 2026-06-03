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
.venv/bin/pylama chessshootout tests                                        # lint (≤100 cols)
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
(rects produced, expected colors/state), not just "didn't raise". There is no
allowlist — the guard fails on any weak test, so strengthen it rather than ship it.

## Determinism (xdist-safe)

The suite runs under `pytest-xdist`, where each worker imports the test modules in
its own process. A `parametrize`'s argvalues must therefore be **identical across
processes**, or collection diverges and the run errors with "Different tests were
collected between gw0 and gwN". Use fixed literals — never build argvalues from
`uuid.uuid4()`, `random`, the clock, or unsorted `set`/`dict` iteration (sort if you
must). Verify a parametrize change with `pytest tests -n auto`, not just `-n0`.

## Worked examples (before → after)

**Collapse a cluster** — ten near-identical material checks become one table:

```python
# before: 10 functions, each make_backend(...) then assert game_result() == ...
def test_kvk_is_draw():
    bk = make_backend({sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK)})
    assert bk.game_result() == "draw_insufficient_material"
# ...nine more...

# after: one parametrized test; each FIDE case keeps its own expected, rationale in the id
@pytest.mark.parametrize("pieces, expected", [
    pytest.param(KV_K, "draw_insufficient_material", id="kvk_draw"),
    pytest.param(KNN_V_K, "draw_insufficient_material", id="knn_v_k_draw_fide_5_2_2"),
    pytest.param(KBB_V_K, None, id="kbb_v_k_mate_exists_not_drawn"),
])
def test_insufficient_material(pieces, expected):
    assert make_backend(pieces).game_result() == expected
```

**Strengthen a render smoke** — assert the output, not just "doesn't crash":

```python
# before: a weak smoke (banned by the guard)
def test_draw_button_smoke_idle(font):
    draw_button(surface, rect, "OK", font)   # no assertion

# after: assert the rendered pixels match the state colour, with an idle-vs-pressed diff
def test_draw_button_idle_and_pressed_render_differently(font):
    draw_button(surface, rect, "OK", font, force_pressed=False)
    idle = surface.get_at((rect.x + 8, rect.centery))[:3]
    draw_button(surface, rect, "OK", font, force_pressed=True)
    pressed = surface.get_at((rect.x + 8, rect.centery))[:3]
    assert idle != pressed
    assert idle == pg.Color(Colors.dark_menu)[:3]
```

To prove a render assertion bites, neutralize the draw **inside the test** with
`monkeypatch` (it auto-reverts) — never edit a source file, even temporarily.
