"""Lock the public class layout after the M13 dir restructure.

Each import path here is the canonical home of the named class. If a
later refactor moves something, this test fails immediately rather than
later from some random downstream module.
"""

import pytest

from frontend.audio.sound_manager import SoundManager
from frontend.board import Board, DRAG_THRESHOLD_PX
from frontend.modals.base import BaseModal
from frontend.modals.confirm import ConfirmModal
from frontend.modals.file_picker import FilePicker
from frontend.modals.help import HelpModal
from frontend.modals.result import ResultMenu
from frontend.modals.server import ServerAddressModal
from frontend.modals.start import StartMenu
from frontend.modals.wait import WaitModal
from frontend.online.client import OnlineClient
from frontend.panels.audio import AudioPanel
from frontend.panels.base import BasePanel
from frontend.panels.player_strip import PlayerStrip
from frontend.panels.right import RightMenu
from frontend.pgn.generate import generate_pgn
from frontend.pgn.load import load_pgn_into_backend
from frontend.visual.animation import PieceAnimation
from frontend.visual.clock_visual import LOW_TIME_FRACTION, clock_pocket_color
from frontend.visual.colors import Colors
from frontend.visual.text_input import TextInput
from frontend.visual.toast import Toast
from frontend.visual.widgets import draw_button, draw_button_row


@pytest.mark.parametrize("symbol", [
    SoundManager, Board, BaseModal, ConfirmModal, FilePicker, HelpModal,
    ResultMenu, ServerAddressModal, StartMenu, WaitModal, OnlineClient,
    AudioPanel, BasePanel, PlayerStrip, RightMenu, PieceAnimation, Colors,
    TextInput, Toast,
])
def test_public_class_is_importable(symbol):
    assert symbol is not None


def test_drag_threshold_constant_re_exported():
    assert isinstance(DRAG_THRESHOLD_PX, int)


def test_pgn_module_exports():
    assert callable(generate_pgn)
    assert callable(load_pgn_into_backend)


def test_clock_visual_exports():
    assert isinstance(LOW_TIME_FRACTION, float)
    assert callable(clock_pocket_color)


def test_widgets_module_exports():
    assert callable(draw_button)
    assert callable(draw_button_row)
