import math
from collections.abc import Callable
from typing import cast

import pygame as pg

from chessshootout.backend.utils import BOARD_SIZE, Square
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.skillcheck.controller import SkillCheckController
from chessshootout.frontend.skillcheck.juice import (
    TORN_MAX_TIER, Trauma, Hitstop, sakurai_vibrate, torn_sprite)
from chessshootout.frontend.visual.cache import (
    new_size_cache, memoized_surface, render_text)
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import (
    chevron_surface, circle_surface, cosine_pulse, cut_rect_surface, smoothstep,
    strike_pip_surface, supersample)
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_display_font
from chessshootout.frontend.visual.tween import out_back
from chessshootout.skillcheck.combo import (
    ComboChallenge, COMBO_INTRO_MS, COMBO_WRONG_LOCKOUT_MS, COMBO_MAX_WRONGS,
    COMBO_MIN_INTER_PRESS_MS)
from chessshootout.skillcheck.online import SKILLCHECK_HUMAN_FLOOR_MS
from chessshootout.skillcheck.rng import seeded_floats
from chessshootout.skillcheck.wheel import SKILLCHECK_DEADLINE_MS

COMBO_TIME_LIMIT_MS = SKILLCHECK_DEADLINE_MS
COMBO_VIEW_RESULT_HOLD_MS = 420

COMBO_VIEW_PAD_RADIUS_FRAC = 1.35
COMBO_VIEW_PAD_RADIUS_MIN_PX = 72
COMBO_VIEW_HUB_FRAC = 0.22
COMBO_VIEW_SEP_W_FRAC = 0.04
COMBO_VIEW_SEP_W_MIN_PX = 2
COMBO_VIEW_CHEVRON_FRAC = 0.34
COMBO_VIEW_CHEVRON_DIST_FRAC = 0.60
COMBO_VIEW_HOVER_ALPHA = 45

COMBO_VIEW_STRIP_GAP_FRAC = 0.55
COMBO_VIEW_STRIP_CHEVRON_FRAC = 0.34
COMBO_VIEW_STRIP_CURRENT_SCALE = 1.35

COMBO_VIEW_CHIP_FILL = Colors.well_deep
COMBO_VIEW_CHIP_ALPHA = 215
COMBO_VIEW_CHIP_DONE_ALPHA = 140
COMBO_VIEW_CHIP_BORDER = Colors.border_strong
COMBO_VIEW_CHIP_NEXT_BORDER = Colors.accent
COMBO_VIEW_CHIP_PAD_FRAC = 0.09
COMBO_VIEW_CHIP_PAD_MIN_PX = 4
COMBO_VIEW_CHIP_GAP_FRAC = 0.10
COMBO_VIEW_CHIP_GAP_MIN_PX = 4
COMBO_VIEW_CHIP_CUT_FRAC = 0.22
COMBO_VIEW_CHIP_CORNERS = ("tr", "bl")

COMBO_VIEW_PIP_GAP_FRAC = 0.34
COMBO_VIEW_PIP_SIZE_FRAC = 0.22
COMBO_VIEW_PIP_ROW_GAP_FRAC = 0.5
COMBO_VIEW_PIP_STRIKE_LW_FRAC = 0.12
COMBO_VIEW_PIP_STRIKE_PAD_FRAC = 0.28
COMBO_VIEW_PIP_RING_LW_FRAC = 0.1

COMBO_VIEW_SCRIM_ALPHA = 206
COMBO_VIEW_SPOT_START_FRAC = 1.05
COMBO_VIEW_SPOT_END_FRAC = 1.2
COMBO_VIEW_SPOT_FEATHER_STEPS = 3
COMBO_VIEW_SPOT_FEATHER_FRAC = 0.18
COMBO_VIEW_SPOT_WARN_FRAC = 0.2
COMBO_VIEW_SPOT_RIM_W_FRAC = 0.03
COMBO_VIEW_SPOT_RIM_W_MIN_PX = 2
COMBO_VIEW_SPOT_WARN_PULSE_MS = 280.0
COMBO_VIEW_SPOT_WARN_FLICKER_MIN = 0.5

COMBO_VIEW_BPM_BASE = 125.0
COMBO_VIEW_BPM_RAMP = 55.0
COMBO_VIEW_DANCE_ALPHA = 70

COMBO_VIEW_RECEPTOR_FLASH_MS = 100.0
COMBO_VIEW_RECEPTOR_FLASH_ALPHA = 255
COMBO_VIEW_ARROW_FLY_MS = 120.0
COMBO_VIEW_ARROW_FLY_RISE_FRAC = 0.9
COMBO_VIEW_SPARK_MIN = 5
COMBO_VIEW_SPARK_MAX = 8
COMBO_VIEW_SPARK_MS = 260.0
COMBO_VIEW_SPARK_REACH_FRAC = 0.7
COMBO_VIEW_SPARK_SIZE_FRAC = 0.05
COMBO_VIEW_WHITE_FLASH_MS = 80.0
COMBO_VIEW_WHITE_FLASH_ALPHA = 150

COMBO_VIEW_JUDGE_BRILLIANT_MS = 350.0
COMBO_VIEW_JUDGE_CLEAN_MS = 700.0
COMBO_VIEW_JUDGE_HOLD_MS = 520.0
COMBO_VIEW_JUDGE_FONT_FRAC = 0.5
COMBO_VIEW_JUDGE_RISE_FRAC = 0.4
COMBO_VIEW_JUDGE_OFFSET_FRAC = 0.7
COMBO_VIEW_JUDGE_OFFSET_MIN_PX = 16
COMBO_VIEW_BRILLIANT_TEXT = "BRILLIANT!"
COMBO_VIEW_CLEAN_TEXT = "CLEAN!"
COMBO_VIEW_FAIL_TEXT = "BLUNDER??"

COMBO_VIEW_TRAUMA_CORRECT = 0.2
COMBO_VIEW_TRAUMA_MAX_OFFSET = 6.0

COMBO_VIEW_WIN_HITSTOP_MS = 200.0
COMBO_VIEW_WIN_FLASH_MS = 80.0
COMBO_VIEW_WIN_FLASH_ALPHA = 160
COMBO_VIEW_TORN_MS = 480.0
COMBO_VIEW_DEFLATE_FLOOR = 0.35
COMBO_VIEW_DEFLATE_SPAN = 0.65

COMBO_VIEW_WRONG_HITSTOP_MS = 70.0
COMBO_VIEW_WRONG_FLASH_MS = 220.0
COMBO_VIEW_WRONG_FLASH_ALPHA = 220
COMBO_VIEW_WIGGLE_MS = 260.0
COMBO_VIEW_WIGGLE_AMP_FRAC = 0.12
COMBO_VIEW_PAD_DIM_ALPHA = 130

COMBO_VIEW_CONFETTI = ("🎉", "✨", "🔥")
COMBO_VIEW_CONFETTI_COUNT = 14
COMBO_VIEW_CONFETTI_MS = 900.0
COMBO_VIEW_CONFETTI_SPREAD_FRAC = 2.2
COMBO_VIEW_CONFETTI_GRAV_FRAC = 2.6
COMBO_VIEW_CONFETTI_SIZE_FRAC = 0.34
COMBO_VIEW_CONFETTI_SPEED_JITTER = (0.5, 1.0)

COMBO_VIEW_STREAK_FIRE = 3
COMBO_VIEW_FIRE_EMOJI = "🔥"
COMBO_VIEW_FIRE_SIZE_FRAC = 1.3
COMBO_VIEW_FIRE_PULSE_MS = 140.0
COMBO_VIEW_FIRE_ALPHA_MIN = 120
COMBO_VIEW_FIRE_ALPHA_MAX = 230
COMBO_VIEW_FIRE_BOB_FRAC = 0.12

COMBO_VIEW_BOB_AMP_FRAC = 0.12
COMBO_VIEW_SHUFFLE_AMP_FRAC = 0.06
COMBO_VIEW_SHUFFLE_PERIOD = 90.0

COMBO_VIEW_INTRO_FADE_MS = 200.0
COMBO_VIEW_INTRO_RISE_FRAC = 0.18
COMBO_VIEW_INTRO_ARROW_MS = 140.0
COMBO_VIEW_INTRO_STAGGER_MS = 35.0
COMBO_VIEW_INTRO_DROP_FRAC = 0.35

COMBO_VIEW_PRESS_NUDGE_FRAC = 0.05
COMBO_VIEW_PRESS_NUDGE_MS = 90.0

COMBO_VIEW_JUDGE_FADE_FRAC = 0.45

COMBO_VIEW_FIRE_IGNITE_MS = 220.0
COMBO_VIEW_FIRE_IGNITE_RISE_FRAC = 0.8
COMBO_VIEW_TRAUMA_IGNITE = 0.25

COMBO_VIEW_EXIT_FADE_MS = 200.0

COMBO_VIEW_FLASH_WHITE = Colors.white

_RECEPTOR_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_DIR_ANGLE = {"up": 0, "left": 90, "down": 180, "right": -90}
_DIR_WEDGE_SPAN = {
    "up": (-0.75, -0.25), "right": (-0.25, 0.25), "down": (0.25, 0.75), "left": (0.75, 1.25),
}
_WEDGE_ARC_SEGS = 20
_KEY_DIRECTION = {
    pg.K_UP: "up", pg.K_w: "up", pg.K_DOWN: "down", pg.K_s: "down",
    pg.K_LEFT: "left", pg.K_a: "left", pg.K_RIGHT: "right", pg.K_d: "right",
}

_JUDGE_BRILLIANT = "brilliant"
_JUDGE_CLEAN = "clean"
_JUDGE_FAIL = "fail"
_JUDGE_TEXT = {
    _JUDGE_BRILLIANT: COMBO_VIEW_BRILLIANT_TEXT,
    _JUDGE_CLEAN: COMBO_VIEW_CLEAN_TEXT,
    _JUDGE_FAIL: COMBO_VIEW_FAIL_TEXT,
}
_JUDGE_COLOR = {
    _JUDGE_BRILLIANT: Colors.accent_hi,
    _JUDGE_CLEAN: Colors.win,
    _JUDGE_FAIL: Colors.loss,
}

_CHIP_DONE = "done"
_CHIP_NEXT = "next"
_CHIP_IDLE = "idle"
_CHIP_BAKED_ALPHA = {
    _CHIP_DONE: COMBO_VIEW_CHIP_DONE_ALPHA,
    _CHIP_NEXT: COMBO_VIEW_CHIP_ALPHA,
    _CHIP_IDLE: COMBO_VIEW_CHIP_ALPHA,
}

_SPOT_BG = pg.Color(Colors.bg)
_SPOT_FILL_RGBA = (_SPOT_BG.r, _SPOT_BG.g, _SPOT_BG.b, COMBO_VIEW_SCRIM_ALPHA)
_SPOT_FEATHER_RGBA = tuple(
    (_SPOT_BG.r, _SPOT_BG.g, _SPOT_BG.b,
     int(COMBO_VIEW_SCRIM_ALPHA * k / (COMBO_VIEW_SPOT_FEATHER_STEPS + 1)))
    for k in range(COMBO_VIEW_SPOT_FEATHER_STEPS, 0, -1))
_SPOT_HOLE_RGBA = (0, 0, 0, 0)
_RIM_LOSS = pg.Color(Colors.loss)

_PAD_STATIC_CACHE = new_size_cache()
_DIR_CHEVRON_CACHE = new_size_cache()
_RECEPTOR_FILL_CACHE = new_size_cache()
_SOLID_CACHE = new_size_cache()
_FLASH_CACHE = new_size_cache()
_EMOJI_CACHE = new_size_cache()
_CHIP_CACHE = new_size_cache()


def _direction_chevron(size: int, color: str, direction: str) -> pg.Surface:
    """
    Draw one of the four arrows the Combo check is played with, pointing the
    way its prompt asks for. Every arrow the check shows comes from here --
    the run of prompts above the board, the faces of the pad, and the one that
    flies up on a correct press -- so they all read as the same symbol

    :param size: arrow height in pixels, before rotation
    :param color: ink colour as a hex token from Colors
    :param direction: one of up, down, left or right
    :returns: the shared arrow for that size, colour and direction
    """
    def build() -> pg.Surface:
        """
        Turn the upward arrow to face the asked-for way, the first time this
        exact arrow is wanted

        :returns: the finished arrow
        """
        base = chevron_surface(size, color, up=True)
        angle = _DIR_ANGLE[direction]
        return base if angle == 0 else pg.transform.rotate(base, angle)
    return memoized_surface(_DIR_CHEVRON_CACHE, (size, str(color), direction), build)


def _chip_surface(side: int, cut: int, state: str,
                  next_border: str = COMBO_VIEW_CHIP_NEXT_BORDER) -> pg.Surface:
    """
    Draw the cut-corner tile that sits behind one prompt in the run, in the
    same panel shape the rest of the game is built from. How that prompt
    stands is baked into the pixels -- prompts already hit are dimmed, the one
    owed now wears the accent outline -- so the row costs nothing per frame

    :param side: tile width and height in pixels
    :param cut: length of the sliced corner in pixels
    :param state: done, next or idle, which picks the outline and the baked
        opacity
    :param next_border: outline colour for the prompt owed now, muted in the
        read-only mirror of the opponent's check
    :returns: the shared tile for exactly that look
    """
    border = next_border if state == _CHIP_NEXT else COMBO_VIEW_CHIP_BORDER

    def build() -> pg.Surface:
        """
        Cut the panel and multiply the state's opacity into it, the first time
        this look is asked for

        :returns: the finished tile
        """
        surf = cut_rect_surface((side, side), cut, COMBO_VIEW_CHIP_FILL,
                                border=border, border_width=1,
                                corners=COMBO_VIEW_CHIP_CORNERS).copy()
        surf.fill((255, 255, 255, _CHIP_BAKED_ALPHA[state]), special_flags=pg.BLEND_RGBA_MULT)
        return surf
    return memoized_surface(_CHIP_CACHE, (side, cut, state, border), build)


def _pad_static(radius: int, hub_r: int) -> pg.Surface:
    """
    Draw the pad the player presses: a ring quartered into four receptors,
    each carrying a faint arrow, around a dead hub in the middle. Nothing on
    it moves, so it is drawn once per size and everything live -- the hover
    tint, the press flashes, the lockout dimming -- is laid over it

    :param radius: outer radius of the pad in pixels
    :param hub_r: radius of the dead centre, which belongs to no direction
    :returns: the shared pad art for that pair of radii
    """
    sep_w = max(int(radius * COMBO_VIEW_SEP_W_FRAC), COMBO_VIEW_SEP_W_MIN_PX)
    chev = max(int(radius * COMBO_VIEW_CHEVRON_FRAC), 6)

    def build() -> pg.Surface:
        """
        Draw the pad oversized and shrink it down for clean edges, then stamp
        the four arrows on, the first time this size is wanted

        :returns: the finished pad
        """
        def render(surf: pg.Surface, k: int) -> None:
            """
            Lay the pad's rings, quartering lines and hub onto the oversized
            canvas

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the pad
            """
            c = surf.get_width() / 2.0
            r = radius * k
            w = max(int(sep_w * k), 1)
            half = r * math.cos(math.pi / 4.0)
            pg.draw.circle(surf, pg.Color(Colors.surface_raised), (c, c), r)
            pg.draw.line(surf, pg.Color(Colors.border_strong),
                         (c - half, c - half), (c + half, c + half), w)
            pg.draw.line(surf, pg.Color(Colors.border_strong),
                         (c - half, c + half), (c + half, c - half), w)
            pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), r, w)
            pg.draw.circle(surf, pg.Color(Colors.surface), (c, c), hub_r * k)
            pg.draw.circle(surf, pg.Color(Colors.border_strong), (c, c), hub_r * k, w)
        base = supersample(2 * radius, render)
        for direction, (dx, dy) in _RECEPTOR_DIRS.items():
            arrow = _direction_chevron(chev, Colors.text_dim, direction)
            arrow.set_alpha(255)
            cx = radius + dx * radius * COMBO_VIEW_CHEVRON_DIST_FRAC
            cy = radius + dy * radius * COMBO_VIEW_CHEVRON_DIST_FRAC
            base.blit(arrow, arrow.get_rect(center=(int(cx), int(cy))))
        return base
    return memoized_surface(_PAD_STATIC_CACHE, (radius, hub_r), build)


def _wedge_overlay(radius: int, hub_r: int, direction: str, color: str) -> pg.Surface:
    """
    Fill one quarter of the pad, the shape every pad highlight is made from --
    the hover tint under the cursor, the accent flash on a correct press, the
    red one on a wrong press. It covers exactly the receptor a press is judged
    against, so what lights up is what was hit

    :param radius: outer radius of the pad in pixels
    :param hub_r: radius of the dead centre the wedge stops short of
    :param direction: which quarter to fill
    :param color: fill colour as a hex token from Colors
    :returns: the shared wedge for that geometry and colour
    """
    def build() -> pg.Surface:
        """
        Trace the quarter between its two radii and fill it, the first time
        this wedge is wanted

        :returns: the finished wedge
        """
        span = _DIR_WEDGE_SPAN[direction]
        a0, a1 = span[0] * math.pi, span[1] * math.pi

        def render(surf: pg.Surface, k: int) -> None:
            """
            Walk the outer arc out and the hub arc back, and fill what they
            enclose

            :param surf: oversized canvas being drawn on
            :param k: how many times bigger that canvas is than the pad
            """
            c = surf.get_width() / 2.0
            pts = []
            for i in range(_WEDGE_ARC_SEGS + 1):
                a = a0 + (a1 - a0) * i / _WEDGE_ARC_SEGS
                pts.append((c + radius * k * math.cos(a), c + radius * k * math.sin(a)))
            for i in range(_WEDGE_ARC_SEGS + 1):
                a = a1 + (a0 - a1) * i / _WEDGE_ARC_SEGS
                pts.append((c + hub_r * k * math.cos(a), c + hub_r * k * math.sin(a)))
            pg.draw.polygon(surf, pg.Color(color), pts)
        return supersample(2 * radius, render)
    return memoized_surface(
        _RECEPTOR_FILL_CACHE, (radius, hub_r, direction, str(color)), build)


def _solid_square(size: int, color: str) -> pg.Surface:
    """
    A plain filled square, used both for the tint that pulses over the board
    squares on the beat and for the sparks a correct press throws off. Cached,
    so neither effect allocates while it runs

    :param size: square width and height in pixels
    :param color: fill colour as a hex token from Colors
    :returns: the shared square for that size and colour
    """
    def build() -> pg.Surface:
        """
        Make the square the first time this size and colour are asked for

        :returns: the finished square
        """
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(color))
        return surf
    return memoized_surface(_SOLID_CACHE, (size, str(color)), build)


def _pip_surface(size: int, struck: bool) -> pg.Surface:
    """
    One of the strike pips under the pad, which tell the player how many wrong
    presses they have left before the check is lost. Whack-a-Mole draws the
    same pip, so both checks show the room for error in one language

    :param size: pip width and height in pixels
    :param struck: True once this wrong press has been spent
    :returns: the shared pip for that size and state
    """
    return strike_pip_surface(size, struck,
                              lw_frac=COMBO_VIEW_PIP_STRIKE_LW_FRAC,
                              pad_frac=COMBO_VIEW_PIP_STRIKE_PAD_FRAC,
                              ring_lw_frac=COMBO_VIEW_PIP_RING_LW_FRAC)


def _flash_layer(w: int, h: int) -> pg.Surface:
    """
    The white sheet thrown over the board for a few frames the moment the run
    is completed, the loudest cue the check gives that the capture is going
    through

    :param w: sheet width in pixels, normally the board's
    :param h: sheet height in pixels
    :returns: the shared sheet for that size
    """
    def build() -> pg.Surface:
        """
        Make the sheet the first time this size is asked for

        :returns: the finished sheet
        """
        surf = pg.Surface((max(int(w), 1), max(int(h), 1)))
        surf.fill(pg.Color(COMBO_VIEW_FLASH_WHITE))
        return surf
    return memoized_surface(_FLASH_CACHE, (int(w), int(h)), build)


def _emoji_sprite(char: str, size: int) -> pg.Surface | None:
    """
    Fetch one of the pre-rendered emoji the check celebrates with -- the
    streak flame over the prompts still to come, and the confetti on a win.
    The copy is deliberate: both are faded by setting alpha, which would
    otherwise scar the emoji cache the whole interface shares

    :param char: the emoji to draw
    :param size: sprite width and height in pixels
    :returns: this module's own copy of the sprite, or None when no artwork is
        bundled for that character
    """
    def build() -> pg.Surface | None:
        """
        Take the private copy the first time this emoji and size are asked for

        :returns: the copy, or None when the emoji has no artwork
        """
        base = emoji_surface(char, size)
        return base.copy() if base is not None else None
    return memoized_surface(_EMOJI_CACHE, (char, size), build)


def _victim_token(surface: pg.Surface | None) -> tuple[tuple[int, int], int] | None:
    """
    Boil the sprite of the piece being taken down to something hashable, so
    the torn artwork shown over it on a win is cached per piece instead of
    being shredded again every frame

    :param surface: the victim's sprite, None when the square holds no piece
    :returns: that sprite's size and a digest of its pixels, or None when
        there is no sprite
    """
    if surface is None:
        return None
    return (surface.get_size(), hash(pg.image.tobytes(surface, "RGBA")))


class ComboController(SkillCheckController):
    """
    The Combo mini-game: a run of directional prompts -- up, down, left,
    right -- the player has to press in order before the deadline. It is one
    of the four checks a capture can fire; hitting the whole run lands the
    capture, and COMBO_MAX_WRONGS wrong presses lose it and lock that move for
    the turn. Online it only draws and reports -- the server judges every
    press and hands the verdict back through resolve
    """

    challenge: ComboChallenge

    def __init__(self, challenge: ComboChallenge, cell_rect: pg.Rect, now_ms: int,
                 deadline_ms: float = COMBO_TIME_LIMIT_MS, *,
                 board_rect: pg.Rect | None = None,
                 geom: Callable[[Square | str], tuple[float, float]] | None = None,
                 victim_surface: pg.Surface | None = None,
                 attacker_surface: pg.Surface | None = None,
                 from_sq: Square | None = None, victim_sq: Square | None = None,
                 on_shot: Callable[..., None] | None = None, miss_count: int = 0,
                 progress: int = 0, passive: bool = False,
                 audio: SoundManager | None = None) -> None:
        """
        Set one Combo check up over the board and start it running. A check
        adopted mid-flight after a reconnect is handed the presses already
        made, so it picks the run up where it stood rather than starting again
        from the first prompt

        :param challenge: the run of prompts, built from the check's seed so
            both players see the same arrows in the same order
        :param cell_rect: board square the check is anchored on, which every
            size in the view is measured from
        :param now_ms: pygame ticks the check started at, backdated when time
            has already gone by
        :param deadline_ms: how long the whole run may take, normally
            SKILLCHECK_DEADLINE_MS or the smaller share a fast time control
            allows
        :param board_rect: the board in window pixels, which the spotlight and
            the win flash are sized to; None leaves both out
        :param geom: maps a board square to its centre in window pixels, used
            to place the two pieces and the lit floor
        :param victim_surface: sprite of the piece being taken, drawn by the
            check for as long as the board hides it
        :param attacker_surface: sprite of the capturing piece, hidden by the
            board for the same reason
        :param from_sq: square the capturing piece stands on
        :param victim_sq: square the piece being taken stands on, which is not
            the move's target square for an en-passant capture
        :param on_shot: reports one press to the server; None offline, where
            this controller is the judge
        :param miss_count: wrong presses already made, for a resumed check
        :param progress: prompts already hit, likewise
        :param passive: True for the read-only mirror of the opponent's check,
            which takes no input of its own
        :param audio: sound manager to cue from; silent in the mirror and when
            there is none
        """
        self._init_common(challenge, now_ms, deadline_ms, on_shot=on_shot, passive=passive,
                          audio=audio)
        self._progress = progress
        self._wrong_count = miss_count
        self._from_sq = from_sq
        self._victim_sq = victim_sq
        self._geom = geom
        self._board_rect = pg.Rect(board_rect) if board_rect is not None else None
        self._victim_src = victim_surface
        self._attacker_src = attacker_surface
        self._closed = False
        self._closed_at: int | None = None
        self._lockout_until = now_ms
        self._last_accept_ms: int | None = None
        self._torn_key = (hash(challenge.prompts), _victim_token(victim_surface))
        self._prompt_started_ms = now_ms + COMBO_INTRO_MS
        self._judgement: str | None = None
        self._judgement_at = now_ms
        self._brilliant_streak = 0
        self._fire_started_ms: int | None = None
        self._beat_phase = 0.0
        self._press_nudge: tuple[str, int] | None = None
        self._reset_effects()
        self._apply_geometry(cell_rect)
        self._cue("play_skillcheck_appear")

    def _reset_effects(self) -> None:
        """
        Bring every effect the check can run -- receptor flashes, flying
        arrows, sparks, confetti, the torn sprite, the shake and the freeze --
        into being at a known zero, so the draw pass can test each one without
        wondering whether it exists yet. Called once, from the constructor
        """
        self._receptor_flash: dict[str, int] = {}
        self._wrong_flash: tuple[str, int] | None = None
        self._wiggle_started: int | None = None
        self._flying: list[tuple[str, int, int, int]] = []
        self._sparks: tuple[float, ...] | None = None
        self._sparks_at: int | None = None
        self._spark_count = 0
        self._white_flash: tuple[str, float] | None = None
        self._win_flash_until: float | None = None
        self._torn_until: float | None = None
        self._confetti: tuple[float, ...] | None = None
        self._confetti_at: int | None = None
        self._fail_started: int | None = None
        self._trauma = Trauma()
        self._hitstop = Hitstop()
        self._scaled: dict[int, pg.Surface] = {}
        self._spot_layer: pg.Surface | None = None

    def _apply_geometry(self, cell_rect: pg.Rect) -> None:
        """
        Re-measure the whole view against the board square it sits on: the pad
        and its hub, the row of prompts above it, the judgement lettering and
        the spotlight layer. Every size is derived from that square, so the
        check keeps its proportions at any window size -- the base controller
        routes each relayout through here

        :param cell_rect: board square the check is anchored on, in window
            pixels
        """
        self._cell_rect = pg.Rect(cell_rect)
        self._flying = []
        self._cell = max(int(cell_rect.width), 1)
        cx, cy = (self._board_rect.center if self._board_rect is not None
                  else cell_rect.center)
        self._pad_center = (cx, cy)
        self._pad_r = max(int(self._cell * COMBO_VIEW_PAD_RADIUS_FRAC),
                          COMBO_VIEW_PAD_RADIUS_MIN_PX)
        self._hub_r = max(int(self._pad_r * COMBO_VIEW_HUB_FRAC), 1)
        self._pad_size = 2 * self._pad_r
        self._pad_top = cy - self._pad_r
        self._pad_bottom = cy + self._pad_r
        self._judge_font = get_display_font(max(int(self._cell * COMBO_VIEW_JUDGE_FONT_FRAC), 14))
        self._scaled = {}
        self._ensure_spot_layer()
        self._layout_strip()

    def _ensure_spot_layer(self) -> None:
        """
        Keep the scratch surface the spotlight is painted on matched to the
        board, rebuilding it only when the board's size really changed. The
        mirror never gets one, so the player watching keeps a clear view of
        the position while the opponent shoots
        """
        if self._passive or self._board_rect is None:
            self._spot_layer = None
            return
        size = self._board_rect.size
        if self._spot_layer is None or self._spot_layer.get_size() != size:
            self._spot_layer = pg.Surface(size, pg.SRCALPHA)

    def _layout_strip(self) -> None:
        """
        Lay out the row of prompts above the pad -- one slot per press the run
        asks for, centred over it, with the prompt owed now drawn larger than
        the rest. This is where the length of the run becomes something the
        player can count at a glance
        """
        n = self.challenge.prompt_count
        self._strip_chev = max(int(self._cell * COMBO_VIEW_STRIP_CHEVRON_FRAC), 8)
        self._strip_big = max(int(self._strip_chev * COMBO_VIEW_STRIP_CURRENT_SCALE),
                              self._strip_chev + 2)
        self._fire_size = max(int(self._strip_chev * COMBO_VIEW_FIRE_SIZE_FRAC), 12)
        arrow_span = _direction_chevron(self._strip_big, Colors.accent, "up").get_width()
        pad = max(int(self._cell * COMBO_VIEW_CHIP_PAD_FRAC), COMBO_VIEW_CHIP_PAD_MIN_PX)
        self._chip = arrow_span + 2 * pad
        self._chip_cut = max(int(self._chip * COMBO_VIEW_CHIP_CUT_FRAC), 3)
        gap = max(int(self._cell * COMBO_VIEW_CHIP_GAP_FRAC), COMBO_VIEW_CHIP_GAP_MIN_PX)
        total = n * self._chip + max(n - 1, 0) * gap
        start = self._pad_center[0] - total // 2
        self._strip_y = self._pad_top - max(int(self._cell * COMBO_VIEW_STRIP_GAP_FRAC), 12)
        self._strip_slots = [start + i * (self._chip + gap) + self._chip // 2 for i in range(n)]

    def set_board_rect(self, board_rect: pg.Rect | None) -> None:
        """
        Follow the board when it moves or is resized, which the game screen
        does after every layout pass. The view is rebuilt only when the
        rectangle really changed, so an unchanged layout costs nothing

        :param board_rect: the board in window pixels, or None when there is
            no board to follow
        """
        new_rect = pg.Rect(board_rect) if board_rect is not None else None
        if new_rect == self._board_rect:
            return
        self._board_rect = new_rect
        self._apply_geometry(self._cell_rect)

    def handle_event(self, event: pg.event.Event) -> bool:
        """
        Take one input for the check: a click on a quarter of the pad, or an
        arrow or WASD key. While a check is live it swallows every left click
        and every direction key so none of them reach the board behind it; the
        mirror takes nothing at all, and a run already decided just absorbs
        input while its verdict plays out

        :param event: the pygame event being offered
        :returns: True when the check consumed it
        """
        if self._passive:
            return False
        if self._closed:
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            direction = self._receptor_hit(event.pos)
            if direction is not None and self._now >= self._lockout_until:
                self._press(direction)
            return True
        if event.type == pg.KEYDOWN:
            direction = _KEY_DIRECTION.get(event.key)
            if direction is None:
                return False
            if self._now >= self._lockout_until:
                self._press(direction)
            return True
        return False

    def _receptor_hit(self, pos: tuple[int, int]) -> str | None:
        """
        Work out which quarter of the pad a point falls on, the same reading
        used for the hover tint and for a real press. The dead hub and
        everything outside the ring belong to no direction, so a click there
        is not counted as a wrong press

        :param pos: point in window pixels, normally the cursor
        :returns: the direction that quarter stands for, or None for a point
            off the receptors
        """
        dx = pos[0] - self._pad_center[0]
        dy = pos[1] - self._pad_center[1]
        r = math.hypot(dx, dy)
        if r > self._pad_r or r < self._hub_r:
            return None
        if abs(dx) > abs(dy):
            return "left" if dx < 0 else "right"
        return "up" if dy < 0 else "down"

    def _press(self, direction: str) -> None:
        """
        Answer the prompt the run currently owes. A press arriving sooner than
        a human could react, or hammered in faster than
        COMBO_MIN_INTER_PRESS_MS after the last one, is dropped rather than
        judged. Online the press is reported to the server whatever the local
        reading of it was -- only the server's answer settles the check

        :param direction: direction the player pressed
        """
        elapsed = self._now - self.start_ms
        if elapsed < SKILLCHECK_HUMAN_FLOOR_MS:
            return
        if (self._last_accept_ms is not None
                and self._now - self._last_accept_ms < COMBO_MIN_INTER_PRESS_MS):
            return
        self._last_accept_ms = self._now
        self._press_nudge = (direction, self._now)
        if self.challenge.press_correct(self._progress, direction):
            self._register_correct(direction)
        else:
            self._register_wrong(direction)
        if self._online:
            cast(Callable[..., None], self._on_shot)(elapsed, direction=direction)

    def _register_correct(self, direction: str) -> None:
        """
        Bank a correct press: grade how quickly it came, light the receptor,
        throw the arrow up to the strip and step the run on. Each hit plays
        the next sound up the combo ladder, so a run climbs in pitch and
        clamps at its top rung, and the hit that fills the run wins the check

        :param direction: direction that was pressed
        """
        self._judgement = self._judge(self._now - self._prompt_started_ms)
        self._judgement_at = self._now
        if not self._passive:
            if self._judgement == _JUDGE_BRILLIANT:
                self._brilliant_streak += 1
                if self._brilliant_streak == COMBO_VIEW_STREAK_FIRE:
                    self._ignite_fire()
            else:
                self._brilliant_streak = 0
                self._fire_started_ms = None
        self._receptor_flash[direction] = self._now
        self._spawn_flying(direction)
        self._spawn_sparks()
        self._white_flash = (direction, self._now + COMBO_VIEW_WHITE_FLASH_MS)
        self._trauma.add(COMBO_VIEW_TRAUMA_CORRECT)
        self._progress += 1
        self._prompt_started_ms = self._now
        if self._audio is not None and not self._passive:
            self._audio.play_combo_hit(self._progress - 1)
        if self.challenge.is_complete(self._progress):
            self._win()

    def _ignite_fire(self) -> None:
        """
        Set the run alight once enough presses in a row have been graded
        brilliant, the check's reward for playing it fast: flames over the
        prompts still to come, a kick of shake and a streak cue
        """
        self._fire_started_ms = self._now
        self._trauma.add(COMBO_VIEW_TRAUMA_IGNITE)
        self._cue("play_combo_streak")

    def _register_wrong(self, direction: str) -> None:
        """
        Charge one wrong press: the pad locks out briefly so a mashed arrow
        cannot spend a second life, the brilliant streak dies and a strike pip
        is struck out. COMBO_MAX_WRONGS of them lose the check, which costs
        the player that capture for the rest of the turn

        :param direction: direction that was pressed
        """
        self._wrong_count += 1
        self._brilliant_streak = 0
        self._fire_started_ms = None
        self._lockout_until = self._now + int(COMBO_WRONG_LOCKOUT_MS)
        self._wrong_flash = (direction, self._now)
        self._wiggle_started = self._now
        self._hitstop.trigger(self._now, COMBO_VIEW_WRONG_HITSTOP_MS)
        self._cue("play_combo_wrong")
        if self.challenge.wrongs_exhausted(self._wrong_count):
            self._fail()

    def _register_spectate_wrong(self, direction: str) -> None:
        """
        Show the opponent's wrong press in the mirror -- the red flash and the
        wobble -- without charging anything, since the count came from the
        server along with the press. When it was their last one the mirror
        closes on the same press their check did

        :param direction: direction they pressed
        """
        self._wrong_flash = (direction, self._now)
        self._wiggle_started = self._now
        self._cue("play_combo_wrong")
        if self.challenge.wrongs_exhausted(self._wrong_count):
            self._close()

    def _close(self) -> None:
        """
        Mark the check finished and stamp when, which starts the view fading
        out and, once the result hold has run, lets the overlay hand the
        verdict back to the game screen. The stamp is kept from the first
        close, so a later one cannot restart the fade
        """
        self._closed = True
        if self._closed_at is None:
            self._closed_at = self._now

    def _present_win(self) -> None:
        """
        Play the winning flourish -- a freeze frame, a white flash over the
        board, the piece being taken torn apart, and confetti. Presentation
        only: offline the verdict is already settled, online the server can
        still contradict it
        """
        self._hitstop.trigger(self._now, COMBO_VIEW_WIN_HITSTOP_MS)
        self._win_flash_until = self._now + COMBO_VIEW_WIN_FLASH_MS
        self._torn_until = self._now + COMBO_VIEW_TORN_MS
        self._spawn_confetti()
        self._cue("play_combo_complete")

    def _present_fail(self) -> None:
        """
        Play the losing flourish: the blunder call over the pad, the prompt
        that was owed deflating, and the sound that goes with them.
        Presentation only -- what the loss costs the player is settled
        elsewhere
        """
        self._judgement = _JUDGE_FAIL
        self._judgement_at = self._now
        self._fail_started = self._now
        self._cue("play_combo_fail")

    def _retract_win(self) -> None:
        """
        Take the winning flourish back down, for the case where this view ran
        ahead of the server and the server then says the check was lost
        """
        self._win_flash_until = None
        self._torn_until = None
        self._confetti = None
        self._confetti_at = None

    def _retract_fail(self) -> None:
        """
        Take the losing flourish back down, for the case where this view had
        given the check up and the server says it was won after all
        """
        self._fail_started = None
        if self._judgement == _JUDGE_FAIL:
            self._judgement = None

    def _win(self) -> None:
        """
        Win the check here and now: play the flourish and close. Offline that
        is the verdict and the capture the check was fought over goes through;
        online nothing is settled until the server answers, so the outcome is
        deliberately left open
        """
        self._present_win()
        self._close()
        if not self._online:
            self._landed = True
            self._committed_at = self._now

    def _fail(self) -> None:
        """
        Lose the check here and now, either by spending the last wrong press
        or by letting the deadline run out. Offline that is the verdict and
        the move is locked for the turn; online the server still has the final
        word, so the outcome is left open
        """
        self._present_fail()
        self._close()
        if not self._online:
            self._landed = False
            self._committed_at = self._now

    def _judge(self, latency: float) -> str | None:
        """
        Grade how quickly a correct press came, which is what the call over
        the pad says and what feeds the brilliant streak. A press that is
        right but slow still counts for the run and simply goes ungraded

        :param latency: milliseconds between the prompt being owed and the
            press answering it
        :returns: brilliant or clean, or None when it was correct but slow
        """
        if latency < COMBO_VIEW_JUDGE_BRILLIANT_MS:
            return _JUDGE_BRILLIANT
        if latency < COMBO_VIEW_JUDGE_CLEAN_MS:
            return _JUDGE_CLEAN
        return None

    def _fire_active(self) -> bool:
        """
        Whether flames are burning over the prompts still to come, which they
        are from the moment a long enough run of brilliant presses is strung
        together until one of them is dropped

        :returns: True while the streak is alight
        """
        return self._brilliant_streak >= COMBO_VIEW_STREAK_FIRE

    def resolve(self, won: bool) -> None:
        """
        Adopt the server's verdict on an online check, the only word that ever
        settles one. Whatever the view had already shown is corrected first,
        so a run the player finished can still end in a blunder call, and one
        they had given up on can still be won

        :param won: the server's verdict, True when the capture goes through
        """
        if won:
            self._retract_fail()
            if self._win_flash_until is None:
                self._present_win()
        elif self._fail_started is None:
            if self._win_flash_until is not None:
                self._retract_win()
            self._present_fail()
        self._landed = won
        if self._committed_at is None:
            self._committed_at = self._now
        self._resolved_at = self._now
        self._close()

    def spectate_shot(self, elapsed: float, miss_count: int, won: bool, progress: int = 0,
                      direction: str | None = None,
                      target: tuple[float, float] | None = None) -> None:
        """
        Replay one press the opponent just made, inside the read-only mirror.
        The server reports how far they have got rather than a running
        commentary, so any prompts skipped over are filled in from the run
        itself and the watcher sees the same arrows light in the same order

        :param elapsed: milliseconds into their check the press happened, part
            of the shot signature every kind shares and unused here
        :param miss_count: wrong presses they had made before this one
        :param won: whether the server counted the press; the progress it
            reports already says the same thing
        :param progress: prompts they have hit in total, this press included
        :param direction: direction they actually pressed, None when the
            server did not name one
        :param target: aim point in board space, which Combo has no use for
        """
        if progress > self._progress:
            while self._progress < progress:
                last = self._progress == progress - 1
                step = (direction if direction is not None and last
                        else self.challenge.expected(self._progress))
                self._register_correct(step if step is not None else "up")
        elif miss_count + 1 > self._wrong_count:
            self._wrong_count = miss_count + 1
            step = direction if direction is not None else self.challenge.expected(self._progress)
            self._register_spectate_wrong(step if step is not None else "up")

    def update(self, now_ms: int) -> None:
        """
        Move the check on by one frame: advance its clock, decay the shake and
        step the dance beat, except while a hit has the picture frozen.
        Offline this is also where the deadline bites, so a player who stops
        pressing loses the check; online only the server times one out

        :param now_ms: pygame ticks for this frame
        """
        dt = now_ms - self._now
        self._now = now_ms
        self._trauma.update(now_ms)
        if dt > 0 and not self._hitstop.frozen(now_ms):
            self._beat_phase += dt * self._bpm() / 60000.0
        if (not self._online and not self._closed
                and now_ms - self.start_ms >= self.deadline_ms):
            self._fail()

    @property
    def done(self) -> bool:
        """
        Whether the overlay may close and pass the verdict on to the game
        screen. The result is held on screen for a beat first, so the flourish
        is always seen before the board comes back

        :returns: True once the check is finished and its hold has run out
        """
        return self._done_after(COMBO_VIEW_RESULT_HOLD_MS)

    def _spawn_flying(self, direction: str) -> None:
        """
        Send the arrow just pressed flying up to its slot in the strip, which
        is what visibly ties the pad to the run of prompts above it

        :param direction: direction that was pressed, which picks the arrow
        """
        sx = (self._strip_slots[self._progress] if self._progress < len(self._strip_slots)
              else self._pad_center[0])
        self._flying.append((direction, sx, self._strip_y, self._now))

    def _spawn_sparks(self) -> None:
        """
        Throw a burst of sparks off the pad on a correct press. The scatter is
        drawn from the run and the place reached in it, so it is the same on
        every frame without any per-spark state being kept
        """
        self._sparks = seeded_floats(
            f"combospark:{self.challenge.prompts}:{self._progress}",
            COMBO_VIEW_SPARK_MAX)
        self._sparks_at = self._now
        self._spark_count = COMBO_VIEW_SPARK_MIN + int(
            self._sparks[0] * (COMBO_VIEW_SPARK_MAX - COMBO_VIEW_SPARK_MIN + 1))

    def _spawn_confetti(self) -> None:
        """
        Set the winning confetti off, its spread drawn from the run so both
        players watching the same check see the same burst
        """
        self._confetti = seeded_floats(
            f"comboconfetti:{self.challenge.prompts}", COMBO_VIEW_CONFETTI_COUNT * 3)
        self._confetti_at = self._now

    def _shake(self) -> tuple[float, float]:
        """
        Give this frame's screen-shake offset, which the pad, the strip and
        the pips are all drawn through so a correct press and a lit streak
        land with some weight

        :returns: (x, y) offset in pixels, both zero once the shake has decayed
        """
        return self._trauma.offset(self._now, COMBO_VIEW_TRAUMA_MAX_OFFSET)

    def _actor_center(self, sq: Square | None) -> tuple[float, float]:
        """
        Give the point on screen a piece taking part in this check stands at,
        falling back to the middle of the pad when the board geometry was
        never handed over

        :param sq: board square to place, None when there is none
        :returns: centre in window pixels
        """
        if self._geom is not None and sq is not None:
            return self._geom(sq)
        return self._pad_center

    def _scaled_sprite(self, src: pg.Surface | None) -> pg.Surface | None:
        """
        Fit a piece sprite to the board square this check is sized against,
        remembered per source sprite so the two dancers are scaled once rather
        than every frame

        :param src: the piece's sprite at whatever size it arrived in, or None
        :returns: that sprite at board-square size, or None when there was
            none to scale
        """
        if src is None:
            return None
        cached = self._scaled.get(id(src))
        if cached is not None:
            return cached
        surf = (src if src.get_size() == (self._cell, self._cell)
                else pg.transform.smoothscale(src, (self._cell, self._cell)))
        self._scaled[id(src)] = surf
        return surf

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the whole check for this frame, back to front: the lit dance
        floor and the two pieces on it, the closing spotlight, the run of
        prompts, the pad, the strike pips, and then every effect layered over
        them. The shake and the fade are measured once here and handed down,
        so every part of the view moves together

        :param window: the window surface to draw on
        """
        fade = self._exit_fade()
        shake = self._shake()
        self._draw_dance_floor(window, fade)
        self._draw_actors(window, fade)
        self._draw_spotlight(window, fade)
        self._draw_strip_chips(window, fade, shake)
        self._draw_strip(window, fade, shake)
        self._draw_pad(window, fade, shake)
        self._draw_pips(window, fade, shake)
        self._draw_flying(window, shake)
        self._draw_sparks(window, shake)
        self._draw_white_flash(window, shake)
        self._draw_confetti(window)
        self._draw_torn_victim(window)
        self._draw_win_flash(window)
        self._draw_judgement(window)

    def _timer_frac(self) -> float:
        """
        How far the check has run through its deadline, which is what closes
        the spotlight in and turns its rim red. Once the check is over the
        reading freezes, so the closing stops where it ended rather than
        carrying on through the fade-out

        :returns: share of the deadline spent, clamped to [0, 1]
        """
        terminal = self._terminal_at()
        now = self._now if terminal is None else terminal
        frac = (now - self.start_ms) / max(self.deadline_ms, 1)
        return min(max(frac, 0.0), 1.0)

    def _terminal_at(self) -> int | None:
        """
        When this check stopped mattering -- the moment its outcome was
        settled, or failing that the moment it closed. Everything that winds
        the view down is measured from here

        :returns: pygame ticks it ended at, or None while it is still running
        """
        if self._committed_at is not None:
            return self._committed_at
        return self._closed_at

    def _exit_fade(self) -> float:
        """
        How much of the view is still on screen while it bows out, so a
        finished check dissolves off the board instead of blinking away

        :returns: opacity, 1.0 while the check is live falling to 0.0 once it
            has faded out
        """
        terminal = self._terminal_at()
        if terminal is None:
            return 1.0
        return max(0.0, 1.0 - (self._now - terminal) / COMBO_VIEW_EXIT_FADE_MS)

    def _intro_k(self) -> float:
        """
        How far the opening flourish has come, which fades the pad up and
        lifts it into place over the first moments of the check

        :returns: 0.0 on the first frame, rising smoothly to 1.0
        """
        return smoothstep(min((self._now - self.start_ms) / COMBO_VIEW_INTRO_FADE_MS, 1.0))

    def _slot_intro_k(self, index: int) -> float:
        """
        How far one prompt has dropped into its slot, staggered along the row
        so the run deals itself out left to right instead of appearing whole

        :param index: position in the run, counted from zero
        :returns: 0.0 before that slot starts moving, rising to 1.0 in place
        """
        t = self._now - self.start_ms - index * COMBO_VIEW_INTRO_STAGGER_MS
        return smoothstep(min(max(t / COMBO_VIEW_INTRO_ARROW_MS, 0.0), 1.0))

    def _press_offset(self) -> tuple[int, int]:
        """
        Nudge the pad the way it was last pressed, for the moment just after a
        press. It is what makes the pad feel struck rather than merely lit up

        :returns: (x, y) offset in pixels, zero once the nudge has run
        """
        if self._press_nudge is None:
            return (0, 0)
        direction, start = self._press_nudge
        t = self._now - start
        if t < 0 or t >= COMBO_VIEW_PRESS_NUDGE_MS:
            return (0, 0)
        depth = self._cell * COMBO_VIEW_PRESS_NUDGE_FRAC * (
            1.0 - t / COMBO_VIEW_PRESS_NUDGE_MS)
        dx, dy = _RECEPTOR_DIRS[direction]
        return (int(dx * depth), int(dy * depth))

    def _spot_radius(self) -> float:
        """
        How wide the spotlight still is. It opens large enough to cover the
        whole board and closes to just around the pad as the deadline burns
        down, which is the check's clock made visible

        :returns: spotlight radius in pixels
        """
        board = cast(pg.Rect, self._board_rect)
        start_r = COMBO_VIEW_SPOT_START_FRAC * 0.5 * math.hypot(board.width, board.height)
        end_r = COMBO_VIEW_SPOT_END_FRAC * self._pad_r
        return start_r + (end_r - start_r) * self._timer_frac()

    def _rim_color(self) -> pg.Color:
        """
        Colour the ring around the spotlight: the accent while there is time,
        flickering toward the loss colour over the last stretch, which is the
        warning that the run is about to time out

        :returns: the rim colour for this frame
        """
        base = pg.Color(self._signal_color(Colors.accent))
        frac = self._timer_frac()
        warn_start = 1.0 - COMBO_VIEW_SPOT_WARN_FRAC
        if frac < warn_start:
            return base
        warn_t = (frac - warn_start) / COMBO_VIEW_SPOT_WARN_FRAC
        flicker = cosine_pulse(self._now, COMBO_VIEW_SPOT_WARN_PULSE_MS)
        mix = warn_t * (COMBO_VIEW_SPOT_WARN_FLICKER_MIN
                        + (1.0 - COMBO_VIEW_SPOT_WARN_FLICKER_MIN) * flicker)
        return base.lerp(_RIM_LOSS, min(max(mix, 0.0), 1.0))

    def _draw_spotlight(self, window: pg.Surface, fade: float | None = None) -> None:
        """
        Darken everything outside the spotlight so the eye is pulled onto the
        pad, with a feathered edge and the warning rim around it. Only the
        player actually pressing gets one -- the mirror leaves the board clear
        for the watcher

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        """
        if self._spot_layer is None or self._board_rect is None:
            return
        fade = self._exit_fade() if fade is None else fade
        if fade <= 0.0:
            return
        radius = self._spot_radius()
        layer = self._spot_layer
        layer.fill(_SPOT_FILL_RGBA)
        center = (self._pad_center[0] - self._board_rect.x,
                  self._pad_center[1] - self._board_rect.y)
        band = radius * COMBO_VIEW_SPOT_FEATHER_FRAC
        for i, rgba in enumerate(_SPOT_FEATHER_RGBA):
            step = COMBO_VIEW_SPOT_FEATHER_STEPS - i
            pg.draw.circle(layer, rgba, center, int(radius + band * step))
        pg.draw.circle(layer, _SPOT_HOLE_RGBA, center, max(int(radius), 1))
        rim_w = max(int(self._cell * COMBO_VIEW_SPOT_RIM_W_FRAC), COMBO_VIEW_SPOT_RIM_W_MIN_PX)
        pg.draw.circle(layer, self._rim_color(), center, max(int(radius), 1), rim_w)
        layer.set_alpha(int(255 * fade))
        window.blit(layer, self._board_rect.topleft)

    def _bpm(self) -> float:
        """
        How fast the music the view dances to is running. It winds up as the
        run is worked through, so the last prompts feel more urgent than the
        first ones did

        :returns: beats per minute at this point in the run
        """
        remaining = max(self.challenge.prompt_count - self._progress, 0)
        total = max(self.challenge.prompt_count, 1)
        return COMBO_VIEW_BPM_BASE + COMBO_VIEW_BPM_RAMP * (1.0 - remaining / total)

    def _beat(self) -> float:
        """
        Where the beat stands right now -- the pulse the board tint and both
        pieces move on, which is what makes the check read as a dance

        :returns: 0.0 at the trough of the beat rising to 1.0 at its peak
        """
        return (1.0 - math.cos(2.0 * math.pi * self._beat_phase)) / 2.0

    def _draw_dance_floor(self, window: pg.Surface, fade: float | None = None) -> None:
        """
        Pulse an accent tint over the board squares in time with the beat,
        skipping the ones the spotlight has already closed past. It is what
        turns the board into a dance floor for the length of the check

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        """
        if self._geom is None or self._victim_sq is None:
            return
        fade = self._exit_fade() if fade is None else fade
        alpha = int(COMBO_VIEW_DANCE_ALPHA * self._beat() * fade)
        if alpha <= 0:
            return
        lit_r = None if self._board_rect is None else self._spot_radius()
        tint = _solid_square(self._cell, Colors.accent)
        tint.set_alpha(alpha)
        px, py = self._pad_center
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                cx, cy = self._geom(Square(row, col))
                if lit_r is not None and math.hypot(cx - px, cy - py) > lit_r:
                    continue
                window.blit(tint, (cx - self._cell // 2, cy - self._cell // 2))

    def _draw_actors(self, window: pg.Surface, fade: float | None = None) -> None:
        """
        Draw the two pieces the check is being fought over -- the capturer
        bobbing on the beat, its target shuffling in place. The board stops
        drawing both of them while a Combo check is up, so this is the only
        thing keeping them on screen

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        """
        if self._geom is None:
            return
        fade = self._exit_fade() if fade is None else fade
        beat = (1.0 if self._hitstop.frozen(self._now) else self._beat()) * fade
        attacker = self._scaled_sprite(self._attacker_src)
        if attacker is not None and self._from_sq is not None:
            cx, cy = self._geom(self._from_sq)
            bob = int(self._cell * COMBO_VIEW_BOB_AMP_FRAC * beat)
            window.blit(attacker, attacker.get_rect(center=(cx, cy - bob)))
        victim = self._scaled_sprite(self._victim_src)
        showing_torn = self._torn_until is not None and self._now < self._torn_until
        if victim is not None and self._victim_sq is not None and not showing_torn:
            cx, cy = self._geom(self._victim_sq)
            shuffle = int(self._cell * COMBO_VIEW_SHUFFLE_AMP_FRAC * fade
                          * math.sin(self._now / COMBO_VIEW_SHUFFLE_PERIOD))
            window.blit(victim, victim.get_rect(center=(cx + shuffle, cy)))

    def _chip_state(self, index: int) -> str:
        """
        Say how one prompt in the run stands -- already hit, owed right now,
        or still to come -- which picks the tile the strip is drawn from

        :param index: position in the run, counted from zero
        :returns: done, next or idle
        """
        if index < self._progress:
            return _CHIP_DONE
        if index == self._progress:
            return _CHIP_NEXT
        return _CHIP_IDLE

    def _slot_wiggle(self, index: int) -> int:
        """
        Shake the prompt currently owed after a wrong press, which is how the
        view says it was not that arrow but this one

        :param index: position in the run, counted from zero
        :returns: sideways offset in pixels, zero for every other prompt
        """
        if index == self._progress and self._wiggle_started is not None:
            return int(sakurai_vibrate(self._now, self._wiggle_started, COMBO_VIEW_WIGGLE_MS,
                                       self._cell * COMBO_VIEW_WIGGLE_AMP_FRAC))
        return 0

    def _draw_strip_chips(self, window: pg.Surface, fade: float | None = None,
                          shake: tuple[float, float] | None = None) -> None:
        """
        Draw the tiles behind the run of prompts, each dropping into place on
        its own beat of the opening flourish. They are what give the row of
        arrows a shape to sit in

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        :param shake: this frame's shake offset, or None to measure it here
        """
        fade = self._exit_fade() if fade is None else fade
        if fade <= 0.0:
            return
        ox, oy = self._shake() if shake is None else shake
        for i, sx in enumerate(self._strip_slots):
            intro = self._slot_intro_k(i)
            if intro <= 0.0:
                continue
            dy = int(self._cell * COMBO_VIEW_INTRO_DROP_FRAC * (1.0 - intro))
            chip = _chip_surface(self._chip, self._chip_cut, self._chip_state(i),
                                 self._signal_color(COMBO_VIEW_CHIP_NEXT_BORDER))
            chip.set_alpha(int(255 * intro * fade))
            rect = chip.get_rect(
                center=(sx + ox + self._slot_wiggle(i), self._strip_y + oy - dy))
            window.blit(chip, rect)

    def _draw_strip(self, window: pg.Surface, fade: float | None = None,
                    shake: tuple[float, float] | None = None) -> None:
        """
        Draw the run of prompts itself, the one thing the player has to read:
        arrows already hit in the win colour, the one owed now large and in
        the accent, the rest dimmed ahead of it -- with flames over the
        remainder while a brilliant streak is alight

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        :param shake: this frame's shake offset, or None to measure it here
        """
        fade = self._exit_fade() if fade is None else fade
        if fade <= 0.0:
            return
        ox, oy = self._shake() if shake is None else shake
        deflate = self._deflate_scale()
        fire = self._fire_active()
        for i, sx in enumerate(self._strip_slots):
            direction = cast(str, self.challenge.expected(i))
            intro = self._slot_intro_k(i)
            if intro <= 0.0:
                continue
            dy = int(self._cell * COMBO_VIEW_INTRO_DROP_FRAC * (1.0 - intro))
            wiggle = self._slot_wiggle(i)
            if fire and i >= self._progress:
                self._draw_fire(window, sx + ox + wiggle, self._strip_y + oy, fade)
            if i < self._progress:
                size, color = self._strip_chev, Colors.win
            elif i == self._progress:
                size = max(int(self._strip_big * deflate), 4)
                color = self._signal_color(Colors.accent)
            else:
                size, color = self._strip_chev, Colors.text_dim
            chev = _direction_chevron(size, color, direction)
            chev.set_alpha(int(255 * intro * fade))
            rect = chev.get_rect(center=(sx + ox + wiggle, self._strip_y + oy - dy))
            window.blit(chev, rect)

    def _draw_fire(self, window: pg.Surface, cx: float, cy: float,
                   fade: float = 1.0) -> None:
        """
        Draw the streak flame over one prompt still to come, breathing on its
        own pulse and surging up out of nothing at the moment the streak is
        lit

        :param window: the window surface to draw on
        :param cx: horizontal centre in window pixels
        :param cy: vertical centre in window pixels, which the flame bobs
            around
        :param fade: exit opacity to draw at
        """
        sprite = _emoji_sprite(COMBO_VIEW_FIRE_EMOJI, self._fire_size)
        if sprite is None:
            return
        ignite = 1.0
        if self._fire_started_ms is not None:
            ignite = min(max((self._now - self._fire_started_ms)
                             / COMBO_VIEW_FIRE_IGNITE_MS, 0.0), 1.0)
        pulse = cosine_pulse(self._now, COMBO_VIEW_FIRE_PULSE_MS)
        alpha = (COMBO_VIEW_FIRE_ALPHA_MIN
                 + (COMBO_VIEW_FIRE_ALPHA_MAX - COMBO_VIEW_FIRE_ALPHA_MIN) * pulse)
        sprite.set_alpha(int(alpha * ignite * fade))
        bob = int(self._fire_size * COMBO_VIEW_FIRE_BOB_FRAC * pulse)
        surge = int(self._fire_size * COMBO_VIEW_FIRE_IGNITE_RISE_FRAC
                    * (1.0 - out_back(ignite)))
        window.blit(sprite, sprite.get_rect(center=(cx, cy - bob + surge)))

    def _deflate_scale(self) -> float:
        """
        Shrink the prompt that was owed at the moment the run was lost, so the
        arrow visibly deflates instead of standing there still waiting to be
        pressed

        :returns: scale for that arrow, 1.0 until the check is lost
        """
        if self._fail_started is None:
            return 1.0
        t = self._now - self._fail_started
        if t >= COMBO_VIEW_TORN_MS:
            return COMBO_VIEW_DEFLATE_FLOOR
        return max(COMBO_VIEW_DEFLATE_FLOOR,
                   1.0 - COMBO_VIEW_DEFLATE_SPAN * (t / COMBO_VIEW_TORN_MS))

    def _draw_pad(self, window: pg.Surface, fade: float | None = None,
                  shake: tuple[float, float] | None = None) -> None:
        """
        Draw the pad the player presses: the static art lifted into place by
        the opening flourish and nudged the way it was last struck, then the
        hover tint, the dimming while it is locked out after a wrong press,
        and any receptor still flashing. The mirror has no pad, since the
        watcher has nothing to press

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        :param shake: this frame's shake offset, or None to measure it here
        """
        if self._passive:
            return
        fade = self._exit_fade() if fade is None else fade
        if fade <= 0.0:
            return
        ox, oy = self._shake() if shake is None else shake
        nx, ny = self._press_offset()
        intro = self._intro_k()
        rise = int(self._cell * COMBO_VIEW_INTRO_RISE_FRAC * (1.0 - intro))
        left = self._pad_center[0] - self._pad_r + ox + nx
        top = self._pad_center[1] - self._pad_r + oy + ny + rise
        static = _pad_static(self._pad_r, self._hub_r)
        static.set_alpha(int(255 * intro * fade))
        window.blit(static, (left, top))
        self._draw_hover(window, left, top)
        if self._now < self._lockout_until:
            dim = circle_surface(2 * self._pad_r, Colors.bg)
            dim.set_alpha(int(COMBO_VIEW_PAD_DIM_ALPHA * fade))
            window.blit(dim, (left, top))
        self._draw_receptor_flashes(window, left, top)

    def _draw_hover(self, window: pg.Surface, left: float, top: float) -> None:
        """
        Tint the quarter of the pad the cursor is over, so a player using the
        mouse can see what they are about to press. It goes away while the pad
        is locked out and once the check is over

        :param window: the window surface to draw on
        :param left: left edge of the pad in window pixels, shake included
        :param top: top edge of the pad in window pixels, shake included
        """
        if self._passive or self._closed or self._now < self._lockout_until:
            return
        direction = self._receptor_hit(pg.mouse.get_pos())
        if direction is None:
            return
        fill = _wedge_overlay(self._pad_r, self._hub_r, direction,
                              self._signal_color(Colors.accent))
        fill.set_alpha(COMBO_VIEW_HOVER_ALPHA)
        window.blit(fill, (left, top))

    def _draw_receptor_flashes(self, window: pg.Surface, left: float, top: float) -> None:
        """
        Light up the quarters that were just pressed -- accent and brief for a
        correct press, red and longer for a wrong one -- each fading out over
        its own span, so the pad reads back what the player did

        :param window: the window surface to draw on
        :param left: left edge of the pad in window pixels, shake included
        :param top: top edge of the pad in window pixels, shake included
        """
        flashes = [(direction, start, COMBO_VIEW_RECEPTOR_FLASH_MS,
                    COMBO_VIEW_RECEPTOR_FLASH_ALPHA, self._signal_color(Colors.accent_hi))
                   for direction, start in self._receptor_flash.items()]
        if self._wrong_flash is not None:
            flashes.append((*self._wrong_flash, COMBO_VIEW_WRONG_FLASH_MS,
                            COMBO_VIEW_WRONG_FLASH_ALPHA, Colors.loss))
        for direction, start, span, alpha, color in flashes:
            t = self._now - start
            if t < 0 or t >= span:
                continue
            fill = _wedge_overlay(self._pad_r, self._hub_r, direction, color)
            fill.set_alpha(int(alpha * (1.0 - t / span)))
            window.blit(fill, (left, top))

    def _draw_pips(self, window: pg.Surface, fade: float | None = None,
                   shake: tuple[float, float] | None = None) -> None:
        """
        Draw the row of strike pips under the pad, one for each wrong press
        the rules allow, struck out as they are spent. It is the player's
        running count of how much room for error is left before the capture
        is lost

        :param window: the window surface to draw on
        :param fade: exit opacity, or None to measure it here
        :param shake: this frame's shake offset, or None to measure it here
        """
        fade = self._exit_fade() if fade is None else fade
        if fade <= 0.0:
            return
        ox, oy = self._shake() if shake is None else shake
        intro = self._intro_k()
        size = max(int(self._cell * COMBO_VIEW_PIP_SIZE_FRAC), 8)
        gap = max(int(self._cell * COMBO_VIEW_PIP_GAP_FRAC), 4)
        total = COMBO_MAX_WRONGS * size + (COMBO_MAX_WRONGS - 1) * gap
        start = self._pad_center[0] - total // 2
        y = self._pad_bottom + max(int(self._cell * COMBO_VIEW_PIP_ROW_GAP_FRAC), 10)
        for i in range(COMBO_MAX_WRONGS):
            x = start + i * (size + gap) + size // 2
            pip = _pip_surface(size, i < self._wrong_count)
            pip.set_alpha(int(255 * intro * fade))
            window.blit(pip, pip.get_rect(center=(x + ox, y + oy)))

    def _draw_flying(self, window: pg.Surface,
                     shake: tuple[float, float] | None = None) -> None:
        """
        Draw the arrows thrown from the pad up to the strip on each correct
        press, rising and fading as they go -- the visible receipt for a
        prompt answered

        :param window: the window surface to draw on
        :param shake: this frame's shake offset, or None to measure it here
        """
        ox, oy = self._shake() if shake is None else shake
        for direction, sx, sy, start in self._flying:
            t = self._now - start
            if t < 0 or t >= COMBO_VIEW_ARROW_FLY_MS:
                continue
            progress = out_back(min(t / COMBO_VIEW_ARROW_FLY_MS, 1.0))
            rise = int(self._cell * COMBO_VIEW_ARROW_FLY_RISE_FRAC * progress)
            chev = _direction_chevron(self._strip_big, self._signal_color(Colors.accent_hi),
                                      direction)
            chev.set_alpha(int(255 * (1.0 - t / COMBO_VIEW_ARROW_FLY_MS)))
            window.blit(chev, chev.get_rect(center=(sx + ox, sy - rise + oy)))

    def _draw_sparks(self, window: pg.Surface,
                     shake: tuple[float, float] | None = None) -> None:
        """
        Draw the burst of sparks flung out from the pad on a correct press,
        spreading and fading over their short life. The mirror does without
        them, so the watcher is not sold the feel of a press they did not make

        :param window: the window surface to draw on
        :param shake: this frame's shake offset, or None to measure it here
        """
        if self._passive or self._sparks is None or self._sparks_at is None:
            return
        t = self._now - self._sparks_at
        if t < 0 or t >= COMBO_VIEW_SPARK_MS:
            return
        ox, oy = self._shake() if shake is None else shake
        cx, cy = self._pad_center
        progress = t / COMBO_VIEW_SPARK_MS
        reach = self._cell * COMBO_VIEW_SPARK_REACH_FRAC * progress
        size = max(int(self._cell * COMBO_VIEW_SPARK_SIZE_FRAC), 3)
        spark = _solid_square(size, Colors.amber_hi)
        spark.set_alpha(int(255 * (1.0 - progress)))
        for i in range(self._spark_count):
            ang = self._sparks[i] * 2.0 * math.pi
            x = cx + math.cos(ang) * reach + ox
            y = cy + math.sin(ang) * reach + oy
            window.blit(spark, (x - size / 2.0, y - size / 2.0))

    def _draw_white_flash(self, window: pg.Surface,
                          shake: tuple[float, float] | None = None) -> None:
        """
        Punch a white wedge over the quarter just pressed correctly, the
        brightest single piece of feedback the pad gives. Like the sparks, it
        belongs to the player pressing and not to the mirror

        :param window: the window surface to draw on
        :param shake: this frame's shake offset, or None to measure it here
        """
        if self._passive or self._white_flash is None:
            return
        direction, until = self._white_flash
        remaining = until - self._now
        if remaining <= 0:
            return
        ox, oy = self._shake() if shake is None else shake
        nx, ny = self._press_offset()
        fill = _wedge_overlay(self._pad_r, self._hub_r, direction, COMBO_VIEW_FLASH_WHITE)
        fill.set_alpha(int(COMBO_VIEW_WHITE_FLASH_ALPHA * (remaining / COMBO_VIEW_WHITE_FLASH_MS)))
        window.blit(fill, (self._pad_center[0] - self._pad_r + ox + nx,
                           self._pad_center[1] - self._pad_r + oy + ny))

    def _draw_win_flash(self, window: pg.Surface) -> None:
        """
        Flash the whole board white for a few frames the moment the run is
        completed, falling back to the pad's own footprint when the check was
        never told where the board is

        :param window: the window surface to draw on
        """
        if self._win_flash_until is None:
            return
        remaining = self._win_flash_until - self._now
        if remaining <= 0:
            return
        if self._board_rect is not None:
            layer = _flash_layer(self._board_rect.width, self._board_rect.height)
            pos = self._board_rect.topleft
        else:
            layer = _flash_layer(self._pad_size, self._pad_size)
            pos = (self._pad_center[0] - self._pad_r, self._pad_center[1] - self._pad_r)
        layer.set_alpha(int(COMBO_VIEW_WIN_FLASH_ALPHA * (remaining / COMBO_VIEW_WIN_FLASH_MS)))
        window.blit(layer, pos)

    def _draw_confetti(self, window: pg.Surface) -> None:
        """
        Throw the winning confetti up from the pad and let it arc back down.
        Every piece is placed from the seeded numbers and the time since the
        win, so nothing has to be tracked between frames

        :param window: the window surface to draw on
        """
        if self._confetti is None or self._confetti_at is None:
            return
        t = self._now - self._confetti_at
        if t < 0 or t >= COMBO_VIEW_CONFETTI_MS:
            return
        progress = t / COMBO_VIEW_CONFETTI_MS
        cx, cy = self._pad_center
        size = max(int(self._cell * COMBO_VIEW_CONFETTI_SIZE_FRAC), 10)
        spread = self._cell * COMBO_VIEW_CONFETTI_SPREAD_FRAC
        grav = self._cell * COMBO_VIEW_CONFETTI_GRAV_FRAC
        alpha = int(255 * (1.0 - progress))
        f = self._confetti
        speed_base, speed_span = COMBO_VIEW_CONFETTI_SPEED_JITTER
        for i in range(COMBO_VIEW_CONFETTI_COUNT):
            ang = (f[i * 3] - 0.5) * math.pi
            speed = speed_base + speed_span * f[i * 3 + 1]
            char = COMBO_VIEW_CONFETTI[
                int(f[i * 3 + 2] * len(COMBO_VIEW_CONFETTI)) % len(COMBO_VIEW_CONFETTI)]
            surf = _emoji_sprite(char, size)
            if surf is None:
                continue
            x = cx + math.sin(ang) * spread * speed * progress
            y = cy - math.cos(ang) * spread * speed * progress + grav * progress * progress
            surf.set_alpha(alpha)
            window.blit(surf, (x - surf.get_width() / 2.0, y - surf.get_height() / 2.0))

    def _torn_victim(self) -> pg.Surface | None:
        """
        Build the shredded version of the piece being taken, shown in its
        place for a moment once the run is completed. It is cached against
        that piece and the board size, so the shredding is worked out once

        :returns: the torn sprite, or None when there is no piece to tear
        """
        victim = self._scaled_sprite(self._victim_src)
        if victim is None:
            return None
        return torn_sprite(victim, (self._torn_key, self._cell), TORN_MAX_TIER)

    def _draw_torn_victim(self, window: pg.Surface) -> None:
        """
        Draw the torn piece over the square it stood on for the short spell
        after a win, standing in for the sprite the board is not drawing while
        the check owns that square

        :param window: the window surface to draw on
        """
        if self._torn_until is None or self._now >= self._torn_until:
            return
        torn = self._torn_victim()
        if torn is None:
            return
        window.blit(torn, torn.get_rect(center=self._actor_center(self._victim_sq)))

    def _judge_alpha(self, t: int) -> int:
        """
        Fade the call over the pad out across the back part of its stay, so it
        holds still long enough to read and then gets out of the way of the
        next prompt

        :param t: milliseconds since the call went up
        :returns: opacity from 255 down to 0
        """
        hold = COMBO_VIEW_JUDGE_HOLD_MS * COMBO_VIEW_JUDGE_FADE_FRAC
        if t <= hold:
            return 255
        span = COMBO_VIEW_JUDGE_HOLD_MS - hold
        return int(255 * (1.0 - (t - hold) / max(span, 1.0)))

    def _draw_judgement(self, window: pg.Surface) -> None:
        """
        Draw the call over the pad -- brilliant or clean for a quick press,
        the blunder cry when the run is lost -- rising and fading as it goes.
        It is the check's running commentary on how well the player is playing

        :param window: the window surface to draw on
        """
        if self._judgement is None:
            return
        t = self._now - self._judgement_at
        if t < 0 or t >= COMBO_VIEW_JUDGE_HOLD_MS:
            return
        text = render_text(self._judge_font, _JUDGE_TEXT[self._judgement],
                           pg.Color(_JUDGE_COLOR[self._judgement]))
        text.set_alpha(self._judge_alpha(t))
        u = t / COMBO_VIEW_JUDGE_HOLD_MS
        rise = int(self._cell * COMBO_VIEW_JUDGE_RISE_FRAC * (1.0 - (1.0 - u) ** 3))
        offset = max(int(self._cell * COMBO_VIEW_JUDGE_OFFSET_FRAC),
                     COMBO_VIEW_JUDGE_OFFSET_MIN_PX)
        y = self._strip_y - offset - rise
        window.blit(text, text.get_rect(center=(self._pad_center[0], y)))
