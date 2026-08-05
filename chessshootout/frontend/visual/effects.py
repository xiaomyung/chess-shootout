import math
import random

import pygame as pg

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


def _impact_ring_sprite(r, stroke):
    def build():
        layer = pg.Surface((2 * r + 8, 2 * r + 8), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.amber_hi), (r + 4, r + 4), r, stroke)
        return layer
    return cache.memoized_surface(_IMPACT_RING_CACHE, (r, stroke), build)


def _blood_sprite(r):
    def build():
        layer = pg.Surface((2 * r + 2, 2 * r + 2), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.blood), (r + 1, r + 1), r)
        pg.draw.circle(layer, pg.Color(Colors.blood_dark), (r + 1, r + 1), int(r * 0.6))
        return layer
    return cache.memoized_surface(_BLOOD_CACHE, r, build)


def _spark_sprite(size):
    def build():
        surf = pg.Surface((size, size), pg.SRCALPHA)
        surf.fill(pg.Color(Colors.amber_hi))
        return surf
    return cache.memoized_surface(_SPARK_CACHE, size, build)


def _smoke_sprite(r):
    def build():
        layer = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.smoke), (r, r), r)
        return layer
    return cache.memoized_surface(_SMOKE_CACHE, r, build)


def _hole_sprite(r):
    def build():
        layer = pg.Surface((2 * r + 4, 2 * r + 4), pg.SRCALPHA)
        pg.draw.circle(layer, pg.Color(Colors.bullet_hole), (r + 2, r + 2), r)
        return layer
    return cache.memoized_surface(_HOLE_CACHE, r, build)


def _takeover_bg_sprite(w, h):
    def build():
        surf = pg.Surface((w, h))
        surf.fill(pg.Color(Colors.takeover_bg))
        return surf
    return cache.memoized_surface(_TAKEOVER_BG_CACHE, (w, h), build)


class EffectManager:

    def __init__(self, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.geom = None
        self._art = None
        self._weapon_cache = {}
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
        self._last_now = None
        self.board_rect = None
        self._streak_color = None
        self._streak_count = 0
        self._first_blood_spent = False
        self._shake = None

    def _ensure_art(self):
        if self._art is None:
            self._art = gunfx.load_battle_art()
        return self._art

    def clear_transients(self):
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

    def clear(self):
        self.clear_transients()
        self._first_blood_spent = False

    def cut(self, now=None):
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

    def is_active(self):
        return bool(
            self.particles or self.holes or self.captures or self.projectiles
            or self.drops or self.callouts or self.flags or self._piece_shakes
            or self._bystanders or self._takeover is not None
            or self._check_gun is not None or self._whack_gun is not None
            or self._king_shake is not None or self._shake is not None)

    def held_squares(self):
        return {c["to_sq"] for c in self.captures if not c.get("miss")}

    def _rnd(self, lo, hi):
        return lo + self.rng.random() * (hi - lo)

    def _pick(self, seq):
        return seq[int(self.rng.random() * len(seq))]

    def _center(self, sq):
        return self.geom(sq)

    def _anchor(self, p):
        if "px" in p:
            return p["px"]
        return self._center(p["victim_sq"])

    @staticmethod
    def _angle_to(origin, target):
        return math.atan2(target[1] - origin[1], target[0] - origin[0])

    def _aim(self, from_sq, victim_sq):
        return self._angle_to(self._center(from_sq), self._center(victim_sq))

    def _pivot(self, from_sq, cell):
        cx, cy = self._center(from_sq)
        return (cx, cy - cell * GUN_PIVOT_RISE_FRAC)

    def _muzzle(self, weapon, from_sq, victim_sq, cell):
        aim = self._aim(from_sq, victim_sq)
        pivot = self._pivot(from_sq, cell)
        muzzle = gunfx.aimed_target(weapon["gun"], weapon["grip"], weapon["barrel"], pivot, aim)
        return muzzle, aim

    def _weapon(self, gun, cell):
        key = (gun, cell)
        if key not in self._weapon_cache:
            art = self._ensure_art()
            self._weapon_cache[key] = gunfx.build_weapon(art, gun, cell * gunfx.GUN_LEN_RATIO)
        return self._weapon_cache[key]

    def clear_weapon_cache(self):
        self._weapon_cache.clear()

    def capture(self, *, now_ms, attacker_type, attacker_surface, victim_surface,
                from_sq, victim_sq, to_sq, cell_size, power="med",
                on_fire=None, on_slide=None, occupied=None, predrawn=False):
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

    def miss(self, *, now_ms, attacker_type, from_sq, victim_sq, cell_size,
             power="med", on_fire=None, occupied=None, callout=True):
        handed = self.take_gun_handoff(from_sq)
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")
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

    def swear(self, now_ms, victim_sq, cell, text=None):
        self._tag(now_ms, text or self._pick(SWEAR_WORDS), victim_sq, cell)

    def _skill_issue_callout(self, now, cell):
        self._callout(now, SKILL_ISSUE_TITLE, SKILL_ISSUE_SUB, "xl", cell,
                      Colors.loss, Colors.loss_glow)

    def check(self, *, now_ms, attacker_type, king_sq, from_sq, cell_size):
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

    def piece_offset(self, sq, now):
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
    def _jitter(shake, now):
        t = (now - shake["start"]) / shake["dur"]
        if not 0.0 <= t < 1.0:
            return (0, 0)
        amp = shake["amp"] * (1.0 - t)
        return (int(round(math.sin(t * math.tau * 2.5) * amp)), 0)

    def _release_check_gun(self, now):
        g = self._check_gun
        if g is None:
            return
        self._drop_gun(g["weapon"]["gun"], g["from_sq"], g["cell"], now)
        self._check_gun = None

    def _drop_gun(self, img, from_sq, cell, now):
        self.drops.append({
            "img": img, "from_sq": from_sq, "cell": cell,
            "vx": self._rnd(-0.8, 0.8), "spin": self._rnd(-320, 320),
            "fall": cell * GUN_DROP_FALL_FRAC, "start": now, "dur": CHECK_DROP_MS})

    def hold_gun_px(self, *, now_ms, attacker_type, from_sq, cell_size, target_px=None):
        gun = gunfx.PIECE_GUN.get(attacker_type, "revolver")
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

    def has_gun_px(self):
        return self._whack_gun is not None

    def aim_gun_px(self, target_px, now_ms):
        g = self._whack_gun
        if g is None or target_px is None:
            return
        dt = max(0.0, min(DT_MAX, (now_ms - g["last"]) / 1000.0))
        g["last"] = now_ms
        want = self._angle_to(self._pivot(g["from_sq"], g["cell"]), target_px)
        delta = (want - g["aim"] + math.pi) % (2 * math.pi) - math.pi
        g["aim"] += delta * min(1.0, dt * GUN_PX_AIM_RATE)

    def release_gun_px(self, now_ms):
        g = self._whack_gun
        if g is None:
            return
        self._drop_gun(g["weapon"]["gun"], g["from_sq"], g["cell"], now_ms)
        self._whack_gun = None

    def hand_off_gun_px(self):
        g = self._whack_gun
        if g is None:
            return
        self._gun_handoff = g["from_sq"]
        self._whack_gun = None

    def take_gun_handoff(self, from_sq):
        handed = self._gun_handoff == from_sq
        self._gun_handoff = None
        return handed

    def fire_gun_px(self, now_ms, target_px):
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

    def _muzzle_flash_px(self, now, g, muzzle):
        weapon = g["weapon"]
        if not weapon["flashes"]:
            return
        self.particles.append({"kind": "flash_px", "weapon": weapon, "gun": g["gun"],
                               "idx": int(self.rng.random() * len(weapon["flashes"])),
                               "muzzle": muzzle, "aim": g["aim"],
                               "start": now, "dur": MUZZLE_MS})

    def register_kill(self, color, victim_sq, cell, now_ms, px=None):
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

    def _callout(self, now, text, sub, size, cell, fill, glow):
        size_px = max(int(cell * (1.9 if size == "xl" else 1.3)), 24)
        surf = self._build_callout_surface(text, sub, size_px, fill, glow)
        surf = pg.transform.rotozoom(surf, CALLOUT_ROTATION_DEG, 1.0)
        dur = CALLOUT_XL_MS if size == "xl" else CALLOUT_LG_MS
        self.callouts = [{"surf": surf, "start": now, "dur": dur}]

    def _tag(self, now, text, victim_sq, cell, px=None, fill=None, glow=None):
        size_px = max(int(cell * 0.45), 12)
        surf, _ = self._build_text_fx(text, size_px, fill or Colors.amber_hi,
                                      Colors.tag_stroke, glow or Colors.amber_glow)
        surf = pg.transform.rotozoom(surf, TAG_ROTATION_DEG, 1.0)
        particle = {"kind": "tag", "surf": surf, "victim_sq": victim_sq,
                    "cell": cell, "start": now, "dur": TAG_MS}
        if px is not None:
            particle["px"] = px
        self.particles.append(particle)

    def taunt_tag(self, now_ms, text, victim_sq, cell):
        self._tag(now_ms, text, victim_sq, cell, fill=Colors.loss, glow=Colors.loss_glow)

    def raise_flag(self, sq, cell, now_ms):
        self.flags = [{"sq": sq, "cell": cell, "start": now_ms}]

    def start_takeover(self, reason, winner_label, now_ms):
        self._takeover = {"reason": reason, "winner": winner_label, "start": now_ms, "wh": None}

    def has_takeover(self):
        return self._takeover is not None

    def clear_takeover(self):
        self._takeover = None

    def _shoot(self, now, c):
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

    def _spawn_pellets(self, now, c):
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
    def _pellet_speed(muzzle, target, travel_ms):
        dist = math.hypot(target[0] - muzzle[0], target[1] - muzzle[1]) or 1.0
        return dist / (travel_ms / 1000.0)

    def _push_pellet(self, now, spec, muzzle, ang, speed, cell, *, lead=False,
                     capture=None, inert=False, max_ms=PROJECTILE_MAX_MS):
        f = cell / PROJECTILE_REF_CELL
        self.projectiles.append({
            "x": muzzle[0], "y": muzzle[1],
            "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed,
            "color": spec.color, "size": max(spec.size * f, 2),
            "len": max(spec.length * f, 6), "cell": cell,
            "lead": lead, "capture": capture, "inert": inert,
            "born": now, "max_ms": max_ms})

    def _miss_point(self, muzzle, tx, ty, cell):
        aim = self._angle_to(muzzle, (tx, ty))
        side = 1 if self.rng.random() < 0.5 else -1
        perp = aim + math.pi / 2.0
        off = cell * self._rnd(1.0, 1.6) * side
        along = cell * self._rnd(-0.3, 0.6)
        return (tx + math.cos(perp) * off + math.cos(aim) * along,
                ty + math.sin(perp) * off + math.sin(aim) * along)

    def _impact_package(self, now, anchor, cell):
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

    def impact_px(self, now_ms, px, cell):
        self._impact_package(now_ms, {"px": px}, cell)

    def _impact(self, now, from_sq, victim_sq, victim, cell):
        self._impact_package(now, {"victim_sq": victim_sq}, cell)
        if victim is not None:
            aim = self._aim(from_sq, victim_sq)
            self.particles.append({
                "kind": "ragdoll", "surf": victim, "victim_sq": victim_sq,
                "dir": 1 if math.cos(aim) >= 0 else -1,
                "start": now, "dur": RAGDOLL_MS})

    def trigger_shake(self, now, power):
        amp = SHAKE_AMP.get(power, 5)
        dur = SHAKE_HARD_MS if power == "hard" else SHAKE_SOFT_MS
        self._shake = {"start": now, "dur": dur, "amp": amp,
                       "seed": int(self.rng.random() * 1_000_000)}

    def shake_offset(self, now):
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

    def update(self, now):
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

    def _update_projectiles(self, now, dt):
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

    def _pellet_hits_square(self, pr, sq):
        cx, cy = self._center(sq)
        half = pr["cell"] / 2.0
        return abs(pr["x"] - cx) <= half and abs(pr["y"] - cy) <= half

    def _stray_target(self, pr):
        for sq in self._bystanders:
            if self._pellet_hits_square(pr, sq):
                return sq
        return None

    def _off_board(self, pr):
        r = self.board_rect
        if r is None:
            return False
        m = pr["cell"]
        return (pr["x"] < r.x - m or pr["x"] > r.right + m
                or pr["y"] < r.y - m or pr["y"] > r.bottom + m)

    def _resolve_capture(self, now, c):
        if not c.get("advance_only"):
            self._impact(now, c["from_sq"], c["victim_sq"], c["victim"], c["cell"])
        if c["on_slide"] is not None:
            c["on_slide"]()
        if c in self.captures:
            self.captures.remove(c)

    def _wound(self, now, sq, cell):
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

    def draw_holes(self, window, now):
        if self.geom is None:
            return
        for h in self.holes:
            self._draw_hole(window, h, now)

    def draw_over(self, window, now):
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

    def _draw_capture(self, window, c, now):
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

    def _recoil(self, gun, weapon, aim, elapsed):
        if elapsed < 0 or elapsed >= RECOIL_MS:
            return 0.0, 0.0
        r = (gunfx.gun_spec(gun).recoil * weapon["scale"]
             * (1.0 - smoothstep(elapsed / RECOIL_MS)))
        return -math.cos(aim) * r, -math.sin(aim) * r

    def _draw_particle(self, window, p, now):
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

    def _draw_flash(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        weapon = p["weapon"]
        if not weapon["flashes"]:
            return
        fl = weapon["flashes"][min(p["idx"], len(weapon["flashes"]) - 1)]
        muzzle, aim = self._muzzle(weapon, p["from_sq"], p["victim_sq"], p["cell"])
        rx, ry = self._recoil(p["gun"], weapon, aim, now - p["start"])
        gunfx.draw_flash(window, fl["img"], fl["anchor"], (muzzle[0] + rx, muzzle[1] + ry),
                         aim, prog)

    def _draw_flash_px(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        weapon = p["weapon"]
        fl = weapon["flashes"][min(p["idx"], len(weapon["flashes"]) - 1)]
        aim = p["aim"]
        rx, ry = self._recoil(p["gun"], weapon, aim, now - p["start"])
        gunfx.draw_flash(window, fl["img"], fl["anchor"],
                         (p["muzzle"][0] + rx, p["muzzle"][1] + ry), aim, prog)

    def _draw_pellet(self, window, pr):
        speed = math.hypot(pr["vx"], pr["vy"]) or 1.0
        gunfx.draw_bullet(window, (pr["x"], pr["y"]), pr["vx"] / speed, pr["vy"] / speed,
                          pr["color"], pr["size"], pr["len"])

    def _draw_impact(self, window, p, now):
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

    def _draw_blood(self, window, p, now):
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

    def _draw_spark(self, window, p, now):
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

    def _draw_smoke(self, window, p, now):
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

    def _draw_ragdoll(self, window, p, now):
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

    def _draw_held_gun(self, window, now):
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

    def _draw_gun_px(self, window, now):
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
    def _drop_state(d, bx, by, t):
        tm = min(t * 4.0, 1.0)
        cell = d["cell"]
        x = bx + d["vx"] * cell * tm
        y = (by - cell * GUN_PIVOT_RISE_FRAC) - cell * 0.25 * tm + d["fall"] * (tm * tm)
        return x, y, d["spin"] * tm, int(255 * (1.0 - t))

    def _draw_gun_drop(self, window, d, now):
        t = (now - d["start"]) / d["dur"]
        if not 0.0 <= t < 1.0:
            return
        bx, by = self._center(d["from_sq"])
        x, y, angle, alpha = self._drop_state(d, bx, by, t)
        img = pg.transform.rotozoom(d["img"], angle, 1.0)
        img.set_alpha(alpha)
        window.blit(img, img.get_rect(center=(x, y)))

    def _draw_hole(self, window, h, now):
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
    def _build_text_fx(text, size_px, fill, stroke, glow):
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

    def _build_callout_surface(self, text, sub, size_px, fill, glow):
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
    def _callout_anim(prog):
        if prog < 0.12:
            f = prog / 0.12
            return 0.5 + 0.56 * f, int(255 * f)
        if prog < 0.78:
            f = (prog - 0.12) / 0.66
            return 1.06 - 0.06 * f, 255
        f = (prog - 0.78) / 0.22
        return 1.0 + 0.02 * f, int(255 * (1 - f))

    def _draw_callout(self, window, c, now):
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
    def _tag_anim(prog):
        if prog < 0.25:
            f = prog / 0.25
            return 0.65 * f, 0.4 + 0.7 * f, int(255 * f)
        f = (prog - 0.25) / 0.75
        return 0.65 + 0.35 * f, 1.1 - 0.1 * f, int(255 * (1 - f))

    def _draw_tag(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        rise, scale, alpha = self._tag_anim(prog)
        img = pg.transform.smoothscale_by(p["surf"], scale)
        img.set_alpha(max(alpha, 0))
        cx, cy = self._anchor(p)
        window.blit(img, img.get_rect(center=(cx, cy - rise * p["cell"] * 0.8)))

    @staticmethod
    def _pop(x):
        x = max(0.0, min(1.0, x)) - 1.0
        return 1 + (BACK_OVERSHOOT + 1) * x ** 3 + BACK_OVERSHOOT * x ** 2

    def _draw_flag(self, window, f, now):
        surf = emoji_surface(SURRENDER_FLAG, max(int(f["cell"] * 0.6), 8))
        if surf is None:
            return
        t = (now - f["start"]) / FLAG_POP_MS
        if t < 1.0:
            surf = pg.transform.rotozoom(surf, 0.0, max(self._pop(t), 0.05))
        cx, cy = self._center(f["sq"])
        window.blit(surf, surf.get_rect(center=(cx + f["cell"] * 0.3, cy - f["cell"] * 0.3)))

    @staticmethod
    def _takeover_bar(width, height):
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

    def _build_takeover_surfaces(self, tk, w, h):
        main_size = max(int(h * 0.22), 36)
        tk["main"], _ = self._build_text_fx(tk["reason"], main_size, Colors.text,
                                            Colors.outcome_stroke, Colors.accent_glow)
        sub_font = get_font(max(int(h * 0.042), 16), bold=True, family=SANS)
        tk["sub"] = sub_font.render((tk["winner"] + " WINS").upper(), True,
                                    pg.Color(Colors.amber_hi))
        tk["bar"] = self._takeover_bar(int(w * 0.86), max(int(h * 0.013), 4))
        tk["wh"] = (w, h)

    @staticmethod
    def _blit_alpha(window, surf, topleft, alpha):
        if alpha <= 0:
            return
        if alpha >= 255:
            window.blit(surf, topleft)
            return
        img = surf.copy()
        img.fill((255, 255, 255, alpha), special_flags=pg.BLEND_RGBA_MULT)
        window.blit(img, topleft)

    def draw_takeover(self, window, now):
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
