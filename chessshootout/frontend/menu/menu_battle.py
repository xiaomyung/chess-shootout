import math
import os
import random

import pygame as pg

from chessshootout import paths
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


def _hitmark_sprite(spread, length, thick):
    def build():
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
    return memoized_surface(_HITMARK_CACHE, (spread, length, thick), build)


def _menu_spark_sprite(size, color):
    def build():
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(color))
        return surf
    return memoized_surface(_MENU_SPARK_CACHE, (size, color), build)


class MenuBattle:
    def __init__(self, window, rng=None, sound_manager=None):
        self.window = window
        self.rng = rng or random.Random()
        self.sound_manager = sound_manager
        self.rect = pg.Rect(0, 0, 0, 0)
        self.avoid_rects = []
        self.obstacles = []
        self.top_inset = 0
        self.debug = os.environ.get("CHESS_BATTLE_DEBUG") == "1"
        self.scale = 1.0
        self.pawns = []
        self.queen = None
        self.particles = []
        self.projectiles = []
        self.drops = []
        self.acc = {"qfire": 0.0, "talk": 1.5, "spawn": 0.0}
        self._last_ms = None
        self._initialized = False
        self._bg_cache = None
        self._scrim_cache = None
        self._queen_src = self._load_piece("queen", "white")
        self._pawn_src = self._load_piece("pawn", "black")
        self._battle = gunfx.load_battle_art()
        self._art = {}
        self._shadow_surfs = {}
        self._weapons = {}

    def _load_piece(self, piece_type, color):
        def build():
            try:
                path = paths.resource_path("assets", "pieces_png", f"{piece_type}_{color}.png")
                img = pg.image.load(str(path)).convert_alpha()
                return img.subsurface(img.get_bounding_rect()).copy()
            except (pg.error, FileNotFoundError, OSError):
                return None
        return memoized_surface(_BATTLE_PIECE_SRC_CACHE, (piece_type, color), build)

    def _rnd(self, lo, hi):
        return lo + self.rng.random() * (hi - lo)

    def _pick(self, seq):
        return seq[int(self.rng.random() * len(seq))]

    def set_rect(self, rect):
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

    def set_avoid_rects(self, rects):
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

    def set_avoid_rect(self, rect):
        self.set_avoid_rects([rect])

    def _size_entity(self, ent):
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

    def _build_art(self):
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

    def _build_shadows(self):
        self._shadow_surfs = {}
        h = max(int(8 * self.scale), 6)
        for kind, base in (("queen", QUEEN_BASE_H), ("pawn", PAWN_BASE_H)):
            art = self._art.get(kind)
            w = max(int((art["w"] if art else base * self.scale) * 0.8), 4)
            surf = pg.Surface((w, h), pg.SRCALPHA)
            pg.draw.ellipse(surf, (*pg.Color(Colors.battle_shadow)[:3], 130), surf.get_rect())
            self._shadow_surfs[kind] = surf

    def _build_weapons(self):
        self._weapons = {}
        reach = QUEEN_BASE_H * gunfx.GUN_LEN_RATIO * self.scale
        for kind, guns in (("queen", sorted(self._battle["guns"])), ("pawn", (PAWN_WEAPON,))):
            built = {}
            for gun in guns:
                entry = gunfx.build_weapon(self._battle, gun, reach)
                if entry is not None:
                    built[gun] = entry
            self._weapons[kind] = built

    def _entity_art(self, kind):
        return self._art.get(kind)

    def _compute_obstacles(self):
        self.obstacles = []
        for a in self.avoid_rects:
            if a.width <= 0 or a.height <= 0:
                continue
            lx = a.x - self.rect.x
            ly = a.y - self.rect.y
            self.obstacles.append((lx, ly, lx + a.width, ly + a.height))

    def _entity_obstacles(self, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return [(o[0] - hw, o[1], o[2] + hw, o[3] + ent["sprite_h"])
                for o in self.obstacles]

    def _point_in(self, o, x, y):
        return o is not None and o[0] < x < o[2] and o[1] < y < o[3]

    def _point_in_any(self, obstacles, x, y):
        return any(self._point_in(o, x, y) for o in obstacles)

    def _push_out(self, o, x, y, exclude_top=False):
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

    def _push_out_all(self, obstacles, x, y, exclude_top=False):
        for _ in range(4):
            moved = False
            for o in obstacles:
                nx, ny = self._push_out(o, x, y, exclude_top)
                if (nx, ny) != (x, y):
                    x, y, moved = nx, ny, True
            if not moved:
                break
        return x, y

    def _seg_hits(self, o, ax, ay, bx, by):
        if o is None:
            return False
        for i in range(1, 12):
            t = i / 12.0
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if o[0] < x < o[2] and o[1] < y < o[3]:
                return True
        return False

    def _seg_hits_any(self, obstacles, ax, ay, bx, by):
        return any(self._seg_hits(o, ax, ay, bx, by) for o in obstacles)

    def _route(self, obstacles, px, py, tx, ty):
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

    def _rand_waypoint(self, obstacles=None):
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

    def _make_queen(self):
        w, h = self.rect.width, self.rect.height
        qx, qy = w * 0.16, h * 0.52
        q = {"kind": "queen", "x": qx, "y": qy, "face": 1,
             "flinch": 0.0, "aim": 0.0, "wp": None, "bubble": None,
             "anchor_x": qx, "anchor_y": qy, "anchor_ms": None, "weapon": QUEEN_WEAPON,
             "weapon_switch": self._rnd(WEAPON_SWITCH_MIN, WEAPON_SWITCH_MAX), "recoil": 0.0,
             "draw_anim": 0.0, "draw_total": GUN_DRAW_SEC, "draw_spins": 0, "draw_grow": True,
             "kills": 0, "ko_wink_until": 0}
        self._size_entity(q)
        return q

    def _spawn_initial(self):
        self.queen = self._make_queen()
        self.queen["wp"] = self._rand_waypoint()

    def _spawn_pawn(self, initial):
        if len(self.pawns) >= MAX_PAWNS:
            return
        w, h = self.rect.width, self.rect.height
        side = int(self.rng.random() * 4)
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
        p = {
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

    def _body_point(self, ent):
        return ent["x"], ent["y"] - ent["sprite_h"] * 0.55

    def _gun_pivot(self, ent):
        return ent["x"] + ent["face"] * 6 * self.scale, ent["y"] - ent["gy"]

    def _recoil_offset(self, ent):
        r = ent.get("recoil", 0.0)
        if not r:
            return 0.0, 0.0
        return -math.cos(ent["aim"]) * r, -math.sin(ent["aim"]) * r

    def _muzzle_point(self, ent):
        px, py = self._gun_pivot(ent)
        rx, ry = self._recoil_offset(ent)
        px, py = px + rx, py + ry
        entry = self._weapons.get(ent["kind"], {}).get(ent.get("weapon"))
        if entry is None:
            length = ent["gun_len"]
            return px + math.cos(ent["aim"]) * length, py + math.sin(ent["aim"]) * length
        return gunfx.aimed_target(entry["gun"], entry["grip"], entry["barrel"],
                                  (px, py), ent["aim"])

    def _aim_gun(self, ent, target, dt):
        if target is None:
            return
        px, py = self._gun_pivot(ent)
        tx, ty = self._body_point(target)
        want = math.atan2(ty - py, tx - px)
        delta = (want - ent["aim"] + math.pi) % (2 * math.pi) - math.pi
        ent["aim"] += delta * min(1.0, dt * 9)

    def _aligned(self, ent, target):
        px, py = self._gun_pivot(ent)
        tx, ty = self._body_point(target)
        want = math.atan2(ty - py, tx - px)
        delta = (want - ent["aim"] + math.pi) % (2 * math.pi) - math.pi
        return abs(delta) < AIM_TOLERANCE

    def update(self, now_ms):
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
    def _start_gun_flourish(ent, seconds, spins, grow):
        ent["draw_anim"] = seconds
        ent["draw_total"] = seconds
        ent["draw_spins"] = spins
        ent["draw_grow"] = grow

    def _drop_gun(self, weapon, ent, now_ms):
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

    def _update_drops(self, dt):
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

    def _step(self, dt, now_ms):
        q = self.queen
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

        alive = [p for p in self.pawns if p["alive"]]
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

        self.acc["spawn"] -= dt
        while self.acc["spawn"] <= 0 and len(self.pawns) < MAX_PAWNS:
            self.acc["spawn"] += self._rnd(0.18, 0.42)
            self._spawn_pawn(False)

        self.acc["talk"] -= dt
        if self.acc["talk"] <= 0:
            self.acc["talk"] = self._rnd(2.4, 4.6)
            if self.rng.random() < 0.5 or not alive:
                self._say(q, self._pick(QUEEN_LINES), "queen", now_ms)
            else:
                self._say(self._pick(alive), self._pick(PAWN_LINES), "pawn", now_ms)

    def _clamp_entity_to_field(self, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        h = ent["sprite_h"]
        ent["x"] = max(hw, min(self.rect.width - hw, ent["x"]))
        ent["y"] = max(self.top_inset + h, min(float(self.rect.height), ent["y"]))

    def _clamp_queen_to_window(self):
        if self.queen is not None:
            self._clamp_entity_to_field(self.queen)

    def _reconcile_entities(self):
        for ent in (self.queen, *self.pawns):
            if ent is None or ent.get("emerging"):
                continue
            ent["x"], ent["y"] = self._push_out_all(
                self._entity_obstacles(ent), ent["x"], ent["y"],
                exclude_top=ent["kind"] == "queen")
            self._clamp_entity_to_field(ent)

    def _cull_out_of_bounds(self):
        self.projectiles = [pr for pr in self.projectiles
                            if not self._off_screen(pr["x"], pr["y"])]
        self.particles = [p for p in self.particles
                          if not self._off_screen(p["x"], p["y"])]
        self.drops = [d for d in self.drops if not self._off_screen(d["x"], d["y"])]

    def _fully_in_window(self, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return (ent["x"] - hw >= 0 and ent["x"] + hw <= self.rect.width
                and ent["y"] - ent["sprite_h"] >= self.top_inset
                and ent["y"] <= self.rect.height)

    def _visible_with(self, ent, obstacles):
        return (self._fully_in_window(ent)
                and not self._point_in_any(obstacles, ent["x"], ent["y"]))

    def _visible(self, ent):
        return self._visible_with(ent, self._entity_obstacles(ent))

    def _separate_pawns(self):
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

    def _unstick_queen(self, now_ms, qo):
        q = self.queen
        moved = math.hypot(q["x"] - q["anchor_x"], q["y"] - q["anchor_y"])
        if q["anchor_ms"] is None or moved > IDLE_RADIUS:
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms
        elif now_ms - q["anchor_ms"] >= IDLE_TIMEOUT_MS:
            q["wp"] = self._rand_waypoint(qo)
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms

    def _fire(self, shooter, target, is_queen, now_ms):
        shooter["recoil"] = gunfx.gun_spec(shooter.get("weapon")).recoil * self.scale
        if self.sound_manager is not None:
            self.sound_manager.play_menu_gun(shooter.get("weapon"))
        ax, ay = self._muzzle_point(shooter)
        self._add_flash(shooter, ax, ay, now_ms)
        hit = self.rng.random() >= MISS_CHANCE
        self._spawn_projectiles(shooter, target, is_queen, ax, ay, hit, now_ms)

    def _spawn_projectiles(self, shooter, target, is_queen, mx, my, hit, now_ms):
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

    def _kill_pawn(self, p, now_ms):
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

    def _add_hit(self, x, y, now_ms):
        self.particles.append({"kind": "hitmark", "x": x, "y": y,
                               "start": now_ms, "dur": HITMARK_MS})
        self._add_sparks(x, y, 11, now_ms, Colors.blood)

    def _say(self, ent, text, who, now_ms, hold=BUBBLE_HOLD_MS):
        ent["bubble"] = {"text": text, "who": who, "start": now_ms, "hold": hold}

    def _add_flash(self, ent, x, y, now_ms):
        entry = self._weapons.get(ent["kind"], {}).get(ent.get("weapon"))
        if entry is None or not entry["flashes"]:
            return
        idx = int(self.rng.random() * len(entry["flashes"]))
        self.particles.append({"kind": "flash", "ent_kind": ent["kind"],
                               "weapon": ent["weapon"], "idx": idx,
                               "x": x, "y": y, "aim": ent["aim"],
                               "start": now_ms, "dur": FLASH_MS})

    def _update_projectiles(self, dt, now_ms):
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

    def _projectile_hit(self, pr):
        if pr["is_queen"]:
            for p in self.pawns:
                if p["alive"] and self._hits_hitbox(pr, p):
                    return p
            return None
        return self.queen if self._hits_hitbox(pr, self.queen) else None

    def _hits_hitbox(self, pr, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return (ent["x"] - hw <= pr["x"] <= ent["x"] + hw
                and ent["y"] - ent["sprite_h"] <= pr["y"] <= ent["y"])

    def _land_hit(self, is_queen, target, now_ms):
        if is_queen:
            self._kill_pawn(target, now_ms)
            if self.queen["draw_anim"] <= 0 and self.rng.random() < KILL_SPIN_CHANCE:
                self._start_gun_flourish(self.queen, KILL_SPIN_SEC, 1, False)
        else:
            self.queen["flinch"] = 1.0
            bx, by = self._body_point(target)
            self._add_hit(bx, by, now_ms)

    def _off_screen(self, x, y):
        m = 80
        return x < -m or x > self.rect.width + m or y < -m or y > self.rect.height + m

    def _add_sparks(self, x, y, n, now_ms, color=Colors.amber_hi):
        for _ in range(n):
            ang = self._rnd(0, 2 * math.pi)
            dist = self._rnd(20, 70)
            self.particles.append({
                "kind": "spark", "x": x, "y": y, "color": color,
                "vx": math.cos(ang) * dist, "vy": math.sin(ang) * dist - 20,
                "start": now_ms, "dur": self._rnd(*SPARK_MS)})

    def _prune(self, now_ms):
        self.particles = [p for p in self.particles if now_ms - p["start"] < p["dur"]]
        self.drops = [d for d in self.drops if now_ms - d["start"] < d["dur"]]
        self.pawns = [p for p in self.pawns
                      if not (p["dying"] and now_ms - p["death_ms"] >= RAGDOLL_MS)]

    def draw(self, window):
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

    def _scaled_bold_font(self, size, attr):
        cached = getattr(self, attr, None)
        if cached is None or cached[0] != size:
            cached = (size, get_font(size, bold=True))
            setattr(self, attr, cached)
        return cached[1]

    def _draw_ko_counter(self, window):
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

    def draw_scrim(self, window):
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        window.blit(self._scrim((self.rect.width, self.rect.height)), self.rect.topleft)
        if self.debug:
            self._draw_debug(window)

    def _draw_debug(self, window):
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

    def _draw_entity(self, window, ent, now):
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

    def _ragdoll(self, ent, now):
        p = min(1.0, (now - ent["death_ms"]) / RAGDOLL_MS)
        d = ent["death_dir"]
        s = self.scale
        if p < 0.5:
            t = p / 0.5
            return d * 200 * t, 255, d * 60 * t * s, -50 * t * s
        t = (p - 0.5) / 0.5
        return (d * (200 + 340 * t), int(255 * (1 - t)),
                d * (60 + 70 * t) * s, (-50 + 190 * t) * s)

    def _draw_shadow(self, window, cx, cy, kind):
        shadow = self._shadow_surfs.get(kind)
        if shadow is None:
            return
        window.blit(shadow, (cx - shadow.get_width() / 2, cy - shadow.get_height() / 2))

    def _draw_gun(self, window, ent, ox, oy):
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

    def _draw_gun_flourish(self, window, entry, screen_pivot, aim, draw, total, spins, grow):
        p = 1.0 - draw / total
        gunfx.draw_flourish(window, entry["gun"], entry["grip"], screen_pivot, aim, p,
                            spins, grow)

    def _draw_drop(self, window, drop, now):
        prog = (now - drop["start"]) / drop["dur"]
        if prog >= 1.0:
            return
        img = pg.transform.rotozoom(drop["img"], drop["angle"], 1.0)
        img.set_alpha(int(255 * (1.0 - prog)))
        ox, oy = self.rect.topleft
        window.blit(img, img.get_rect(center=(ox + drop["x"], oy + drop["y"])))

    def _draw_particle(self, window, p, now):
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

    def _draw_projectile(self, window, pr):
        ox, oy = self.rect.topleft
        speed = math.hypot(pr["vx"], pr["vy"]) or 1.0
        gunfx.draw_bullet(window, (ox + pr["x"], oy + pr["y"]),
                          pr["vx"] / speed, pr["vy"] / speed,
                          pr["color"], pr["size"], pr["len"])

    def _draw_flash(self, window, p, prog):
        entry = self._weapons.get(p["ent_kind"], {}).get(p["weapon"])
        if entry is None or p["idx"] >= len(entry["flashes"]):
            return
        fl = entry["flashes"][p["idx"]]
        m = (self.rect.x + p["x"], self.rect.y + p["y"])
        gunfx.draw_flash(window, fl["img"], fl["anchor"], m, p["aim"], prog)

    def _draw_hitmark(self, window, x, y, prog):
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

    def _draw_spark(self, window, x, y, p, prog):
        sx = x + p["vx"] * prog
        sy = y + p["vy"] * prog
        alpha = int(255 * (1 - prog))
        size = max(int(5 * self.scale), 2)
        layer = _menu_spark_sprite(size, p.get("color", Colors.amber_hi))
        layer.set_alpha(max(0, alpha))
        window.blit(layer, (sx, sy))

    def _fits_above(self, rect):
        if rect.top < self.rect.y + self.top_inset + 4:
            return False
        return not any(card.width > 0 and rect.colliderect(card)
                       for card in self.avoid_rects)

    def _prefer_right(self, cx, body_y):
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

    def _draw_bubble(self, window, ent, now):
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

        def measure(max_text_w):
            mw = max(int(max_text_w), 1)
            cache = bub.setdefault("_wrap", {})
            ckey = (round(scale, 3), mw // 16)
            if ckey not in cache:
                lines = wrap_words(bub["text"], font, mw)
                surfs = [render_text(font, line, pg.Color(txt)) for line in lines]
                tw = max(s.get_width() for s in surfs)
                th = sum(s.get_height() for s in surfs) + line_gap * (len(surfs) - 1)
                cache[ckey] = (surfs, tw + 2 * pad_x, th + 2 * pad_y)
            return cache[ckey]

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

    def _blit_bubble(self, bub, window, surfs, bx, by, bw, bh, tail, direction,
                     anchor_x, anchor_y, bg, border, alpha, pad_x, pad_y, line_gap):
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

    def _background(self, size):
        if self._bg_cache is not None and self._bg_cache[0] == size:
            return self._bg_cache[1]
        step = max(int(GRID_STEP * self.scale), GRID_STEP_MIN)
        surf = backdrop.arena_background(size, (0.5, 0.18), grid=step).convert()
        self._bg_cache = (size, surf)
        return surf

    def _scrim(self, size):
        if self._scrim_cache is not None and self._scrim_cache[0] == size:
            return self._scrim_cache[1]
        scrim = self._radial(SCRIM_N, SCRIM_INNER_ALPHA, SCRIM_OUTER_ALPHA, Colors.battle_scrim)
        scrim = pg.transform.smoothscale(scrim, size)
        self._scrim_cache = (size, scrim)
        return scrim

    def _radial(self, n, inner_a, outer_a, color):
        surf = pg.Surface((n, n), pg.SRCALPHA)
        cr, cg, cb = pg.Color(color)[:3]
        c = (n - 1) / 2.0
        for yy in range(n):
            for xx in range(n):
                d = math.hypot(xx - c, yy - c) / c
                d = max(0.0, min(1.0, d))
                a = int(inner_a + (outer_a - inner_a) * d)
                surf.set_at((xx, yy), (cr, cg, cb, a))
        return surf
