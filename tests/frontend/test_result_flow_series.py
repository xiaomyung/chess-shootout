"""ResultFlow's running online series score: the reset_series() contract the
game screen and the online coordinator call to cut a series loose, and the
per-game reset that must NOT touch it."""

import pytest

from tests.conftest import pygame_display
from tests.helpers import make_app


_pygame_init = pygame_display(1000, 800)


def _flow():
    return make_app(1000, 800).game.result_flow


def test_reset_series_forgets_every_recorded_point():
    flow = _flow()
    flow.series_scores = {"white": 2.0, "black": 1.5}
    flow.reset_series()
    assert flow.series_scores == {}
    assert flow.series_score("white") == 0.0
    assert flow.series_score("black") == 0.0


def test_reset_series_on_an_empty_series_is_harmless():
    flow = _flow()
    assert flow.series_scores == {}
    flow.reset_series()
    flow.reset_series()
    assert flow.series_scores == {}


def test_reset_series_replaces_the_dict_so_a_held_reference_is_not_reused():
    """A fresh dict, not clear(): anything that captured the old mapping (a
    re-seed in flight, a test probe) never sees the next series' points."""
    flow = _flow()
    old = {"white": 1.0}
    flow.series_scores = old
    flow.reset_series()
    assert flow.series_scores is not old
    assert old == {"white": 1.0}


def test_a_series_counts_up_again_from_zero_after_a_reset():
    flow = _flow()
    flow.series_scores = {"white": 3.0, "black": 2.0}
    flow.reset_series()
    flow._award_series_win("black")
    flow._award_series_draw()
    assert flow.series_scores == {"black": 1.5, "white": 0.5}


def test_reset_series_leaves_the_per_game_latches_alone():
    flow = _flow()
    flow._series_score_awarded = True
    flow._save_failed = True
    flow.reset_series()
    assert flow._series_score_awarded is True
    assert flow._save_failed is True


def test_a_per_game_reset_keeps_the_series():
    """The other half of the contract: reset_for_new_game wipes the per-game
    latches but keeps the series -- that is what makes a run of online games a
    series. Only reset_series ends it."""
    flow = _flow()
    flow.series_scores = {"white": 1.0, "black": 0.5}
    flow._series_score_awarded = True
    flow.reset_for_new_game()
    assert flow.series_scores == {"white": 1.0, "black": 0.5}
    assert flow._series_score_awarded is False


def _online_payload(**extra):
    payload = {
        "variant": "online", "your_color": "white", "white_name": "Alice",
        "black_name": "Bob", "time_minutes": 5, "increment_seconds": 0,
        "white_score": 2.0, "black_score": 1.0,
    }
    payload.update(extra)
    return payload


@pytest.mark.parametrize("payload", [
    {"side": "white", "time_minutes": 5, "increment_seconds": 0},
    {"side": "black", "fen": "4k3/8/8/8/8/8/8/4K3 w - - 0 1"},
], ids=["local", "fen"])
def test_a_non_online_start_after_an_online_series_is_round_one_with_no_series(payload):
    app = make_app(1000, 800)
    app.switch_to("game", **_online_payload())
    assert app.game.result_flow.series_scores == {"white": 2.0, "black": 1.0}
    assert app.game._current_round() == 4
    app.switch_to("game", **payload)
    assert app.game.result_flow.series_scores == {}
    assert app.game._current_round() == 1


def test_an_online_start_after_a_local_game_shows_the_server_score():
    app = make_app(1000, 800)
    app.switch_to("game", **_online_payload(white_score=0.0, black_score=0.0))
    app.switch_to("game", side="white", time_minutes=5, increment_seconds=0)
    app.switch_to("game", **_online_payload(white_score=1.0, black_score=0.5))
    assert app.game.result_flow.series_scores == {"white": 1.0, "black": 0.5}
    assert app.game._current_round() == 2


def test_current_round_ignores_stale_points_off_the_online_variant():
    app = make_app(1000, 800)
    app.switch_to("game", side="white", time_minutes=5, increment_seconds=0)
    app.game.result_flow.series_scores = {"white": 3.0}
    assert app.game._current_round() == 1


def test_aborted_card_has_the_neutral_subtitle_and_awards_nothing():
    from chessshootout.frontend.game.result_flow import RESULT_TEXT
    title, sub = RESULT_TEXT["aborted"]
    assert title == "Game aborted"
    assert sub == "called off before both sides moved"
    app = make_app(1000, 800)
    app.switch_to("game", **_online_payload(white_score=0.0, black_score=0.0))
    app.coordinator._handle_online_result({"reason": "aborted"})
    assert app.game.result_flow.series_scores == {"white": 0.0, "black": 0.0}


def test_resume_adoption_after_a_local_game_shows_the_server_series():
    app = make_app(1000, 800)
    app.switch_to("game", side="white", time_minutes=5, increment_seconds=0)
    app.coordinator._adopt_resumed_game(_online_payload(
        your_color="black", white_score=1.0, black_score=0.5, fen="",
        move_history=[{"san": "e4"}]))
    assert app.game.result_flow.series_scores == {"white": 1.0, "black": 0.5}
    assert app.game._current_round() == 2
