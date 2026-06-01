import json
import math
import os
import random

import pygame as pg

import paths
from frontend.visual.colors import Colors
from frontend.visual.fonts import get_font


AVOID_PAD = 0
ROUTE_MARGIN = 22
MAX_PAWNS = 10
INITIAL_PAWNS = 8
QUEEN_BASE_H = 104
PAWN_BASE_H = 64
DT_MAX = 0.05
RAGDOLL_MS = 900
IDLE_TIMEOUT_MS = 2000
IDLE_RADIUS = 24
FLASH_MS = 120
GUN_LEN_RATIO = 0.62
GUN_SCALE = {"revolver": 0.363, "ray_gun": 0.33, "hand_cannon": 0.50}
GUN_RECOIL = {"revolver": 4, "ray_gun": 4, "lever_action": 7,
              "hand_cannon": 9, "shotgun": 10, "blunderbuss": 12}
RECOIL_DEFAULT = 5
RECOIL_RECOVER = 12.0
AIM_TOLERANCE = 0.12
MISS_CHANCE = 0.20
PROJECTILE_MAX_MS = 1600
PROJECTILES = {
    "revolver": {"style": "bullet", "speed": 1066, "size": 5, "len": 12, "pellets": 1,
                 "spread": 0.0, "color": Colors.amber_hi},
    "lever_action": {"style": "bullet", "speed": 1170, "size": 5, "len": 17, "pellets": 1,
                     "spread": 0.0, "color": Colors.amber_hi},
    "hand_cannon": {"style": "slug", "speed": 780, "size": 9, "len": 13, "pellets": 1,
                    "spread": 0.0, "color": Colors.amber},
    "shotgun": {"style": "pellet", "speed": 936, "size": 4, "len": 8, "pellets": 6,
                "spread": 0.16, "color": Colors.amber_hi},
    "blunderbuss": {"style": "pellet", "speed": 728, "size": 4, "len": 7, "pellets": 8,
                    "spread": 0.26, "color": Colors.amber_hi},
    "ray_gun": {"style": "bolt", "speed": 1300, "size": 6, "len": 28, "pellets": 1,
                "spread": 0.0, "color": Colors.accent},
}
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
INTRO_LINES = ("Let's rock!", "One by one now, kids", "Here we go again",
               "back to work", "miss me?")
INTRO_MS = 1300
INTRO_GRACE_MS = 500
INTRO_ARC = 90
INTRO_DIM = 0.45
GUN_DRAW_SEC = 0.7
GUN_DRAW_SPINS_LAND = 5
GUN_DRAW_SPINS_SWAP = 3
KILL_SPIN_CHANCE = 0.20
KILL_SPIN_SEC = 0.45
DROP_GRAVITY = 900
DROP_MS = 3000


class MenuBattle:
    def __init__(self, window, rng=None):
        self.window = window
        self.rng = rng or random.Random()
        self.rect = pg.Rect(0, 0, 0, 0)
        self.avoid_rect = pg.Rect(0, 0, 0, 0)
        self.obstacle = None
        self.top_inset = 0
        self.debug = os.environ.get("CHESS_BATTLE_DEBUG") == "1"
        self.scale = 1.0
        self._logo_rect = pg.Rect(0, 0, 0, 0)
        self._intro_active = False
        self._intro_start_ms = None
        self._intro_t = 0.0
        self._intro_land = None
        self.pawns = []
        self.queen = None
        self.particles = []
        self.projectiles = []
        self.drops = []
        self.acc = {"qfire": 0.0, "talk": 1.5, "spawn": 0.0}
        self._last_ms = None
        self._initialized = False
        self._static_posed = False
        self._bg_cache = None
        self._scrim_cache = None
        self._queen_src = self._load_piece("queen", "white")
        self._pawn_src = self._load_piece("pawn", "black")
        self._battle = self._load_battle()
        self._art = {}
        self._shadow_surfs = {}
        self._weapons = {}

    def _load_piece(self, piece_type, color):
        try:
            path = paths.resource_path("assets", "pieces_img", f"{piece_type}_{color}.png")
            img = pg.image.load(str(path)).convert_alpha()
            return img.subsurface(img.get_bounding_rect()).copy()
        except (pg.error, FileNotFoundError, OSError):
            return None

    def _load_png(self, *parts):
        try:
            return pg.image.load(str(paths.resource_path("assets", "battle_png", *parts))) \
                .convert_alpha()
        except (pg.error, FileNotFoundError, OSError):
            return None

    def _load_battle(self):
        data = {"guns": {}, "flashes": {}}
        try:
            manifest = paths.resource_path("assets", "battle_png", "battle_manifest.json")
            with open(manifest) as fh:
                man = json.load(fh)
        except (OSError, ValueError):
            return data
        for gun, gm in man.get("guns", {}).items():
            img = self._load_png("guns", f"{gun}.png")
            if img is not None:
                data["guns"][gun] = {"img": img, "ax": gm["ax"], "ay": gm["ay"],
                                     "gx": gm["gx"], "gy": gm["gy"]}
        for gun, variants in man.get("flashes", {}).items():
            flashes = []
            for i, fm in enumerate(variants):
                img = self._load_png("flashes", f"flashes_{gun}", f"flash_{i + 1}.png")
                if img is not None:
                    flashes.append({"img": img, "ax": fm["ax"], "ay": fm["ay"]})
            if flashes:
                data["flashes"][gun] = flashes
        return data

    def _rnd(self, lo, hi):
        return lo + self.rng.random() * (hi - lo)

    def _pick(self, seq):
        return seq[int(self.rng.random() * len(seq))]

    def set_rect(self, rect):
        rect = pg.Rect(rect)
        self.rect = rect
        self.scale = max(0.85, min(1.5, rect.height / 760.0))
        self._build_art()
        self._build_shadows()
        self._build_weapons()
        self._compute_obstacle()
        self._bg_cache = None
        self._scrim_cache = None
        if not self._initialized and rect.width > 0 and rect.height > 0:
            self._spawn_initial()
            self._initialized = True
        elif self.queen is not None:
            self._size_entity(self.queen)
            for p in self.pawns:
                self._size_entity(p)
            self._clamp_queen_to_window()
            self.queen["wp"] = self._rand_waypoint()

    def set_avoid_rect(self, rect):
        self.avoid_rect = pg.Rect(rect)
        self._compute_obstacle()
        if self.queen is not None:
            for ent in (self.queen, *self.pawns):
                ent["x"], ent["y"] = self._push_out(self._entity_obstacle(ent),
                                                    ent["x"], ent["y"],
                                                    exclude_top=ent["kind"] == "queen")
            self._clamp_queen_to_window()

    def _size_entity(self, ent):
        kind = ent["kind"]
        art = self._entity_art(kind)
        base = QUEEN_BASE_H if kind == "queen" else PAWN_BASE_H
        sprite_h = art["h"] if art else int(base * self.scale)
        ent["sprite_h"] = sprite_h
        ent["gun_len"] = sprite_h * GUN_LEN_RATIO
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
        reach = QUEEN_BASE_H * GUN_LEN_RATIO * self.scale
        for kind, guns in (("queen", sorted(self._battle["guns"])), ("pawn", (PAWN_WEAPON,))):
            built = {}
            for gun in guns:
                g = self._battle["guns"].get(gun)
                if g is None:
                    continue
                gbdist = math.hypot(g["ax"] - g["gx"], g["ay"] - g["gy"]) or 1.0
                f = reach / gbdist * GUN_SCALE.get(gun, 1.0)
                built[gun] = {
                    "gun": self._scale_by(g["img"], f),
                    "grip": (g["gx"] * f, g["gy"] * f),
                    "barrel": (g["ax"] * f, g["ay"] * f),
                    "flashes": [{"img": self._scale_by(fl["img"], f),
                                 "anchor": (fl["ax"] * f, fl["ay"] * f)}
                                for fl in self._battle["flashes"].get(gun, [])],
                }
            self._weapons[kind] = built

    @staticmethod
    def _scale_by(img, f):
        w = max(int(img.get_width() * f), 1)
        h = max(int(img.get_height() * f), 1)
        return pg.transform.smoothscale(img, (w, h))

    def _entity_art(self, kind):
        return self._art.get(kind)

    def _compute_obstacle(self):
        a = self.avoid_rect
        if a.width <= 0 or a.height <= 0:
            self.obstacle = None
            return
        lx = a.x - self.rect.x
        ly = a.y - self.rect.y
        self.obstacle = (lx - AVOID_PAD, ly - AVOID_PAD,
                         lx + a.width + AVOID_PAD, ly + a.height + AVOID_PAD)

    def _entity_obstacle(self, ent):
        o = self.obstacle
        if o is None:
            return None
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return (o[0] - hw, o[1], o[2] + hw, o[3] + ent["sprite_h"])

    def _point_in(self, o, x, y):
        return o is not None and o[0] < x < o[2] and o[1] < y < o[3]

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

    def _route(self, o, px, py, tx, ty):
        if o is None or not self._seg_hits(o, px, py, tx, ty):
            return tx, ty
        m = ROUTE_MARGIN
        corners = ((o[0] - m, o[1] - m), (o[2] + m, o[1] - m),
                   (o[2] + m, o[3] + m), (o[0] - m, o[3] + m))
        best, best_cost = corners[0], float("inf")
        for cx, cy in corners:
            cost = math.hypot(cx - px, cy - py) + math.hypot(tx - cx, ty - cy)
            if cost < best_cost:
                best_cost, best = cost, (cx, cy)
        return best

    def _in_obstacle(self, x, y):
        return self._point_in(self.obstacle, x, y)

    def _avoid(self, x, y):
        return self._push_out(self.obstacle, x, y)

    def _seg_hits_rect(self, ax, ay, bx, by):
        return self._seg_hits(self.obstacle, ax, ay, bx, by)

    def _route_target(self, px, py, tx, ty):
        return self._route(self.obstacle, px, py, tx, ty)

    def _rand_waypoint(self, o=None):
        w, h = self.rect.width, self.rect.height
        if o is None:
            o = self.obstacle
        qh = self.queen["sprite_h"] if self.queen else 0.0
        ymin, ymax = self.top_inset + qh, float(h)
        if o is None:
            return [w * self._rnd(0.15, 0.85), self._rnd(ymin, ymax)]
        left = (12, o[0] - 12, ymin, ymax) if o[0] > 90 else None
        right = (o[2] + 12, w - 12, ymin, ymax) if w - o[2] > 90 else None
        extra = []
        if o[1] - ymin > 60:
            extra.append((30, w - 30, ymin, o[1] - 12))
        if ymax - o[3] > 60:
            extra.append((30, w - 30, o[3] + 12, ymax))
        bands = [b for b in (left, right) if b] + extra
        if not bands:
            return [16, (ymin + ymax) / 2]
        if left and right and not extra and self.queen is not None:
            card_cx = (o[0] + o[2]) / 2
            near = left if self.queen["x"] < card_cx else right
            far = right if near is left else left
            b = near if self.rng.random() < 0.78 else far
        else:
            b = bands[int(self.rng.random() * len(bands))]
        return [self._rnd(b[0], b[1]), self._rnd(b[2], b[3])]

    def _make_queen(self):
        w, h = self.rect.width, self.rect.height
        qx, qy = w * 0.16, h * 0.52
        q = {"kind": "queen", "x": qx, "y": qy, "face": 1,
             "flinch": 0.0, "aim": 0.0, "wp": None, "bubble": None,
             "anchor_x": qx, "anchor_y": qy, "anchor_ms": None, "weapon": QUEEN_WEAPON,
             "weapon_switch": self._rnd(WEAPON_SWITCH_MIN, WEAPON_SWITCH_MAX), "recoil": 0.0,
             "draw_anim": 0.0, "draw_total": GUN_DRAW_SEC, "draw_spins": 0, "draw_grow": True}
        self._size_entity(q)
        return q

    def _spawn_initial(self):
        self.queen = self._make_queen()
        self.queen["wp"] = self._rand_waypoint()
        self.begin_intro()

    def set_logo_rect(self, rect):
        self._logo_rect = pg.Rect(rect)

    def begin_intro(self):
        self._intro_active = True
        self._intro_start_ms = None
        self._intro_t = 0.0
        self._intro_land = None
        self.pawns = []
        self.projectiles = []
        self.particles = []
        self.drops = []
        self.acc = {"qfire": 0.0, "talk": 1.5, "spawn": 0.0}
        if self.queen is not None:
            self.queen["bubble"] = None
            self.queen["flinch"] = 0.0

    def _logo_center(self):
        if self._logo_rect.width > 0:
            return (self._logo_rect.centerx - self.rect.x,
                    self._logo_rect.centery - self.rect.y)
        return self.rect.width * 0.5, self.rect.height * 0.22

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
            p["x"], p["y"] = self._push_out(self._entity_obstacle(p), p["x"], p["y"])
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
        return self._aimed_target(entry["gun"], entry["grip"], entry["barrel"],
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

    def update(self, now_ms, reduce_motion=False):
        if self._last_ms is None:
            self._last_ms = now_ms
        dt = max(0.0, min(DT_MAX, (now_ms - self._last_ms) / 1000.0))
        self._last_ms = now_ms
        if self.queen is None:
            return
        if reduce_motion:
            if self._intro_active:
                self._finish_intro(now_ms)
                for _ in range(INITIAL_PAWNS):
                    self._spawn_pawn(True)
            if not self._static_posed:
                self._say(self.queen, "PICK A SIDE, COWARD", "queen", now_ms, hold=10 ** 9)
                self._static_posed = True
            return
        self._static_posed = False
        if self._intro_active:
            self._update_intro(dt, now_ms)
            self._prune(now_ms)
            return
        self._compute_obstacle()
        self._step(dt, now_ms)
        self._update_projectiles(dt, now_ms)
        self._update_drops(dt)
        self._prune(now_ms)

    def _update_intro(self, dt, now_ms):
        if self._intro_start_ms is None:
            self._intro_start_ms = now_ms
            self._intro_land = self._pick_landing()
        t = (now_ms - self._intro_start_ms - INTRO_GRACE_MS) / INTRO_MS
        if t >= 1.0:
            self._finish_intro(now_ms)
        else:
            self._intro_t = max(0.0, t)

    def _pick_landing(self):
        self._compute_obstacle()
        qo = self._entity_obstacle(self.queen)
        land = self._rand_waypoint(qo)
        x, y = self._window_clamped(land[0], land[1])
        return list(self._push_out(qo, x, y, exclude_top=True))

    def _finish_intro(self, now_ms):
        self._intro_active = False
        self._intro_t = 1.0
        if self._intro_land is None:
            self._intro_land = self._pick_landing()
        self.queen["x"], self.queen["y"] = self._intro_land
        self._clamp_queen_to_window()
        self.queen["wp"] = None
        self.queen["anchor_ms"] = None
        self._start_gun_flourish(self.queen, GUN_DRAW_SEC, GUN_DRAW_SPINS_LAND, True)
        self.acc["spawn"] = 0.6
        self._say(self.queen, self._pick(INTRO_LINES), "queen", now_ms)

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
        qo = self._entity_obstacle(q)
        if (q["wp"] is None or self._point_in(qo, q["wp"][0], q["wp"][1])
                or math.hypot(q["wp"][0] - q["x"], q["wp"][1] - q["y"]) < 26):
            q["wp"] = self._rand_waypoint(qo)
        qt = self._route(qo, q["x"], q["y"], q["wp"][0], q["wp"][1])
        q["x"] += (qt[0] - q["x"]) * min(1.0, dt * 1.6)
        q["y"] += (qt[1] - q["y"]) * min(1.0, dt * 1.6)
        q["x"], q["y"] = self._push_out(qo, q["x"], q["y"], exclude_top=True)
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
        targets = [p for p in alive if self._fully_in_window(p)]
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
            self.acc["qfire"] = self._rnd(0.7, 1.6)
            self._fire(q, nearest, True, now_ms)

        for p in alive:
            po = self._entity_obstacle(p)
            rx, ry = self._route(po, p["x"], p["y"], q["x"], q["y"])
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
            p["x"], p["y"] = self._push_out(po, p["x"], p["y"])
            p["recoil"] -= p["recoil"] * min(1.0, dt * RECOIL_RECOVER)
            self._aim_gun(p, q, dt)
            if self._fully_in_window(p):
                p["fire"] -= dt
                if p["fire"] <= 0 and self._aligned(p, q):
                    p["fire"] = self._rnd(2.2, 4.6)
                    self._fire(p, q, False, now_ms)
        self._separate_pawns()

        self.acc["spawn"] -= dt
        if self.acc["spawn"] <= 0 and len(self.pawns) < MAX_PAWNS:
            self.acc["spawn"] = self._rnd(1.2, 2.8)
            self._spawn_pawn(False)

        self.acc["talk"] -= dt
        if self.acc["talk"] <= 0:
            self.acc["talk"] = self._rnd(2.4, 4.6)
            if self.rng.random() < 0.5 or not alive:
                self._say(q, self._pick(QUEEN_LINES), "queen", now_ms)
            else:
                self._say(self._pick(alive), self._pick(PAWN_LINES), "pawn", now_ms)

    def _window_clamped(self, x, y):
        art = self._entity_art("queen")
        hw = (art["w"] if art else QUEEN_BASE_H * self.scale) / 2
        h = self.queen["sprite_h"]
        return (max(hw, min(self.rect.width - hw, x)),
                max(self.top_inset + h, min(float(self.rect.height), y)))

    def _clamp_queen_to_window(self):
        q = self.queen
        if q is None:
            return
        q["x"], q["y"] = self._window_clamped(q["x"], q["y"])

    def _fully_in_window(self, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return (ent["x"] - hw >= 0 and ent["x"] + hw <= self.rect.width
                and ent["y"] - ent["sprite_h"] >= self.top_inset
                and ent["y"] <= self.rect.height)

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
            p["x"], p["y"] = self._push_out(self._entity_obstacle(p), p["x"], p["y"])

    def _unstick_queen(self, now_ms, qo):
        q = self.queen
        moved = math.hypot(q["x"] - q["anchor_x"], q["y"] - q["anchor_y"])
        if q["anchor_ms"] is None or moved > IDLE_RADIUS:
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms
        elif now_ms - q["anchor_ms"] >= IDLE_TIMEOUT_MS:
            q["wp"] = self._rand_waypoint(qo)
            q["anchor_x"], q["anchor_y"], q["anchor_ms"] = q["x"], q["y"], now_ms

    def _fire(self, shooter, target, is_queen, now_ms):
        shooter["recoil"] = GUN_RECOIL.get(shooter.get("weapon"), RECOIL_DEFAULT) * self.scale
        ax, ay = self._muzzle_point(shooter)
        self._add_flash(shooter, ax, ay, now_ms)
        hit = self.rng.random() >= MISS_CHANCE
        self._spawn_projectiles(shooter, target, is_queen, ax, ay, hit, now_ms)

    def _spawn_projectiles(self, shooter, target, is_queen, mx, my, hit, now_ms):
        cfg = PROJECTILES.get(shooter.get("weapon"), PROJECTILES["revolver"])
        bx, by = self._body_point(target)
        if hit:
            ax, ay = bx, by
        else:
            ax = bx + math.cos(shooter["aim"]) * 70
            ay = by - self._rnd(45, 90)
        base = math.atan2(ay - my, ax - mx)
        speed = cfg["speed"] * self.scale
        shot = {"hit": hit, "is_queen": is_queen, "target": target, "resolved": False}
        for i in range(cfg["pellets"]):
            ang = base if i == 0 else base + self._rnd(-cfg["spread"], cfg["spread"])
            sp = speed if i == 0 else speed * self._rnd(0.85, 1.1)
            self.projectiles.append({
                "x": mx, "y": my, "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp,
                "style": cfg["style"], "size": cfg["size"] * self.scale,
                "len": cfg["len"] * self.scale, "color": cfg["color"],
                "shot": shot, "born": now_ms, "max_ms": PROJECTILE_MAX_MS})

    def _kill_pawn(self, p, now_ms):
        if not p["alive"]:
            return
        p["alive"] = False
        p["dying"] = True
        p["death_ms"] = now_ms
        p["death_dir"] = -1 if self.rng.random() < 0.5 else 1
        p["death_x"], p["death_y"] = p["x"], p["y"]
        bx, by = self._body_point(p)
        self._add_hit(bx, by, now_ms)
        if self.rng.random() < 0.4:
            self._say(p, self._pick(DEATH_LINES), "pawn", now_ms, hold=900)

    def _add_hit(self, x, y, now_ms):
        self.particles.append({"kind": "hitmark", "x": x, "y": y,
                               "start": now_ms, "dur": 220})
        self._add_sparks(x, y, 11, now_ms, Colors.blood)

    def _say(self, ent, text, who, now_ms, hold=2200):
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
            shot = pr["shot"]
            if not shot["resolved"] and shot["hit"]:
                tgt = shot["target"]
                if tgt is not None and tgt.get("alive", True) and self._hits_hitbox(pr, tgt):
                    shot["resolved"] = True
                    self._land_hit(shot, now_ms)
                    continue
            if now_ms - pr["born"] <= pr["max_ms"] and not self._off_screen(pr["x"], pr["y"]):
                survivors.append(pr)
        self.projectiles = survivors

    def _hits_hitbox(self, pr, ent):
        art = self._entity_art(ent["kind"])
        base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
        hw = (art["w"] if art else base * self.scale) / 2
        return (ent["x"] - hw <= pr["x"] <= ent["x"] + hw
                and ent["y"] - ent["sprite_h"] <= pr["y"] <= ent["y"])

    def _land_hit(self, shot, now_ms):
        tgt = shot["target"]
        if shot["is_queen"]:
            self._kill_pawn(tgt, now_ms)
            if self.queen["draw_anim"] <= 0 and self.rng.random() < KILL_SPIN_CHANCE:
                self._start_gun_flourish(self.queen, KILL_SPIN_SEC, 1, False)
        else:
            self.queen["flinch"] = 1.0
            bx, by = self._body_point(tgt)
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
                "start": now_ms, "dur": self._rnd(280, 560)})

    def _prune(self, now_ms):
        self.particles = [p for p in self.particles if now_ms - p["start"] < p["dur"]]
        self.drops = [d for d in self.drops if now_ms - d["start"] < d["dur"]]
        self.pawns = [p for p in self.pawns
                      if not (p["dying"] and now_ms - p["death_ms"] >= RAGDOLL_MS)]

    def draw(self, window):
        if self.queen is None:
            return
        window.blit(self._background((self.rect.width, self.rect.height)), self.rect.topleft)
        now = self._last_ms or 0
        for d in self.drops:
            self._draw_drop(window, d, now)
        for p in self.pawns:
            self._draw_entity(window, p, now)
        if not self._intro_active:
            self._draw_entity(window, self.queen, now)
        for p in self.particles:
            self._draw_particle(window, p, now)
        for pr in self.projectiles:
            self._draw_projectile(window, pr)
        for p in self.pawns:
            self._draw_bubble(window, p, now)
        if not self._intro_active:
            self._draw_bubble(window, self.queen, now)

    def draw_scrim(self, window):
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        window.blit(self._scrim((self.rect.width, self.rect.height)), self.rect.topleft)
        if self.debug:
            self._draw_debug(window)

    @staticmethod
    def _smoothstep(x):
        x = max(0.0, min(1.0, x))
        return x * x * (3 - 2 * x)

    def draw_intro_overlay(self, window):
        if not self._intro_active or self.queen is None:
            return
        art = self._entity_art("queen")
        if art is None:
            return
        t = self._intro_t
        ox, oy = self.rect.topleft
        lx, ly = self._logo_center()
        land = self._intro_land or (self.rect.width * 0.5, self.rect.height * 0.6)
        h = art["h"]
        logo_fit = (self._logo_rect.height * 0.92 / h) if self._logo_rect.height > 0 else 0.5
        fly = self._smoothstep((t - 0.1) / 0.9)
        end_cx, end_cy = land[0], land[1] - h / 2
        cx = lx + (end_cx - lx) * fly
        cy = ly + (end_cy - ly) * fly - math.sin(fly * math.pi) * INTRO_ARC * self.scale
        grow = self._smoothstep(t / 0.35)
        s = logo_fit + (1.0 - logo_fit) * grow
        sprite = pg.transform.smoothscale(
            art["normal"], (max(int(art["w"] * s), 1), max(int(h * s), 1))).copy()
        g = int(255 * (1.0 - INTRO_DIM * self._smoothstep(t)))
        sprite.fill((g, g, g, 255), special_flags=pg.BLEND_RGBA_MULT)
        flip = max(0.0, min(1.0, (t - 0.35) / 0.65))
        if flip:
            sprite = pg.transform.rotozoom(sprite, 360.0 * flip, 1.0)
        window.blit(sprite, sprite.get_rect(center=(ox + cx, oy + cy)))

    def _draw_debug(self, window):
        ox, oy = self.rect.topleft
        playable = pg.Rect(ox, oy + self.top_inset,
                           self.rect.width, self.rect.height - self.top_inset)
        pg.draw.rect(window, pg.Color("magenta"), playable, 2)
        if self.obstacle is not None:
            o = self.obstacle
            pg.draw.rect(window, pg.Color("cyan"),
                         pg.Rect(ox + o[0], oy + o[1], o[2] - o[0], o[3] - o[1]), 2)
        for ent in (*self.pawns, self.queen):
            if ent is None:
                continue
            art = self._entity_art(ent["kind"])
            base = QUEEN_BASE_H if ent["kind"] == "queen" else PAWN_BASE_H
            w = art["w"] if art else int(base * self.scale)
            h = ent["sprite_h"]
            color = pg.Color("lime") if ent["kind"] == "queen" else pg.Color("yellow")
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
            color = Colors.white if ent["kind"] == "queen" else Colors.text_dim
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
            self._blit_aimed(window, entry["gun"], entry["grip"], screen_pivot, ent["aim"])

    def _draw_gun_flourish(self, window, entry, screen_pivot, aim, draw, total, spins, grow):
        p = 1.0 - draw / total
        gscale = self._smoothstep(p) if grow else 1.0
        if gscale <= 0.02:
            return
        img = entry["gun"]
        img = pg.transform.smoothscale(
            img, (max(int(img.get_width() * gscale), 1), max(int(img.get_height() * gscale), 1)))
        grip = (entry["grip"][0] * gscale, entry["grip"][1] * gscale)
        img, pivot_img, _, angle_deg = self._aimed(img, grip, None, aim)
        spin = spins * 360.0 * (1.0 - p)
        self._blit_rotated(window, img, pivot_img, screen_pivot, angle_deg - spin)

    def _draw_drop(self, window, drop, now):
        prog = (now - drop["start"]) / drop["dur"]
        if prog >= 1.0:
            return
        img = pg.transform.rotozoom(drop["img"], drop["angle"], 1.0).copy()
        img.set_alpha(int(255 * (1.0 - prog)))
        ox, oy = self.rect.topleft
        window.blit(img, img.get_rect(center=(ox + drop["x"], oy + drop["y"])))

    def _aimed(self, image, pivot_img, target_img, aim):
        w = image.get_width()
        if math.cos(aim) < 0:
            image = pg.transform.flip(image, True, False)
            pivot_img = (w - pivot_img[0], pivot_img[1])
            if target_img is not None:
                target_img = (w - target_img[0], target_img[1])
            angle_deg = math.degrees(math.pi - aim)
        else:
            angle_deg = -math.degrees(aim)
        return image, pivot_img, target_img, angle_deg

    def _blit_aimed(self, window, image, pivot_img, screen_pivot, aim):
        image, pivot_img, _, angle_deg = self._aimed(image, pivot_img, None, aim)
        self._blit_rotated(window, image, pivot_img, screen_pivot, angle_deg)

    def _aimed_target(self, image, pivot_img, target_img, screen_pivot, aim):
        _, pivot_img, target_img, angle_deg = self._aimed(image, pivot_img, target_img, aim)
        vec = pg.math.Vector2(target_img[0] - pivot_img[0],
                              target_img[1] - pivot_img[1]).rotate(-angle_deg)
        return screen_pivot[0] + vec.x, screen_pivot[1] + vec.y

    def _blit_rotated(self, window, image, pivot_img, screen_pivot, angle_deg):
        w, h = image.get_size()
        rotated = pg.transform.rotate(image, angle_deg)
        offset = pg.math.Vector2(pivot_img[0] - w / 2, pivot_img[1] - h / 2).rotate(-angle_deg)
        center = (screen_pivot[0] - offset.x, screen_pivot[1] - offset.y)
        window.blit(rotated, rotated.get_rect(center=center))

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
        hx, hy = ox + pr["x"], oy + pr["y"]
        speed = math.hypot(pr["vx"], pr["vy"]) or 1.0
        ux, uy = pr["vx"] / speed, pr["vy"] / speed
        length = pr["len"]
        tx, ty = hx - ux * length, hy - uy * length
        size = max(pr["size"], 2)
        pad = int(size + 3)
        minx = min(hx, tx) - pad
        miny = min(hy, ty) - pad
        w = max(int(abs(hx - tx) + 2 * pad), 1)
        h = max(int(abs(hy - ty) + 2 * pad), 1)
        layer = pg.Surface((w, h), pg.SRCALPHA)
        head = (hx - minx, hy - miny)
        tail = (tx - minx, ty - miny)
        rgb = pg.Color(pr["color"])[:3]
        if length > 1:
            pg.draw.line(layer, (*rgb, 90), tail, head, max(int(size * 1.6), 3))
            pg.draw.line(layer, (*rgb, 255), tail, head, max(int(size * 0.7), 2))
        pg.draw.circle(layer, (*rgb, 255), (int(head[0]), int(head[1])), int(size / 2) + 1)
        pg.draw.circle(layer, (*pg.Color(Colors.white)[:3], 235),
                       (int(head[0]), int(head[1])), max(int(size / 3), 1))
        window.blit(layer, (minx, miny))

    def _draw_flash(self, window, p, prog):
        entry = self._weapons.get(p["ent_kind"], {}).get(p["weapon"])
        if entry is None or p["idx"] >= len(entry["flashes"]):
            return
        fl = entry["flashes"][p["idx"]]
        img = fl["img"]
        alpha = int(255 * (1 - prog) ** 0.6)
        if alpha < 255:
            img = img.copy()
            img.set_alpha(max(0, alpha))
        m = (self.rect.x + p["x"], self.rect.y + p["y"])
        self._blit_aimed(window, img, fl["anchor"], m, p["aim"])

    def _draw_hitmark(self, window, x, y, prog):
        alpha = int(255 * (1 - prog))
        if alpha <= 0:
            return
        spread = (5 + 16 * prog) * self.scale
        length = 8 * self.scale
        thick = max(int(3 * self.scale), 2)
        diag = 0.7071
        size = int((spread + length) * 2 + thick * 2)
        layer = pg.Surface((size, size), pg.SRCALPHA)
        c = size / 2
        col = (*pg.Color(Colors.amber_hi)[:3], alpha)
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            inner = (c + dx * spread * diag, c + dy * spread * diag)
            outer = (c + dx * (spread + length) * diag, c + dy * (spread + length) * diag)
            pg.draw.line(layer, col, inner, outer, thick)
        window.blit(layer, (x - c, y - c))

    def _draw_spark(self, window, x, y, p, prog):
        sx = x + p["vx"] * prog
        sy = y + p["vy"] * prog
        alpha = int(255 * (1 - prog))
        size = max(int(5 * self.scale), 2)
        layer = pg.Surface((size, size), pg.SRCALPHA)
        layer.fill((*pg.Color(p.get("color", Colors.amber_hi))[:3], max(0, alpha)))
        window.blit(layer, (sx, sy))

    def _draw_bubble(self, window, ent, now):
        bub = ent.get("bubble")
        if bub is None:
            return
        age = now - bub["start"]
        total = bub["hold"]
        if age >= total:
            ent["bubble"] = None
            return
        if age < 180:
            alpha = age / 180.0
        elif age > total - 240:
            alpha = max(0.0, (total - age) / 240.0)
        else:
            alpha = 1.0
        if bub["who"] == "queen":
            bg, txt, border = Colors.amber, Colors.on_accent, Colors.amber_hi
        else:
            bg, txt, border = Colors.bubble_pawn_bg, Colors.bubble_pawn_text, Colors.border_strong
        text_key = (bub["text"], bub["who"], round(self.scale, 3))
        if bub.get("text_key") != text_key:
            font = get_font(max(int(12 * self.scale), 9), bold=True)
            bub["label"] = font.render(bub["text"], True, pg.Color(txt))
            bub["text_key"] = text_key
        label = bub["label"]
        pad_x, pad_y = int(11 * self.scale), int(6 * self.scale)
        bw = label.get_width() + pad_x * 2
        bh = label.get_height() + pad_y * 2
        ox, oy = self.rect.topleft
        cx = ox + ent["x"]
        by = oy + ent["y"] - ent["head"]
        bx = cx - bw / 2
        bx = max(self.rect.x + 2, min(bx, self.rect.right - bw - 2))
        layer = pg.Surface((bw, bh + int(6 * self.scale)), pg.SRCALPHA)
        pg.draw.rect(layer, pg.Color(bg), pg.Rect(0, 0, bw, bh), border_radius=int(10 * self.scale))
        pg.draw.rect(layer, pg.Color(border), pg.Rect(0, 0, bw, bh), 1,
                     border_radius=int(10 * self.scale))
        tail = int(6 * self.scale)
        tip_x = max(tail, min(bw - tail, cx - bx))
        pg.draw.polygon(layer, pg.Color(bg), [(tip_x - tail, bh), (tip_x + tail, bh),
                                              (tip_x, bh + tail)])
        layer.blit(label, (pad_x, pad_y))
        layer.set_alpha(int(alpha * 255))
        window.blit(layer, (bx, by - bh))

    def _background(self, size):
        if self._bg_cache is not None and self._bg_cache[0] == size:
            return self._bg_cache[1]
        w, h = size
        grad = self._gradient(128, 0.5, 0.18, 1.2, 0.8,
                              Colors.battle_bg_hi, Colors.battle_bg, Colors.battle_bg_edge)
        surf = pg.transform.smoothscale(grad, size)
        step = max(int(64 * self.scale), 32)
        grid = pg.Surface(size, pg.SRCALPHA)
        line = (*pg.Color(Colors.battle_grid)[:3], 6)
        for gx in range(0, w, step):
            pg.draw.line(grid, line, (gx, 0), (gx, h))
        for gy in range(0, h, step):
            pg.draw.line(grid, line, (0, gy), (w, gy))
        surf.blit(grid, (0, 0))
        floor_h = int(h * 0.38)
        floor = pg.Surface((w, floor_h), pg.SRCALPHA)
        fr, fg, fb = pg.Color(Colors.battle_floor)[:3]
        for row in range(floor_h):
            a = int(13 * row / floor_h)
            pg.draw.line(floor, (fr, fg, fb, a), (0, row), (w, row))
        surf.blit(floor, (0, h - floor_h))
        self._bg_cache = (size, surf)
        return surf

    def _scrim(self, size):
        if self._scrim_cache is not None and self._scrim_cache[0] == size:
            return self._scrim_cache[1]
        scrim = self._radial(64, 74, 180, Colors.battle_scrim)
        scrim = pg.transform.smoothscale(scrim, size)
        self._scrim_cache = (size, scrim)
        return scrim

    def _gradient(self, n, cx, cy, rx, ry, c0, c1, c2):
        surf = pg.Surface((n, n))
        col0, col1, col2 = pg.Color(c0), pg.Color(c1), pg.Color(c2)
        for yy in range(n):
            fy = (yy / (n - 1) - cy) / ry
            for xx in range(n):
                fx = (xx / (n - 1) - cx) / rx
                d = min(1.0, math.hypot(fx, fy))
                if d < 0.6:
                    surf.set_at((xx, yy), col0.lerp(col1, d / 0.6))
                else:
                    surf.set_at((xx, yy), col1.lerp(col2, (d - 0.6) / 0.4))
        return surf

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
