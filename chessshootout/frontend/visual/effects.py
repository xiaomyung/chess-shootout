import math
import random
from collections.abc import Callable, Iterable, Sequence
from typing import Any, cast

import pygame as pg

from chessshootout.backend.utils import Square
from chessshootout.frontend.visual import gunfx
from chessshootout.frontend.visual import cache
from chessshootout.frontend.visual.gunfx import DT_MAX, RAGDOLL_MS
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import soft_blur, smoothstep, GLOW_BLUR_PASSES
from chessshootout.frontend.visual.emoji import emoji_surface
from chessshootout.frontend.visual.fonts import get_font, DISPLAY, SANS


DRAW_MS = 240
AIM_MS = 110
MUZZLE_MS = 220
IMPACT_MS = 360
BLOOD_MS = 700
HOLE_IN_MS = 160
HOLE_HOLD_MS = 1100
HOLE_FADE_MS = 700
SHAKE_HARD_MS = 420
SHAKE_SOFT_MS = 260
SPARK_MS = (300, 600)
SMOKE_MS = (700, 1100)
CHECK_DROP_MS = 3000
RECOIL_MS = 180
MISS_HOLD_MS = 360
BACK_OVERSHOOT = 1.70158
CALLOUT_ROTATION_DEG = -3.0
TAG_ROTATION_DEG = -6.0

SPARK_COUNT = 10
SMOKE_PUFFS = 3

SHAKE_AMP = {"hard": 18, "med": 11, "soft": 6}

CALLOUT_LG_MS = 1150
CALLOUT_XL_MS = 1500
TAG_MS = 850
GLOW_ALPHA = 175
GLOW_PAD_FRAC = 0.5
FLAG_POP_MS = 300
KING_SHAKE_MS = 360
TAKEOVER_PAUSE_MS = 1000
TAKEOVER_BG_MS = 200
TAKEOVER_BARS_MS = 420
TAKEOVER_MAIN_MS = 360
TAKEOVER_OUT_MS = 340
TAKEOVER_ANIM_MS = 1500
TAKEOVER_TOTAL_MS = TAKEOVER_PAUSE_MS + TAKEOVER_ANIM_MS
TAKEOVER_BG_ALPHA = 224
TAKEOVER_BG_SETTLE = 140
TAKEOVER_MAIN_DELAY_MS = 80
TAKEOVER_SUB_DELAY_MS = 300
SURRENDER_FLAG = "🏳️"

GUN_PIVOT_RISE_FRAC = 0.05
GUN_DROP_FALL_FRAC = 1.4
GUN_PX_AIM_RATE = 9.0
WHACK_SHOT_TRAVEL_MS = 120
WHACK_SHOT_LIFE_EPS_MS = 20
PROJECTILE_REF_CELL = 104.0
PROJECTILE_TRAVEL_MS = 260
PROJECTILE_MAX_MS = 1400
PIECE_SHAKE_AMP_FRAC = 0.06
WOUND_SPARKS = 6
WOUND_SWEAR_CHANCE = 0.5

RAGDOLL_LAUNCH_FRAC = 0.45
RAGDOLL_LAUNCH_X_FRAC = 1.6
RAGDOLL_LAUNCH_Y_FRAC = -0.65
RAGDOLL_LAUNCH_ROT = 120
RAGDOLL_FALL_X_FRAC = 1.2
RAGDOLL_FALL_Y_FRAC = 2.65
RAGDOLL_FALL_ROT = 420
RAGDOLL_FALL_SHRINK = 0.3

STREAK_LABELS = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL",
                 5: "RAMPAGE", 6: "UNSTOPPABLE", 7: "GODLIKE"}
HIT_WORDS = ("BLAM", "BOOM", "POW", "BANG", "HEADSHOT", "BODIED", "WASTED",
             "REKT", "DELETED", "GOT EM")
SWEAR_WORDS = ("DAMN IT", "DANG!", "MISSED!", "ARGH!", "COME ON!", "SO CLOSE", "UGH")
SKILL_ISSUE_TITLE = "SKILL ISSUE"
SKILL_ISSUE_SUB = "GET GOOD, BRO"

_IMPACT_RING_CACHE = cache.new_cache()
_BLOOD_CACHE = cache.new_cache()
_SPARK_CACHE = cache.new_cache()
_SMOKE_CACHE = cache.new_cache()
_HOLE_CACHE = cache.new_cache()
_TAKEOVER_BG_CACHE = cache.new_size_cache()


def _impact_ring_sprite(r: int, stroke: int) -> pg.Surface:
    """
    Hand back the amber ring that flashes outwards when a shot lands, drawn
    once per radius and shared from then on. Impact rings are on screen every
    frame of a hit, so the frame only blits a ready-made sprite and sets its
    alpha

    :param r: ring radius in pixels, part of the cache key
    :param stroke: ring line thickness in pixels, part of the cache key
    :returns: the cached ring sprite, padded so the stroke is not clipped
    """
    def build() -> pg.Surface:
        """
        Draw the ring for this radius and thickness, run only on a cache miss

        :returns: the freshly drawn ring sprite
        """
        layer = pg.Surface((2 * r + 8, 2 * r + 8), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.amber_hi), (r + 4, r + 4), r, stroke)
        return layer
    return cast(pg.Surface, cache.memoized_surface(_IMPACT_RING_CACHE, (r, stroke), build))


def _blood_sprite(r: int) -> pg.Surface:
    """
    Hand back the blood splat left where a piece was shot, a dark core inside
    a lighter pool, cached per radius so the splat costs one blit per frame

    :param r: splat radius in pixels, the cache key
    :returns: the cached blood sprite
    """
    def build() -> pg.Surface:
        """
        Draw the two-tone splat for this radius, run only on a cache miss

        :returns: the freshly drawn blood sprite
        """
        layer = pg.Surface((2 * r + 2, 2 * r + 2), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.blood), (r + 1, r + 1), r)
        pg.draw.circle(layer, pg.Color(Colors.blood_dark), (r + 1, r + 1), int(r * 0.6))
        return layer
    return cast(pg.Surface, cache.memoized_surface(_BLOOD_CACHE, r, build))


def _spark_sprite(size: int) -> pg.Surface:
    """
    Hand back one square spark of the shower thrown off by a hit. A single hit
    spawns ten of them, so they all share one cached square per size

    :param size: spark edge length in pixels, the cache key
    :returns: the cached spark sprite
    """
    def build() -> pg.Surface:
        """
        Fill a small square in the spark colour, run only on a cache miss

        :returns: the freshly drawn spark sprite
        """
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(Colors.amber_hi))
        return surf
    return cast(pg.Surface, cache.memoized_surface(_SPARK_CACHE, size, build))


def _smoke_sprite(r: int) -> pg.Surface:
    """
    Hand back one puff of the smoke that drifts up off a hit, cached per
    radius since each puff grows by scaling its alpha and position, not by
    being redrawn

    :param r: puff radius in pixels, the cache key
    :returns: the cached smoke sprite
    """
    def build() -> pg.Surface:
        """
        Draw the puff circle for this radius, run only on a cache miss

        :returns: the freshly drawn smoke sprite
        """
        layer = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.smoke), (r, r), r)
        return layer
    return cast(pg.Surface, cache.memoized_surface(_SMOKE_CACHE, r, build))


def _hole_sprite(r: int) -> pg.Surface:
    """
    Hand back the bullet hole punched into the board where a shot landed.
    Holes linger for seconds under the pieces, so they are cached per radius
    and only their alpha changes as they fade

    :param r: hole radius in pixels, the cache key
    :returns: the cached bullet-hole sprite
    """
    def build() -> pg.Surface:
        """
        Draw the dark hole disc for this radius, run only on a cache miss

        :returns: the freshly drawn hole sprite
        """
        layer = pg.Surface((2 * r + 4, 2 * r + 4), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.bullet_hole), (r + 2, r + 2), r)
        return layer
    return cast(pg.Surface, cache.memoized_surface(_HOLE_CACHE, r, build))


def _takeover_bg_sprite(w: int, h: int) -> pg.Surface:
    """
    Hand back the flat scrim that darkens the whole window behind the
    checkmate card. It is keyed by window size and lives in the size-keyed
    cache, so a resize throws the old one away

    :param w: window width in pixels
    :param h: window height in pixels
    :returns: the cached full-window scrim
    """
    def build() -> pg.Surface:
        """
        Fill a window-sized surface with the takeover backdrop colour, run
        only on a cache miss

        :returns: the freshly drawn scrim
        """
        surf = pg.Surface((w, h))
        surf.fill(pg.Color(Colors.takeover_bg))
        return surf
    return cast(pg.Surface, cache.memoized_surface(_TAKEOVER_BG_CACHE, (w, h), build))


class EffectManager:
    """
    The board's gun-fight layer: it owns every capture choreography, stray
    pellet, blood splat, bullet hole, screen shake, killstreak callout and the
    checkmate takeover. Board keeps one as `board.effects`, gives it a geom
    resolver plus a per-frame update, and draws it in two passes -- holes
    under the pieces, everything else over them
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        """
        Create an empty effects layer with nothing playing. Tests inject a
        seeded random source so spreads, spark scatter and hit words are
        reproducible; the owner must still install `geom` and `board_rect`
        before anything can be drawn

        :param rng: random source for spread, scatter and word picks, or None
            for a fresh unseeded one
        """
        self.rng = rng if rng is not None else random.Random()
        self.geom: Callable[[Square | str], tuple[float, float]] | None = None
        self._art: dict[str, Any] | None = None
        self._weapon_cache: dict[tuple[str, int], dict[str, Any] | None] = {}
        self.particles: list[dict[str, Any]] = []
        self.holes: list[dict[str, Any]] = []
        self.captures: list[dict[str, Any]] = []
        self.projectiles: list[dict[str, Any]] = []
        self.drops: list[dict[str, Any]] = []
        self.callouts: list[dict[str, Any]] = []
        self.flags: list[dict[str, Any]] = []
        self._takeover: dict[str, Any] | None = None
        self._check_gun: dict[str, Any] | None = None
        self._whack_gun: dict[str, Any] | None = None
        self._gun_handoff: Square | None = None
        self.aim_victim: Square | None = None
        self.aim_victim_scale = 1.0
        self._king_shake: dict[str, Any] | None = None
        self._piece_shakes: dict[Square, dict[str, Any]] = {}
        self._bystanders: set[Square] = set()
        self._last_now: int | None = None
        self.board_rect: pg.Rect | None = None
        self._streak_color: str | None = None
        self._streak_count = 0
        self._first_blood_spent = False
        self._shake: dict[str, Any] | None = None

    def _ensure_art(self) -> dict[str, Any]:
        """
        Load the gun and muzzle-flash artwork the first time a weapon is
        actually needed, so a game without captures never pays for it. The
        images are cached in gunfx, so every board shares one copy

        :returns: the battle-art bundle: guns plus their flash variants
        """
        if self._art is None:
            self._art = gunfx.load_battle_art()
        return self._art

    def clear_transients(self) -> None:
        """
        Wipe everything in flight but keep the once-per-game first-blood
        latch. This is what an undo or a review jump needs: the picture resets
        without FIRST BLOOD being announced a second time
        """
        self.particles = []
        self.holes = []
        self.captures = []
        self.projectiles = []
        self.drops = []
        self.callouts = []
        self.flags = []
        self._takeover = None
        self._check_gun = None
        self._whack_gun = None
        self._gun_handoff = None
        self.aim_victim = None
        self.aim_victim_scale = 1.0
        self._king_shake = None
        self._piece_shakes = {}
        self._bystanders = set()
        self._shake = None
        self._streak_color = None
        self._streak_count = 0

    def clear(self) -> None:
        """
        Reset the layer for a brand new game: everything transient plus the
        first-blood latch, so the opening capture of the next game announces
        FIRST BLOOD again
        """
        self.clear_transients()
        self._first_blood_spent = False

    def cut(self, now: int | None = None) -> None:
        """
        Cut the action short when the position moves on under it. The board
        calls this as the next move starts, which holsters the guns and drops
        anything mid-flight, but deliberately keeps the bullet holes and the
        pending whack-gun handoff alive

        :param now: pygame ticks in milliseconds, so a held gun tumbles away
            as it is let go; None makes the guns vanish silently
        """
        if now is not None:
            self._release_check_gun(now)
            self.release_gun_px(now)
        self._check_gun = None
        self._whack_gun = None
        self._king_shake = None
        self._piece_shakes = {}
        self._bystanders = set()
        self.captures = []
        self.projectiles = []
        self.particles = []
        self._shake = None

    def is_active(self) -> bool:
        """
        Say whether anything at all is still playing. The game screen asks
        before it lets the result menu take over, so a gun-fight is never cut
        off by the end-of-game panel

        :returns: True while any effect, gun, shake or takeover is live
        """
        return bool(
            self.particles or self.holes or self.captures or self.projectiles
            or self.drops or self.callouts or self.flags or self._piece_shakes
            or self._bystanders or self._takeover is not None
            or self._check_gun is not None or self._whack_gun is not None
            or self._king_shake is not None or self._shake is not None)

    def held_squares(self) -> set[Square]:
        """
        Name the squares whose piece the board must not draw itself, because a
        live capture is drawing the attacker and victim in their place. A miss
        holds nothing -- its victim is still standing and stays the board's

        :returns: destination squares currently owned by a capture in flight
        """
        return {c["to_sq"] for c in self.captures if not c.get("miss")}

    def _rnd(self, lo: float, hi: float) -> float:
        """
        Draw a uniform value from the injected random source, the single
        origin of every scattered angle, offset and lifetime in this layer

        :param lo: inclusive lower bound
        :param hi: upper bound
        :returns: a value between the two bounds
        """
        return lo + self.rng.random() * (hi - lo)

    def _pick(self, seq: Sequence[str]) -> str:
        """
        Pick one line out of a word table through the injected random source,
        so hit words and swears vary run to run but stay reproducible in tests

        :param seq: non-empty table of phrases, such as HIT_WORDS
        :returns: one entry of that table
        """
        return seq[int(self.rng.random() * len(seq))]

    def _center(self, sq: Square) -> tuple[float, float]:
        """
        Locate a square's centre in window pixels through the `geom` resolver
        its owner installed. Every effect is positioned through this one hook,
        which is why they follow the board when it is flipped, resized or
        shaking

        :param sq: square to locate
        :returns: the square's centre in window pixels
        """
        return cast(Callable[[Square], tuple[float, float]], self.geom)(sq)

    def _anchor(self, p: dict[str, Any]) -> tuple[float, float]:
        """
        Find where a particle belongs on screen: whack-born particles carry an
        exact pixel point, board-born ones name a square and follow it. One
        impact package can therefore serve both the capture path and a whack
        hit that landed nowhere near a square centre

        :param p: particle or hole record, carrying either px or victim_sq
        :returns: the anchor position in window pixels
        """
        if "px" in p:
            return cast(tuple[float, float], p["px"])
        return self._center(p["victim_sq"])

    @staticmethod
    def _angle_to(origin: tuple[float, float], target: tuple[float, float]) -> float:
        """
        Measure the angle from one screen point to another, the shared basis
        for every barrel direction and pellet heading here

        :param origin: start point in window pixels, usually a gun pivot
        :param target: point being aimed at, in window pixels
        :returns: angle in radians, screen space (y grows downward)
        """
        return math.atan2(target[1] - origin[1], target[0] - origin[0])

    def _aim(self, from_sq: Square, victim_sq: Square) -> float:
        """
        Aim from one square's centre at another's -- the direction a piece
        points its gun for a square-to-square shot

        :param from_sq: shooter's square
        :param victim_sq: square being shot at
        :returns: angle in radians from shooter to target
        """
        return self._angle_to(self._center(from_sq), self._center(victim_sq))

    def _pivot(self, from_sq: Square, cell: int) -> tuple[float, float]:
        """
        Place a shooter's grip: a little above the cell centre, so the weapon
        sits where the sprite's hands are instead of at its feet

        :param from_sq: square the shooter stands on
        :param cell: cell size in pixels, which the rise is a fraction of
        :returns: the grip position in window pixels
        """
        cx, cy = self._center(from_sq)
        return (cx, cy - cell * GUN_PIVOT_RISE_FRAC)

    def _muzzle(self, weapon: dict[str, Any], from_sq: Square, victim_sq: Square,
                cell: int) -> tuple[tuple[float, float], float]:
        """
        Work out where the barrel tip ends up once the weapon is turned onto
        its target, which is where the muzzle flash and the pellets have to
        start if the shot is to leave the gun

        :param weapon: built weapon record (scaled image, grip, barrel anchor)
        :param from_sq: shooter's square
        :param victim_sq: square being shot at
        :param cell: cell size in pixels
        :returns: the barrel tip in window pixels and the aim angle in radians
        """
        aim = self._aim(from_sq, victim_sq)
        pivot = self._pivot(from_sq, cell)
        muzzle = gunfx.aimed_target(weapon["gun"], weapon["grip"], weapon["barrel"], pivot, aim)
        return muzzle, aim

    def _weapon(self, gun: str, cell: int) -> dict[str, Any] | None:
        """
        Build, once per gun and cell size, the scaled weapon a piece carries,
        so no capture ever rescales artwork mid-frame. Board clears this cache
        whenever the cell size changes

        :param gun: gun name from gunfx.PIECE_GUN, such as revolver or shotgun
        :param cell: cell size in pixels, which the gun's reach comes from
        :returns: the weapon record, or None when that gun has no artwork
        """
        key = (gun, cell)
        if key not in self._weapon_cache:
            art = self._ensure_art()
            self._weapon_cache[key] = gunfx.build_weapon(art, gun, cell * gunfx.GUN_LEN_RATIO)
        return self._weapon_cache[key]

    def clear_weapon_cache(self) -> None:
        """
        Throw away the scaled weapon images after the board changes size, so
        the next shot rebuilds them to fit the new cells
        """
        self._weapon_cache.clear()

    def capture(self, *, now_ms: int, attacker_type: str, attacker_surface: pg.Surface,
                victim_surface: pg.Surface, from_sq: Square, victim_sq: Square,
                to_sq: Square, cell_size: int, power: str = "med",
                on_fire: Callable[[bool], None] | None = None,
                on_slide: Callable[[], None] | None = None,
                occupied: Iterable[Square] | None = None, predrawn: bool = False) -> None:
        """
        Stage the gun-fight a capture is in this game: the attacker draws,
        aims, fires, and only when the lead pellet arrives does it slide onto
        the square. The two callbacks are how the board rejoins the move, and
        they still run when the artwork is missing, so a capture always
        completes

        :param now_ms: pygame ticks in milliseconds the capture started at
        :param attacker_type: capturing piece type value, which picks its gun
        :param attacker_surface: attacker sprite, drawn here while the board
            hides the real piece
        :param victim_surface: victim sprite, drawn until the shot kills it
        :param from_sq: square the attacker fires from
        :param victim_sq: square the victim stands on, which is not to_sq for
            an en passant capture
        :param to_sq: square the attacker ends on, held hidden until the slide
        :param cell_size: cell size in pixels
        :param power: screen-shake strength key, one of SHAKE_AMP
        :param on_fire: called as the shot goes off, taking True when the fire
            phase was skipped whole because a won whack check already killed
            the victim
        :param on_slide: called when the attacker may finally move in
        :param occupied: squares holding other pieces, which stray pellets may
            wound; the shooter and the victim are dropped from the set
        :param predrawn: True when the gun is already out, which skips the
            draw flourish
        """
        handed = self.take_gun_handoff(from_sq)
        predrawn = predrawn or handed
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")
        weapon = self._weapon(gun, cell_size)
        if weapon is None:
            if not handed:
                self._impact(now_ms, from_sq, victim_sq, victim_surface, cell_size)
            if on_fire is not None:
                on_fire(False)
            if on_slide is not None:
                on_slide()
            return
        fire_at = now_ms if handed else now_ms + (0 if predrawn else DRAW_MS) + AIM_MS
        self.captures.append({
            "start": now_ms, "predrawn": predrawn, "advance_only": handed,
            "fire_at": fire_at,
            "fired": False, "gun": gun, "weapon": weapon,
            "from_sq": from_sq, "victim_sq": victim_sq, "to_sq": to_sq,
            "attacker": attacker_surface, "victim": victim_surface,
            "cell": cell_size, "power": power, "on_fire": on_fire, "on_slide": on_slide,
            "occupied": {s for s in (occupied or ()) if s not in (from_sq, victim_sq)},
        })

    def miss(self, *, now_ms: int, attacker_type: str | None, from_sq: Square | str,
             victim_sq: Square | str, cell_size: int, power: str = "med",
             on_fire: Callable[[bool], None] | None = None,
             occupied: Iterable[Square] | None = None, callout: bool = True,
             predrawn: bool = False) -> None:
        """
        Stage the same gun-fight for a failed skill check: the attacker draws,
        fires and whiffs. Nobody dies, every pellet is a stray that can wound
        a bystander, and the big SKILL ISSUE taunt is part of the package
        unless the caller shows its own

        :param now_ms: pygame ticks in milliseconds the miss started at
        :param attacker_type: shooting piece type value, which picks its gun;
            None falls back to the revolver
        :param from_sq: square the attacker fires from, or an opaque sentinel
            key the caller's geom resolver understands, as the steady-aim
            overlay passes for its off-board shooter
        :param victim_sq: square that was aimed at and survives, or the same
            kind of sentinel key
        :param cell_size: cell size in pixels
        :param power: screen-shake strength key, one of SHAKE_AMP
        :param on_fire: called as the shot goes off, taking the advance-only
            flag, which a miss always leaves False
        :param occupied: squares holding other pieces a stray may wound
        :param callout: False to fire the volley without the SKILL ISSUE
            taunt, as the steady-aim overlay does for its own repeat shots
        :param predrawn: True when the gun is already out from a check
        """
        handed = self.take_gun_handoff(from_sq) or predrawn
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")  # type: ignore[arg-type]
        weapon = self._weapon(gun, cell_size)
        if weapon is None:
            if callout:
                self._skill_issue_callout(now_ms, cell_size)
            if on_fire is not None:
                on_fire(False)
            return
        self.captures.append({
            "start": now_ms, "predrawn": handed,
            "fire_at": now_ms + (0 if handed else DRAW_MS) + AIM_MS,
            "fired": False, "gun": gun, "weapon": weapon,
            "from_sq": from_sq, "victim_sq": victim_sq, "to_sq": victim_sq,
            "attacker": None, "victim": None,
            "cell": cell_size, "power": power, "on_fire": on_fire, "on_slide": None,
            "occupied": {s for s in (occupied or ()) if s not in (from_sq, victim_sq)},
            "miss": True, "callout": callout,
        })

    def swear(self, now_ms: int, victim_sq: Square | str, cell: int,
              text: str | None = None) -> None:
        """
        Float a frustrated one-liner over a square: what a piece says when it
        whiffs its shot or catches a stray bullet

        :param now_ms: pygame ticks in milliseconds
        :param victim_sq: square the words float over, or an opaque sentinel
            key the installed geom resolver understands
        :param cell: cell size in pixels, which the type size scales from
        :param text: exact words to show, or None to pick from SWEAR_WORDS
        """
        self._tag(now_ms, text or self._pick(SWEAR_WORDS), victim_sq, cell)

    def _skill_issue_callout(self, now: int, cell: int) -> None:
        """
        Post the big centre-board SKILL ISSUE banner that marks a lost skill
        check, the loudest sign a capture was fumbled rather than blocked

        :param now: pygame ticks in milliseconds
        :param cell: cell size in pixels, which the type size scales from
        """
        self._callout(now, SKILL_ISSUE_TITLE, SKILL_ISSUE_SUB, "xl", cell,
                      Colors.loss, Colors.loss_glow)

    def check(self, *, now_ms: int, attacker_type: str, king_sq: Square, from_sq: Square,
              cell_size: int) -> None:
        """
        Show a check: the checking piece keeps its gun out and trained on the
        enemy king, which rattles in place. The gun stays up until the
        position changes -- cut() is what finally drops it -- and a second
        check hands the previous holder's gun to the floor

        :param now_ms: pygame ticks in milliseconds the check landed at
        :param attacker_type: checking piece type value, which picks its gun
        :param king_sq: square of the king in check, which shakes
        :param from_sq: square the checking piece aims from
        :param cell_size: cell size in pixels
        """
        self._king_shake = {"sq": king_sq, "start": now_ms, "dur": KING_SHAKE_MS,
                            "amp": max(int(cell_size * 0.05), 2)}
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")
        weapon = self._weapon(gun, cell_size)
        if weapon is None:
            return
        if self._check_gun is not None:
            self._release_check_gun(now_ms)
        self._check_gun = {"weapon": weapon, "from_sq": from_sq, "victim_sq": king_sq,
                           "cell": cell_size, "start": now_ms}

    def piece_offset(self, sq: Square, now: int) -> tuple[int, int]:
        """
        Tell the board how far off its square to draw a piece this frame,
        which is how a checked king rattles and a piece hit by a stray bullet
        flinches. Every piece asks every frame, so this stays a cheap lookup

        :param sq: square being drawn
        :param now: pygame ticks in milliseconds
        :returns: horizontal and vertical offset in pixels, (0, 0) when still
        """
        ks = self._king_shake
        if ks is not None and ks["sq"] == sq:
            off = self._jitter(ks, now)
            if off != (0, 0):
                return off
        s = self._piece_shakes.get(sq)
        if s is not None:
            return self._jitter(s, now)
        return (0, 0)

    @staticmethod
    def _jitter(shake: dict[str, Any], now: int) -> tuple[int, int]:
        """
        Sample one shake record: a sideways wobble that decays to nothing
        across its window, so a rattle settles instead of stopping dead

        :param shake: shake record carrying start, dur and amp
        :param now: pygame ticks in milliseconds
        :returns: offset in pixels, (0, 0) outside the shake's window
        """
        t = (now - shake["start"]) / shake["dur"]
        if not 0.0 <= t < 1.0:
            return (0, 0)
        amp = shake["amp"] * (1.0 - t)
        return (int(round(math.sin(t * math.tau * 2.5) * amp)), 0)

    def _release_check_gun(self, now: int) -> None:
        """
        Let the checking piece drop its gun, the visible sign that the check
        it was holding has been answered

        :param now: pygame ticks in milliseconds the drop starts at
        """
        g = self._check_gun
        if g is None:
            return
        self._drop_gun(g["weapon"]["gun"], g["from_sq"], g["cell"], now)
        self._check_gun = None

    def _drop_gun(self, img: pg.Surface, from_sq: Square, cell: int, now: int) -> None:
        """
        Send a gun tumbling off a square and fading out, the shared ending for
        both the check gun and the whack gun

        :param img: already scaled gun image to tumble
        :param from_sq: square the gun falls from
        :param cell: cell size in pixels, which the fall distance scales with
        :param now: pygame ticks in milliseconds the drop starts at
        """
        self.drops.append({
            "img": img, "from_sq": from_sq, "cell": cell,
            "vx": self._rnd(-0.8, 0.8), "spin": self._rnd(-320, 320),
            "fall": cell * GUN_DROP_FALL_FRAC, "start": now, "dur": CHECK_DROP_MS})

    def hold_gun_px(self, *, now_ms: int, attacker_type: str | None, from_sq: Square,
                    cell_size: int, target_px: tuple[float, float] | None = None) -> None:
        """
        Arm the whack-a-mole gun: for the length of that check the capturing
        piece keeps its weapon out and tracks a live pixel target -- the
        shooter's crosshair, or the relayed impact point when watching the
        opponent. Arming again releases any gun already up and cancels a stale
        handoff

        :param now_ms: pygame ticks in milliseconds the gun comes out at
        :param attacker_type: capturing piece type value, which picks its gun;
            None falls back to the revolver
        :param from_sq: square the piece stands and fires from
        :param cell_size: cell size in pixels
        :param target_px: first aim point in window pixels, or None to start
            with the barrel level
        """
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")  # type: ignore[arg-type]
        weapon = self._weapon(gun, cell_size)
        if weapon is None:
            return
        self.release_gun_px(now_ms)
        self._gun_handoff = None
        aim = (0.0 if target_px is None
               else self._angle_to(self._pivot(from_sq, cell_size), target_px))
        self._whack_gun = {"weapon": weapon, "gun": gun, "from_sq": from_sq,
                           "cell": cell_size, "start": now_ms, "aim": aim,
                           "last": now_ms, "fired_at": None}

    def has_gun_px(self) -> bool:
        """
        Say whether the whack gun is currently out, which the session checks
        before arming it a second time

        :returns: True while a pixel-aimed gun is held
        """
        return self._whack_gun is not None

    def aim_gun_px(self, target_px: tuple[float, float] | None, now_ms: int) -> None:
        """
        Swing the held whack gun toward a new pixel target. The barrel eases
        after the crosshair at GUN_PX_AIM_RATE and takes the short way round
        the wrap, so the aim reads as a hand following a target rather than
        snapping onto it

        :param target_px: current aim point in window pixels; None leaves the
            barrel where it was
        :param now_ms: pygame ticks in milliseconds, used for the frame delta
        """
        g = self._whack_gun
        if g is None or target_px is None:
            return
        dt = max(0.0, min(DT_MAX, (now_ms - g["last"]) / 1000.0))
        g["last"] = now_ms
        want = self._angle_to(self._pivot(g["from_sq"], g["cell"]), target_px)
        delta = (want - g["aim"] + math.pi) % (2 * math.pi) - math.pi
        g["aim"] += delta * min(1.0, dt * GUN_PX_AIM_RATE)

    def release_gun_px(self, now_ms: int) -> None:
        """
        End the whack gun with a tumble, the plain ending when the check is
        cancelled or lost. Releasing twice is harmless: only the first call
        finds a gun to drop

        :param now_ms: pygame ticks in milliseconds the drop starts at
        """
        g = self._whack_gun
        if g is None:
            return
        self._drop_gun(g["weapon"]["gun"], g["from_sq"], g["cell"], now_ms)
        self._whack_gun = None

    def hand_off_gun_px(self) -> None:
        """
        End the whack gun silently and leave a one-shot handoff keyed to the
        shooter's square, so the capture or miss that follows a finished check
        starts with the gun already aimed instead of replaying the draw. The
        latch survives cut(), which the board fires in between
        """
        g = self._whack_gun
        if g is None:
            return
        self._gun_handoff = g["from_sq"]
        self._whack_gun = None

    def take_gun_handoff(self, from_sq: Square | str) -> bool:
        """
        Claim the pending handoff for one square, spending it either way. Only
        a shot from that same square inherits the drawn gun, so no other piece
        can pick up a weapon it never held

        :param from_sq: square the next shot is coming from
        :returns: True when this square inherited an already-drawn gun
        """
        handed = self._gun_handoff == from_sq
        self._gun_handoff = None
        return handed

    def fire_gun_px(self, now_ms: int, target_px: tuple[float, float] | None) -> None:
        """
        Fire the held whack gun at a pixel point: a muzzle flash plus a purely
        cosmetic slug whose life is capped at its own travel time, so it dies
        at the impact instead of sailing on. The hit itself was adjudicated
        elsewhere -- nothing here resolves a capture or wounds a bystander

        :param now_ms: pygame ticks in milliseconds of the shot
        :param target_px: impact point in window pixels; None fires nothing
        """
        g = self._whack_gun
        if g is None or target_px is None:
            return
        weapon = g["weapon"]
        muzzle = gunfx.aimed_target(weapon["gun"], weapon["grip"], weapon["barrel"],
                                    self._pivot(g["from_sq"], g["cell"]), g["aim"])
        g["fired_at"] = now_ms
        self._muzzle_flash_px(now_ms, g, muzzle)
        spec = gunfx.gun_spec(g["gun"])
        base = self._angle_to(muzzle, target_px)
        speed = self._pellet_speed(muzzle, target_px, WHACK_SHOT_TRAVEL_MS)
        for ang, factor in gunfx.pellet_spread(spec, base, self._rnd):
            self._push_pellet(now_ms, spec, muzzle, ang, speed * factor, g["cell"],
                              inert=True,
                              max_ms=WHACK_SHOT_TRAVEL_MS + WHACK_SHOT_LIFE_EPS_MS)

    def _muzzle_flash_px(self, now: int, g: dict[str, Any],
                         muzzle: tuple[float, float]) -> None:
        """
        Spawn the muzzle flash for a pixel-aimed shot. It records the barrel
        tip and the smoothed angle it fired at, so the flash sits where the
        gun really pointed even as the barrel keeps tracking

        :param now: pygame ticks in milliseconds of the shot
        :param g: held whack-gun record
        :param muzzle: barrel tip in window pixels
        """
        weapon = g["weapon"]
        if not weapon["flashes"]:
            return
        self.particles.append({"kind": "flash_px", "weapon": weapon, "gun": g["gun"],
                               "idx": int(self.rng.random() * len(weapon["flashes"])),
                               "muzzle": muzzle, "aim": g["aim"],
                               "start": now, "dur": MUZZLE_MS})

    def register_kill(self, color: str, victim_sq: Square, cell: int, now_ms: int,
                      px: tuple[float, float] | None = None) -> str:
        """
        Credit a kill and pick its celebration: the first of the game is FIRST
        BLOOD, a run by the same side climbs DOUBLE KILL through GODLIKE, and
        anything beyond that is a hit word over the victim. The returned key
        is what the board hands the announcer, so the voice line always
        matches what is on screen

        :param color: capturing side's colour value, which owns the streak
        :param victim_sq: square the kill happened on
        :param cell: cell size in pixels, which the type size scales from
        :param now_ms: pygame ticks in milliseconds
        :param px: exact impact point in window pixels for a whack kill, or
            None to anchor the tag on the victim's square
        :returns: announcer key, such as first_blood, rampage or hit
        """
        if color == self._streak_color:
            self._streak_count += 1
        else:
            self._streak_color = color
            self._streak_count = 1
        n = self._streak_count
        if not self._first_blood_spent:
            self._first_blood_spent = True
            self._callout(now_ms, "FIRST BLOOD", "FIRST ONE DOWN", "lg", cell,
                          Colors.amber_hi, Colors.amber_glow)
            return "first_blood"
        if n in STREAK_LABELS:
            self._callout(now_ms, STREAK_LABELS[n], "", "xl" if n >= 5 else "lg", cell,
                          Colors.accent_hi, Colors.accent_glow)
            return STREAK_LABELS[n].lower().replace(" ", "_")
        self._tag(now_ms, self._pick(HIT_WORDS), victim_sq, cell, px=px)
        return "hit"

    def _callout(self, now: int, text: str, sub: str, size: str, cell: int,
                 fill: str, glow: str) -> None:
        """
        Put up one big centre-board banner, replacing whatever was there. Only
        one banner exists at a time, so a fast killstreak never stacks text
        over itself

        :param now: pygame ticks in milliseconds
        :param text: headline words, rendered upper case
        :param sub: smaller line beneath it, empty for none
        :param size: lg or xl, which sets both type size and how long it holds
        :param cell: cell size in pixels, which the type size scales from
        :param fill: colour of the letter faces
        :param glow: colour of the glow behind them
        """
        size_px = max(int(cell * (1.9 if size == "xl" else 1.3)), 24)
        surf = self._build_callout_surface(text, sub, size_px, fill, glow)
        surf = pg.transform.rotozoom(surf, CALLOUT_ROTATION_DEG, 1.0)
        dur = CALLOUT_XL_MS if size == "xl" else CALLOUT_LG_MS
        self.callouts = [{"surf": surf, "start": now, "dur": dur}]

    def _tag(self, now: int, text: str, victim_sq: Square | str, cell: int,
             px: tuple[float, float] | None = None, fill: str | None = None,
             glow: str | None = None) -> None:
        """
        Float a small tilted word over a square, the light-weight cousin of
        the banner used for hit words, swears and the mole's taunts

        :param now: pygame ticks in milliseconds
        :param text: words to show, rendered upper case
        :param victim_sq: square the tag floats over
        :param cell: cell size in pixels, which the type size scales from
        :param px: exact anchor in window pixels, or None to follow the square
        :param fill: colour of the letters, or None for the default amber
        :param glow: colour of the glow, or None for the default amber glow
        """
        size_px = max(int(cell * 0.45), 12)
        surf, _ = self._build_text_fx(text, size_px, fill or Colors.amber_hi,
                                      Colors.tag_stroke, glow or Colors.amber_glow)
        surf = pg.transform.rotozoom(surf, TAG_ROTATION_DEG, 1.0)
        particle = {"kind": "tag", "surf": surf, "victim_sq": victim_sq,
                    "cell": cell, "start": now, "dur": TAG_MS}
        if px is not None:
            particle["px"] = px
        self.particles.append(particle)

    def taunt_tag(self, now_ms: int, text: str, victim_sq: Square, cell: int) -> None:
        """
        Float the mole's gloating line over a piece that survived, in the loss
        colour -- the visible sting of a lost whack-a-mole check

        :param now_ms: pygame ticks in milliseconds
        :param text: taunt line, chosen from the check's seed
        :param victim_sq: square of the piece that got away
        :param cell: cell size in pixels
        """
        self._tag(now_ms, text, victim_sq, cell, fill=Colors.loss, glow=Colors.loss_glow)

    def raise_flag(self, sq: Square, cell: int, now_ms: int) -> None:
        """
        Pop a white flag over a king to show that side resigned, replacing any
        flag already flying

        :param sq: square of the resigning side's king
        :param cell: cell size in pixels, which the flag is sized from
        :param now_ms: pygame ticks in milliseconds
        """
        self.flags = [{"sq": sq, "cell": cell, "start": now_ms}]

    def start_takeover(self, reason: str, winner_label: str, now_ms: int) -> None:
        """
        Begin the full-window end-of-game card, the CHECKMATE slam that plays
        before the result menu is allowed to appear

        :param reason: headline word, CHECKMATE today
        :param winner_label: winner's name, which the subtitle reads as WINS
        :param now_ms: pygame ticks in milliseconds the game ended at
        """
        self._takeover = {"reason": reason, "winner": winner_label, "start": now_ms, "wh": None}

    def has_takeover(self) -> bool:
        """
        Say whether the end-of-game card is up, which the game screen asks
        before it draws the result menu over it

        :returns: True while a takeover is armed or playing
        """
        return self._takeover is not None

    def clear_takeover(self) -> None:
        """
        Take the end-of-game card down, which the game screen does the moment
        the result menu takes the screen instead
        """
        self._takeover = None

    def _shoot(self, now: int, c: dict[str, Any]) -> None:
        """
        Run the fire beat of a staged shot: muzzle flash, the pellet volley,
        the screen shake, and on a miss the SKILL ISSUE taunt

        :param now: pygame ticks in milliseconds of the shot
        :param c: capture record being fired
        """
        weapon = c["weapon"]
        if weapon["flashes"]:
            self.particles.append({"kind": "flash", "weapon": weapon, "gun": c["gun"],
                                   "idx": int(self.rng.random() * len(weapon["flashes"])),
                                   "from_sq": c["from_sq"], "victim_sq": c["victim_sq"],
                                   "cell": c["cell"], "start": now, "dur": MUZZLE_MS})
        self._spawn_pellets(now, c)
        self.trigger_shake(now, c["power"])
        if c.get("miss") and c.get("callout", True):
            self._skill_issue_callout(now, c["cell"])

    def _spawn_pellets(self, now: int, c: dict[str, Any]) -> None:
        """
        Launch the volley for one shot from the barrel tip. Exactly one lead
        pellet carries the capture and resolves it on arrival; a miss aims
        clear of the victim and launches no lead at all, which is why nobody
        dies to a fumbled check. The bystanders a stray may wound are latched
        here

        :param now: pygame ticks in milliseconds of the shot
        :param c: capture record being fired
        """
        spec = gunfx.gun_spec(c["gun"])
        muzzle, _ = self._muzzle(c["weapon"], c["from_sq"], c["victim_sq"], c["cell"])
        tx, ty = self._center(c["victim_sq"])
        miss = c.get("miss")
        if miss:
            tx, ty = self._miss_point(muzzle, tx, ty, c["cell"])
        base = self._angle_to(muzzle, (tx, ty))
        speed = self._pellet_speed(muzzle, (tx, ty), PROJECTILE_TRAVEL_MS)
        self._bystanders = set(c["occupied"])
        for i, (ang, factor) in enumerate(gunfx.pellet_spread(spec, base, self._rnd)):
            lead = i == 0 and not miss
            self._push_pellet(now, spec, muzzle, ang, speed * factor, c["cell"],
                              lead=lead, capture=c if lead else None)

    @staticmethod
    def _pellet_speed(muzzle: tuple[float, float], target: tuple[float, float],
                      travel_ms: int) -> float:
        """
        Pick the speed that covers this distance in the intended flight time,
        so a board-length shot and a next-door shot both land on the same
        beat and captures resolve at a steady rhythm

        :param muzzle: start point in window pixels
        :param target: point being shot at, in window pixels
        :param travel_ms: intended flight time in milliseconds
        :returns: speed in pixels per second
        """
        dist = math.hypot(target[0] - muzzle[0], target[1] - muzzle[1]) or 1.0
        return dist / (travel_ms / 1000.0)

    def _push_pellet(self, now: int, spec: gunfx.GunSpec, muzzle: tuple[float, float],
                     ang: float, speed: float, cell: int, *, lead: bool = False,
                     capture: dict[str, Any] | None = None, inert: bool = False,
                     max_ms: int = PROJECTILE_MAX_MS) -> None:
        """
        Put one pellet in the air, wearing the look its gun gives it -- colour,
        thickness and tracer length -- scaled to the current cell size so the
        volley reads the same on any board size

        :param now: pygame ticks in milliseconds the pellet was born at
        :param spec: gun spec supplying the pellet's colour and dimensions
        :param muzzle: start point in window pixels
        :param ang: heading in radians
        :param speed: speed in pixels per second
        :param cell: cell size in pixels, which the pellet art scales with
        :param lead: True for the single pellet that resolves the capture
        :param capture: capture record this pellet resolves on arrival, None
            for every other pellet
        :param inert: True for a cosmetic whack slug, which wounds nobody
        :param max_ms: lifetime cap in milliseconds before the pellet expires
        """
        f = cell / PROJECTILE_REF_CELL
        self.projectiles.append({
            "x": muzzle[0], "y": muzzle[1],
            "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed,
            "color": spec.color, "size": max(spec.size * f, 2),
            "len": max(spec.length * f, 6), "cell": cell,
            "lead": lead, "capture": capture, "inert": inert,
            "born": now, "max_ms": max_ms})

    def _miss_point(self, muzzle: tuple[float, float], tx: float, ty: float,
                    cell: int) -> tuple[float, float]:
        """
        Choose where a whiffed shot actually goes: at least a whole cell to
        one side of the victim, so a miss reads as a miss rather than a hit
        that somehow did nothing

        :param muzzle: barrel tip in window pixels
        :param tx: victim centre x in window pixels
        :param ty: victim centre y in window pixels
        :param cell: cell size in pixels, which the offset scales with
        :returns: the point the volley is aimed at instead, in window pixels
        """
        aim = self._angle_to(muzzle, (tx, ty))
        side = 1 if self.rng.random() < 0.5 else -1
        perp = aim + math.pi / 2.0
        off = cell * self._rnd(1.0, 1.6) * side
        along = cell * self._rnd(-0.3, 0.6)
        return (tx + math.cos(perp) * off + math.cos(aim) * along,
                ty + math.sin(perp) * off + math.sin(aim) * along)

    def _impact_package(self, now: int, anchor: dict[str, Any], cell: int) -> None:
        """
        Spawn a whole hit at one anchor: the ring, the blood, the sparks, the
        smoke and the bullet hole that outlives them all. Every hit in the
        game comes through here, whether it was aimed at a square or at a
        loose pixel

        :param now: pygame ticks in milliseconds of the hit
        :param anchor: particle anchor fragment, either a px point or a
            victim_sq, merged into each spawned record
        :param cell: cell size in pixels, which every element scales with
        """
        self.particles.append({"kind": "impact", **anchor, "cell": cell,
                               "start": now, "dur": IMPACT_MS})
        self.particles.append({"kind": "blood", **anchor, "cell": cell,
                               "start": now, "dur": BLOOD_MS})
        self.holes.append({**anchor, "cell": cell, "start": now,
                           "dur": HOLE_IN_MS + HOLE_HOLD_MS + HOLE_FADE_MS})
        spark_size = max(int(cell * 0.06), 3)
        for _ in range(SPARK_COUNT):
            self.particles.append({
                "kind": "spark", **anchor, "ang": self._rnd(0, math.tau),
                "dist": self._rnd(20, 70) * cell / 80.0, "size": spark_size,
                "start": now, "dur": self._rnd(*SPARK_MS)})
        for _ in range(SMOKE_PUFFS):
            self.particles.append({
                "kind": "smoke", **anchor,
                "jx": self._rnd(-8, 8), "jy": self._rnd(-8, 8),
                "cell": cell, "start": now, "dur": self._rnd(*SMOKE_MS)})

    def impact_px(self, now_ms: int, px: tuple[float, float], cell: int) -> None:
        """
        Blow a hit open at an exact pixel, which is how a whack-a-mole pop
        lands its damage away from any square centre

        :param now_ms: pygame ticks in milliseconds
        :param px: impact point in window pixels
        :param cell: cell size in pixels
        """
        self._impact_package(now_ms, {"px": px}, cell)

    def _impact(self, now: int, from_sq: Square, victim_sq: Square,
                victim: pg.Surface | None, cell: int) -> None:
        """
        Kill the piece on a square: the full hit package plus the victim's
        body flung away along the line the bullet came in on

        :param now: pygame ticks in milliseconds
        :param from_sq: shooter's square, which decides which way the body
            flies
        :param victim_sq: square being hit
        :param victim: victim sprite to fling, None to skip the ragdoll
        :param cell: cell size in pixels
        """
        self._impact_package(now, {"victim_sq": victim_sq}, cell)
        if victim is not None:
            aim = self._aim(from_sq, victim_sq)
            self.particles.append({
                "kind": "ragdoll", "surf": victim, "victim_sq": victim_sq,
                "dir": 1 if math.cos(aim) >= 0 else -1,
                "start": now, "dur": RAGDOLL_MS})

    def trigger_shake(self, now: int, power: str) -> None:
        """
        Kick the whole board, the weight behind a gunshot: a queen or rook
        going down rocks the screen far harder than a pawn does

        :param now: pygame ticks in milliseconds
        :param power: strength key from SHAKE_AMP; an unknown key shakes only
            gently
        """
        amp = SHAKE_AMP.get(power, 5)
        dur = SHAKE_HARD_MS if power == "hard" else SHAKE_SOFT_MS
        self._shake = {"start": now, "dur": dur, "amp": amp,
                       "seed": int(self.rng.random() * 1_000_000)}

    def shake_offset(self, now: int) -> tuple[int, int]:
        """
        Tell the board how far to draw itself off true this frame. The kick
        decays across its window and clears itself at the end; review browsing
        ignores it, so replaying history is never shaken

        :param now: pygame ticks in milliseconds
        :returns: horizontal and vertical offset in pixels, (0, 0) when still
        """
        s = self._shake
        if s is None:
            return (0, 0)
        t = (now - s["start"]) / s["dur"]
        if t >= 1.0:
            self._shake = None
            return (0, 0)
        amp = s["amp"] * (1.0 - t)
        r = random.Random(s["seed"] + int(t * 8))
        return (int((r.random() * 2 - 1) * amp), int((r.random() * 2 - 1) * amp))

    def update(self, now: int) -> None:
        """
        Advance every effect by one frame: fire the shots whose moment has
        come, step the pellets, and retire everything that has outlived its
        window. Board calls this once per frame before it draws anything, so
        nothing here may be heavy

        :param now: pygame tick count in milliseconds since pygame init
        """
        dt = (0.0 if self._last_now is None
              else max(0.0, min(DT_MAX, (now - self._last_now) / 1000.0)))
        self._last_now = now
        for c in list(self.captures):
            if not c["fired"] and now >= c["fire_at"]:
                advance_only = bool(c.get("advance_only"))
                if not advance_only:
                    self._shoot(now, c)
                c["fired"] = True
                if c["on_fire"] is not None:
                    c["on_fire"](advance_only)
                if advance_only:
                    self._resolve_capture(now, c)
        self.captures = [c for c in self.captures
                         if not (c.get("miss") and c["fired"]
                                 and now >= c["fire_at"] + MISS_HOLD_MS)]
        self._update_projectiles(now, dt)
        self.particles = [p for p in self.particles if now < p["start"] + p["dur"]]
        self.holes = [h for h in self.holes if now < h["start"] + h["dur"]]
        self.drops = [d for d in self.drops if now < d["start"] + d["dur"]]
        self.callouts = [c for c in self.callouts if now < c["start"] + c["dur"]]
        self._piece_shakes = {sq: s for sq, s in self._piece_shakes.items()
                              if now < s["start"] + s["dur"]}

    def _update_projectiles(self, now: int, dt: float) -> None:
        """
        Fly every pellet and decide what it meets: the lead pellet resolves
        its capture on arrival (or the moment it would be lost), a stray
        wounds the first bystander it crosses and is spent doing so, and
        anything expired or off the board is dropped

        :param now: pygame ticks in milliseconds
        :param dt: seconds since the previous frame, clamped by DT_MAX
        """
        survivors = []
        for pr in self.projectiles:
            pr["x"] += pr["vx"] * dt
            pr["y"] += pr["vy"] * dt
            expired = now - pr["born"] >= pr["max_ms"] or self._off_board(pr)
            if pr["lead"]:
                c = pr["capture"]
                pending = c is not None and c in self.captures
                arrived = now - pr["born"] >= PROJECTILE_TRAVEL_MS
                if pending and (arrived or expired):
                    self._resolve_capture(now, c)
                    continue
                if expired:
                    continue
            else:
                sq = None if pr.get("inert") else self._stray_target(pr)
                if sq is not None:
                    self._wound(now, sq, pr["cell"])
                    self._bystanders.discard(sq)
                    continue
                if expired:
                    continue
            survivors.append(pr)
        self.projectiles = survivors

    def _pellet_hits_square(self, pr: dict[str, Any], sq: Square) -> bool:
        """
        Test whether a pellet is inside a square's cell right now, the hit
        test that decides whether a bystander gets wounded

        :param pr: pellet record carrying its position and cell size
        :param sq: square being tested
        :returns: True when the pellet is over that square
        """
        cx, cy = self._center(sq)
        half = pr["cell"] / 2.0
        return cast(bool, abs(pr["x"] - cx) <= half and abs(pr["y"] - cy) <= half)

    def _stray_target(self, pr: dict[str, Any]) -> Square | None:
        """
        Find the first bystander a stray pellet is crossing. Each square
        leaves the set once wounded, so no piece is shot twice by one volley

        :param pr: pellet record
        :returns: the square that gets wounded, or None when nothing is hit
        """
        for sq in self._bystanders:
            if self._pellet_hits_square(pr, sq):
                return sq
        return None

    def _off_board(self, pr: dict[str, Any]) -> bool:
        """
        Tell whether a pellet has flown clear of the board, plus a cell of
        margin, so it can be dropped instead of tracked forever. Without a
        board rect installed nothing is ever off board

        :param pr: pellet record
        :returns: True once the pellet is outside the board area
        """
        r = self.board_rect
        if r is None:
            return False
        m = pr["cell"]
        return cast(bool, (pr["x"] < r.x - m or pr["x"] > r.right + m
                           or pr["y"] < r.y - m or pr["y"] > r.bottom + m))

    def _resolve_capture(self, now: int, c: dict[str, Any]) -> None:
        """
        Finish a capture: kill the victim and let the attacker slide onto the
        square. An advance-only capture -- the whack check already killed the
        piece -- skips straight to the slide with no second death

        :param now: pygame ticks in milliseconds
        :param c: capture record being resolved
        """
        if not c.get("advance_only"):
            self._impact(now, c["from_sq"], c["victim_sq"], c["victim"], c["cell"])
        if c["on_slide"] is not None:
            c["on_slide"]()
        if c in self.captures:
            self.captures.remove(c)

    def _wound(self, now: int, sq: Square, cell: int) -> None:
        """
        Wound the piece on a square without killing it: blood, sparks, a
        flinch and, about half the time, a swear. This is all a stray pellet
        ever does -- only the lead pellet can take a piece off the board

        :param now: pygame ticks in milliseconds
        :param sq: square of the wounded piece
        :param cell: cell size in pixels
        """
        swears = self.rng.random() < WOUND_SWEAR_CHANCE
        self.particles.append({"kind": "blood", "victim_sq": sq, "cell": cell,
                               "start": now, "dur": BLOOD_MS})
        spark_size = max(int(cell * 0.06), 3)
        for _ in range(WOUND_SPARKS):
            self.particles.append({
                "kind": "spark", "victim_sq": sq, "ang": self._rnd(0, math.tau),
                "dist": self._rnd(20, 70) * cell / 80.0, "size": spark_size,
                "start": now, "dur": self._rnd(*SPARK_MS)})
        self._piece_shakes[sq] = {"start": now, "dur": SHAKE_SOFT_MS,
                                  "amp": max(int(cell * PIECE_SHAKE_AMP_FRAC), 2)}
        if swears:
            self.swear(now, sq, cell)

    def draw_holes(self, window: pg.Surface, now: int) -> None:
        """
        Paint the bullet holes. Board draws them under the pieces, so a hole
        reads as damage to the board rather than to whoever is standing there
        now

        :param window: surface to draw on, the app window
        :param now: pygame ticks in milliseconds
        """
        if self.geom is None:
            return
        for h in self.holes:
            self._draw_hole(window, h, now)

    def draw_over(self, window: pg.Surface, now: int) -> None:
        """
        Paint everything that belongs above the pieces, in the order the fight
        reads: capture choreography, pellets, particles, dropped guns, held
        guns, surrender flags and finally the centre-board banner

        :param window: surface to draw on, the app window
        :param now: pygame ticks in milliseconds
        """
        if self.geom is None:
            return
        for c in self.captures:
            self._draw_capture(window, c, now)
        for pr in self.projectiles:
            self._draw_pellet(window, pr)
        for p in self.particles:
            self._draw_particle(window, p, now)
        for d in self.drops:
            self._draw_gun_drop(window, d, now)
        self._draw_held_gun(window, now)
        self._draw_gun_px(window, now)
        for f in self.flags:
            self._draw_flag(window, f, now)
        for c in self.callouts:
            self._draw_callout(window, c, now)

    def _draw_capture(self, window: pg.Surface, c: dict[str, Any], now: int) -> None:
        """
        Draw one capture in whatever beat it has reached: the attacker and
        victim sprites the board is hiding, plus the gun either spinning up in
        its draw flourish or held on target with the recoil kick behind it

        :param window: surface to draw on
        :param c: capture record being drawn
        :param now: pygame ticks in milliseconds
        """
        fx, fy = self._center(c["from_sq"])
        tx, ty = self._center(c["victim_sq"])
        advance_only = c.get("advance_only")
        if c["victim"] is not None and not advance_only:
            window.blit(c["victim"], c["victim"].get_rect(center=(tx, ty)))
        if c["attacker"] is not None:
            window.blit(c["attacker"], c["attacker"].get_rect(center=(fx, fy)))
        weapon = c["weapon"]
        aim = self._angle_to((fx, fy), (tx, ty))
        pivot = (fx, fy - c["cell"] * GUN_PIVOT_RISE_FRAC)
        t = now - c["start"]
        if not c.get("predrawn") and t < DRAW_MS:
            gunfx.draw_flourish(window, weapon["gun"], weapon["grip"], pivot, aim,
                                t / DRAW_MS, gunfx.GUN_DRAW_SPINS_LAND)
        else:
            if c["fired"] and not advance_only:
                rx, ry = self._recoil(c["gun"], weapon, aim, now - c["fire_at"])
                pivot = (pivot[0] + rx, pivot[1] + ry)
            gunfx.blit_aimed(window, weapon["gun"], weapon["grip"], pivot, aim)

    def _recoil(self, gun: str, weapon: dict[str, Any], aim: float,
                elapsed: int) -> tuple[float, float]:
        """
        Kick a gun back along its aim line right after the shot and ease it
        home again, which is the weight difference between a pawn's revolver
        and a knight's hand cannon

        :param gun: gun name, which sets how hard it kicks
        :param weapon: built weapon record, whose scale keeps the kick in
            proportion to the current cell size
        :param aim: aim angle in radians
        :param elapsed: milliseconds since the shot; outside the recoil window
            there is no kick at all
        :returns: horizontal and vertical offset in pixels
        """
        if elapsed < 0 or elapsed >= RECOIL_MS:
            return 0.0, 0.0
        r = (gunfx.gun_spec(gun).recoil * weapon["scale"]
             * (1.0 - smoothstep(elapsed / RECOIL_MS)))
        return -math.cos(aim) * r, -math.sin(aim) * r

    def _draw_particle(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Send one particle to the routine that knows how to draw its kind

        :param window: surface to draw on
        :param p: particle record, dispatched on its kind
        :param now: pygame ticks in milliseconds
        """
        kind = p["kind"]
        if kind == "flash":
            self._draw_flash(window, p, now)
        elif kind == "flash_px":
            self._draw_flash_px(window, p, now)
        elif kind == "impact":
            self._draw_impact(window, p, now)
        elif kind == "blood":
            self._draw_blood(window, p, now)
        elif kind == "spark":
            self._draw_spark(window, p, now)
        elif kind == "smoke":
            self._draw_smoke(window, p, now)
        elif kind == "ragdoll":
            self._draw_ragdoll(window, p, now)
        elif kind == "tag":
            self._draw_tag(window, p, now)

    def _blit_flash(self, window: pg.Surface, p: dict[str, Any], now: int, prog: float,
                    muzzle: tuple[float, float], aim: float) -> None:
        """
        Blit the chosen muzzle-flash frame at the barrel tip, moved by the
        same recoil the gun is under so flash and gun never come apart

        :param window: surface to draw on
        :param p: flash particle record, naming the weapon and the variant
        :param now: pygame ticks in milliseconds
        :param prog: 0..1 progress through the flash's life
        :param muzzle: barrel tip in window pixels
        :param aim: aim angle in radians
        """
        weapon = p["weapon"]
        fl = weapon["flashes"][min(p["idx"], len(weapon["flashes"]) - 1)]
        rx, ry = self._recoil(p["gun"], weapon, aim, now - p["start"])
        gunfx.draw_flash(window, fl["img"], fl["anchor"], (muzzle[0] + rx, muzzle[1] + ry),
                         aim, prog)

    def _draw_flash(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw a square-aimed muzzle flash, working the barrel tip out afresh
        each frame so it follows a board that flips, resizes or shakes

        :param window: surface to draw on
        :param p: flash particle record
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0 or not p["weapon"]["flashes"]:
            return
        muzzle, aim = self._muzzle(p["weapon"], p["from_sq"], p["victim_sq"], p["cell"])
        self._blit_flash(window, p, now, prog, muzzle, aim)

    def _draw_flash_px(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw a pixel-aimed muzzle flash from the whack gun, which recorded its
        barrel tip and angle at the instant it fired

        :param window: surface to draw on
        :param p: flash particle record carrying muzzle and aim
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        self._blit_flash(window, p, now, prog, p["muzzle"], p["aim"])

    def _draw_pellet(self, window: pg.Surface, pr: dict[str, Any]) -> None:
        """
        Draw one pellet as a streak lying along the way it is travelling

        :param window: surface to draw on
        :param pr: pellet record carrying position, velocity and look
        """
        speed = math.hypot(pr["vx"], pr["vy"]) or 1.0
        gunfx.draw_bullet(window, (pr["x"], pr["y"]), pr["vx"] / speed, pr["vy"] / speed,
                          pr["color"], pr["size"], pr["len"])

    def _draw_impact(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw the amber ring of a hit, growing outwards and fading as it goes

        :param window: surface to draw on
        :param p: impact particle record
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        d = p["cell"] * 0.8 * (0.2 + 1.4 * prog)
        r = int(d / 2)
        if r < 1:
            return
        alpha = int(230 * (1 - prog))
        stroke = max(int(p["cell"] * 0.045), 2)
        layer = _impact_ring_sprite(r, stroke)
        layer.set_alpha(alpha)
        cx, cy = self._anchor(p)
        window.blit(layer, (cx - r - 4, cy - r - 4))

    def _draw_blood(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw a blood splat: it pops out to full size early, then sits there
        fading for the rest of its life

        :param window: surface to draw on
        :param p: blood particle record
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        scale = 0.3 + 0.7 * min(prog / 0.3, 1.0)
        r = int(p["cell"] * 0.6 * scale / 2)
        if r < 1:
            return
        alpha = int(217 * (1 - prog))
        layer = _blood_sprite(r)
        layer.set_alpha(alpha)
        cx, cy = self._anchor(p)
        window.blit(layer, (cx - r - 1, cy - r - 1))

    def _draw_spark(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw one spark flying out from the hit, drifting downwards a little as
        it fades so the shower has some weight to it

        :param window: surface to draw on
        :param p: spark particle record with its angle and travel distance
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        cx, cy = self._anchor(p)
        dist = p["dist"] * prog
        x = cx + math.cos(p["ang"]) * dist
        y = cy + math.sin(p["ang"]) * dist + 6 * prog
        alpha = int(255 * (1 - prog))
        s = p["size"]
        surf = _spark_sprite(s)
        surf.set_alpha(alpha)
        window.blit(surf, (x - s / 2, y - s / 2))

    def _draw_smoke(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw one puff of smoke growing and rising off the hit, with a small
        random offset so the puffs of one hit do not sit on top of each other

        :param window: surface to draw on
        :param p: smoke particle record
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        r = int(p["cell"] * 0.5 * (0.4 + prog) / 2)
        if r < 1:
            return
        alpha = int(130 * (1 - prog))
        layer = _smoke_sprite(r)
        layer.set_alpha(alpha)
        cx, cy = self._anchor(p)
        window.blit(layer, (cx + p["jx"] - r, cy + p["jy"] - p["cell"] * 0.9 * prog - r))

    def _draw_ragdoll(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw a shot piece being blasted off the board: it is launched away
        from the shooter, spinning, then falls, shrinks and fades out

        :param window: surface to draw on
        :param p: ragdoll particle record with the victim sprite and the
            direction it flies
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        d = p["dir"]
        w = p["surf"].get_width()
        if prog < RAGDOLL_LAUNCH_FRAC:
            t = prog / RAGDOLL_LAUNCH_FRAC
            tx = d * RAGDOLL_LAUNCH_X_FRAC * w * t
            ty = RAGDOLL_LAUNCH_Y_FRAC * w * t
            rot, alpha, scl = d * RAGDOLL_LAUNCH_ROT * t, 255, 1.0
        else:
            t = (prog - RAGDOLL_LAUNCH_FRAC) / (1.0 - RAGDOLL_LAUNCH_FRAC)
            tx = d * w * (RAGDOLL_LAUNCH_X_FRAC + RAGDOLL_FALL_X_FRAC * t)
            ty = w * (RAGDOLL_LAUNCH_Y_FRAC + RAGDOLL_FALL_Y_FRAC * t)
            rot = d * (RAGDOLL_LAUNCH_ROT + RAGDOLL_FALL_ROT * t)
            alpha = int(255 * (1 - t))
            scl = 1.0 - RAGDOLL_FALL_SHRINK * t
        img = pg.transform.rotozoom(p["surf"], rot, max(scl, 0.1))
        if alpha < 255:
            img.fill((255, 255, 255, max(alpha, 0)), special_flags=pg.BLEND_RGBA_MULT)
        cx, cy = self._center(p["victim_sq"])
        window.blit(img, img.get_rect(center=(cx + tx, cy + ty)))

    def _draw_held_gun(self, window: pg.Surface, now: int) -> None:
        """
        Draw the gun a checking piece keeps trained on the enemy king: the
        draw flourish first, then held on target. When a steady-aim check is
        shrinking that very piece away, the gun shrinks with it so the two
        never come apart

        :param window: surface to draw on
        :param now: pygame ticks in milliseconds
        """
        g = self._check_gun
        if g is None:
            return
        scale = self.aim_victim_scale if g["from_sq"] == self.aim_victim else 1.0
        if scale <= 0.02:
            return
        t = now - g["start"]
        weapon = g["weapon"]
        fx, fy = self._center(g["from_sq"])
        aim = self._aim(g["from_sq"], g["victim_sq"])
        pivot = (fx, fy - g["cell"] * GUN_PIVOT_RISE_FRAC * scale)
        if t < DRAW_MS:
            gunfx.draw_flourish(window, weapon["gun"], weapon["grip"], pivot, aim,
                                t / DRAW_MS, gunfx.GUN_DRAW_SPINS_LAND)
        elif scale >= 0.999:
            gunfx.blit_aimed(window, weapon["gun"], weapon["grip"], pivot, aim)
        else:
            gun_img = pg.transform.smoothscale(
                weapon["gun"], (max(int(weapon["gun"].get_width() * scale), 1),
                                max(int(weapon["gun"].get_height() * scale), 1)))
            grip = (weapon["grip"][0] * scale, weapon["grip"][1] * scale)
            gunfx.blit_aimed(window, gun_img, grip, pivot, aim)

    def _draw_gun_px(self, window: pg.Surface, now: int) -> None:
        """
        Draw the whack gun the capturing piece is holding: the draw flourish
        first, then held along the smoothed aim with the recoil kick of its
        last shot still fading

        :param window: surface to draw on
        :param now: pygame ticks in milliseconds
        """
        g = self._whack_gun
        if g is None:
            return
        weapon = g["weapon"]
        aim = g["aim"]
        pivot = self._pivot(g["from_sq"], g["cell"])
        t = now - g["start"]
        if t < DRAW_MS:
            gunfx.draw_flourish(window, weapon["gun"], weapon["grip"], pivot, aim,
                                t / DRAW_MS, gunfx.GUN_DRAW_SPINS_LAND)
            return
        if g["fired_at"] is not None:
            rx, ry = self._recoil(g["gun"], weapon, aim, now - g["fired_at"])
            pivot = (pivot[0] + rx, pivot[1] + ry)
        gunfx.blit_aimed(window, weapon["gun"], weapon["grip"], pivot, aim)

    @staticmethod
    def _drop_state(d: dict[str, Any], bx: float, by: float,
                    t: float) -> tuple[float, float, float, int]:
        """
        Place a tumbling dropped gun at one instant: it flies out, falls and
        comes to rest within the first quarter of the window, then simply lies
        there fading for the rest of it

        :param d: drop record with sideways speed, spin and fall distance
        :param bx: source square centre x in window pixels
        :param by: source square centre y in window pixels
        :param t: 0..1 progress through the drop's life
        :returns: position, rotation in degrees and alpha for this frame
        """
        tm = min(t * 4.0, 1.0)
        cell = d["cell"]
        x = bx + d["vx"] * cell * tm
        y = (by - cell * GUN_PIVOT_RISE_FRAC) - cell * 0.25 * tm + d["fall"] * (tm * tm)
        return x, y, d["spin"] * tm, int(255 * (1.0 - t))

    def _draw_gun_drop(self, window: pg.Surface, d: dict[str, Any], now: int) -> None:
        """
        Draw one discarded gun mid-tumble, fading out over its window

        :param window: surface to draw on
        :param d: drop record
        :param now: pygame ticks in milliseconds
        """
        t = (now - d["start"]) / d["dur"]
        if not 0.0 <= t < 1.0:
            return
        bx, by = self._center(d["from_sq"])
        x, y, angle, alpha = self._drop_state(d, bx, by, t)
        img = pg.transform.rotozoom(d["img"], angle, 1.0)
        img.set_alpha(alpha)
        window.blit(img, img.get_rect(center=(x, y)))

    def _draw_hole(self, window: pg.Surface, h: dict[str, Any], now: int) -> None:
        """
        Draw one bullet hole through its three beats -- punched in, held, then
        faded away -- so the board slowly forgets where it was shot

        :param window: surface to draw on
        :param h: hole record
        :param now: pygame ticks in milliseconds
        """
        t = now - h["start"]
        if t < 0:
            return
        if t < HOLE_IN_MS:
            scale, alpha = t / HOLE_IN_MS, int(255 * (t / HOLE_IN_MS))
        elif t < HOLE_IN_MS + HOLE_HOLD_MS:
            scale, alpha = 1.0, 255
        else:
            scale = 1.0
            alpha = int(255 * (1 - (t - HOLE_IN_MS - HOLE_HOLD_MS) / HOLE_FADE_MS))
        r = int(h["cell"] * 0.26 * scale / 2)
        if r < 1 or alpha <= 0:
            return
        layer = _hole_sprite(r)
        layer.set_alpha(max(alpha, 0))
        cx, cy = self._anchor(h)
        window.blit(layer, (cx - r - 2, cy - r - 2))

    @staticmethod
    def _build_text_fx(text: str, size_px: int, fill: str, stroke: str,
                       glow: str) -> tuple[pg.Surface, int]:
        """
        Render the game's poster lettering: a soft glow, an extruded shadow, a
        fat outline and the letter faces on top. Far too heavy to run per
        frame, so every caller renders once and animates the surface

        :param text: words to render, upper-cased here
        :param size_px: type size in pixels for the display face
        :param fill: colour of the letter faces
        :param stroke: colour of the outline and the extrusion under it
        :param glow: colour of the glow behind the letters
        :returns: the lettering surface and the y of the ink's bottom edge,
            which callers use to tuck a subtitle underneath
        """
        text = text.upper()
        font = get_font(max(int(size_px), 8), family=DISPLAY)
        base = font.render(text, True, pg.Color(fill))
        sw, sh = base.get_size()
        stroke_w = max(int(size_px * 0.03), 2)
        extrude = max(int(size_px * 0.06), 2)
        glow_pad = max(int(size_px * GLOW_PAD_FRAC), 8)
        pad = stroke_w + glow_pad + 4
        surf = pg.Surface((sw + pad * 2, sh + pad * 2 + extrude), pg.SRCALPHA)
        cx, cy = pad, pad
        glow_rgb = pg.Color(glow)[:3]
        gtext = font.render(text, True, (*glow_rgb, 255))
        gw, gh = gtext.get_size()
        glow_layer = pg.Surface((gw + glow_pad * 2, gh + glow_pad * 2), pg.SRCALPHA)
        glow_layer.blit(gtext, (glow_pad, glow_pad))
        glow_layer = soft_blur(glow_layer, max(GLOW_BLUR_PASSES, int(math.log2(glow_pad))))
        glow_layer.fill((255, 255, 255, GLOW_ALPHA), special_flags=pg.BLEND_RGBA_MULT)
        surf.blit(glow_layer, (cx - glow_pad, cy - glow_pad))
        stroke_img = font.render(text, True, pg.Color(stroke))
        surf.blit(stroke_img, (cx, cy + extrude))
        for dx in (-stroke_w, 0, stroke_w):
            for dy in (-stroke_w, 0, stroke_w):
                if dx or dy:
                    surf.blit(stroke_img, (cx + dx, cy + dy))
        surf.blit(base, (cx, cy))
        ink_bottom = cy + base.get_bounding_rect().bottom
        return surf, ink_bottom

    def _build_callout_surface(self, text: str, sub: str, size_px: int, fill: str,
                               glow: str) -> pg.Surface:
        """
        Compose one centre-board banner: the headline lettering with an
        optional smaller line tucked under its ink, centred as a single image
        the animation can then scale and fade as a whole

        :param text: headline words
        :param sub: subtitle words, empty for a headline on its own
        :param size_px: headline type size in pixels
        :param fill: colour of the headline faces
        :param glow: colour of the glow behind the headline
        :returns: the finished banner surface
        """
        main, ink_bottom = self._build_text_fx(text, size_px, fill, Colors.outcome_stroke, glow)
        if not sub:
            return main
        sub_font = get_font(max(int(size_px * 0.17), 11), bold=True, family=SANS)
        sub_img = sub_font.render(sub.upper(), True, pg.Color(Colors.text_dim))
        gap = max(int(size_px * 0.13), 4)
        top = ink_bottom + gap
        w = max(main.get_width(), sub_img.get_width())
        h = max(main.get_height(), top + sub_img.get_height())
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.blit(main, ((w - main.get_width()) // 2, 0))
        surf.blit(sub_img, ((w - sub_img.get_width()) // 2, top))
        return surf

    @staticmethod
    def _callout_anim(prog: float) -> tuple[float, int]:
        """
        Give a banner its punch: it snaps in oversized, eases back and holds
        there, then drifts a little larger again as it fades out

        :param prog: 0..1 progress through the banner's life
        :returns: scale factor and alpha for this frame
        """
        if prog < 0.12:
            f = prog / 0.12
            return 0.5 + 0.56 * f, int(255 * f)
        if prog < 0.78:
            f = (prog - 0.12) / 0.66
            return 1.06 - 0.06 * f, 255
        f = (prog - 0.78) / 0.22
        return 1.0 + 0.02 * f, int(255 * (1 - f))

    def _draw_callout(self, window: pg.Surface, c: dict[str, Any], now: int) -> None:
        """
        Draw the current banner across the board, a little above its centre so
        the pieces underneath stay readable

        :param window: surface to draw on
        :param c: banner record
        :param now: pygame ticks in milliseconds
        """
        if self.board_rect is None:
            return
        prog = (now - c["start"]) / c["dur"]
        if not 0.0 <= prog < 1.0:
            return
        scale, alpha = self._callout_anim(prog)
        img = pg.transform.smoothscale_by(c["surf"], scale)
        img.set_alpha(max(alpha, 0))
        cx = self.board_rect.centerx
        cy = self.board_rect.y + int(self.board_rect.height * 0.42)
        window.blit(img, img.get_rect(center=(cx, cy)))

    @staticmethod
    def _tag_anim(prog: float) -> tuple[float, float, int]:
        """
        Give a floating tag its arc: it pops in oversized, then rises off the
        piece and fades as it settles back

        :param prog: 0..1 progress through the tag's life
        :returns: rise fraction, scale factor and alpha for this frame
        """
        if prog < 0.25:
            f = prog / 0.25
            return 0.65 * f, 0.4 + 0.7 * f, int(255 * f)
        f = (prog - 0.25) / 0.75
        return 0.65 + 0.35 * f, 1.1 - 0.1 * f, int(255 * (1 - f))

    def _draw_tag(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Draw one floating tag over its anchor, climbing as it fades

        :param window: surface to draw on
        :param p: tag particle record
        :param now: pygame ticks in milliseconds
        """
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        rise, scale, alpha = self._tag_anim(prog)
        img = pg.transform.smoothscale_by(p["surf"], scale)
        img.set_alpha(max(alpha, 0))
        cx, cy = self._anchor(p)
        window.blit(img, img.get_rect(center=(cx, cy - rise * p["cell"] * 0.8)))

    @staticmethod
    def _pop(x: float) -> float:
        """
        Ease with an overshoot: the value swings past its target and settles
        back, which is what makes the surrender flag pop rather than merely
        appear

        :param x: 0..1 progress, clamped
        :returns: eased value, briefly above 1 before it settles
        """
        x = max(0.0, min(1.0, x)) - 1.0
        return 1 + (BACK_OVERSHOOT + 1) * x ** 3 + BACK_OVERSHOOT * x ** 2

    def _draw_flag(self, window: pg.Surface, f: dict[str, Any], now: int) -> None:
        """
        Draw the white flag beside a resigning king, popping in as it arrives

        :param window: surface to draw on
        :param f: flag record naming the king's square
        :param now: pygame ticks in milliseconds
        """
        surf = emoji_surface(SURRENDER_FLAG, max(int(f["cell"] * 0.6), 8))
        if surf is None:
            return
        t = (now - f["start"]) / FLAG_POP_MS
        if t < 1.0:
            surf = pg.transform.rotozoom(surf, 0.0, max(self._pop(t), 0.05))
        cx, cy = self._center(f["sq"])
        window.blit(surf, surf.get_rect(center=(cx + f["cell"] * 0.3, cy - f["cell"] * 0.3)))

    @staticmethod
    def _takeover_bar(width: int, height: int) -> pg.Surface:
        """
        Build one of the two accent bars that slide in above and below the
        takeover headline: a gradient between the two brand colours that fades
        out towards both ends

        :param width: bar width in pixels
        :param height: bar thickness in pixels
        :returns: the bar surface
        """
        width = max(width, 4)
        height = max(height, 2)
        acc, amb = pg.Color(Colors.accent), pg.Color(Colors.amber)
        bar = pg.Surface((width, height), pg.SRCALPHA)
        for x in range(width):
            f = x / (width - 1)
            a = int(255 * math.sin(f * math.pi))
            r = int(acc.r + (amb.r - acc.r) * f)
            g = int(acc.g + (amb.g - acc.g) * f)
            b = int(acc.b + (amb.b - acc.b) * f)
            pg.draw.line(bar, (r, g, b, a), (x, 0), (x, height - 1))
        return bar

    def _build_takeover_surfaces(self, tk: dict[str, Any], w: int, h: int) -> None:
        """
        Render the takeover's headline, winner line and bar for one window
        size and keep them on the record, so the animation only ever scales
        ready-made surfaces. They are rebuilt when the window size changes

        :param tk: takeover record to fill in
        :param w: window width in pixels
        :param h: window height in pixels
        """
        main_size = max(int(h * 0.22), 36)
        tk["main"], _ = self._build_text_fx(tk["reason"], main_size, Colors.text,
                                            Colors.outcome_stroke, Colors.accent_glow)
        sub_font = get_font(max(int(h * 0.042), 16), bold=True, family=SANS)
        tk["sub"] = sub_font.render((tk["winner"] + " WINS").upper(), True,
                                    pg.Color(Colors.amber_hi))
        tk["bar"] = self._takeover_bar(int(w * 0.86), max(int(h * 0.013), 4))
        tk["wh"] = (w, h)

    @staticmethod
    def _blit_alpha(window: pg.Surface, surf: pg.Surface, topleft: tuple[float, float],
                    alpha: int) -> None:
        """
        Blit a surface at a given transparency, skipping the copy entirely
        when it is fully opaque and skipping the blit when it is invisible

        :param window: surface to draw on
        :param surf: surface to blit
        :param topleft: destination position in window pixels
        :param alpha: transparency from 0 to 255
        """
        if alpha <= 0:
            return
        if alpha >= 255:
            window.blit(surf, topleft)
            return
        img = surf.copy()
        img.fill((255, 255, 255, alpha), special_flags=pg.BLEND_RGBA_MULT)
        window.blit(img, topleft)

    def draw_takeover(self, window: pg.Surface, now: int) -> None:
        """
        Paint the full-window end-of-game card over the game: a beat of
        silence, a darkening scrim, the bars sliding in, the headline slamming
        down and the winner's line under it, then the whole thing withdrawing.
        The game screen shows this instead of the result menu until it is done

        :param window: surface to draw on, the app window
        :param now: pygame ticks in milliseconds
        """
        tk = self._takeover
        if tk is None:
            return
        t = now - tk["start"] - TAKEOVER_PAUSE_MS
        if t < 0:
            return
        w, h = window.get_size()
        out = max(0.0, min((t - (TAKEOVER_ANIM_MS - TAKEOVER_OUT_MS)) / TAKEOVER_OUT_MS, 1.0))
        fade = 1.0 - out
        bg_in = min(t / TAKEOVER_BG_MS, 1.0)
        bg_alpha = int((TAKEOVER_BG_ALPHA - (TAKEOVER_BG_ALPHA - TAKEOVER_BG_SETTLE) * out) * bg_in)
        overlay = _takeover_bg_sprite(w, h)
        overlay.set_alpha(max(bg_alpha, 0))
        window.blit(overlay, (0, 0))
        if tk["wh"] != (w, h):
            self._build_takeover_surfaces(tk, w, h)
        main, sub, bar = tk["main"], tk["sub"], tk["bar"]
        cx, cy = w // 2, int(h * 0.45)
        bw = bar.get_width()
        eased = 1 - (1 - min(t / TAKEOVER_BARS_MS, 1.0)) ** 3
        off = int(bw * 1.2 * (1 - eased)) + int(bw * 1.2 * out)
        center_x = cx - bw // 2
        gap = main.get_height() // 2 + int(h * 0.05)
        bar_alpha = int(255 * fade)
        self._blit_alpha(window, bar, (center_x - off, cy - gap - bar.get_height() // 2), bar_alpha)
        self._blit_alpha(window, bar, (center_x + off, cy + gap + sub.get_height()), bar_alpha)
        md = t - TAKEOVER_MAIN_DELAY_MS
        if md < 0:
            m_scale, m_alpha = 2.4, 0
        elif md < TAKEOVER_MAIN_MS:
            fm = md / TAKEOVER_MAIN_MS
            m_scale = 2.4 - 1.4 * (1 - (1 - fm) ** 3)
            m_alpha = int(255 * min(fm * 2, 1.0))
        else:
            m_scale, m_alpha = 1.0, 255
        m_scale += 0.12 * out
        m_alpha = int(m_alpha * fade)
        if m_scale == 1.0 and m_alpha == 255:
            window.blit(main, main.get_rect(center=(cx, cy)))
        else:
            img = pg.transform.rotozoom(main, 0.0, m_scale)
            if m_alpha < 255:
                img.fill((255, 255, 255, max(m_alpha, 0)), special_flags=pg.BLEND_RGBA_MULT)
            window.blit(img, img.get_rect(center=(cx, cy)))
        s_alpha = int(min(max(t - TAKEOVER_SUB_DELAY_MS, 0) / float(TAKEOVER_SUB_DELAY_MS),
                          1.0) * 255 * fade)
        sub_pos = (cx, cy + main.get_height() // 2 + sub.get_height())
        if s_alpha >= 255:
            window.blit(sub, sub.get_rect(center=sub_pos))
        elif s_alpha > 0:
            s = sub.copy()
            s.fill((255, 255, 255, s_alpha), special_flags=pg.BLEND_RGBA_MULT)
            window.blit(s, s.get_rect(center=sub_pos))
