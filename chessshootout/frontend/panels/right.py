from typing import NamedTuple

import pygame as pg

from chessshootout.frontend.visual.colors import Colors
from chessshootout.infra import env
from chessshootout.domain.pgn.generate import iter_move_pairs
from chessshootout.frontend.visual.scroll_view import ScrollView
from chessshootout.frontend.visual.widgets import draw_pill
from chessshootout.frontend.visual.draw import (
    cut_rect_surface, rounded_rect_surface, dashed_hline, scale_floor,
    smoothstep, rotated_chevron_surface, dashed_rounded_rect_surface, circle_surface,
    build_tooltip_bubble, notch_geometry, notch_value_from_click, notch_readout_slot_w,
)
from chessshootout.frontend.visual.icons import (
    draw_undo_arrow, draw_resign_flag, draw_flip_arrows, draw_left_arrow, draw_file,
)
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.frontend.visual.cache import render_text, new_cache, memoized_surface


class Cap(NamedTuple):
    key: str
    icon: str
    glyph: str
    glyph_pt: int
    glyph_bold: bool
    label: str
    tooltip: str


CAPS = [
    Cap("undo",      "undo",   "",    0,  False, "Undo",     "UNDO — KEY Z"),
    Cap("draw",      "",       "½",   26, False, "Draw",     "OFFER DRAW — KEY D"),
    Cap("resign",    "resign", "",    0,  False, "Resign",   "RESIGN — KEY R"),
    Cap("give_time", "",       "+15", 14, True,  "Give +15", "GIVE +15 — KEY G · HOLD TO RAMP"),
    Cap("flip",      "flip",   "",    0,  False, "Flip",     "FLIP — KEY F"),
    Cap("help",      "",       "?",   18, True,  "Help",     "HELP — KEY ?"),
]

UNTIMED_CAPS = [cap for cap in CAPS if cap.key != "give_time"]

REVIEW_CAPS = [
    Cap("menu",     "menu", "", 0, False, "Menu",     "BACK TO MENU"),
    Cap("flip",     "flip", "", 0, False, "Flip",     "FLIP — KEY F"),
    Cap("open_pgn", "file", "", 0, False, "Open PGN", "OPEN PGN FILE"),
]

CAP_ICON_FUNCS = {
    "undo": draw_undo_arrow,
    "resign": draw_resign_flag,
    "flip": draw_flip_arrows,
    "menu": draw_left_arrow,
    "file": draw_file,
}

_GLYPH_SPECS = {
    (cap.glyph_pt, cap.glyph_bold)
    for table in (CAPS, UNTIMED_CAPS, REVIEW_CAPS) for cap in table if cap.glyph
}

SECTION_OPEN = {}


def section_open(key):
    if key not in SECTION_OPEN:
        SECTION_OPEN[key] = env.get_rail_section_open(key)
    return SECTION_OPEN[key]


SECTION_ORDER = ("actions", "signals", "chat")
SECTION_LABELS = {"actions": "ACTIONS", "signals": "SIGNALS", "chat": "QUICK CHAT"}
SECTION_TOOLTIPS = {
    "actions": "ACTIONS — KEY A",
    "signals": "SIGNALS — KEY S",
    "chat": "QUICK CHAT — KEY C",
}

INFO_HEADER_PAD = 12
ROUND_RIGHT_PAD = 10
MOVE_PREFIX_CHARS = 5
MOVE_CELL_PAD = 4
MOVE_MIN_CELL_CHARS = 4

CARD_INSET = 12
CARD_CUT = 16
LOG_RADIUS = 9
LOG_MIN_H = 110
LOG_HEADER_TOP = 10
LOG_SEP_GAP = 8
LOG_ROWS_GAP = 9
MOVE_CELL_CUT = 8
MICRO_FONT_PT = 10
WHIFF_ALPHA = 190

DEBUT_NAME_PT = 12
DEBUT_NAME_FLOOR = 10
DEBUT_ROW_GAP = 4
MARQUEE_EASE = 0.12

SECTION_HEADER_PT = 10
SECTION_HEADER_VPAD = 9
SECTION_DIVIDER_TOP = 10
SECTION_DIVIDER_BOTTOM = 6
SECTION_BODY_TOP = 10
SECTION_CHEVRON_MS = 200
SECTION_CHEVRON_H = 7

CAP_H_GAME = 44
CAP_H_REVIEW = 40
CAP_GAP = 8
CAP_CUT = 7
CAP_ICON_BOX = 32
CAP_LABEL_PT = 14
CAP_LABEL_PAD = 9
FADED_ICON_ALPHA = 102

TOOLTIP_DELAY_MS = 250
TOOLTIP_FADE_MS = 120
TOOLTIP_PT = 10
TOOLTIP_GAP = 6

SIGNAL_CHIP_H = 31
SIGNAL_CHIP_GAP = 7
SIGNAL_CHIP_DOT = 7
SIGNAL_CHIP_DOT_GAP = 5
SIGNAL_CHIP_LABEL_PT = 11
SIGNAL_CHIP_LABEL_FLOOR = 10
SIGNAL_ROW_GAP = 16
SIGNAL_NOTCH_COUNT = 10
SIGNAL_NOTCH_CELL_W = 15
SIGNAL_NOTCH_CELL_H = 24
SIGNAL_NOTCH_GAP = 4
SIGNAL_NOTCH_CUT = 4
SIGNAL_VOL_READOUT_PT = 10
SIGNAL_VOL_GAP = 8
SIGNAL_DIM_ALPHA = 89
SIGNAL_SHARE_DISABLED_ALPHA = 102
SIGNAL_ON_BORDER_ALPHA = "8c"

CHAT_BUTTON_H = 30
CHAT_BUTTON_FLOOR = 26
CHAT_LABEL_PT = 12
CHAT_LABEL_FLOOR = 11
CHAT_GAP = 7
CHAT_CUT = 7
CHAT_COLS = 2
CHAT_DIM_ALPHA = 102

_CAP_FG_CACHE = new_cache()
_SIGNAL_CACHE = new_cache()
_CHAT_CACHE = new_cache()
_WHIFF_CACHE = new_cache()


class SignalChip(NamedTuple):
    key: str
    label: str
    on_color: str
    state_key: str
    callback: str
    tooltip: str


SIGNAL_CHIPS = [
    SignalChip("share", "SHARE", Colors.amber, "share_on", "share_toggle",
               "SHARE MARKS — BROADCAST YOUR DRAWINGS"),
    SignalChip("auto_q", "AUTO-Q", Colors.accent, "auto_q", "auto_q_toggle",
               "AUTO-QUEEN — PROMOTIONS PICK QUEEN"),
    SignalChip("sound", "SOUND", Colors.accent, "sound_on", "sound_toggle",
               "SOUND — MUTE ALL"),
]
REVIEW_SIGNAL_CHIPS = [chip for chip in SIGNAL_CHIPS if chip.key == "sound"]
SIGNAL_VOL_TOOLTIP = "VOLUME — CLICK A NOTCH; FIRST NOTCH TOGGLES 0%"


class SectionBlock(NamedTuple):
    key: str
    divider_y: int
    header: pg.Rect
    body: pg.Rect
    show_body: bool


class RailTooltip:

    def __init__(self):
        self.entries = []
        self._hover_key = None
        self._hover_since = 0
        self._mouse = (0, 0)
        self._cache = new_cache()

    def begin_frame(self):
        self.entries.clear()
        self._mouse = pg.mouse.get_pos()

    def register(self, key, rect, label):
        self.entries.append((key, pg.Rect(rect), label))

    def draw(self, window, clip_rect, scale, now, font):
        hovered = None
        for key, rect, label in self.entries:
            if rect.collidepoint(self._mouse):
                hovered = (key, rect, label)
                break
        if hovered is None:
            self._hover_key = None
            return
        key, rect, label = hovered
        if key != self._hover_key:
            self._hover_key = key
            self._hover_since = now
            return
        elapsed = now - self._hover_since
        if elapsed < TOOLTIP_DELAY_MS:
            return
        alpha = smoothstep((elapsed - TOOLTIP_DELAY_MS) / TOOLTIP_FADE_MS)
        bubble = self._bubble(label, scale, font)
        bubble.set_alpha(int(255 * alpha))
        window.blit(bubble, self._position(bubble, rect, clip_rect))

    def _bubble(self, label, scale, font):
        key = (label, font.get_height())
        return memoized_surface(
            self._cache, key, lambda: build_tooltip_bubble(font, label, scale))

    def _position(self, bubble, rect, clip_rect):
        w, h = bubble.get_size()
        x = max(clip_rect.left, min(rect.centerx - w // 2, clip_rect.right - w))
        y = rect.top - h - TOOLTIP_GAP
        if y < clip_rect.top:
            y = rect.bottom + TOOLTIP_GAP
        return (x, y)


class RightMenu:

    def __init__(self, window, match, callbacks, board=None,
                 buttons_provider=None,
                 disabled_keys_provider=None, whiffs_provider=None,
                 debut_provider=None, signals_provider=None,
                 sounds=None, chat_visible_provider=None,
                 chat_presets_provider=None, chat_cooldown_provider=None,
                 caps_stacked=False, suppress_click=None):
        self.window = window
        self.match = match
        self.callbacks = callbacks
        self.board = board
        self.buttons_provider = buttons_provider or (lambda: CAPS)
        self.disabled_keys_provider = disabled_keys_provider or (lambda: set())
        self.whiffs_provider = whiffs_provider or (lambda: {})
        self.suppress_click = suppress_click or (lambda: None)
        self.debut_provider = debut_provider or (lambda: None)
        self.signals_provider = signals_provider
        self.sounds = sounds
        self.chat_visible_provider = chat_visible_provider or (lambda: False)
        self.chat_presets_provider = chat_presets_provider or (lambda: [])
        self.chat_cooldown_provider = chat_cooldown_provider or (lambda: False)
        self.caps_stacked = caps_stacked
        self._pair_to_row = {}
        self._marquee_off = 0.0

        self.padding = 10
        self.moves_font_factor = 21
        self.pill_font_factor = 30

        self.scale = 1.0
        self.font = get_font(13, mono=True)
        self.moves_font = get_font(14, bold=True)
        self.pill_font = get_font(11, bold=True)
        self.round_font = get_font(11, bold=True)
        self.micro_font = get_font(MICRO_FONT_PT, bold=True, mono=True)
        self.debut_name_font = get_font(DEBUT_NAME_PT, bold=True, mono=True)
        self.section_font = get_font(SECTION_HEADER_PT, mono=True, bold=True)
        self.cap_label_font = get_font(CAP_LABEL_PT, bold=True)
        self.chip_font = get_font(SIGNAL_CHIP_LABEL_PT, bold=True, mono=True)
        self.chat_font = get_font(CHAT_LABEL_PT, bold=True)
        self.signal_num_font = get_font(SIGNAL_VOL_READOUT_PT, mono=True)
        self.tooltip_font = get_font(TOOLTIP_PT, mono=True)
        self._glyph_fonts = {
            spec: get_font(spec[0], mono=True, bold=spec[1]) for spec in _GLYPH_SPECS
        }
        self._cap_fg_box = CAP_ICON_BOX

        self.outer_rect = pg.Rect(0, 0, 0, 0)
        self.moves_rect = pg.Rect(0, 0, 0, 0)
        self.info_rect = pg.Rect(0, 0, 0, 0)
        self.button_rects = {}
        self._section_blocks = []
        self._cap_draws = []
        self._signal_chips = []
        self._chat_buttons = []
        self._signal_vol_rect = pg.Rect(0, 0, 0, 0)
        self._signal_notch_band = pg.Rect(0, 0, 0, 0)
        self._signal_notch_step = 1
        self._chevron_anim = {}
        self.rail_tooltip = RailTooltip()
        self.game_info = None
        self._last_outer_rect = None

        self.scroll_offset = 0
        self._total_rows = 0
        self._max_lines = 0
        self._line_h = 1
        self._content_px = 0
        self._moves_viewport = pg.Rect(0, 0, 0, 0)
        self.scroll = ScrollView(
            self._get_scroll_px,
            self._set_scroll_px,
            lambda: (self._moves_viewport, self._content_px),
            wheel_step_px=lambda: self._line_h,
        )
        self._move_cell_hits = []
        self._last_seen_total_rows = 0
        self._last_review_ply = None
        self._move_rows_cache = None

    @property
    def backend(self):
        return getattr(self.match, "backend", self.match)

    def _max_off_rows(self):
        return max(0, self._total_rows - self._max_lines)

    def _get_scroll_px(self):
        return (self._max_off_rows() - self.scroll_offset) * self._line_h

    def _set_scroll_px(self, px):
        rows_from_top = round(px / self._line_h) if self._line_h else 0
        self.scroll_offset = max(0, min(self._max_off_rows() - rows_from_top,
                                        self._max_off_rows()))

    def is_visible(self):
        return True

    def set_rect(self, rect, scale=1.0):
        self.scale = scale
        self.font = get_font(max(int(rect.width / self.moves_font_factor), 10), mono=True)
        self.moves_font = get_font(
            max(int(rect.width / self.moves_font_factor), 10), bold=True)
        self.pill_font = get_font(max(int(rect.width / self.pill_font_factor), 9), bold=True)
        self.round_font = get_font(max(int(rect.width / self.pill_font_factor), 9), bold=True)
        self.micro_font = get_font(scale_floor(MICRO_FONT_PT, scale, 8), bold=True, mono=True)
        self.debut_name_font = get_font(
            scale_floor(DEBUT_NAME_PT, scale, DEBUT_NAME_FLOOR), bold=True, mono=True)
        self.section_font = get_font(
            scale_floor(SECTION_HEADER_PT, scale, 7), mono=True, bold=True)
        self.cap_label_font = get_font(scale_floor(CAP_LABEL_PT, scale, 10), bold=True)
        self.chip_font = get_font(
            scale_floor(SIGNAL_CHIP_LABEL_PT, scale, SIGNAL_CHIP_LABEL_FLOOR),
            bold=True, mono=True)
        self.chat_font = get_font(scale_floor(CHAT_LABEL_PT, scale, CHAT_LABEL_FLOOR), bold=True)
        self.signal_num_font = get_font(scale_floor(SIGNAL_VOL_READOUT_PT, scale, 8), mono=True)
        self.tooltip_font = get_font(scale_floor(TOOLTIP_PT, scale, 8), mono=True)
        self._glyph_fonts = {
            spec: get_font(scale_floor(spec[0], scale, max(spec[0] - 4, 8)),
                           mono=True, bold=spec[1])
            for spec in _GLYPH_SPECS
        }
        self._cap_fg_box = scale_floor(CAP_ICON_BOX, scale, 16)

        p = self.padding
        inset = scale_floor(CARD_INSET, scale, 8)
        self.outer_rect = pg.Rect(
            rect.x + p, rect.y + inset,
            rect.width - inset - p, rect.height - 2 * inset,
        )
        self._last_outer_rect = pg.Rect(rect)

        inner_w = self.outer_rect.width - 2 * p
        small_gap = max(int(self.outer_rect.height * 0.01), 4)

        stack_top = self._layout_sections(inner_w)

        info_h = self._info_section_height()
        info_y = self.outer_rect.y + p
        self.info_rect = pg.Rect(self.outer_rect.x + p, info_y, inner_w, info_h)

        moves_top = info_y + info_h + (small_gap if info_h > 0 else 0)
        moves_h = max(stack_top - moves_top - small_gap,
                      scale_floor(LOG_MIN_H, scale, 70))
        self.moves_rect = pg.Rect(self.outer_rect.x + p, moves_top, inner_w, moves_h)

    def _layout_sections(self, inner_w):
        scale = self.scale
        p = self.padding
        div_top = scale_floor(SECTION_DIVIDER_TOP, scale, 4)
        div_bottom = scale_floor(SECTION_DIVIDER_BOTTOM, scale, 3)
        header_h = self.section_font.get_height() + 2 * scale_floor(
            SECTION_HEADER_VPAD, scale, 4)

        metas = []
        stack_h = 0
        for key in self._visible_sections():
            body_h = self._section_body_height(key)
            block_h = div_top + div_bottom + header_h + body_h
            metas.append((key, body_h, block_h))
            stack_h += block_h

        stack_top = self.outer_rect.bottom - p - stack_h
        x = self.outer_rect.x + p
        y = stack_top
        self._section_blocks = []
        self._cap_draws = []
        self._signal_chips = []
        self._chat_buttons = []
        self.button_rects = {}
        for key, body_h, block_h in metas:
            divider_y = y + div_top
            header = pg.Rect(x, divider_y + div_bottom, inner_w, header_h)
            body = pg.Rect(x, header.bottom, inner_w, body_h)
            show_body = body_h > 0 and section_open(key)
            self._section_blocks.append(
                SectionBlock(key, divider_y, header, body, show_body))
            if key == "actions" and show_body:
                self._cap_draws = self._layout_caps(self.buttons_provider(), body)
                for cap, cap_rect in self._cap_draws:
                    self.button_rects[cap.key] = cap_rect
            elif key == "signals" and show_body:
                self._layout_signals(body)
            elif key == "chat" and show_body:
                self._layout_chat(body)
            y += block_h
        return stack_top

    def _visible_sections(self):
        if self.chat_visible_provider():
            return list(SECTION_ORDER)
        return [key for key in SECTION_ORDER if key != "chat"]

    def _section_body_height(self, key):
        if not section_open(key):
            return 0
        if key == "actions":
            return self._actions_body_height()
        if key == "signals":
            return self._signals_body_height()
        if key == "chat":
            return self._chat_body_height()
        return 0

    def _actions_body_height(self):
        caps = self.buttons_provider()
        if not caps:
            return 0
        body_top = scale_floor(SECTION_BODY_TOP, self.scale, 4)
        if self.caps_stacked:
            cap_h = scale_floor(CAP_H_REVIEW, self.scale, 28)
            gap = scale_floor(CAP_GAP, self.scale, 5)
            return body_top + len(caps) * cap_h + (len(caps) - 1) * gap
        return body_top + scale_floor(CAP_H_GAME, self.scale, 30)

    def _signals_body_height(self):
        if self.signals_provider is None:
            return 0
        body_top = scale_floor(SECTION_BODY_TOP, self.scale, 4)
        chip_h = scale_floor(SIGNAL_CHIP_H, self.scale, 20)
        gap = scale_floor(SIGNAL_ROW_GAP, self.scale, 5)
        vol_h = scale_floor(SIGNAL_NOTCH_CELL_H, self.scale, 14)
        return body_top + chip_h + gap + vol_h

    def _chat_body_height(self):
        presets = self.chat_presets_provider()
        if not presets:
            return 0
        body_top = scale_floor(SECTION_BODY_TOP, self.scale, 4)
        btn_h = scale_floor(CHAT_BUTTON_H, self.scale, CHAT_BUTTON_FLOOR)
        gap = scale_floor(CHAT_GAP, self.scale, 4)
        rows = -(-len(presets) // CHAT_COLS)
        return body_top + rows * btn_h + (rows - 1) * gap

    def _layout_caps(self, caps, body):
        result = []
        if not caps:
            return result
        gap = scale_floor(CAP_GAP, self.scale, 5)
        top = body.y + scale_floor(SECTION_BODY_TOP, self.scale, 4)
        if self.caps_stacked:
            cap_h = scale_floor(CAP_H_REVIEW, self.scale, 28)
            y = top
            for cap in caps:
                result.append((cap, pg.Rect(body.x, y, body.width, cap_h)))
                y += cap_h + gap
            return result
        cap_h = scale_floor(CAP_H_GAME, self.scale, 30)
        cap_w = (body.width - gap * (len(caps) - 1)) / len(caps)
        x = float(body.x)
        for cap in caps:
            result.append((cap, pg.Rect(round(x), top, round(cap_w), cap_h)))
            x += cap_w + gap
        return result

    def _layout_signals(self, body):
        chips = REVIEW_SIGNAL_CHIPS if self.signals_provider()["review"] else SIGNAL_CHIPS
        body_top = scale_floor(SECTION_BODY_TOP, self.scale, 4)
        chip_h = scale_floor(SIGNAL_CHIP_H, self.scale, 20)
        gap = scale_floor(SIGNAL_CHIP_GAP, self.scale, 4)
        chip_w = (body.width - gap * (len(chips) - 1)) / len(chips)
        top = body.y + body_top
        x = float(body.x)
        self._signal_chips = []
        for chip in chips:
            self._signal_chips.append((chip, pg.Rect(round(x), top, round(chip_w), chip_h)))
            x += chip_w + gap
        vol_top = top + chip_h + scale_floor(SIGNAL_ROW_GAP, self.scale, 5)
        vol_h = scale_floor(SIGNAL_NOTCH_CELL_H, self.scale, 14)
        self._signal_vol_rect = pg.Rect(body.x, vol_top, body.width, vol_h)
        x0, cell_w, notch_gap, total = self._vol_geometry(body.width)
        self._signal_notch_step = cell_w + notch_gap
        self._signal_notch_band = pg.Rect(body.x + x0, vol_top, total, vol_h)

    def _layout_chat(self, body):
        presets = self.chat_presets_provider()
        self._chat_buttons = []
        if not presets:
            return
        body_top = scale_floor(SECTION_BODY_TOP, self.scale, 4)
        btn_h = scale_floor(CHAT_BUTTON_H, self.scale, CHAT_BUTTON_FLOOR)
        gap = scale_floor(CHAT_GAP, self.scale, 4)
        btn_w = (body.width - gap * (CHAT_COLS - 1)) / CHAT_COLS
        top = body.y + body_top
        for index in range(len(presets)):
            row, col = divmod(index, CHAT_COLS)
            x = body.x + col * (btn_w + gap)
            y = top + row * (btn_h + gap)
            self._chat_buttons.append(
                (index, pg.Rect(round(x), round(y), round(btn_w), btn_h)))

    def _vol_geometry(self, width):
        cell_w = scale_floor(SIGNAL_NOTCH_CELL_W, self.scale, 8)
        gap = scale_floor(SIGNAL_NOTCH_GAP, self.scale, 2)
        slot_w = notch_readout_slot_w(self.signal_num_font)
        readout_gap = scale_floor(SIGNAL_VOL_GAP, self.scale, 5)
        x0, total = notch_geometry(width, SIGNAL_NOTCH_COUNT, cell_w, gap, slot_w, readout_gap)
        return x0, cell_w, gap, total

    def _info_section_height(self):
        if self.game_info is None:
            return 0
        header_h = self.pill_font.get_height() + INFO_HEADER_PAD
        lines = self.game_info.get("lines", [])
        return header_h + self._info_line_height() * len(lines) + self.padding

    def _info_line_height(self):
        return self.font.get_linesize() + 2

    def set_game_info(self, info):
        self.game_info = info
        if self._last_outer_rect is not None:
            self.set_rect(self._last_outer_rect, self.scale)

    def reset_for_new_game(self):
        self.scroll_offset = 0
        self._total_rows = 0
        self._last_seen_total_rows = 0
        self.scroll.cancel()
        self.scroll.last_activity_ms = 0
        self._last_review_ply = None
        self._marquee_off = 0.0
        self._move_rows_cache = None

    def draw_menu(self):
        self.scroll.tick()
        prev_clip = self.window.get_clip()
        self.window.set_clip(self.outer_rect)
        self.window.blit(
            cut_rect_surface(self.outer_rect.size, scale_floor(CARD_CUT, self.scale, 10),
                             Colors.surface, border=Colors.border, border_width=1,
                             corners=("tr",)),
            self.outer_rect.topleft)
        if self.game_info is not None and self.info_rect.height > 0:
            self._draw_game_info(self.info_rect)
        self.window.blit(
            rounded_rect_surface(self.moves_rect.size,
                                 scale_floor(LOG_RADIUS, self.scale, 6), Colors.well_deep),
            self.moves_rect.topleft)
        self._draw_moves(self.moves_rect)
        self.scroll.draw_thumb(self.window)
        self._draw_sections()
        self.window.set_clip(prev_clip)

    def _draw_game_info(self, rect):
        info = self.game_info
        header_h = self.pill_font.get_height() + INFO_HEADER_PAD
        cx = rect.x
        cy = rect.y + header_h // 2
        mode = info.get("mode")
        if mode:
            cx = self._draw_mode_pill(mode.upper(), cx, cy) + 10
        tc = info.get("time_control")
        if tc:
            tc_surf = render_text(self.font, tc, Colors.text)
            self.window.blit(tc_surf, (cx, cy - tc_surf.get_height() / 2))
            cx += tc_surf.get_width() + 10
        rnd = info.get("round")
        if rnd:
            rnd_surf = render_text(self.round_font, f"ROUND {rnd}", Colors.text_muted)
            rnd_right = rect.right - scale_floor(ROUND_RIGHT_PAD, self.scale, 6)
            sep_x = rnd_right - rnd_surf.get_width() - 12
            pg.draw.line(self.window, Colors.border,
                         (sep_x, cy - rnd_surf.get_height() // 2),
                         (sep_x, cy + rnd_surf.get_height() // 2))
            self.window.blit(rnd_surf, (rnd_right - rnd_surf.get_width(),
                                        cy - rnd_surf.get_height() / 2))
        line_h = self._info_line_height()
        for i, line in enumerate(info.get("lines", [])):
            surf = render_text(self.font, line, Colors.text_dim)
            max_w = rect.width
            if surf.get_width() > max_w > 0:
                surf = surf.subsurface(pg.Rect(0, 0, max_w, surf.get_height()))
            self.window.blit(surf, (rect.x, rect.y + header_h + i * line_h))

    def _draw_mode_pill(self, text, x, cy):
        return draw_pill(self.window, text, x, cy, self.pill_font)

    def handle_click(self, pos):
        disabled = self.disabled_keys_provider()
        for key, rect in self.button_rects.items():
            if rect.collidepoint(pos):
                if key in disabled:
                    return True
                callback = self.callbacks.get(key)
                if callback is not None:
                    if self.sounds is not None:
                        self.sounds.play_cap_press()
                    self.suppress_click()
                    callback()
                return True
        signal = self._handle_signal_click(pos)
        if signal is not None:
            return signal
        chat = self._handle_chat_click(pos)
        if chat is not None:
            return chat
        for block in self._section_blocks:
            if block.header.collidepoint(pos):
                self.suppress_click()
                self.toggle_section(block.key)
                return True
        if self.board is None or not self.moves_rect.collidepoint(pos):
            return False
        for cell_rect, ply in self._move_cell_hits:
            if not cell_rect.collidepoint(pos):
                continue
            self.board.jump_to_review_ply(ply)
            return True
        return False

    def handle_scroll(self, pos, dy):
        return self.scroll.handle_wheel(pos, dy)

    def handle_press(self, pos):
        return self.scroll.handle_press(pos) is not None

    def handle_motion(self, pos):
        return self.scroll.handle_motion(pos)

    def handle_release(self, pos):
        return self.scroll.handle_release()

    def _move_rows(self, history, whiffs):
        key = (len(history), tuple(sorted((ply, len(v)) for ply, v in whiffs.items())))
        if self._move_rows_cache is None or self._move_rows_cache[0] != key:
            self._move_rows_cache = (key, *self._build_move_rows(history, whiffs))
        self._pair_to_row = self._move_rows_cache[2]
        return self._move_rows_cache[1]

    def _build_move_rows(self, history, whiffs):
        rows = []
        pair_to_row = {}
        for pair_idx, (number, white_entry, black_entry) in enumerate(iter_move_pairs(history)):
            pair_to_row[pair_idx] = len(rows)
            rows.append(("pair", pair_idx, number, white_entry, black_entry))
            white_ply = pair_idx * 2 + 1
            black_ply = pair_idx * 2 + 2 if black_entry is not None else None
            white_whiffs = whiffs.get(white_ply) or []
            black_whiffs = (whiffs.get(black_ply) or []) if black_ply is not None else []
            for k in range(max(len(white_whiffs), len(black_whiffs))):
                rows.append((
                    "whiff",
                    white_whiffs[k] if k < len(white_whiffs) else None,
                    black_whiffs[k] if k < len(black_whiffs) else None))
        return rows, pair_to_row

    def _draw_log_header(self, rect):
        pad = self.padding
        label = render_text(self.micro_font, "SHOT LOG", Colors.text_muted)
        count = render_text(self.micro_font, f"{len(self.match.move_history)} PLY",
                            Colors.text_muted)
        ly = rect.y + scale_floor(LOG_HEADER_TOP, self.scale, 6)
        self.window.blit(label, (rect.x + pad, ly))
        self.window.blit(count, (rect.right - pad - count.get_width(), ly))
        cursor = ly + label.get_height()
        debut = self.debut_provider()
        if debut is not None:
            cursor = self._draw_debut_row(
                rect, debut, cursor + scale_floor(DEBUT_ROW_GAP, self.scale, 3))
        else:
            self._marquee_off = 0.0
        sep_y = cursor + scale_floor(LOG_SEP_GAP, self.scale, 4)
        self.window.blit(dashed_hline(rect.width - 2 * pad, Colors.border),
                         (rect.x + pad, sep_y))
        return sep_y + scale_floor(LOG_ROWS_GAP, self.scale, 4) - rect.y

    def _draw_debut_row(self, rect, debut, y):
        pad = self.padding
        _, name = debut
        name_surf = render_text(self.debut_name_font, name.upper(), Colors.text_dim)
        row_h = name_surf.get_height()
        name_x = rect.x + pad
        avail = rect.right - pad - name_x
        name_y = y
        text_w = name_surf.get_width()
        if text_w <= avail or avail <= 0:
            self._marquee_off = 0.0
            self.window.blit(name_surf, (name_x, name_y))
            return y + row_h
        row_rect = pg.Rect(name_x, y, rect.width - 2 * pad, row_h)
        hovered = row_rect.collidepoint(pg.mouse.get_pos())
        target = float(text_w - avail) if hovered else 0.0
        self._marquee_off += (target - self._marquee_off) * MARQUEE_EASE
        prev_clip = self.window.get_clip()
        clip = pg.Rect(name_x, y, avail, row_h)
        if prev_clip is not None:
            clip = clip.clip(prev_clip)
        self.window.set_clip(clip)
        self.window.blit(name_surf, (name_x - int(self._marquee_off), name_y))
        self.window.set_clip(prev_clip)
        return y + row_h

    def _draw_moves(self, rect):
        header_h = self._draw_log_header(rect)
        history = self.match.move_history
        line_h = self.moves_font.get_linesize() + 6
        self._line_h = line_h
        rows_top = rect.y + header_h
        self._max_lines = max(int((rect.bottom - self.padding - rows_top) // line_h), 0)

        rows = self._move_rows(history, self.whiffs_provider())
        self._total_rows = len(rows)
        self._content_px = self._total_rows * line_h
        self._moves_viewport = pg.Rect(rect.x, rows_top, rect.width,
                                       self._max_lines * line_h)

        if (not self.scroll.is_active()
                and self._last_seen_total_rows
                and self._total_rows > self._last_seen_total_rows
                and self.scroll_offset > 0):
            self.scroll_offset += self._total_rows - self._last_seen_total_rows
        self._last_seen_total_rows = self._total_rows

        max_offset = max(0, self._total_rows - self._max_lines)
        self.scroll_offset = min(self.scroll_offset, max_offset)

        if not self.scroll.is_active():
            self._reveal_active_ply_on_nav()

        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)

        active_ply = self._active_ply(len(history))
        self._move_cell_hits = []

        char_w, _ = self.font.size("0")
        prefix_w = char_w * MOVE_PREFIX_CHARS
        cell_pad = MOVE_CELL_PAD
        inner_w = rect.width - 2 * self.padding
        cell_w = max((inner_w - prefix_w) // 2 - cell_pad, char_w * MOVE_MIN_CELL_CHARS)

        for i, row_idx in enumerate(range(start, end)):
            row = rows[row_idx]
            row_y = rows_top + i * line_h
            row_x = rect.x + self.padding
            white_x = row_x + prefix_w
            black_x = white_x + cell_w + cell_pad
            if row[0] == "whiff":
                self._draw_whiff(white_x, row_y, cell_w, line_h, row[1])
                self._draw_whiff(black_x, row_y, cell_w, line_h, row[2])
                continue
            _, pair_idx, number, white_entry, black_entry = row
            white_ply = pair_idx * 2 + 1
            black_ply = pair_idx * 2 + 2 if black_entry is not None else None

            prefix_surf = render_text(self.font, f"{number:>3}.", Colors.text_muted)
            self.window.blit(prefix_surf, (row_x, row_y + (line_h - prefix_surf.get_height()) // 2))

            white_cell = pg.Rect(white_x, row_y, cell_w, line_h)
            self._draw_move_cell(white_cell, white_entry, active_ply == white_ply)
            self._move_cell_hits.append((white_cell, white_ply))

            if black_entry is not None:
                black_cell = pg.Rect(black_x, row_y, cell_w, line_h)
                self._draw_move_cell(black_cell, black_entry, active_ply == black_ply)
                self._move_cell_hits.append((black_cell, black_ply))

    def _whiff_surface(self, san):
        key = (san, self.moves_font.get_height())

        def build():
            surf = self.moves_font.render(san, True, pg.Color(Colors.loss))
            surf.set_alpha(WHIFF_ALPHA)
            return surf
        return memoized_surface(_WHIFF_CACHE, key, build)

    def _draw_whiff(self, x, y, w, line_h, whiff):
        if whiff is None:
            return
        surf = self._whiff_surface(whiff[1])
        max_w = w - 8
        draw_w = surf.get_width()
        area = None
        if draw_w > max_w > 0:
            draw_w = max_w
            area = pg.Rect(0, 0, max_w, surf.get_height())
        self.window.blit(surf, (x + 4, y + (line_h - surf.get_height()) // 2), area=area)
        strike_y = y + line_h // 2
        pg.draw.line(self.window, pg.Color(Colors.loss),
                     (x + 4, strike_y), (x + 4 + draw_w, strike_y), 1)

    def _reveal_active_ply_on_nav(self):
        review_ply = self.board.review_ply if self.board is not None else None
        if review_ply == self._last_review_ply:
            return
        self._last_review_ply = review_ply
        if review_ply is None or review_ply <= 0:
            return
        pair_idx = (review_ply - 1) // 2
        self.scroll_offset = self._scroll_offset_to_show_row(
            self._pair_to_row.get(pair_idx, pair_idx))

    def _draw_move_cell(self, rect, entry, active):
        if active:
            self.window.blit(
                cut_rect_surface(rect.size, scale_floor(MOVE_CELL_CUT, self.scale, 5),
                                 Colors.surface_active, border=Colors.accent,
                                 border_width=1, corners=("tr",)),
                rect.topleft)
        color = Colors.text if active else Colors.text_dim
        surf = render_text(self.moves_font, entry.san, color)
        self.window.blit(surf, (rect.x + 4, rect.centery - surf.get_height() / 2))

    def _active_ply(self, history_len):
        if self.board is not None and self.board.review_ply is not None:
            return self.board.review_ply
        return history_len

    def _scroll_offset_to_show_row(self, row_idx):
        if self._max_lines <= 0:
            return self.scroll_offset
        max_offset = max(0, self._total_rows - self._max_lines)
        end = self._total_rows - self.scroll_offset
        start = max(0, end - self._max_lines)
        if start <= row_idx < end:
            return self.scroll_offset
        if row_idx >= end:
            new_end = row_idx + 1
        else:
            new_end = row_idx + self._max_lines
        new_offset = self._total_rows - new_end
        return max(0, min(new_offset, max_offset))

    def toggle_section(self, key):
        now = pg.time.get_ticks()
        cur = self._chevron_frac(key, now)
        SECTION_OPEN[key] = not section_open(key)
        env.set_rail_section_open(key, SECTION_OPEN[key])
        target = 1.0 if SECTION_OPEN[key] else 0.0
        self._chevron_anim[key] = (now, cur, target)
        if self._last_outer_rect is not None:
            self.set_rect(self._last_outer_rect, self.scale)
        if self.sounds is not None:
            self.sounds.play_section_toggle()

    def _draw_sections(self):
        now = pg.time.get_ticks()
        self.rail_tooltip.begin_frame()
        for block in self._section_blocks:
            self._draw_divider(block)
            self._draw_section_header(block, now)
            self.rail_tooltip.register(
                ("section", block.key), block.header, SECTION_TOOLTIPS[block.key])
        self._draw_caps()
        self._draw_signals()
        self._draw_chat()
        self.rail_tooltip.draw(
            self.window, self.outer_rect, self.scale, now, self.tooltip_font)

    def _draw_divider(self, block):
        self.window.blit(dashed_hline(block.header.width, Colors.border),
                         (block.header.x, block.divider_y))

    def _draw_section_header(self, block, now):
        header = block.header
        label = render_text(self.section_font, SECTION_LABELS[block.key], Colors.text_muted)
        self.window.blit(label, (header.x, header.centery - label.get_height() // 2))
        frac = self._chevron_frac(block.key, now)
        chev_h = scale_floor(SECTION_CHEVRON_H, self.scale, 5)
        chev = rotated_chevron_surface(chev_h, Colors.text_muted, 90.0 * (1.0 - frac))
        self.window.blit(chev, (header.right - chev.get_width(),
                                header.centery - chev.get_height() // 2))

    def _chevron_frac(self, key, now):
        target = 1.0 if section_open(key) else 0.0
        anim = self._chevron_anim.get(key)
        if anim is None:
            return target
        start_ms, from_frac, to_frac = anim
        t = (now - start_ms) / SECTION_CHEVRON_MS
        if t >= 1.0:
            return to_frac
        if t <= 0.0:
            return from_frac
        return from_frac + (to_frac - from_frac) * smoothstep(t)

    def _draw_caps(self):
        if not self._cap_draws:
            return
        disabled = self.disabled_keys_provider()
        mouse = pg.mouse.get_pos()
        mouse_down = pg.mouse.get_pressed()[0]
        for cap, rect in self._cap_draws:
            is_disabled = cap.key in disabled
            hovered = (not is_disabled) and rect.collidepoint(mouse)
            pressed = hovered and mouse_down
            fill = (Colors.surface if is_disabled
                    else Colors.surface_hover if hovered else Colors.surface_raised)
            self.window.blit(
                cut_rect_surface(rect.size, scale_floor(CAP_CUT, self.scale, 5), fill,
                                 border=Colors.border, border_width=1, corners=("tr",)),
                rect.topleft)
            off = 1 if pressed else 0
            if self.caps_stacked:
                self._draw_cap_stacked(cap, rect, is_disabled, off)
            else:
                self._draw_cap_icon(cap, rect, is_disabled, off)
            self.rail_tooltip.register(("cap", cap.key), rect, cap.tooltip)

    def _draw_cap_icon(self, cap, rect, faded, off):
        fg = self._cap_foreground(cap, faded)
        self.window.blit(fg, (rect.centerx - fg.get_width() // 2,
                              rect.centery - fg.get_height() // 2 + off))

    def _draw_cap_stacked(self, cap, rect, faded, off):
        fg = self._cap_foreground(cap, faded)
        pad = scale_floor(CAP_LABEL_PAD, self.scale, 6)
        icon_x = rect.x + pad
        self.window.blit(fg, (icon_x, rect.centery - fg.get_height() // 2 + off))
        color = Colors.text_muted if faded else Colors.rail_icon
        label = render_text(self.cap_label_font, cap.label, color)
        self.window.blit(label, (icon_x + fg.get_width() + pad,
                                 rect.centery - label.get_height() // 2 + off))

    def _cap_foreground(self, cap, faded):
        box = self._cap_fg_box
        key = (cap.key, box, faded)

        def build():
            if cap.glyph:
                font = self._glyph_fonts[(cap.glyph_pt, cap.glyph_bold)]
                surf = font.render(cap.glyph, True, pg.Color(Colors.rail_icon))
            else:
                surf = pg.Surface((box, box), pg.SRCALPHA)
                CAP_ICON_FUNCS[cap.icon](surf, surf.get_rect(), Colors.rail_icon)
            ink = surf.get_bounding_rect()
            canvas = pg.Surface(surf.get_size(), pg.SRCALPHA)
            canvas.blit(surf, (surf.get_width() // 2 - ink.centerx,
                               surf.get_height() // 2 - ink.centery))
            if faded:
                canvas.set_alpha(FADED_ICON_ALPHA)
            return canvas
        return memoized_surface(_CAP_FG_CACHE, key, build)

    def _draw_signals(self):
        if not self._signal_chips:
            return
        state = self.signals_provider()
        for chip, rect in self._signal_chips:
            on = bool(state.get(chip.state_key))
            disabled = chip.key == "share" and not state.get("share_enabled")
            self.window.blit(
                self._chip_surface(chip, rect.width, rect.height, on, disabled),
                rect.topleft)
            self.rail_tooltip.register(("signal", chip.key), rect, chip.tooltip)
        self._draw_vol_row(state)

    def _draw_chat(self):
        if not self._chat_buttons:
            return
        presets = self.chat_presets_provider()
        cooling = self.chat_cooldown_provider()
        mouse = pg.mouse.get_pos()
        mouse_down = pg.mouse.get_pressed()[0]
        for index, rect in self._chat_buttons:
            if index >= len(presets):
                continue
            label = presets[index]
            hovered = (not cooling) and rect.collidepoint(mouse)
            pressed = hovered and mouse_down
            self.window.blit(
                self._chat_button_surface(rect.size, label, hovered, pressed, cooling),
                rect.topleft)
            tooltip = "CHAT COOLING DOWN" if cooling else f"SEND: {label}"
            self.rail_tooltip.register(("chat", index), rect, tooltip)

    def _chat_button_surface(self, size, label, hovered, pressed, cooling):
        key = (tuple(size), label, hovered, pressed, cooling, self.chat_font.get_height())

        def build():
            fill = Colors.surface_hover if hovered else Colors.surface_raised
            surf = cut_rect_surface(size, scale_floor(CHAT_CUT, self.scale, 5), fill,
                                    border=Colors.border, border_width=1,
                                    corners=("tr",)).copy()
            color = Colors.text_muted if cooling else Colors.rail_icon
            text = render_text(self.chat_font, label, color)
            off = 1 if pressed else 0
            surf.blit(text, (size[0] // 2 - text.get_width() // 2,
                             size[1] // 2 - text.get_height() // 2 + off))
            if cooling:
                surf.set_alpha(CHAT_DIM_ALPHA)
            return surf
        return memoized_surface(_CHAT_CACHE, key, build)

    def _handle_chat_click(self, pos):
        if not self._chat_buttons:
            return None
        cooling = self.chat_cooldown_provider()
        for index, rect in self._chat_buttons:
            if not rect.collidepoint(pos):
                continue
            if cooling:
                return True
            callback = self.callbacks.get("quick_chat")
            if callback is not None:
                if self.sounds is not None:
                    self.sounds.play_cap_press()
                self.suppress_click()
                callback(index)
            return True
        return None

    def _chip_surface(self, chip, w, h, on, disabled):
        key = ("chip", chip.key, w, h, on, disabled, self.chip_font.get_height())

        def build():
            if disabled:
                surf = rounded_rect_surface((w, h), h, Colors.surface_raised).copy()
                surf.blit(dashed_rounded_rect_surface((w, h), h, Colors.border), (0, 0))
                dot_color, label_color = Colors.border_strong, Colors.text_muted
            else:
                border = (chip.on_color + SIGNAL_ON_BORDER_ALPHA) if on else Colors.border
                surf = rounded_rect_surface(
                    (w, h), h, Colors.surface_raised, border=border, border_width=1).copy()
                dot_color = chip.on_color if on else Colors.border_strong
                label_color = Colors.text if on else Colors.text_muted
            dot = circle_surface(scale_floor(SIGNAL_CHIP_DOT, self.scale, 5), dot_color)
            label = render_text(self.chip_font, chip.label, label_color)
            inner = scale_floor(SIGNAL_CHIP_DOT_GAP, self.scale, 3)
            gx = (w - (dot.get_width() + inner + label.get_width())) // 2
            label_y = (h - label.get_height()) // 2
            cap_ink = self.chip_font.render("X", True, (255, 255, 255)).get_bounding_rect()
            dot_y = round(label_y + cap_ink.centery - dot.get_height() / 2)
            surf.blit(dot, (gx, dot_y))
            surf.blit(label, (gx + dot.get_width() + inner, label_y))
            if disabled:
                surf.set_alpha(SIGNAL_SHARE_DISABLED_ALPHA)
            return surf
        return memoized_surface(_SIGNAL_CACHE, key, build)

    def _draw_vol_row(self, state):
        rect = self._signal_vol_rect
        if rect.width <= 0:
            return
        vol = max(0.0, min(1.0, float(state.get("volume", 0.0))))
        self.window.blit(
            self._vol_surface(rect.width, rect.height, vol, not state.get("sound_on")),
            rect.topleft)
        self.rail_tooltip.register(("signal", "vol"), rect, SIGNAL_VOL_TOOLTIP)

    def _vol_surface(self, w, h, vol, dimmed):
        filled = int(round(vol * SIGNAL_NOTCH_COUNT))
        pct = int(round(vol * 100))
        key = ("vol", w, h, filled, pct, dimmed,
               self.micro_font.get_height(), self.signal_num_font.get_height())

        def build():
            surf = pg.Surface((w, h), pg.SRCALPHA)
            label = render_text(self.micro_font, "VOL", Colors.text_muted)
            surf.blit(label, (0, (h - label.get_height()) // 2))
            x0, cell_w, gap, _ = self._vol_geometry(w)
            cut = scale_floor(SIGNAL_NOTCH_CUT, self.scale, 3)
            for i in range(SIGNAL_NOTCH_COUNT):
                cx = x0 + i * (cell_w + gap)
                if i < filled:
                    cell = cut_rect_surface((cell_w, h), cut, Colors.accent, corners=("tr",))
                else:
                    cell = cut_rect_surface((cell_w, h), cut, Colors.surface_raised,
                                            border=Colors.border, border_width=1,
                                            corners=("tr",))
                surf.blit(cell, (cx, 0))
            readout = render_text(self.signal_num_font, f"{pct}%", Colors.text_dim)
            surf.blit(readout, (w - readout.get_width(), (h - readout.get_height()) // 2))
            if dimmed:
                surf.set_alpha(SIGNAL_DIM_ALPHA)
            return surf
        return memoized_surface(_SIGNAL_CACHE, key, build)

    def _handle_signal_click(self, pos):
        if not self._signal_chips:
            return None
        state = self.signals_provider()
        for chip, rect in self._signal_chips:
            if not rect.collidepoint(pos):
                continue
            if chip.key == "share" and not state.get("share_enabled"):
                blocked = self.callbacks.get("share_blocked")
                if blocked is not None:
                    blocked()
                return True
            callback = self.callbacks.get(chip.callback)
            if callback is not None:
                callback()
            if self.sounds is not None:
                self.sounds.play_chip_toggle()
            self.suppress_click()
            return True
        if self._signal_notch_band.collidepoint(pos):
            if state.get("sound_on"):
                self._handle_vol_click(pos, state)
            return True
        return None

    def _handle_vol_click(self, pos, state):
        target = notch_value_from_click(
            pos[0], self._signal_notch_band.x, self._signal_notch_step,
            SIGNAL_NOTCH_COUNT, state.get("volume", 0.0))
        callback = self.callbacks.get("set_volume")
        if callback is not None:
            callback(target)
        if self.sounds is not None:
            self.sounds.play_vol_notch()
        self.suppress_click()
