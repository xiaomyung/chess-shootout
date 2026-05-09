from frontend.pgn.generate import generate_pgn


def test_player_names_in_headers():
    out = generate_pgn(
        [], "white_wins",
        white_name="alice", black_name="bob",
        time_control=(300, 5),
    )
    assert '[White "alice"]' in out
    assert '[Black "bob"]' in out
    assert '[TimeControl "300+5"]' in out
    assert '[Termination' not in out
    assert '[Result "1-0"]' in out


def test_no_time_control_emits_dash():
    out = generate_pgn([], "white_wins", time_control=None)
    assert '[TimeControl "-"]' in out


def test_time_forfeit_white_wins():
    out = generate_pgn(
        [], "white_wins_on_time",
        white_name="alice", black_name="bob",
        time_control=(60, 0),
    )
    assert '[Termination "Time forfeit"]' in out
    assert '[Result "1-0"]' in out


def test_time_forfeit_black_wins():
    out = generate_pgn(
        [], "black_wins_on_time",
        time_control=(60, 0),
    )
    assert '[Termination "Time forfeit"]' in out
    assert '[Result "0-1"]' in out


def test_time_forfeit_with_no_time_control_still_marks_termination():
    # Edge case: result claims timeout but time_control was not set. Render anyway
    # because the result code is what drives the termination tag.
    out = generate_pgn([], "white_wins_on_time", time_control=None)
    assert '[Termination "Time forfeit"]' in out
    assert '[TimeControl "-"]' in out


def test_backwards_compat_default_kwargs():
    out = generate_pgn([], "white_wins")
    assert '[White "?"]' in out
    assert '[Black "?"]' in out
    assert '[TimeControl "-"]' in out
    assert '[Termination' not in out


def test_explicit_termination_kwarg_wins_over_result_inference():
    out = generate_pgn(
        [], "draw_agreement",
        termination="Time forfeit",
    )
    # If caller explicitly sets termination, we honor it.
    assert '[Termination "Time forfeit"]' in out
