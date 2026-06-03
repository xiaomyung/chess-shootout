import pytest

from domain.pgn.generate import generate_pgn


@pytest.mark.parametrize(
    "result, kwargs, present, absent",
    [
        pytest.param(
            "white_wins",
            dict(white_name="alice", black_name="bob", time_control=(300, 5)),
            ['[White "alice"]', '[Black "bob"]', '[TimeControl "300+5"]', '[Result "1-0"]'],
            ["[Termination"],
            id="player_names_and_time_control",
        ),
        pytest.param(
            "white_wins",
            dict(time_control=None),
            ['[TimeControl "-"]'],
            [],
            id="no_time_control_emits_dash",
        ),
        pytest.param(
            "white_wins_on_time",
            dict(white_name="alice", black_name="bob", time_control=(60, 0)),
            ['[Termination "Time forfeit"]', '[Result "1-0"]'],
            [],
            id="time_forfeit_white_wins",
        ),
        pytest.param(
            "black_wins_on_time",
            dict(time_control=(60, 0)),
            ['[Termination "Time forfeit"]', '[Result "0-1"]'],
            [],
            id="time_forfeit_black_wins",
        ),
        pytest.param(
            "white_wins_on_time",
            dict(time_control=None),
            ['[Termination "Time forfeit"]', '[TimeControl "-"]'],
            [],
            id="time_forfeit_no_time_control_still_marks",
        ),
        pytest.param(
            "white_wins",
            dict(),
            ['[White "?"]', '[Black "?"]', '[TimeControl "-"]'],
            ["[Termination"],
            id="backwards_compat_default_kwargs",
        ),
        pytest.param(
            "draw_agreement",
            dict(termination="Time forfeit"),
            ['[Termination "Time forfeit"]'],
            [],
            id="explicit_termination_overrides_inference",
        ),
    ],
)
def test_generate_pgn_headers(result, kwargs, present, absent):
    """Header tags are driven by result code + kwargs; explicit termination wins."""
    out = generate_pgn([], result, **kwargs)
    for fragment in present:
        assert fragment in out
    for fragment in absent:
        assert fragment not in out
