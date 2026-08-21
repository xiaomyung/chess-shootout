import math
import os
import random
from collections.abc import Sequence
from typing import Any, cast

import pygame as pg

from chessshootout import paths
from chessshootout.frontend.audio.sound_manager import SoundManager
from chessshootout.frontend.visual import gunfx
from chessshootout.frontend.visual import backdrop
from chessshootout.frontend.visual.gunfx import DT_MAX, GUN_DRAW_SPINS_LAND, RAGDOLL_MS
from chessshootout.frontend.visual.cache import render_text, new_cache, memoized_surface
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.fonts import get_font
from chessshootout.frontend.visual.widgets import build_ko_badge, wrap_words, KO_WINK_MS


ROUTE_MARGIN = 22
MAX_PAWNS = 15
QUEEN_BASE_H = 104
PAWN_BASE_H = 64
IDLE_TIMEOUT_MS = 2000
IDLE_RADIUS = 24
FLASH_MS = 120
RECOIL_RECOVER = 12.0
AIM_TOLERANCE = 0.12
MISS_CHANCE = 0.20
MISS_AIM_MIN = 0.35
MISS_AIM_MAX = 0.6
PROJECTILE_MAX_MS = 1600
PAWN_WEAPON = "revolver"
QUEEN_WEAPON = "blunderbuss"
WEAPON_SWITCH_MIN = 3.0
WEAPON_SWITCH_MAX = 10.0

QUEEN_LINES = (
    "PICK A SIDE, COWARD", "fresh meat", "IS THAT ALL?", "i do this for fun",
    "NEXT.", "nine points of PAIN", "say checkmate again", "born to e4",
    "RUN ALONG, PAWN", "you call that a gambit?", "skill issue", "GET BACK IN LINE",
)
PAWN_LINES = (
    "get her, boys!", "1v1 me", "we got NUMBERS", "promotion soon",
    "rush b... ishop", "ur queen castled", "she/dead", "i felt that one",
    "tactical retreat!!", "mom said im next", "pawnocalypse now", "EN PASSANT??",
)
DEATH_LINES = ("ough", "noooo", "tell my wife...", "gg")
GUN_DRAW_SEC = 0.7
GUN_DRAW_SPINS_SWAP = 3
KILL_SPIN_CHANCE = 0.20
KILL_SPIN_SEC = 0.45
DROP_GRAVITY = 900
DROP_MS = 3000
KO_HEIGHT_REF = 26
HITMARK_MS = 220
SPARK_MS = (280, 560)
BUBBLE_HOLD_MS = 2200
DEATH_BUBBLE_HOLD_MS = 900
BUBBLE_FADE_IN_MS = 180
BUBBLE_FADE_OUT_MS = 240
SCRIM_N = 64
SCRIM_INNER_ALPHA = 74
SCRIM_OUTER_ALPHA = 180
GRID_STEP = 44
GRID_STEP_MIN = 28

_HITMARK_CACHE = new_cache()
_MENU_SPARK_CACHE = new_cache()
_BATTLE_PIECE_SRC_CACHE = new_cache()


def _hitmark_sprite(spread: int, length: float, thick: int) -> pg.Surface:
    """
    Hand back the four-armed crosshair tick that flashes on whoever was just
    shot, the same hit marker a shooter expects to see. It is drawn once per
    size and shared from then on, since a landed shot puts one on screen for
    several frames

    :param spread: gap in pixels between the centre and the inner end of each
        arm, which widens as the marker expands
    :param length: length of each arm in pixels
    :param thick: arm thickness in pixels
    :returns: the cached hit-marker sprite for these dimensions
    """
    def build() -> pg.Surface:
        """
        Draw the four diagonal arms at this size, run only on a cache miss

        :returns: the freshly drawn hit-marker sprite
        """
        diag = 0.7071
        size = int((spread + length) * 2 + thick * 2)
        layer = pg.Surface((size, size), pg.SRCALPHA)
        c = size / 2
        col = pg.Color(Colors.amber_hi)
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            inner = (c + dx * spread * diag, c + dy * spread * diag)
            outer = (c + dx * (spread + length) * diag, c + dy * (spread + length) * diag)
            pg.draw.line(layer, col, inner, outer, thick)
        return layer
    return cast(pg.Surface, memoized_surface(_HITMARK_CACHE, (spread, length, thick), build))


def _menu_spark_sprite(size: int, color: str) -> pg.Surface:
    """
    Hand back one square of the spark shower a hit throws off in the menu
    battle. Every spark of a burst shares one cached square per size and
    colour, so a firefight costs blits instead of fills

    :param size: spark edge length in pixels
    :param color: spark colour, red for damage and amber elsewhere
    :returns: the cached spark sprite
    """
    def build() -> pg.Surface:
        """
        Fill a small square in the spark colour, run only on a cache miss

        :returns: the freshly drawn spark sprite
        """
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(color))
        return surf
    return cast(pg.Surface, memoized_surface(_MENU_SPARK_CACHE, (size, color), build))


class MenuBattle:
    """
    The gunfight that plays behind the main menu: one white queen against an
    endless stream of black pawns, drawn into the arena backdrop under the
    menu itself. The shell owns a single instance and drives it only while the
    showing screen asks for a battle backdrop, and the menu keeps telling it
    which panels to stay out from under
    """

    def __init__(self, rng: random.Random | None = None,
                 sound_manager: SoundManager | None = None) -> None:
        """
        Build an idle battle with no field yet: nothing spawns and nothing
        draws until the shell hands over an arena rect. Piece and gun artwork
        come from shared caches, so building one costs no disk reads once the
        game has drawn a board

        :param rng: random source behind every spawn, spread, timer and taunt,
            injected by tests for a reproducible fight; None makes a fresh
            unseeded one
        :param sound_manager: plays the menu gunshots, or None to run silent
        """
        self.rng = rng or random.Random()
        self.sound_manager = sound_manager
        self.rect = pg.Rect(0, 0, 0, 0)
        self.avoid_rects: list[pg.Rect] = []
        self.obstacles: list[tuple[float, float, float, float]] = []
        self.top_inset = 0
        self.debug = os.environ.get("CHESS_BATTLE_DEBUG") == "1"
        self.scale = 1.0
        self.pawns: list[dict[str, Any]] = []
        self.queen: dict[str, Any] | None = None
        self.particles: list[dict[str, Any]] = []
        self.projectiles: list[dict[str, Any]] = []
        self.drops: list[dict[str, Any]] = []
        self.acc = {"qfire": 0.0, "talk": 1.5, "spawn": 0.0}
        self._last_ms: int | None = None
        self._initialized = False
        self._bg_cache: tuple[tuple[int, int], pg.Surface] | None = None
        self._scrim_cache: tuple[tuple[int, int], pg.Surface] | None = None
        self._queen_src = self._load_piece("queen", "white")
        self._pawn_src = self._load_piece("pawn", "black")
        self._battle = gunfx.load_battle_art()
        self._art: dict[str, dict[str, Any]] = {}
        self._shadow_surfs: dict[str, pg.Surface] = {}
        self._weapons: dict[str, dict[Any, Any]] = {}

    def _load_piece(self, piece_type: str, color: str) -> pg.Surface | None:
        """
        Load one piece image, trimmed to its ink, for the fighters to be scaled
        from. A missing or unreadable file gives None instead of raising, which
        the battle falls back on by drawing plain circles

        :param piece_type: piece name, queen or pawn here
        :param color: white or black, which picks the artwork file
        :returns: the trimmed piece image, or None when it could not be read
        """
        def build() -> pg.Surface | None:
            """
            Read the image off disk and trim it to its ink, run only on a
            cache miss

            :returns: the trimmed image, or None when the file is unusable
            """
            try:
                path = paths.resource_path("assets", "pieces_png", f"{piece_type}_{color}.png")
                img = pg.image.load(str(path)).convert_alpha()
                return img.subsurface(img.get_bounding_rect()).copy()
            except (pg.error, FileNotFoundError, OSError):
                return None
        return cast(pg.Surface | None,
                    memoized_surface(_BATTLE_PIECE_SRC_CACHE, (piece_type, color), build))

    def _rnd(self, lo: float, hi: float) -> float:
        """
        Draw a uniform value from the injected random source, the single origin
        of every timer, offset and scatter in the battle

        :param lo: inclusive lower bound
        :param hi: upper bound
        :returns: a value between the two bounds
        """
        return lo + self.rng.random() * (hi - lo)

    def _pick(self, seq: Sequence[Any]) -> Any:
        """
        Pick one entry at random through the injected source: a taunt line, the
        queen's next weapon, or which pawn speaks next

        :param seq: non-empty sequence to choose from
        :returns: one entry of that sequence
        """
        return seq[int(self.rng.random() * len(seq))]

    def set_rect(self, rect: pg.Rect) -> None:
        """
        Give the battle the part of the window it plays in, which the shell
        does at startup and on every resize. Artwork, shadows and weapons are
        rebuilt at the new scale. The very first sizing spawns the queen; later
        ones rescale and reposition the fighters already on the field rather
        than starting the fight over

        :param rect: the arena in window pixels; fighters are positioned
            relative to its top-left corner
        """
        rect = pg.Rect(rect)
        self.rect = rect
        self.scale = max(backdrop.SCALE_MIN,
                         min(backdrop.SCALE_MAX, rect.height / backdrop.SCALE_REF_HEIGHT))
        self._build_art()
        self._build_shadows()
        self._build_weapons()
        self._compute_obstacles()
        self._bg_cache = None
        self._scrim_cache = None
        if not self._initialized and rect.width > 0 and rect.height > 0:
            self._spawn_initial()
            self._initialized = True
        elif self.queen is not None:
            self._size_entity(self.queen)
            for p in self.pawns:
                self._size_entity(p)
            self._reconcile_entities()
            self._cull_out_of_bounds()
            self.queen["wp"] = self._rand_waypoint()

    def set_avoid_rects(self, rects: Sequence[pg.Rect]) -> None:
        """
        Tell the battle which menu panels it must not walk under -- the nav
        rail, the card column, whatever the showing sub-view puts up. The menu
        pushes the current list every frame, and anyone caught under a panel
        that has just appeared is pushed out from under it, except a pawn still
        walking in from off-screen

        :param rects: panel rects in window pixels; empty ones are ignored
        """
        coerced = [pg.Rect(r) for r in rects]
        self.avoid_rects = [r for r in coerced if r.width > 0 and r.height > 0]
        self._compute_obstacles()
        if self.queen is not None:
            for ent in (self.queen, *self.pawns):
                if ent.get("emerging"):
                    continue
                ent["x"], ent["y"] = self._push_out_all(
                    self._entity_obstacles(ent), ent["x"], ent["y"],
                    exclude_top=ent["kind"] == "queen")
            self._clamp_queen_to_window()

    def set_avoid_rect(self, rect: pg.Rect) -> None:
        """
        Stay clear of a single panel, the one-rect shorthand for callers and
        tests with only one card in the way

        :param rect: panel rect in window pixels
        """
        self.set_avoid_rects([rect])

    def _size_entity(self, ent: dict[str, Any]) -> None:
        """
        Fit one fighter to the current arena scale: how tall it draws, how far
        its gun reaches, where its hand sits and how high its head is. Run at
        spawn and again after every resize, so a resized window never leaves a
        fighter with stale proportions

        :param ent: queen or pawn record, updated in place
        """
        kind = ent["kind"]
        art = self._entity_art(kind)
        base = QUEEN_BASE_H if kind == "queen" else PAWN_BASE_H
        sprite_h = art["h"] if art else int(base * self.scale)
        ent["sprite_h"] = sprite_h
        ent["gun_len"] = sprite_h * gunfx.GUN_LEN_RATIO
        if kind == "queen":
            ent["gy"] = sprite_h * 0.46
            ent["head"] = sprite_h + 12 * self.scale
        else:
            ent["gy"] = sprite_h * 0.55
            ent["head"] = sprite_h + 10 * self.scale

    def _build_art(self) -> None:
        """
        Scale the queen and pawn images to the current arena size and keep both
        facings ready, so a fighter turning round is a blit rather than a flip.
        A piece whose image never loaded is simply left out, and the battle
        draws a circle in its place
        """
        self._art = {}
        for key, src, base in (("queen", self._queen_src, QUEEN_BASE_H),
                               ("pawn", self._pawn_src, PAWN_BASE_H)):
            if src is None:
                continue
            h = max(int(base * self.scale), 8)
            w = max(int(src.get_width() * h / src.get_height()), 8)
            normal = pg.transform.smoothscale(src, (w, h))
            self._art[key] = {
                "normal": normal,
                "flipped": pg.transform.flip(normal, True, False),
                "w": w, "h": h,
            }

    def _build_shadows(self) -> None:
        """
        Draw the soft ellipse that sits under each kind of fighter, once per
        arena size. It is what plants them on the floor instead of leaving them
        floating over the backdrop
        """
        self._shadow_surfs = {}
        h = max(int(8 * self.scale), 6)
        for kind, base in (("queen", QUEEN_BASE_H), ("pawn", PAWN_BASE_H)):
            art = self._art.get(kind)
            w = max(int((art["w"] if art else base * self.scale) * 0.8), 4)
            surf = pg.Surface((w, h), pg.SRCALPHA)
            pg.draw.ellipse(surf, (*pg.Color(Colors.battle_shadow)[:3], 130), surf.get_rect())
            self._shadow_surfs[kind] = surf

    def _build_weapons(self) -> None:
        """
        Build every gun the fight can show at the current scale: the whole
        arsenal for the queen, who swaps between them, and the revolver for the
        pawns. All of them are scaled to one reach, so a given gun is the same
        size in any hand
        """
        self._weapons = {}
        reach = QUEEN_BASE_H * gunfx.GUN_LEN_RATIO * self.scale
        for kind, guns in (("queen", sorted(self._battle["guns"])), ("pawn", (PAWN_WEAPON,))):
            built = {}
            for gun in guns:
                entry = gunfx.build_weapon(self._battle, gun, reach)
                if entry is not None:
                    built[gun] = entry
            self._weapons[kind] = built

    def _entity_art(self, kind: str) -> dict[str, Any] | None:
        """
        Look up the scaled artwork for one kind of fighter

        :param kind: queen or pawn
        :returns: that kind's art record -- both facings and their size -- or
            None when the image never loaded
        """
        return self._art.get(kind)

    def _compute_obstacles(self) -> None:
        """
        Turn the menu's panel rects into the arena-local boxes the movement code
        works in, the one place window coordinates become battle coordinates.
        It is redone every frame and on every layout change, so a panel sliding
        in is dodged from the frame it appears
        """
        self.obstacles = []
        for a in self.avoid_rects:
            if a.width <= 0 or a.height <= 0:
                continue
            lx = a.x - self.rect.x
            ly = a.y - self.rect.y
            self.obstacles.append((lx, ly, lx + a.width, ly + a.height))

    def _entity_obstacles(self, ent: dict[str, Any]) -> list[tuple[float, float, float, float]]:
        """
        Widen every panel box by one fighter's body, so testing the point it
        stands on keeps its whole model off the panel instead of letting half a
        sprite overlap. The top edge is left alone, because a fighter's feet may
        legitimately sit below a panel it is standing in front of

        :param ent: queen or pawn record, whose width and height set the margins
        :returns: the widened boxes as left, top, right and bottom in
            arena-local pixels
        """
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return [(o[0] - hw, o[1], o[2] + hw, o[3] + ent["sprite_h"])
                for o in self.obstacles]

    def _point_in(self, o: tuple[float, float, float, float] | None,
                  x: float, y: float) -> bool:
        """
        Test whether a point lies inside one obstacle box, the primitive every
        placement decision in the battle is built on

        :param o: obstacle box, or None which contains nothing
        :param x: horizontal position in arena-local pixels
        :param y: vertical position in arena-local pixels
        :returns: True when the point is strictly inside the box
        """
        return o is not None and o[0] < x < o[2] and o[1] < y < o[3]

    def _point_in_any(self, obstacles: Sequence[tuple[float, float, float, float]],
                      x: float, y: float) -> bool:
        """
        Test a point against a whole set of panels at once, since the menu can
        show a rail, a card and a right-hand column together

        :param obstacles: obstacle boxes to test against
        :param x: horizontal position in arena-local pixels
        :param y: vertical position in arena-local pixels
        :returns: True when the point is inside any of them
        """
        return any(self._point_in(o, x, y) for o in obstacles)

    def _push_out(self, o: tuple[float, float, float, float], x: float, y: float,
                  exclude_top: bool = False) -> tuple[float, float]:
        """
        Shove a point out of one panel the shortest way, which is how a fighter
        caught under a panel that has just appeared steps back into the open

        :param o: obstacle box to escape
        :param x: horizontal position in arena-local pixels
        :param y: vertical position in arena-local pixels
        :param exclude_top: True to forbid the exit over the top edge, which
            stops the queen being pushed up behind the menu
        :returns: the point moved onto the nearest allowed edge, or unchanged
            when it was already outside
        """
        if not self._point_in(o, x, y):
            return x, y
        dl, dr, db = x - o[0], o[2] - x, o[3] - y
        dt = float("inf") if exclude_top else y - o[1]
        m = min(dl, dr, dt, db)
        if m == dl:
            return o[0], y
        if m == dr:
            return o[2], y
        if m == dt:
            return x, o[1]
        return x, o[3]

    def _push_out_all(self, obstacles: Sequence[tuple[float, float, float, float]],
                      x: float, y: float, exclude_top: bool = False) -> tuple[float, float]:
        """
        Walk a point out of every panel it is inside, in repeated passes because
        escaping one panel can push it into its neighbour. It gives up after
        four passes, so a point wedged into an impossible corner still costs a
        bounded amount of work

        :param obstacles: obstacle boxes to escape
        :param x: horizontal position in arena-local pixels
        :param y: vertical position in arena-local pixels
        :param exclude_top: True to forbid exits over the top edge
        :returns: the point once it is clear of every box it can escape
        """
        for _ in range(4):
            moved = False
            for o in obstacles:
                nx, ny = self._push_out(o, x, y, exclude_top)
                if (nx, ny) != (x, y):
                    x, y, moved = nx, ny, True
            if not moved:
                break
        return x, y

    def _seg_hits(self, o: tuple[float, float, float, float] | None,
                  ax: float, ay: float, bx: float, by: float) -> bool:
        """
        Say whether walking straight from one point to another would cross a
        panel. It samples a dozen points along the way rather than solving the
        crossing exactly, which is accurate enough at the speeds fighters move

        :param o: obstacle box, or None which nothing can cross
        :param ax: start x in arena-local pixels
        :param ay: start y in arena-local pixels
        :param bx: end x in arena-local pixels
        :param by: end y in arena-local pixels
        :returns: True when the walk passes through the box
        """
        if o is None:
            return False
        for i in range(1, 12):
            t = i / 12.0
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if o[0] < x < o[2] and o[1] < y < o[3]:
                return True
        return False

    def _seg_hits_any(self, obstacles: Sequence[tuple[float, float, float, float]],
                      ax: float, ay: float, bx: float, by: float) -> bool:
        """
        Say whether walking straight from one point to another would cross any
        of the panels currently on screen

        :param obstacles: obstacle boxes to test against
        :param ax: start x in arena-local pixels
        :param ay: start y in arena-local pixels
        :param bx: end x in arena-local pixels
        :param by: end y in arena-local pixels
        :returns: True when the walk crosses at least one of them
        """
        return any(self._seg_hits(o, ax, ay, bx, by) for o in obstacles)

    def _route(self, obstacles: Sequence[tuple[float, float, float, float]],
               px: float, py: float, tx: float, ty: float) -> tuple[float, float]:
        """
        Pick where a fighter should head next so it walks around the menu
        instead of into it: straight at its target when the way is clear,
        otherwise to the cheapest corner of the first panel in the way. This is
        one step of steering rather than a path -- the next frame routes again

        :param obstacles: obstacle boxes to route around
        :param px: walker's x in arena-local pixels
        :param py: walker's y in arena-local pixels
        :param tx: target x in arena-local pixels
        :param ty: target y in arena-local pixels
        :returns: the point to walk toward this frame, in arena-local pixels
        """
        if not self._seg_hits_any(obstacles, px, py, tx, ty):
            return tx, ty
        o = next(o for o in obstacles if self._seg_hits(o, px, py, tx, ty))
        m = ROUTE_MARGIN
        corners = ((o[0] - m, o[1] - m), (o[2] + m, o[1] - m),
                   (o[2] + m, o[3] + m), (o[0] - m, o[3] + m))
        best, best_cost = corners[0], float("inf")
        for cx, cy in corners:
            cost = math.hypot(cx - px, cy - py) + math.hypot(tx - cx, ty - cy)
            if cost < best_cost:
                best_cost, best = cost, (cx, cy)
        return best

    def _rand_waypoint(self,
                       obstacles: Sequence[tuple[float, float, float, float]] | None = None
                       ) -> list[float]:
        """
        Pick somewhere fresh for the queen to stroll to: a random spot in the
        band of the arena she can reach, drawn again until it is clear of the
        panels. After thirty tries it settles for a clamped point, so an arena
        almost entirely covered by menu panels still returns something

        :param obstacles: boxes the spot must avoid, or None to use the plain
            panel boxes instead of her widened ones
        :returns: the waypoint as x and y in arena-local pixels
        """
        w, h = self.rect.width, self.rect.height
        if obstacles is None:
            obstacles = self.obstacles
        art = self._entity_art("queen")
        hw = (art["w"] if art else QUEEN_BASE_H * self.scale) / 2
        qh = self.queen["sprite_h"] if self.queen else 0.0
        xmin, xmax = hw, max(hw, w - hw)
        ymin, ymax = self.top_inset + qh, float(h)
        candidate = [(xmin + xmax) / 2, (ymin + ymax) / 2]
        for _ in range(30):
            candidate = [self._rnd(xmin, xmax), self._rnd(ymin, ymax)]
            if not self._point_in_any(obstacles, candidate[0], candidate[1]):
                return candidate
        return [max(xmin, min(xmax, candidate[0])), max(ymin, min(ymax, candidate[1]))]

    def _make_queen(self) -> dict[str, Any]:
        """
        Create the queen: where she stands, which way she faces, the weapon she
        opens with, and every timer the fight runs her by -- flinch, aim,
        recoil, gun-draw, weapon swap and her knockout count

        :returns: the queen record, already sized for the current arena
        """
        w, h = self.rect.width, self.rect.height
        qx, qy = w * 0.16, h * 0.52
        q: dict[str, Any] = {
            "kind": "queen", "x": qx, "y": qy, "face": 1,
            "flinch": 0.0, "aim": 0.0, "wp": None, "bubble": None,
            "anchor_x": qx, "anchor_y": qy, "anchor_ms": None, "weapon": QUEEN_WEAPON,
            "weapon_switch": self._rnd(WEAPON_SWITCH_MIN, WEAPON_SWITCH_MAX), "recoil": 0.0,
            "draw_anim": 0.0, "draw_total": GUN_DRAW_SEC, "draw_spins": 0, "draw_grow": True,
            "kills": 0, "ko_wink_until": 0}
        self._size_entity(q)
        return q

    def _spawn_initial(self) -> None:
        """
        Put the queen on the field the moment the arena has a size, with a first
        waypoint to walk toward. There is no entrance animation -- the menu is
        never seen without her
        """
        self.queen = self._make_queen()
        self.queen["wp"] = self._rand_waypoint()

    def _spawn_pawn(self, initial: bool) -> None:
        """
        Add one pawn to the fight, up to the cap. A walk-in pawn starts off
        screen on a random edge and carries a pass that lets it cross a menu
        panel on its way in; an initial pawn is placed straight into the field,
        already clear of every panel

        :param initial: True to place it in the field at once, False to walk it
            in from off-screen
        """
        if len(self.pawns) >= MAX_PAWNS:
            return
        w, h = self.rect.width, self.rect.height
        side = int(self.rng.random() * 4)
        x: float
        y: float
        if side == 0:
            x, y = -80, h * self.rng.random()
        elif side == 1:
            x, y = w + 80, h * self.rng.random()
        elif side == 2:
            x, y = w * self.rng.random(), h + 80
        else:
            x, y = w * self.rng.random(), -80
        if initial:
            x, y = w * self._rnd(0.08, 0.92), h * self._rnd(0.18, 0.9)
        p: dict[str, Any] = {
            "kind": "pawn", "x": x, "y": y, "face": 1, "aim": 0.0, "bubble": None,
            "alive": True, "dying": False, "death_ms": 0, "death_dir": 1,
            "standoff": self._rnd(150, 270), "fire": self._rnd(1.5, 4.0),
            "speed": self._rnd(42, 68), "weapon": PAWN_WEAPON, "recoil": 0.0,
        }
        self._size_entity(p)
        if initial:
            p["x"], p["y"] = self._push_out_all(self._entity_obstacles(p), p["x"], p["y"])
        p["emerging"] = not initial
        self.pawns.append(p)

    def _body_point(self, ent: dict[str, Any]) -> tuple[float, float]:
        """
        Locate the middle of a fighter's body, which is what everyone aims at
        rather than the feet its position is measured from

        :param ent: queen or pawn record
        :returns: the body point in arena-local pixels
        """
        return ent["x"], ent["y"] - ent["sprite_h"] * 0.55

    def _gun_pivot(self, ent: dict[str, Any]) -> tuple[float, float]:
        """
        Locate the hand a fighter holds its gun in, slightly ahead of it on the
        side it faces. Every weapon is drawn and fired from this point

        :param ent: queen or pawn record
        :returns: the grip position in arena-local pixels
        """
        return ent["x"] + ent["face"] * 6 * self.scale, ent["y"] - ent["gy"]

    def _recoil_offset(self, ent: dict[str, Any]) -> tuple[float, float]:
        """
        Work out how far a gun is still kicked back along its aim line, which is
        what gives a shot its weight. A settled gun contributes nothing at all

        :param ent: queen or pawn record carrying the live recoil
        :returns: horizontal and vertical offset in arena-local pixels
        """
        r = ent.get("recoil", 0.0)
        if not r:
            return 0.0, 0.0
        return -math.cos(ent["aim"]) * r, -math.sin(ent["aim"]) * r

    def _muzzle_point(self, ent: dict[str, Any]) -> tuple[float, float]:
        """
        Work out where a fighter's barrel tip is right now, recoil included.
        Muzzle flashes and bullets both start here, which is what keeps a shot
        leaving the gun that fired it; with no artwork the barrel is assumed to
        sit one gun length along the aim

        :param ent: queen or pawn record
        :returns: the barrel tip in arena-local pixels
        """
        px, py = self._gun_pivot(ent)
        rx, ry = self._recoil_offset(ent)
        px, py = px + rx, py + ry
        entry = self._weapons.get(ent["kind"], {}).get(ent.get("weapon"))
        if entry is None:
            length = ent["gun_len"]
            return px + math.cos(ent["aim"]) * length, py + math.sin(ent["aim"]) * length
        return gunfx.aimed_target(entry["gun"], entry["grip"], entry["barrel"],
                                  (px, py), ent["aim"])

    def _aim_gun(self, ent: dict[str, Any], target: dict[str, Any] | None, dt: float) -> None:
        """
        Swing a fighter's barrel toward its target, easing round the short way
        so the aim reads as a hand tracking rather than snapping on. Without a
        target nothing moves, which is how the queen simply holds her aim while
        no pawn is out in the open

        :param ent: queen or pawn record whose aim is updated in place
        :param target: fighter being tracked, or None to leave the aim alone
        :param dt: seconds since the previous frame, capped by DT_MAX
        """
        if target is None:
            return
        px, py = self._gun_pivot(ent)
        tx, ty = self._body_point(target)
        want = math.atan2(ty - py, tx - px)
        delta = (want - ent["aim"] + math.pi) % (2 * math.pi) - math.pi
        ent["aim"] += delta * min(1.0, dt * 9)

    def _aligned(self, ent: dict[str, Any], target: dict[str, Any]) -> bool:
        """
        Say whether a fighter is pointed closely enough at its target to shoot,
        the gate that stops anyone firing while still swinging round

        :param ent: queen or pawn record doing the aiming
        :param target: fighter being aimed at
        :returns: True when the barrel is within the firing tolerance
        """
        px, py = self._gun_pivot(ent)
        tx, ty = self._body_point(target)
        want = math.atan2(ty - py, tx - px)
        delta: float = (want - ent["aim"] + math.pi) % (2 * math.pi) - math.pi
        return abs(delta) < AIM_TOLERANCE

    def update(self, now_ms: int) -> None:
        """
        Advance the whole fight by one frame -- movement, shooting, banter,
        bullets, dropped guns and the retirement of anything finished. The shell
        calls it every frame the showing screen asks for a battle backdrop, and
        it does nothing until the arena has been given a size

        :param now_ms: pygame tick count in milliseconds since pygame init
        """
        if self._last_ms is None:
            self._last_ms = now_ms
        dt = max(0.0, min(DT_MAX, (now_ms - self._last_ms) / 1000.0))
        self._last_ms = now_ms
        if self.queen is None:
            return
        self._compute_obstacles()
        self._step(dt, now_ms)
        self._update_projectiles(dt, now_ms)
        self._update_drops(dt)
        self._prune(now_ms)

    @staticmethod
    def _start_gun_flourish(ent: dict[str, Any], seconds: float, spins: int,
                            grow: bool) -> None:
        """
        Set a fighter twirling its gun: the flourish that produces a fresh
        weapon out of nowhere after a swap, and the shorter celebratory spin
        after a kill

        :param ent: queen or pawn record, updated in place
        :param seconds: how long the twirl lasts
        :param spins: whole turns before it lands back on the aim
        :param grow: True to grow the gun in as it spins, False to twirl one
            already in hand
        """
        ent["draw_anim"] = seconds
        ent["draw_total"] = seconds
        ent["draw_spins"] = spins
        ent["draw_grow"] = grow

    def _drop_gun(self, weapon: str, ent: dict[str, Any], now_ms: int) -> None:
        """
        Throw a discarded gun onto the floor, which is what makes a weapon swap
        readable: it flies out in front of the fighter, tumbles, lands and
        fades. A gun with no artwork is let go silently

        :param weapon: name of the gun being dropped
        :param ent: fighter dropping it, which sets where and which way it flies
        :param now_ms: pygame ticks in milliseconds the drop starts at
        """
        entry = self._weapons.get(ent["kind"], {}).get(weapon)
        if entry is None:
            return
        px, py = self._gun_pivot(ent)
        face = ent.get("face", 1)
        self.drops.append({
            "img": entry["gun"], "x": px, "y": py,
            "vx": face * self._rnd(25, 55) * self.scale, "vy": self._rnd(-25, 5) * self.scale,
            "angle": 0.0, "spin": self._rnd(-260, 260),
            "ground_y": ent["y"], "resting": False, "start": now_ms, "dur": DROP_MS})

    def _update_drops(self, dt: float) -> None:
        """
        Let every dropped gun fall: gravity, tumble, and a landing on the floor
        the fighter was standing on, after which it just lies there fading

        :param dt: seconds since the previous frame, capped by DT_MAX
        """
        for d in self.drops:
            if d["resting"]:
                continue
            d["vy"] += DROP_GRAVITY * self.scale * dt
            d["x"] += d["vx"] * dt
            d["y"] += d["vy"] * dt
            d["angle"] += d["spin"] * dt
            if d["y"] >= d["ground_y"]:
                d["y"] = d["ground_y"]
                d["resting"] = True
                d["spin"] = 0.0

    def _step(self, dt: float, now_ms: int) -> None:
        """
        Run one frame of the fight itself, in the order it reads: the queen
        moves and shoots, the pawns close in and shoot back, reinforcements walk
        on, and somebody says something

        :param dt: seconds since the previous frame, capped by DT_MAX
        :param now_ms: pygame ticks in milliseconds
        """
        alive = [p for p in self.pawns if p["alive"]]
        self._step_queen(dt, now_ms, alive)
        self._step_pawns(dt, now_ms, alive)
        self._step_spawns(dt)
        self._step_dialogue(dt, now_ms, alive)

    def _step_queen(self, dt: float, now_ms: int, alive: list[dict[str, Any]]) -> None:
        """
        Move and fight the queen for one frame: stroll toward her waypoint
        around the panels, unstick herself when she has been idle too long, swap
        weapons when her timer runs out, then track and shoot the nearest pawn
        she can actually see. She never fires mid-flourish, so a freshly drawn
        gun always lands before it goes off

        :param dt: seconds since the previous frame, capped by DT_MAX
        :param now_ms: pygame ticks in milliseconds
        :param alive: the pawns still standing this frame
        """
        q = cast(dict[str, Any], self.queen)
        qo = self._entity_obstacles(q)
        if (q["wp"] is None or self._point_in_any(qo, q["wp"][0], q["wp"][1])
                or math.hypot(q["wp"][0] - q["x"], q["wp"][1] - q["y"]) < 26):
            q["wp"] = self._rand_waypoint(qo)
        qt = self._route(qo, q["x"], q["y"], q["wp"][0], q["wp"][1])
        q["x"] += (qt[0] - q["x"]) * min(1.0, dt * 1.6)
        q["y"] += (qt[1] - q["y"]) * min(1.0, dt * 1.6)
        q["x"], q["y"] = self._push_out_all(qo, q["x"], q["y"], exclude_top=True)
        self._clamp_queen_to_window()
        q["flinch"] = max(0.0, q["flinch"] - dt * 4)
        q["recoil"] -= q["recoil"] * min(1.0, dt * RECOIL_RECOVER)
        q["draw_anim"] = max(0.0, q["draw_anim"] - dt)
        self._unstick_queen(now_ms, qo)
        q["weapon_switch"] -= dt
        if q["weapon_switch"] <= 0:
            pool = sorted(self._weapons.get("queen", {}))
            if pool:
                new_weapon = self._pick(pool)
                if new_weapon != q["weapon"]:
                    self._drop_gun(q["weapon"], q, now_ms)
                    q["weapon"] = new_weapon
                    self._start_gun_flourish(q, GUN_DRAW_SEC, GUN_DRAW_SPINS_SWAP, True)
            q["weapon_switch"] = self._rnd(WEAPON_SWITCH_MIN, WEAPON_SWITCH_MAX)

        targets = [p for p in alive if self._visible(p)]
        nearest, nd = None, 1e9
        for p in targets:
            d = math.hypot(p["x"] - q["x"], p["y"] - q["y"])
            if d < nd:
                nd, nearest = d, p
        if nearest is not None:
            q["face"] = 1 if nearest["x"] >= q["x"] else -1
        self._aim_gun(q, nearest, dt)
        self.acc["qfire"] -= dt
        if (self.acc["qfire"] <= 0 and nearest is not None and self._aligned(q, nearest)
                and q["draw_anim"] <= 0):
            self.acc["qfire"] = self._rnd(0.23, 0.53)
            self._fire(q, nearest, True, now_ms)

    def _step_pawns(self, dt: float, now_ms: int, alive: list[dict[str, Any]]) -> None:
        """
        Move and fight the pawns for one frame: each walks at the queen around
        the panels, edges back once it is inside its standoff distance, and
        shoots whenever it is aimed and out in the open. A pawn still walking in
        ignores the panels until it is fully clear of them, which is what lets
        it cross the rail it arrived behind

        :param dt: seconds since the previous frame, capped by DT_MAX
        :param now_ms: pygame ticks in milliseconds
        :param alive: the pawns still standing this frame
        """
        q = cast(dict[str, Any], self.queen)
        for p in alive:
            po = self._entity_obstacles(p)
            if p.get("emerging") and self._visible_with(p, po):
                p["emerging"] = False
            emerging = p.get("emerging", False)
            rx, ry = self._route(() if emerging else po, p["x"], p["y"], q["x"], q["y"])
            dx, dy = rx - p["x"], ry - p["y"]
            rd = math.hypot(dx, dy) or 1.0
            qx, qy = q["x"] - p["x"], q["y"] - p["y"]
            qd = math.hypot(qx, qy) or 1.0
            p["face"] = 1 if qx >= 0 else -1
            if qd > p["standoff"]:
                p["x"] += (dx / rd) * p["speed"] * dt
                p["y"] += (dy / rd) * p["speed"] * dt
            else:
                p["x"] -= (qx / qd) * p["speed"] * 0.3 * dt
            if not emerging:
                p["x"], p["y"] = self._push_out_all(po, p["x"], p["y"])
            p["recoil"] -= p["recoil"] * min(1.0, dt * RECOIL_RECOVER)
            self._aim_gun(p, q, dt)
            if self._visible_with(p, po):
                p["fire"] -= dt
                if p["fire"] <= 0 and self._aligned(p, q):
                    p["fire"] = self._rnd(2.2, 4.6)
                    self._fire(p, q, False, now_ms)
        self._separate_pawns()

    def _step_spawns(self, dt: float) -> None:
        """
        Trickle reinforcements onto the field so the queen is never left with
        nothing to shoot at, up to the pawn cap

        :param dt: seconds since the previous frame, capped by DT_MAX
        """
        self.acc["spawn"] -= dt
        while self.acc["spawn"] <= 0 and len(self.pawns) < MAX_PAWNS:
            self.acc["spawn"] += self._rnd(0.18, 0.42)
            self._spawn_pawn(False)

    def _step_dialogue(self, dt: float, now_ms: int, alive: list[dict[str, Any]]) -> None:
        """
        Let somebody talk every few seconds -- the queen taunting, or one of the
        pawns answering back. With every pawn down she gets the line to herself

        :param dt: seconds since the previous frame, capped by DT_MAX
        :param now_ms: pygame ticks in milliseconds
        :param alive: the pawns still standing this frame
        """
        self.acc["talk"] -= dt
        if self.acc["talk"] <= 0:
            self.acc["talk"] = self._rnd(2.4, 4.6)
            if self.rng.random() < 0.5 or not alive:
                self._say(cast(dict[str, Any], self.queen),
                          self._pick(QUEEN_LINES), "queen", now_ms)
            else:
                self._say(self._pick(alive), self._pick(PAWN_LINES), "pawn", now_ms)

    def _clamp_entity_to_field(self, ent: dict[str, Any]) -> None:
        """
        Pull a fighter back inside the arena: fully on screen left and right,
        below the strip reserved for the title bar, and never past the floor

        :param ent: queen or pawn record, moved in place
        """
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        h = ent["sprite_h"]
        ent["x"] = max(hw, min(self.rect.width - hw, ent["x"]))
        ent["y"] = max(self.top_inset + h, min(float(self.rect.height), ent["y"]))

    def _clamp_queen_to_window(self) -> None:
        """
        Keep the queen inside the arena. Only she is clamped: pawns walk in from
        off screen, so clamping them would strand them against the edge
        """
        if self.queen is not None:
            self._clamp_entity_to_field(self.queen)

    def _reconcile_entities(self) -> None:
        """
        Put every settled fighter somewhere legal again after the arena or the
        panels changed: out from under every panel and back inside the field.
        Pawns still walking in are left alone, so a resize never pushes them
        back out of the edge they came in by
        """
        for ent in (self.queen, *self.pawns):
            if ent is None or ent.get("emerging"):
                continue
            ent["x"], ent["y"] = self._push_out_all(
                self._entity_obstacles(ent), ent["x"], ent["y"],
                exclude_top=ent["kind"] == "queen")
            self._clamp_entity_to_field(ent)

    def _cull_out_of_bounds(self) -> None:
        """
        Drop the bullets, particles and dropped guns that a shrinking arena has
        left outside the field, which is what stops leaving fullscreen from
        parking debris off the edge of the menu
        """
        self.projectiles = [pr for pr in self.projectiles
                            if not self._off_screen(pr["x"], pr["y"])]
        self.particles = [p for p in self.particles
                          if not self._off_screen(p["x"], p["y"])]
        self.drops = [d for d in self.drops if not self._off_screen(d["x"], d["y"])]

    def _fully_in_window(self, ent: dict[str, Any]) -> bool:
        """
        Say whether a fighter's whole model is inside the arena. It is what
        keeps anyone half off screen out of the shooting -- nobody fires at, or
        from, a body that is only partly drawn

        :param ent: queen or pawn record
        :returns: True when its full model fits inside the field
        """
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return cast(bool, ent["x"] - hw >= 0 and ent["x"] + hw <= self.rect.width
                    and ent["y"] - ent["sprite_h"] >= self.top_inset
                    and ent["y"] <= self.rect.height)

    def _visible_with(self, ent: dict[str, Any],
                      obstacles: Sequence[tuple[float, float, float, float]]) -> bool:
        """
        Say whether a fighter can be seen, and so fought: fully inside the arena
        and not standing under a menu panel. It reads whichever panel set it is
        handed, so a rail sliding in hides whoever is beneath it from that same
        frame

        :param ent: queen or pawn record
        :param obstacles: obstacle boxes that count as cover
        :returns: True when the fighter is out in the open
        """
        return (self._fully_in_window(ent)
                and not self._point_in_any(obstacles, ent["x"], ent["y"]))

    def _visible(self, ent: dict[str, Any]) -> bool:
        """
        Say whether a fighter is out in the open, measured against the panels as
        they stand right now

        :param ent: queen or pawn record
        :returns: True when the fighter can be seen and shot at
        """
        return self._visible_with(ent, self._entity_obstacles(ent))

    def _separate_pawns(self) -> None:
        """
        Stop the pawns standing inside one another: an overlapping pair is
        pushed apart along whichever axis they overlap least, and then everyone
        is pushed clear of the panels again. Dying pawns are left out, so a
        ragdoll is never shoved around mid-fall
        """
        art = self._entity_art("pawn")
        w = art["w"] if art else int(PAWN_BASE_H * self.scale)
        movers = [p for p in self.pawns if p["alive"] and not p["dying"]]
        for i, a in enumerate(movers):
            for b in movers[i + 1:]:
                dx = b["x"] - a["x"]
                dy = (b["y"] - b["sprite_h"] / 2) - (a["y"] - a["sprite_h"] / 2)
                px = w - abs(dx)
                py = (a["sprite_h"] + b["sprite_h"]) / 2 - abs(dy)
                if px <= 0 or py <= 0:
                    continue
                if px < py:
                    shift = px / 2
                    s = 1.0 if dx >= 0 else -1.0
                    a["x"] -= s * shift
                    b["x"] += s * shift
                else:
                    shift = py / 2
                    s = 1.0 if dy >= 0 else -1.0
                    a["y"] -= s * shift
                    b["y"] += s * shift
        for p in movers:
            if p.get("emerging"):
                continue
            p["x"], p["y"] = self._push_out_all(self._entity_obstacles(p), p["x"], p["y"])

    def _unstick_queen(self, now_ms: int,
                       qo: Sequence[tuple[float, float, float, float]]) -> None:
        """
        Give the queen a new waypoint once she has stood still for too long,
        which is what rescues her from a corner the menu panels have boxed her
        into. Any real movement resets the timer, so a queen who is merely
        walking is never interrupted

        :param now_ms: pygame ticks in milliseconds
        :param qo: her widened obstacle boxes, which the fresh waypoint avoids
        """
        q = cast(dict[str, Any], self.queen)
        moved = math.hypot(q["x"] - q["anchor_x"], q["y"] - q["anchor_y"])
        if q["anchor_ms"] is None or moved > IDLE_RADIUS:
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms
        elif now_ms - q["anchor_ms"] >= IDLE_TIMEOUT_MS:
            q["wp"] = self._rand_waypoint(qo)
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms

    def _fire(self, shooter: dict[str, Any], target: dict[str, Any], is_queen: bool,
              now_ms: int) -> None:
        """
        Take one shot: kick the shooter back, play the gunshot, flash the muzzle
        and send the pellets on their way. Whether the shot is going to hit is
        decided here rather than by the flight, which is how a fifth of every
        fighter's shots are aimed wide on purpose

        :param shooter: fighter pulling the trigger
        :param target: fighter being shot at
        :param is_queen: True when the queen is firing, which decides who the
            pellets are able to hurt
        :param now_ms: pygame ticks in milliseconds of the shot
        """
        shooter["recoil"] = gunfx.gun_spec(shooter.get("weapon")).recoil * self.scale
        if self.sound_manager is not None:
            self.sound_manager.play_menu_gun(cast(str, shooter.get("weapon")))
        ax, ay = self._muzzle_point(shooter)
        self._add_flash(shooter, ax, ay, now_ms)
        hit = self.rng.random() >= MISS_CHANCE
        self._spawn_projectiles(shooter, target, is_queen, ax, ay, hit, now_ms)

    def _spawn_projectiles(self, shooter: dict[str, Any], target: dict[str, Any],
                           is_queen: bool, mx: float, my: float, hit: bool,
                           now_ms: int) -> None:
        """
        Launch one volley from the barrel tip, scattered the way its gun
        scatters: a revolver sends a single pellet, a blunderbuss a spray. A
        shot marked as a miss is angled well clear of the target, which is why
        it can never kill by accident

        :param shooter: fighter firing, whose gun sets the spread and speed
        :param target: fighter being aimed at
        :param is_queen: True when the queen fired, which decides who the
            pellets are able to hurt
        :param mx: barrel tip x in arena-local pixels
        :param my: barrel tip y in arena-local pixels
        :param hit: False to aim the volley deliberately wide
        :param now_ms: pygame ticks in milliseconds of the shot
        """
        spec = gunfx.gun_spec(shooter.get("weapon"))
        bx, by = self._body_point(target)
        base = math.atan2(by - my, bx - mx)
        if not hit:
            miss = self._rnd(MISS_AIM_MIN, MISS_AIM_MAX)
            base += miss if self.rng.random() < 0.5 else -miss
        speed = spec.speed * self.scale
        for ang, factor in gunfx.pellet_spread(spec, base, self._rnd):
            sp = speed * factor
            self.projectiles.append({
                "x": mx, "y": my, "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp,
                "size": spec.size * self.scale,
                "len": spec.length * self.scale, "color": spec.color,
                "is_queen": is_queen, "born": now_ms, "max_ms": PROJECTILE_MAX_MS})

    def _kill_pawn(self, p: dict[str, Any], now_ms: int) -> None:
        """
        Drop a pawn: it stops fighting, begins its ragdoll, bumps the queen's
        knockout badge into its amber wink and sometimes gets a last word.
        Calling it on a pawn already down does nothing, so one volley can never
        score the same kill twice

        :param p: pawn record being killed
        :param now_ms: pygame ticks in milliseconds of the hit
        """
        if not p["alive"]:
            return
        if self.queen is not None:
            self.queen["kills"] += 1
            self.queen["ko_wink_until"] = now_ms + KO_WINK_MS
        p["alive"] = False
        p["dying"] = True
        p["death_ms"] = now_ms
        p["death_dir"] = -1 if self.rng.random() < 0.5 else 1
        p["death_x"], p["death_y"] = p["x"], p["y"]
        bx, by = self._body_point(p)
        self._add_hit(bx, by, now_ms)
        if self.rng.random() < 0.4:
            self._say(p, self._pick(DEATH_LINES), "pawn", now_ms, hold=DEATH_BUBBLE_HOLD_MS)

    def _add_hit(self, x: float, y: float, now_ms: int) -> None:
        """
        Mark a landed shot with the crosshair tick and a spray of red particles,
        the same package for a downed pawn and for a queen who has been hit

        :param x: impact x in arena-local pixels
        :param y: impact y in arena-local pixels
        :param now_ms: pygame ticks in milliseconds of the hit
        """
        self.particles.append({"kind": "hitmark", "x": x, "y": y,
                               "start": now_ms, "dur": HITMARK_MS})
        self._add_sparks(x, y, 11, now_ms, Colors.blood)

    def _say(self, ent: dict[str, Any], text: str, who: str, now_ms: int,
             hold: int = BUBBLE_HOLD_MS) -> None:
        """
        Put a speech bubble over a fighter, replacing whatever it was saying.
        This is the whole of the menu's banter: the taunts, the comebacks and a
        dying pawn's last word

        :param ent: fighter doing the talking
        :param text: line to show, wrapped to fit when it is drawn
        :param who: queen or pawn, which picks the bubble's colours
        :param now_ms: pygame ticks in milliseconds
        :param hold: how long the bubble stays up, in milliseconds, its fades
            included
        """
        ent["bubble"] = {"text": text, "who": who, "start": now_ms, "hold": hold}

    def _add_flash(self, ent: dict[str, Any], x: float, y: float, now_ms: int) -> None:
        """
        Flash the muzzle of the gun that just fired, taking one of that weapon's
        flash variants at random so repeated shots never look stamped out. A gun
        with no flash artwork simply shows none

        :param ent: fighter that fired, naming the weapon and its aim
        :param x: barrel tip x in arena-local pixels
        :param y: barrel tip y in arena-local pixels
        :param now_ms: pygame ticks in milliseconds of the shot
        """
        entry = self._weapons.get(ent["kind"], {}).get(ent.get("weapon"))
        if entry is None or not entry["flashes"]:
            return
        idx = int(self.rng.random() * len(entry["flashes"]))
        self.particles.append({"kind": "flash", "ent_kind": ent["kind"],
                               "weapon": ent["weapon"], "idx": idx,
                               "x": x, "y": y, "aim": ent["aim"],
                               "start": now_ms, "dur": FLASH_MS})

    def _update_projectiles(self, dt: float, now_ms: int) -> None:
        """
        Fly every pellet and settle what it meets: one that reaches a fighter it
        is allowed to hurt lands on it and is spent, and anything that has flown
        too long or left the arena is dropped. Each pellet resolves on its own,
        so a single spread can drop several pawns at once

        :param dt: seconds since the previous frame, capped by DT_MAX
        :param now_ms: pygame ticks in milliseconds
        """
        survivors = []
        for pr in self.projectiles:
            pr["x"] += pr["vx"] * dt
            pr["y"] += pr["vy"] * dt
            target = self._projectile_hit(pr)
            if target is not None:
                self._land_hit(pr["is_queen"], target, now_ms)
                continue
            if now_ms - pr["born"] <= pr["max_ms"] and not self._off_screen(pr["x"], pr["y"]):
                survivors.append(pr)
        self.projectiles = survivors

    def _projectile_hit(self, pr: dict[str, Any]) -> dict[str, Any] | None:
        """
        Find what a pellet has hit, if anything. The queen's pellets can only
        strike a pawn that is alive and out in the open -- one sheltering under
        a menu panel is safe -- and a pawn's pellets can only strike the queen,
        so the pawns never shoot each other

        :param pr: pellet record carrying its position
        :returns: the fighter it landed on, or None when it hit nothing
        """
        if pr["is_queen"]:
            for p in self.pawns:
                if p["alive"] and self._visible(p) and self._hits_hitbox(pr, p):
                    return p
            return None
        queen = cast(dict[str, Any], self.queen)
        return queen if self._hits_hitbox(pr, queen) else None

    def _hits_hitbox(self, pr: dict[str, Any], ent: dict[str, Any]) -> bool:
        """
        Test a pellet against a fighter's body box, which is the whole of this
        battle's collision: a rectangle as wide as the artwork and as tall as
        the sprite standing on its feet

        :param pr: pellet record carrying its position
        :param ent: fighter being tested
        :returns: True when the pellet is inside that box
        """
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return cast(bool, ent["x"] - hw <= pr["x"] <= ent["x"] + hw
                    and ent["y"] - ent["sprite_h"] <= pr["y"] <= ent["y"])

    def _land_hit(self, is_queen: bool, target: dict[str, Any], now_ms: int) -> None:
        """
        Apply a hit to whoever caught it: a pawn goes down, and now and then the
        queen twirls her gun over it. The queen herself is never killed -- she
        only flinches, which is what keeps the menu fight running forever

        :param is_queen: True when the queen fired the pellet
        :param target: fighter that was hit
        :param now_ms: pygame ticks in milliseconds of the hit
        """
        queen = cast(dict[str, Any], self.queen)
        if is_queen:
            self._kill_pawn(target, now_ms)
            if queen["draw_anim"] <= 0 and self.rng.random() < KILL_SPIN_CHANCE:
                self._start_gun_flourish(queen, KILL_SPIN_SEC, 1, False)
        else:
            queen["flinch"] = 1.0
            bx, by = self._body_point(target)
            self._add_hit(bx, by, now_ms)

    def _off_screen(self, x: float, y: float) -> bool:
        """
        Say whether a point has left the arena with a margin to spare, the test
        that retires bullets and debris instead of tracking them forever

        :param x: horizontal position in arena-local pixels
        :param y: vertical position in arena-local pixels
        :returns: True once the point is well outside the field
        """
        m = 80
        return x < -m or x > self.rect.width + m or y < -m or y > self.rect.height + m

    def _add_sparks(self, x: float, y: float, n: int, now_ms: int,
                    color: str = Colors.amber_hi) -> None:
        """
        Throw a burst of sparks out of a point, the shower that sells a hit.
        They fly outwards with a slight upward bias and fade over lifetimes of
        their own, so no two bursts look alike

        :param x: burst centre x in arena-local pixels
        :param y: burst centre y in arena-local pixels
        :param n: how many sparks to throw
        :param now_ms: pygame ticks in milliseconds
        :param color: spark colour; damage throws red, everything else amber
        """
        for _ in range(n):
            ang = self._rnd(0, 2 * math.pi)
            dist = self._rnd(20, 70)
            self.particles.append({
                "kind": "spark", "x": x, "y": y, "color": color,
                "vx": math.cos(ang) * dist, "vy": math.sin(ang) * dist - 20,
                "start": now_ms, "dur": self._rnd(*SPARK_MS)})

    def _prune(self, now_ms: int) -> None:
        """
        Retire everything that has outlived its window -- spent particles, faded
        guns on the floor, and pawns whose ragdoll has finished. It is what
        keeps a menu left running for an hour from growing without end

        :param now_ms: pygame ticks in milliseconds
        """
        self.particles = [p for p in self.particles if now_ms - p["start"] < p["dur"]]
        self.drops = [d for d in self.drops if now_ms - d["start"] < d["dur"]]
        self.pawns = [p for p in self.pawns
                      if not (p["dying"] and now_ms - p["death_ms"] >= RAGDOLL_MS)]

    def draw(self, window: pg.Surface) -> None:
        """
        Paint the whole fight behind the menu, back to front: the arena
        backdrop, dropped guns, the pawns, the queen, particles, bullets, her
        knockout badge, and the speech bubbles last so nothing covers them.
        Nothing is drawn at all until the arena has been given a size

        :param window: surface to draw on, normally the app window
        """
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        window.blit(self._background((self.rect.width, self.rect.height)), self.rect.topleft)
        if self.queen is None:
            return
        now = self._last_ms or 0
        for d in self.drops:
            self._draw_drop(window, d, now)
        for p in self.pawns:
            self._draw_entity(window, p, now)
        self._draw_entity(window, self.queen, now)
        for p in self.particles:
            self._draw_particle(window, p, now)
        for pr in self.projectiles:
            self._draw_projectile(window, pr)
        self._draw_ko_counter(window)
        for p in self.pawns:
            self._draw_bubble(window, p, now)
        self._draw_bubble(window, self.queen, now)

    def _scaled_bold_font(self, size: int, attr: str) -> pg.font.Font:
        """
        Hand back a bold font at a pixel size, reloading it only when that size
        actually changes. Fonts must never be loaded per frame, and the two
        pieces of battle text each keep their own slot so they cannot evict one
        another

        :param size: type size in pixels
        :param attr: attribute this font is remembered on, one slot per piece of
            text
        :returns: the bold font at that size
        """
        cached = getattr(self, attr, None)
        if cached is None or cached[0] != size:
            cached = (size, get_font(size, bold=True))
            setattr(self, attr, cached)
        return cached[1]

    def _draw_ko_counter(self, window: pg.Surface) -> None:
        """
        Draw the queen's kill count on a pill above her head, winking amber for
        a moment after each fresh knockout. With no room overhead -- the title
        bar or a menu card in the way -- it moves to whichever side of her has
        more space, and it is always kept inside the arena

        :param window: surface to draw on, normally the app window
        """
        q = self.queen
        if q is None:
            return
        now = self._last_ms or 0
        scale = self.scale
        height = max(int(KO_HEIGHT_REF * scale), 16)
        font = self._scaled_bold_font(max(int(height * 0.3), 9), "_ko_font")
        winking = now < q["ko_wink_until"]
        badge = build_ko_badge(q["kills"], font, height, winking)
        pad_x = max(int(7 * scale), 5)
        pad_y = max(int(3 * scale), 2)
        bw = badge.get_width() + pad_x * 2
        bh = badge.get_height() + pad_y * 2
        ox, oy = self.rect.topleft
        cx = ox + q["x"]
        gap = max(int(6 * scale), 4)
        sprite_h = q["sprite_h"]
        body_y = oy + q["y"] - sprite_h * 0.72
        bx = max(self.rect.x + 2, min(cx - bw / 2, self.rect.right - bw - 2))
        by = oy + q["y"] - sprite_h - gap - bh
        if not self._fits_above(pg.Rect(int(bx), int(by), bw, bh)):
            art = self._entity_art("queen")
            half_w = (art["w"] if art else QUEEN_BASE_H * self.scale) / 2
            bx = cx + half_w + gap if self._prefer_right(cx, body_y) else cx - half_w - gap - bw
            by = body_y - bh / 2
        bx = max(self.rect.x + 2, min(bx, self.rect.right - bw - 2))
        by = max(self.rect.y + self.top_inset + 2, min(by, self.rect.bottom - bh - 2))
        radius = max(int(bh * 0.42), 4)
        pill = pg.Surface((bw, bh), pg.SRCALPHA)
        pg.draw.rect(pill, pg.Color(Colors.surface), pill.get_rect(), border_radius=radius)
        pg.draw.rect(pill, pg.Color(Colors.border_strong), pill.get_rect(), 1,
                     border_radius=radius)
        pill.blit(badge, (pad_x, pad_y))
        window.blit(pill, (int(bx), int(by)))

    def draw_scrim(self, window: pg.Surface) -> None:
        """
        Lay the vignette over the finished fight, darkening the edges so the
        menu on top of it stays readable. The shell draws it straight after
        draw() and before the screen itself, which is what puts the battle
        behind the menu; with CHESS_BATTLE_DEBUG set the hitboxes go over it

        :param window: surface to draw on, normally the app window
        """
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        window.blit(self._scrim((self.rect.width, self.rect.height)), self.rect.topleft)
        if self.debug:
            self._draw_debug(window)

    def _draw_debug(self, window: pg.Surface) -> None:
        """
        Draw the developer overlay behind CHESS_BATTLE_DEBUG: the playable area,
        every panel the fighters are dodging, and each fighter's body box,
        colour-coded for the queen, a settled pawn and one still walking in

        :param window: surface to draw on, normally the app window
        """
        ox, oy = self.rect.topleft
        playable = pg.Rect(ox, oy + self.top_inset,
                           self.rect.width, self.rect.height - self.top_inset)
        pg.draw.rect(window, pg.Color("magenta"), playable, 2)
        for o in self.obstacles:
            pg.draw.rect(window, pg.Color("cyan"),
                         pg.Rect(ox + o[0], oy + o[1], o[2] - o[0], o[3] - o[1]), 2)
        for ent in (*self.pawns, self.queen):
            if ent is None:
                continue
            art = self._entity_art(ent["kind"])
            base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
            w = art["w"] if art else int(base * self.scale)
            h = ent["sprite_h"]
            if ent["kind"] == "queen":
                color = pg.Color("lime")
            elif ent.get("emerging"):
                color = pg.Color("orange")
            else:
                color = pg.Color("yellow")
            pg.draw.rect(window, color,
                         pg.Rect(ox + ent["x"] - w / 2, oy + ent["y"] - h, w, h), 2)

    def _draw_entity(self, window: pg.Surface, ent: dict[str, Any], now: int) -> None:
        """
        Draw one fighter where it stands: its shadow, its sprite facing the way
        it is looking, and its gun unless it is already dying. A queen who has
        just been hit shudders, a dying pawn is placed by its ragdoll, and a
        fighter with no artwork is drawn as a plain circle

        :param window: surface to draw on
        :param ent: queen or pawn record being drawn
        :param now: pygame ticks in milliseconds of this frame
        """
        ox, oy = self.rect.topleft
        art = self._entity_art(ent["kind"])
        sprite_h = ent["sprite_h"]
        flinch_dx = 0.0
        if ent["kind"] == "queen" and ent["flinch"] > 0:
            flinch_dx = math.sin(ent["flinch"] * 30) * 4 * self.scale
        rot, alpha, tx, ty = 0.0, 255, 0.0, 0.0
        if ent.get("dying"):
            rot, alpha, tx, ty = self._ragdoll(ent, now)
        feet_x = ox + ent["x"] + flinch_dx + tx
        feet_y = oy + ent["y"] + ty
        self._draw_shadow(window, ox + ent["x"], oy + ent["y"], ent["kind"])
        if art is not None:
            img = art["flipped"] if ent["face"] < 0 else art["normal"]
            if rot:
                img = pg.transform.rotozoom(img, rot, 1.0)
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            window.blit(img, (feet_x - img.get_width() / 2, feet_y - img.get_height()))
        else:
            color = Colors.text if ent["kind"] == "queen" else Colors.text_dim
            pg.draw.circle(window, color, (int(feet_x), int(feet_y - sprite_h / 2)),
                           int(sprite_h * 0.32))
        if not ent.get("dying"):
            self._draw_gun(window, ent, ox, oy)

    def _ragdoll(self, ent: dict[str, Any], now: int) -> tuple[float, int, float, float]:
        """
        Place a dying pawn through its death throw: flung up and away from the
        shot through the first half, then tumbling on and fading out through the
        second

        :param ent: dying pawn record, carrying when and which way it fell
        :param now: pygame ticks in milliseconds of this frame
        :returns: rotation in degrees, alpha, and the horizontal and vertical
            offset from where it fell, in pixels
        """
        p = min(1.0, (now - ent["death_ms"]) / RAGDOLL_MS)
        d = ent["death_dir"]
        s = self.scale
        if p < 0.5:
            t = p / 0.5
            return d * 200 * t, 255, d * 60 * t * s, -50 * t * s
        t = (p - 0.5) / 0.5
        return (d * (200 + 340 * t), int(255 * (1 - t)),
                d * (60 + 70 * t) * s, (-50 + 190 * t) * s)

    def _draw_shadow(self, window: pg.Surface, cx: float, cy: float, kind: str) -> None:
        """
        Blot the prebuilt shadow under a fighter's feet, skipped for a kind that
        has no shadow built

        :param window: surface to draw on
        :param cx: feet x in window pixels
        :param cy: feet y in window pixels
        :param kind: queen or pawn, which picks the shadow size
        """
        shadow = self._shadow_surfs.get(kind)
        if shadow is None:
            return
        window.blit(shadow, (cx - shadow.get_width() / 2, cy - shadow.get_height() / 2))

    def _draw_gun(self, window: pg.Surface, ent: dict[str, Any], ox: int, oy: int) -> None:
        """
        Draw the gun in a fighter's hand: mid-flourish while it is still being
        produced or twirled, otherwise held on the aim with the kick of its last
        shot still fading. A weapon with no artwork draws nothing

        :param window: surface to draw on
        :param ent: fighter holding the gun
        :param ox: arena left edge in window pixels
        :param oy: arena top edge in window pixels
        """
        entry = self._weapons.get(ent["kind"], {}).get(ent.get("weapon"))
        if entry is None:
            return
        px, py = self._gun_pivot(ent)
        rx, ry = self._recoil_offset(ent)
        screen_pivot = (ox + px + rx, oy + py + ry)
        draw = ent.get("draw_anim", 0.0)
        if draw > 0:
            self._draw_gun_flourish(
                window, entry, screen_pivot, ent["aim"], draw,
                ent.get("draw_total", GUN_DRAW_SEC) or GUN_DRAW_SEC,
                ent.get("draw_spins", GUN_DRAW_SPINS_LAND), ent.get("draw_grow", True))
        else:
            gunfx.blit_aimed(window, entry["gun"], entry["grip"], screen_pivot, ent["aim"])

    def _draw_gun_flourish(self, window: pg.Surface, entry: dict[str, Any],
                           screen_pivot: tuple[float, float], aim: float, draw: float,
                           total: float, spins: int, grow: bool) -> None:
        """
        Draw one frame of a gun twirl, turning the time left into how far
        through the spin it is. It is the shared front end for both the
        weapon-swap flourish and the shorter celebratory kill spin

        :param window: surface to draw on
        :param entry: built weapon record with the scaled gun and its grip
        :param screen_pivot: the hand holding it, in window pixels
        :param aim: angle in radians the spin lands on
        :param draw: seconds of the twirl still to run
        :param total: the twirl's full length in seconds
        :param spins: whole turns before it lands
        :param grow: True to grow the gun in as it spins
        """
        p = 1.0 - draw / total
        gunfx.draw_flourish(window, entry["gun"], entry["grip"], screen_pivot, aim, p,
                            spins, grow)

    def _draw_drop(self, window: pg.Surface, drop: dict[str, Any], now: int) -> None:
        """
        Draw a discarded gun tumbling or lying on the floor, fading out over its
        three seconds

        :param window: surface to draw on
        :param drop: dropped-gun record
        :param now: pygame ticks in milliseconds of this frame
        """
        prog = (now - drop["start"]) / drop["dur"]
        if prog >= 1.0:
            return
        img = pg.transform.rotozoom(drop["img"], drop["angle"], 1.0)
        img.set_alpha(int(255 * (1.0 - prog)))
        ox, oy = self.rect.topleft
        window.blit(img, img.get_rect(center=(ox + drop["x"], oy + drop["y"])))

    def _draw_particle(self, window: pg.Surface, p: dict[str, Any], now: int) -> None:
        """
        Send one particle to whichever routine knows how to draw its kind, after
        turning its age into a 0..1 progress

        :param window: surface to draw on
        :param p: particle record, dispatched on its kind
        :param now: pygame ticks in milliseconds of this frame
        """
        ox, oy = self.rect.topleft
        prog = (now - p["start"]) / p["dur"]
        prog = max(0.0, min(1.0, prog))
        kind = p["kind"]
        if kind == "flash":
            self._draw_flash(window, p, prog)
        elif kind == "hitmark":
            self._draw_hitmark(window, ox + p["x"], oy + p["y"], prog)
        elif kind == "spark":
            self._draw_spark(window, ox + p["x"], oy + p["y"], p, prog)

    def _draw_projectile(self, window: pg.Surface, pr: dict[str, Any]) -> None:
        """
        Draw one bullet in flight as a streak lying along the way it travels, in
        the colour and size its gun gives it

        :param window: surface to draw on
        :param pr: pellet record carrying position, velocity and look
        """
        ox, oy = self.rect.topleft
        speed = math.hypot(pr["vx"], pr["vy"]) or 1.0
        gunfx.draw_bullet(window, (ox + pr["x"], oy + pr["y"]),
                          pr["vx"] / speed, pr["vy"] / speed,
                          pr["color"], pr["size"], pr["len"])

    def _draw_flash(self, window: pg.Surface, p: dict[str, Any], prog: float) -> None:
        """
        Draw a muzzle flash where its shot left the barrel, pointing along the
        angle it was fired at and fading over its short life

        :param window: surface to draw on
        :param p: flash particle record naming the weapon and the variant
        :param prog: 0..1 progress through the flash's life
        """
        entry = self._weapons.get(p["ent_kind"], {}).get(p["weapon"])
        if entry is None or p["idx"] >= len(entry["flashes"]):
            return
        fl = entry["flashes"][p["idx"]]
        m = (self.rect.x + p["x"], self.rect.y + p["y"])
        gunfx.draw_flash(window, fl["img"], fl["anchor"], m, p["aim"], prog)

    def _draw_hitmark(self, window: pg.Surface, x: float, y: float, prog: float) -> None:
        """
        Draw the crosshair tick over a landed shot, its arms spreading outwards
        and fading as they go

        :param window: surface to draw on
        :param x: impact x in window pixels
        :param y: impact y in window pixels
        :param prog: 0..1 progress through the marker's life
        """
        alpha = int(255 * (1 - prog))
        if alpha <= 0:
            return
        spread = round((5 + 16 * prog) * self.scale)
        length = round(8 * self.scale, 1)
        thick = max(int(3 * self.scale), 2)
        layer = _hitmark_sprite(spread, length, thick)
        layer.set_alpha(alpha)
        c = layer.get_width() / 2
        window.blit(layer, (x - c, y - c))

    def _draw_spark(self, window: pg.Surface, x: float, y: float, p: dict[str, Any],
                    prog: float) -> None:
        """
        Draw one spark of a burst, carried along its own heading and fading as
        it flies

        :param window: surface to draw on
        :param x: burst centre x in window pixels
        :param y: burst centre y in window pixels
        :param p: spark particle record carrying its velocity and colour
        :param prog: 0..1 progress through the spark's life
        """
        sx = x + p["vx"] * prog
        sy = y + p["vy"] * prog
        alpha = int(255 * (1 - prog))
        size = max(int(5 * self.scale), 2)
        layer = _menu_spark_sprite(size, p.get("color", Colors.amber_hi))
        layer.set_alpha(max(0, alpha))
        window.blit(layer, (sx, sy))

    def _fits_above(self, rect: pg.Rect) -> bool:
        """
        Say whether a badge or bubble can sit above a fighter's head: below the
        strip reserved for the title bar and clear of every menu panel. This is
        the test that decides whether the battle's chatter is placed overhead or
        pushed off to one side

        :param rect: the box being placed, in window pixels
        :returns: True when it fits above without striking anything
        """
        if rect.top < self.rect.y + self.top_inset + 4:
            return False
        return not any(card.width > 0 and rect.colliderect(card)
                       for card in self.avoid_rects)

    def _prefer_right(self, cx: float, body_y: float) -> bool:
        """
        Choose which side of a fighter a badge or bubble goes on when there is
        no room above -- whichever side has more clear space, counting the menu
        panels level with its body as walls

        :param cx: the fighter's x in window pixels
        :param body_y: the height of the fighter's body in window pixels, which
            picks out the panels level with it
        :returns: True to place it to the right, False to the left
        """
        lw, rw = self.rect.x + 4, self.rect.right - 4
        leftroom, rightroom = cx - lw, rw - cx
        for card in self.avoid_rects:
            if card.width <= 0 or not card.top - 12 <= body_y <= card.bottom + 12:
                continue
            if cx <= card.centerx:
                rightroom = min(rightroom, card.left - 6 - cx)
            else:
                leftroom = min(leftroom, cx - card.right - 6)
        return rightroom >= leftroom

    def _draw_bubble(self, window: pg.Surface, ent: dict[str, Any], now: int) -> None:
        """
        Draw whatever a fighter is saying, and retire the bubble once its time
        is up. It fades in, holds and fades out, and it is placed wherever it
        actually fits -- above the head by preference, otherwise to whichever
        side has room -- so a line never lands on a menu panel or in the title
        bar

        :param window: surface to draw on
        :param ent: fighter whose bubble is drawn; its bubble is cleared here
            when it expires
        :param now: pygame ticks in milliseconds of this frame
        """
        bub = ent.get("bubble")
        if bub is None:
            return
        age = now - bub["start"]
        total = bub["hold"]
        if age >= total:
            ent["bubble"] = None
            return
        if age < BUBBLE_FADE_IN_MS:
            alpha = age / BUBBLE_FADE_IN_MS
        elif age > total - BUBBLE_FADE_OUT_MS:
            alpha = max(0.0, (total - age) / BUBBLE_FADE_OUT_MS)
        else:
            alpha = 1.0
        if bub["who"] == "queen":
            bg, txt, border = Colors.amber, Colors.on_accent, Colors.amber_hi
        else:
            bg, txt, border = Colors.bubble_pawn_bg, Colors.bubble_pawn_text, Colors.border_strong
        scale = self.scale
        font = self._scaled_bold_font(max(int(12 * scale), 9), "_bubble_font")
        pad_x, pad_y = int(11 * scale), int(6 * scale)
        tail = max(int(6 * scale), 3)
        line_gap = max(int(2 * scale), 1)
        ox, oy = self.rect.topleft
        cx = ox + ent["x"]
        sprite_h = ent["sprite_h"]
        top = oy + ent["y"] - sprite_h
        body_y = oy + ent["y"] - sprite_h * 0.72
        art = self._entity_art(ent["kind"])
        half_w = art["normal"].get_width() / 2 if art else sprite_h * 0.32
        lw, rw = self.rect.x + 4, self.rect.right - 4

        def measure(max_text_w: float) -> tuple[list[pg.Surface], int, int]:
            """
            Wrap and render this bubble's line to a width, keeping the result on
            the bubble itself so a line held for two seconds is laid out once
            rather than every frame

            :param max_text_w: width the text has to fit into, in pixels
            :returns: the rendered lines and the bubble's full width and height
                in pixels, padding included
            """
            mw = max(int(max_text_w), 1)
            cache = bub.setdefault("_wrap", {})
            ckey = (round(scale, 3), mw // 16)
            if ckey not in cache:
                lines = wrap_words(bub["text"], font, mw)
                surfs = [render_text(font, line, pg.Color(txt)) for line in lines]
                tw = max(s.get_width() for s in surfs)
                th = sum(s.get_height() for s in surfs) + line_gap * (len(surfs) - 1)
                cache[ckey] = (surfs, tw + 2 * pad_x, th + 2 * pad_y)
            return cast(tuple[list[pg.Surface], int, int], cache[ckey])

        above_lw, above_rw = lw, rw
        for card in self.avoid_rects:
            if card.width <= 0:
                continue
            if cx <= card.centerx:
                above_rw = min(above_rw, card.left - 6)
            else:
                above_lw = max(above_lw, card.right + 6)
        surfs, bw, bh = measure(above_rw - above_lw - 2 * pad_x)
        bx = max(above_lw, min(cx - bw / 2, above_rw - bw))
        by = top - tail - bh
        if self._fits_above(pg.Rect(bx, by, bw, bh)):
            self._blit_bubble(bub, window, surfs, bx, by, bw, bh, tail, "down",
                              cx, top, bg, border, alpha, pad_x, pad_y, line_gap)
            return

        if self._prefer_right(cx, body_y):
            edge_x = cx + half_w
            surfs, bw, bh = measure(rw - edge_x - tail - 2 * pad_x)
            by = max(self.top_inset + 4, min(body_y - bh / 2, self.rect.bottom - bh - 4))
            self._blit_bubble(bub, window, surfs, edge_x + tail, by, bw, bh, tail, "left",
                              edge_x, body_y, bg, border, alpha, pad_x, pad_y, line_gap)
        else:
            edge_x = cx - half_w
            surfs, bw, bh = measure(edge_x - tail - lw - 2 * pad_x)
            by = max(self.top_inset + 4, min(body_y - bh / 2, self.rect.bottom - bh - 4))
            self._blit_bubble(bub, window, surfs, edge_x - tail - bw, by, bw, bh, tail, "right",
                              edge_x, body_y, bg, border, alpha, pad_x, pad_y, line_gap)

    def _blit_bubble(self, bub: dict[str, Any], window: pg.Surface, surfs: list[pg.Surface],
                     bx: float, by: float, bw: int, bh: int, tail: int, direction: str,
                     anchor_x: float, anchor_y: float, bg: str, border: str, alpha: float,
                     pad_x: int, pad_y: int, line_gap: int) -> None:
        """
        Paint one speech bubble: a rounded panel with a tail pointing back at
        whoever is speaking, and the wrapped lines inside it. The finished panel
        is kept on the bubble and only its alpha changes from frame to frame, so
        a held line is drawn once and then merely faded

        :param bub: bubble record the finished panel is cached on
        :param window: surface to draw on
        :param surfs: the rendered lines, in reading order
        :param bx: panel left edge in window pixels
        :param by: panel top edge in window pixels
        :param bw: panel width in pixels
        :param bh: panel height in pixels
        :param tail: tail size in pixels, which is also the panel's margin
            inside the drawn layer
        :param direction: which way the tail points -- down, up, left or right
        :param anchor_x: the speaker's x in window pixels, where the tail aims
        :param anchor_y: the speaker's y in window pixels, where the tail aims
        :param bg: panel fill colour
        :param border: panel outline colour
        :param alpha: 0.0 to 1.0 opacity for this frame, from the fade
        :param pad_x: horizontal padding inside the panel, in pixels
        :param pad_y: vertical padding inside the panel, in pixels
        :param line_gap: pixel gap between the wrapped lines
        """
        key = (id(surfs), direction, round(bw, 2), round(bh, 2), round(tail, 2),
               round(anchor_x - bx, 2), round(anchor_y - by, 2))
        cached = bub.get("_layer")
        if cached is not None and cached[0] == key:
            layer = cached[1]
        else:
            layer = pg.Surface((int(bw) + 2 * tail, int(bh) + 2 * tail), pg.SRCALPHA)
            body = pg.Rect(tail, tail, int(bw), int(bh))
            radius = max(int(10 * self.scale), 4)
            pg.draw.rect(layer, pg.Color(bg), body, border_radius=radius)
            pg.draw.rect(layer, pg.Color(border), body, 1, border_radius=radius)
            if direction in ("down", "up"):
                tip = max(body.left + tail, min(int(anchor_x - bx) + tail, body.right - tail))
                edge = body.bottom if direction == "down" else body.top
                point = (tip, edge + tail) if direction == "down" else (tip, edge - tail)
                pg.draw.polygon(layer, pg.Color(bg),
                                [(tip - tail, edge), (tip + tail, edge), point])
            else:
                tip = max(body.top + tail, min(int(anchor_y - by) + tail, body.bottom - tail))
                edge = body.left if direction == "left" else body.right
                point = (edge - tail, tip) if direction == "left" else (edge + tail, tip)
                pg.draw.polygon(layer, pg.Color(bg),
                                [(edge, tip - tail), (edge, tip + tail), point])
            y = body.y + pad_y
            for surf in surfs:
                layer.blit(surf, (body.x + pad_x, y))
                y += surf.get_height() + line_gap
            bub["_layer"] = (key, layer)
        layer.set_alpha(int(alpha * 255))
        window.blit(layer, (bx - tail, by - tail))

    def _background(self, size: tuple[int, int]) -> pg.Surface:
        """
        Paint the arena the fight happens in -- the same radial backdrop the
        game screen uses, on a denser grid -- and keep it until the arena
        changes size, since painting it pixel by pixel is far too heavy to
        repeat per frame

        :param size: arena width and height in pixels
        :returns: the backdrop surface for that size
        """
        if self._bg_cache is not None and self._bg_cache[0] == size:
            return self._bg_cache[1]
        step = max(int(GRID_STEP * self.scale), GRID_STEP_MIN)
        surf = backdrop.arena_background(size, (0.5, 0.18), grid=step).convert()
        self._bg_cache = (size, surf)
        return surf

    def _scrim(self, size: tuple[int, int]) -> pg.Surface:
        """
        Build the vignette laid over the fight and keep it until the arena
        changes size. It is drawn tiny and then stretched, which is what makes a
        full-window radial gradient affordable

        :param size: arena width and height in pixels
        :returns: the vignette surface for that size
        """
        if self._scrim_cache is not None and self._scrim_cache[0] == size:
            return self._scrim_cache[1]
        scrim = self._radial(SCRIM_N, SCRIM_INNER_ALPHA, SCRIM_OUTER_ALPHA, Colors.battle_scrim)
        scrim = pg.transform.smoothscale(scrim, size)
        self._scrim_cache = (size, scrim)
        return scrim

    def _radial(self, n: int, inner_a: int, outer_a: int, color: str) -> pg.Surface:
        """
        Draw a small square of one colour whose transparency fades from the
        centre outwards, the seed the vignette is stretched from

        :param n: side of the square in pixels, before it is stretched
        :param inner_a: alpha at the centre
        :param outer_a: alpha at the outer edge
        :param color: the colour it is filled with
        :returns: the gradient square
        """
        surf = pg.Surface((n, n), pg.SRCALPHA)
        cr, cg, cb = pg.Color(color)[:3]  # type: ignore[misc]
        c = (n - 1) / 2.0
        for yy in range(n):
            for xx in range(n):
                d = math.hypot(xx - c, yy - c) / c
                d = max(0.0, min(1.0, d))
                a = int(inner_a + (outer_a - inner_a) * d)
                surf.set_at((xx, yy), (cr, cg, cb, a))
        return surf
