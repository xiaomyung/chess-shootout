"""The country picker overlay: a searchable, scrollable list of flag+name rows with a
"No flag" clear option at the top. Search filters by name (accent-insensitive) or code,
clicking a row reports the code and hides, Cancel hides without a callback, and the list
scrolls. Picking "No flag" reports an empty code (clears the setting)."""

import pygame as pg
import pytest

from tests.conftest import pygame_display
from chessshootout.frontend.modals.country_picker import CountryPicker


_pygame_init = pygame_display(900, 700)


@pytest.fixture
def picker():
    p = CountryPicker(pg.display.get_surface())
    p.set_rect(pg.Rect(40, 40, 520, 560))
    return p


def test_hidden_until_shown(picker):
    assert picker.is_visible() is False
    picker.show("", lambda c: None)
    assert picker.is_visible() is True


def test_entries_lead_with_no_flag_when_query_empty(picker):
    picker.show("RO", lambda c: None)
    assert picker._entries()[0] == ("", "No flag")


def test_filter_matches_country_name(picker):
    picker.show("", lambda c: None)
    picker.search.text = "roma"
    picker._apply_filter()
    assert "RO" in [code for code, _ in picker._filtered]
    assert ("", "No flag") not in picker._entries()


def test_filter_is_accent_insensitive(picker):
    picker.show("", lambda c: None)
    picker.search.text = "cote d"
    picker._apply_filter()
    assert "CI" in [code for code, _ in picker._filtered]


def test_filter_matches_code(picker):
    picker.show("", lambda c: None)
    picker.search.text = "jp"
    picker._apply_filter()
    assert ("JP", "Japan") in picker._filtered


def test_pick_country_reports_code_and_hides(picker):
    picked = []
    picker.show("", picked.append)
    picker.search.text = "Japan"
    picker._apply_filter()
    picker.draw()
    rows = [r for r, code in picker._row_rects if code == "JP"]
    assert rows
    assert picker.handle_click(rows[0].center) is True
    assert picked == ["JP"]
    assert picker.is_visible() is False


def test_pick_no_flag_reports_empty(picker):
    picked = []
    picker.show("US", picked.append)
    picker.draw()
    rows = [r for r, code in picker._row_rects if code == ""]
    assert rows
    picker.handle_click(rows[0].center)
    assert picked == [""]


def test_cancel_hides_without_callback(picker):
    picked = []
    picker.show("US", picked.append)
    picker.draw()
    picker.handle_click(picker._cancel_rect.center)
    assert picker.is_visible() is False
    assert picked == []


def test_scroll_advances_offset(picker):
    picker.show("", lambda c: None)
    picker.draw()
    assert picker.handle_scroll(picker._list_rect.center, -1) is True
    assert picker.scroll_offset > 0


def test_scroll_outside_list_ignored(picker):
    picker.show("", lambda c: None)
    picker.draw()
    assert picker.handle_scroll((5, 5), -1) is False


def test_draw_populates_rows(picker):
    picker.show("", lambda c: None)
    picker.draw()
    assert len(picker._row_rects) > 0
