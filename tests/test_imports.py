"""Lock the public class layout after the M13 dir restructure.

Each import path here is the canonical home of the named class. If a
later refactor moves something, this test fails immediately rather than
later from some random downstream module.
"""

import inspect

import pytest

from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.board import Board, DRAG_THRESHOLD_PX
from chessshootout.frontend.modals.base import BaseModal
from chessshootout.frontend.modals.confirm import ConfirmModal
from chessshootout.frontend.menu.history import HistoryView
from chessshootout.frontend.modals.help import HelpModal
from chessshootout.frontend.modals.match_found import MatchFoundModal
from chessshootout.frontend.online.banners import OfferBanners
from chessshootout.frontend.modals.options import OptionsModal
from chessshootout.frontend.modals.result import ResultMenu
from chessshootout.frontend.modals.start import StartMenu
from chessshootout.frontend.modals.wait import WaitModal
from chessshootout.online.client import OnlineClient
from chessshootout.frontend.panels.audio import AudioPanel
from chessshootout.frontend.panels.base import BasePanel
from chessshootout.frontend.panels.player_strip import PlayerStrip
from chessshootout.frontend.panels.right import RightMenu
from chessshootout.domain.pgn.generate import generate_pgn
from chessshootout.domain.pgn.load import load_pgn_into_backend
from chessshootout.frontend.visual.animation import PieceAnimation
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.text_input import TextInput
from chessshootout.frontend.visual.toast import Toast
from chessshootout.frontend.visual.widgets import draw_button, draw_button_row


@pytest.mark.parametrize("symbol", [
    SoundManager, Board, BaseModal, ConfirmModal, HistoryView, HelpModal,
    MatchFoundModal, OfferBanners, OptionsModal, ResultMenu, StartMenu,
    WaitModal, OnlineClient, AudioPanel, BasePanel, PlayerStrip, RightMenu,
    PieceAnimation, Colors, TextInput, Toast,
])
def test_public_class_is_importable(symbol):
    assert inspect.isclass(symbol)


def test_drag_threshold_constant_re_exported():
    """6 px before a click upgrades to a drag; a real int, not a bool."""
    assert type(DRAG_THRESHOLD_PX) is int
    assert DRAG_THRESHOLD_PX == 6


def test_pgn_module_exports():
    assert inspect.isfunction(generate_pgn)
    assert inspect.isfunction(load_pgn_into_backend)


def test_clock_visual_exports():
    assert type(LOW_TIME_FRACTION) is float
    assert LOW_TIME_FRACTION == 0.10


def test_widgets_module_exports():
    assert inspect.isfunction(draw_button)
    assert inspect.isfunction(draw_button_row)
