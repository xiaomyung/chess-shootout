"""Lock the public class layout after the M13 dir restructure.

Each import path here is the canonical home of the named class. If a
later refactor moves something, this test fails immediately rather than
later from some random downstream module.
"""

import inspect

import pytest

from frontend.audio.sound_manager import SoundManager
from frontend.board import Board, DRAG_THRESHOLD_PX
from frontend.modals.base import BaseModal
from frontend.modals.confirm import ConfirmModal
from frontend.menu.history import HistoryView
from frontend.modals.help import HelpModal
from frontend.modals.match_found import MatchFoundModal
from frontend.online.banners import OfferBanners
from frontend.modals.options import OptionsModal
from frontend.modals.result import ResultMenu
from frontend.modals.start import StartMenu
from frontend.modals.wait import WaitModal
from online.client import OnlineClient
from frontend.panels.audio import AudioPanel
from frontend.panels.base import BasePanel
from frontend.panels.player_strip import PlayerStrip
from frontend.panels.right import RightMenu
from frontend.pgn.generate import generate_pgn
from frontend.pgn.load import load_pgn_into_backend
from frontend.visual.animation import PieceAnimation
from frontend.visual.clock_visual import LOW_TIME_FRACTION
from frontend.visual.colors import Colors
from frontend.visual.text_input import TextInput
from frontend.visual.toast import Toast
from frontend.visual.widgets import draw_button, draw_button_row


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
