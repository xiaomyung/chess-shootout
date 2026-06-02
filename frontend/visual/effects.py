import math
import random

import pygame as pg

from frontend.visual import gunfx
from frontend.visual.colors import Colors


DRAW_MS = 240
AIM_MS = 110
MUZZLE_MS = 220
IMPACT_MS = 360
BLOOD_MS = 700
HOLE_IN_MS = 160
HOLE_HOLD_MS = 1100
HOLE_FADE_MS = 700
RAGDOLL_MS = 900
SHAKE_HARD_MS = 420
SHAKE_SOFT_MS = 260
SPARK_MS = (300, 600)
SMOKE_MS = (700, 1100)
CHECK_DROP_MS = 3000
RECOIL_MS = 180

SPARK_COUNT = 10
SPARK_COUNT_RM = 4
SMOKE_PUFFS = 3

SHAKE_AMP = {"hard": 18, "med": 11, "soft": 6}
INTENSITY_SCALE = {"subtle": 0.34, "balanced": 0.67, "full": 1.0}

PIECE_GUN = {
    "pawn": "revolver",
    "knight": "hand_cannon",
    "bishop": "lever_action",
    "rook": "shotgun",
    "queen": "blunderbuss",
    "king": "ray_gun",
}


class EffectManager:

    def __init__(self, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.geom = None
        self._art = None
        self._weapon_cache = {}
        self.particles = []
        self.holes = []
        self.captures = []
        self.drops = []
        self._check_gun = None
        self.reduce_motion = False
        self.intensity = "full"
        self._shake = None

    def configure(self, reduce_motion, intensity):
        self.reduce_motion = bool(reduce_motion)
        self.intensity = intensity if intensity in INTENSITY_SCALE else "full"

    def _ensure_art(self):
        if self._art is None:
            self._art = gunfx.load_battle_art()
        return self._art

    def has_art(self):
        return bool(self._ensure_art()["guns"])

    def clear(self):
        self.particles = []
        self.holes = []
        self.captures = []
        self.drops = []
        self._check_gun = None
        self._shake = None

    def cut(self, now=None):
        if self._check_gun is not None and now is not None:
            self._release_check_gun(now)
        self._check_gun = None
        self.captures = []
        self.particles = []
        self._shake = None

    def held_squares(self):
        return {c["to_sq"] for c in self.captures}

    def busy(self):
        return bool(self.captures or self.particles or self.holes
                    or self.drops or self._check_gun)

    def _rnd(self, lo, hi):
        return lo + self.rng.random() * (hi - lo)

    def _count(self, n):
        return max(1, int(round(n * INTENSITY_SCALE[self.intensity])))

    def _center(self, sq):
        return self.geom(sq)

    def _aim(self, from_sq, victim_sq):
        fx, fy = self._center(from_sq)
        tx, ty = self._center(victim_sq)
        return math.atan2(ty - fy, tx - fx)

    def _pivot(self, from_sq, cell):
        cx, cy = self._center(from_sq)
        return (cx, cy - cell * 0.05)

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

    def capture(self, *, now_ms, attacker_type, attacker_surface, victim_surface,
                from_sq, victim_sq, to_sq, cell_size, power="med",
                on_fire=None, on_slide=None):
        gun = PIECE_GUN.get(attacker_type, "revolver")
        weapon = self._weapon(gun, cell_size)
        if self.reduce_motion or weapon is None:
            self._impact(now_ms, from_sq, victim_sq, victim_surface, cell_size)
            if on_fire is not None:
                on_fire()
            if on_slide is not None:
                on_slide()
            return
        fire_at = now_ms + DRAW_MS + AIM_MS
        fx, fy = self.geom(from_sq)
        tx, ty = self.geom(victim_sq)
        travel = max(90, min(int(math.hypot(tx - fx, ty - fy) * 0.85), 300))
        self.captures.append({
            "start": now_ms, "fire_at": fire_at, "impact_at": fire_at + travel,
            "fired": False, "gun": gun, "weapon": weapon,
            "from_sq": from_sq, "victim_sq": victim_sq, "to_sq": to_sq,
            "attacker": attacker_surface, "victim": victim_surface,
            "cell": cell_size, "power": power, "on_fire": on_fire, "on_slide": on_slide,
        })

    def check(self, *, now_ms, attacker_type, king_sq, from_sq, cell_size):
        gun = PIECE_GUN.get(attacker_type, "revolver")
        weapon = self._weapon(gun, cell_size)
        if weapon is None or self.reduce_motion:
            return
        if self._check_gun is not None:
            self._release_check_gun(now_ms)
        self._check_gun = {"weapon": weapon, "from_sq": from_sq, "victim_sq": king_sq,
                           "cell": cell_size, "start": now_ms}

    def _release_check_gun(self, now):
        g = self._check_gun
        if g is None:
            return
        self.drops.append({
            "img": g["weapon"]["gun"], "from_sq": g["from_sq"], "cell": g["cell"],
            "vx": self._rnd(-0.8, 0.8), "spin": self._rnd(-320, 320),
            "fall": g["cell"] * 1.4, "start": now, "dur": CHECK_DROP_MS})
        self._check_gun = None

    def _shoot(self, now, c):
        weapon = c["weapon"]
        if weapon["flashes"]:
            self.particles.append({"kind": "flash", "weapon": weapon, "gun": c["gun"],
                                   "idx": int(self.rng.random() * len(weapon["flashes"])),
                                   "from_sq": c["from_sq"], "victim_sq": c["victim_sq"],
                                   "cell": c["cell"], "start": now, "dur": MUZZLE_MS})
        self.particles.append({"kind": "projectile", "gun": c["gun"], "weapon": weapon,
                               "from_sq": c["from_sq"], "victim_sq": c["victim_sq"],
                               "cell": c["cell"], "start": now,
                               "dur": max(c["impact_at"] - now, 1)})
        self._trigger_shake(now, c["power"])

    def _impact(self, now, from_sq, victim_sq, victim, cell):
        self.particles.append({"kind": "impact", "victim_sq": victim_sq, "cell": cell,
                               "start": now, "dur": IMPACT_MS})
        self.particles.append({"kind": "blood", "victim_sq": victim_sq, "cell": cell,
                               "start": now, "dur": BLOOD_MS})
        self.holes.append({"victim_sq": victim_sq, "cell": cell, "start": now,
                           "dur": HOLE_IN_MS + HOLE_HOLD_MS + HOLE_FADE_MS})
        spark_n = SPARK_COUNT_RM if self.reduce_motion else self._count(SPARK_COUNT)
        spark_size = max(int(cell * 0.06), 3)
        for _ in range(spark_n):
            self.particles.append({
                "kind": "spark", "victim_sq": victim_sq, "ang": self._rnd(0, math.tau),
                "dist": self._rnd(20, 70) * cell / 80.0, "size": spark_size,
                "start": now, "dur": self._rnd(*SPARK_MS)})
        if not self.reduce_motion:
            for _ in range(SMOKE_PUFFS):
                self.particles.append({
                    "kind": "smoke", "victim_sq": victim_sq,
                    "jx": self._rnd(-8, 8), "jy": self._rnd(-8, 8),
                    "cell": cell, "start": now, "dur": self._rnd(*SMOKE_MS)})
            if victim is not None:
                aim = self._aim(from_sq, victim_sq)
                self.particles.append({
                    "kind": "ragdoll", "surf": victim, "victim_sq": victim_sq,
                    "dir": 1 if math.cos(aim) >= 0 else -1,
                    "start": now, "dur": RAGDOLL_MS})

    def _trigger_shake(self, now, power):
        if self.reduce_motion:
            return
        amp = SHAKE_AMP.get(power, 5) * INTENSITY_SCALE[self.intensity]
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
        for c in list(self.captures):
            if not c["fired"] and now >= c["fire_at"]:
                self._shoot(now, c)
                c["fired"] = True
                if c["on_fire"] is not None:
                    c["on_fire"]()
            if c["fired"] and now >= c["impact_at"]:
                self._impact(now, c["from_sq"], c["victim_sq"], c["victim"], c["cell"])
                if c["on_slide"] is not None:
                    c["on_slide"]()
                self.captures.remove(c)
        self.particles = [p for p in self.particles if now < p["start"] + p["dur"]]
        self.holes = [h for h in self.holes if now < h["start"] + h["dur"]]
        self.drops = [d for d in self.drops if now < d["start"] + d["dur"]]

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
        for p in self.particles:
            self._draw_particle(window, p, now)
        for d in self.drops:
            self._draw_gun_drop(window, d, now)
        self._draw_held_gun(window, now)

    def _draw_capture(self, window, c, now):
        fx, fy = self._center(c["from_sq"])
        tx, ty = self._center(c["victim_sq"])
        if c["victim"] is not None:
            window.blit(c["victim"], c["victim"].get_rect(center=(tx, ty)))
        if c["attacker"] is not None:
            window.blit(c["attacker"], c["attacker"].get_rect(center=(fx, fy)))
        weapon = c["weapon"]
        aim = math.atan2(ty - fy, tx - fx)
        pivot = (fx, fy - c["cell"] * 0.05)
        t = now - c["start"]
        if t < DRAW_MS:
            gunfx.draw_flourish(window, weapon["gun"], weapon["grip"], pivot, aim,
                                t / DRAW_MS, gunfx.GUN_DRAW_SPINS_LAND)
        else:
            if c["fired"]:
                rx, ry = self._recoil(c["gun"], weapon, aim, now - c["fire_at"])
                pivot = (pivot[0] + rx, pivot[1] + ry)
            gunfx.blit_aimed(window, weapon["gun"], weapon["grip"], pivot, aim)

    def _recoil(self, gun, weapon, aim, elapsed):
        if elapsed < 0 or elapsed >= RECOIL_MS:
            return 0.0, 0.0
        r = (gunfx.gun_spec(gun).recoil * weapon["scale"]
             * (1.0 - gunfx.smoothstep(elapsed / RECOIL_MS)))
        return -math.cos(aim) * r, -math.sin(aim) * r

    def _draw_particle(self, window, p, now):
        kind = p["kind"]
        if kind == "flash":
            self._draw_flash(window, p, now)
        elif kind == "projectile":
            self._draw_projectile(window, p, now)
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

    def _draw_projectile(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        muzzle, _ = self._muzzle(p["weapon"], p["from_sq"], p["victim_sq"], p["cell"])
        tx, ty = self._center(p["victim_sq"])
        hx = muzzle[0] + (tx - muzzle[0]) * prog
        hy = muzzle[1] + (ty - muzzle[1]) * prog
        dx, dy = tx - muzzle[0], ty - muzzle[1]
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist
        spec = gunfx.gun_spec(p["gun"])
        f = p["cell"] / 104.0
        length = max(spec.length * f, 6)
        size = max(spec.size * f, 2)
        bx, by = hx - ux * length, hy - uy * length
        rgb = pg.Color(spec.color)[:3]
        pad = int(size + 4)
        minx, miny = min(hx, bx) - pad, min(hy, by) - pad
        w = max(int(abs(hx - bx) + 2 * pad), 1)
        h = max(int(abs(hy - by) + 2 * pad), 1)
        layer = pg.Surface((w, h), pg.SRCALPHA)
        head = (hx - minx, hy - miny)
        tail = (bx - minx, by - miny)
        pg.draw.line(layer, (*rgb, 90), tail, head, max(int(size * 1.6), 3))
        pg.draw.line(layer, (*rgb, 255), tail, head, max(int(size * 0.7), 2))
        pg.draw.circle(layer, (*rgb, 255), (int(head[0]), int(head[1])), int(size / 2) + 1)
        pg.draw.circle(layer, (255, 255, 255, 235), (int(head[0]), int(head[1])),
                       max(int(size / 3), 1))
        window.blit(layer, (minx, miny))

    def _draw_impact(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        d = p["cell"] * 0.8 * (0.2 + 1.4 * prog)
        r = int(d / 2)
        if r < 1:
            return
        alpha = int(230 * (1 - prog))
        layer = pg.Surface((2 * r + 8, 2 * r + 8), pg.SRCALPHA)
        pg.draw.circle(layer, (*pg.Color(Colors.amber_hi)[:3], alpha), (r + 4, r + 4), r,
                       max(int(p["cell"] * 0.045), 2))
        cx, cy = self._center(p["victim_sq"])
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
        layer = pg.Surface((2 * r + 2, 2 * r + 2), pg.SRCALPHA)
        pg.draw.circle(layer, (*pg.Color(Colors.blood)[:3], alpha), (r + 1, r + 1), r)
        pg.draw.circle(layer, (*pg.Color(Colors.blood_dark)[:3], alpha), (r + 1, r + 1),
                       int(r * 0.6))
        cx, cy = self._center(p["victim_sq"])
        window.blit(layer, (cx - r - 1, cy - r - 1))

    def _draw_spark(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        cx, cy = self._center(p["victim_sq"])
        dist = p["dist"] * prog
        x = cx + math.cos(p["ang"]) * dist
        y = cy + math.sin(p["ang"]) * dist + 6 * prog
        alpha = int(255 * (1 - prog))
        s = p["size"]
        surf = pg.Surface((s, s), pg.SRCALPHA)
        surf.fill((*pg.Color(Colors.amber_hi)[:3], alpha))
        window.blit(surf, (x - s / 2, y - s / 2))

    def _draw_smoke(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        r = int(p["cell"] * 0.5 * (0.4 + prog) / 2)
        if r < 1:
            return
        alpha = int(130 * (1 - prog))
        layer = pg.Surface((2 * r, 2 * r), pg.SRCALPHA)
        pg.draw.circle(layer, (*pg.Color(Colors.smoke)[:3], alpha), (r, r), r)
        cx, cy = self._center(p["victim_sq"])
        window.blit(layer, (cx + p["jx"] - r, cy + p["jy"] - p["cell"] * 0.9 * prog - r))

    def _draw_ragdoll(self, window, p, now):
        prog = (now - p["start"]) / p["dur"]
        if not 0.0 <= prog < 1.0:
            return
        d = p["dir"]
        w = p["surf"].get_width()
        if prog < 0.45:
            t = prog / 0.45
            tx, ty, rot, alpha, scl = d * 1.6 * w * t, -0.65 * w * t, d * 120 * t, 255, 1.0
        else:
            t = (prog - 0.45) / 0.55
            tx = d * w * (1.6 + 1.2 * t)
            ty = w * (-0.65 + 2.65 * t)
            rot = d * (120 + 420 * t)
            alpha = int(255 * (1 - t))
            scl = 1.0 - 0.3 * t
        img = pg.transform.rotozoom(p["surf"], rot, max(scl, 0.1))
        if alpha < 255:
            img = img.copy()
            img.fill((255, 255, 255, max(alpha, 0)), special_flags=pg.BLEND_RGBA_MULT)
        cx, cy = self._center(p["victim_sq"])
        window.blit(img, img.get_rect(center=(cx + tx, cy + ty)))

    def _draw_held_gun(self, window, now):
        g = self._check_gun
        if g is None:
            return
        t = now - g["start"]
        weapon = g["weapon"]
        fx, fy = self._center(g["from_sq"])
        aim = self._aim(g["from_sq"], g["victim_sq"])
        pivot = (fx, fy - g["cell"] * 0.05)
        if t < DRAW_MS:
            gunfx.draw_flourish(window, weapon["gun"], weapon["grip"], pivot, aim,
                                t / DRAW_MS, gunfx.GUN_DRAW_SPINS_LAND)
        else:
            gunfx.blit_aimed(window, weapon["gun"], weapon["grip"], pivot, aim)

    @staticmethod
    def _drop_state(d, bx, by, t):
        tm = min(t * 4.0, 1.0)
        cell = d["cell"]
        x = bx + d["vx"] * cell * tm
        y = (by - cell * 0.05) - cell * 0.25 * tm + d["fall"] * (tm * tm)
        return x, y, d["spin"] * tm, int(255 * (1.0 - t))

    def _draw_gun_drop(self, window, d, now):
        t = (now - d["start"]) / d["dur"]
        if not 0.0 <= t < 1.0:
            return
        bx, by = self._center(d["from_sq"])
        x, y, angle, alpha = self._drop_state(d, bx, by, t)
        img = pg.transform.rotozoom(d["img"], angle, 1.0).copy()
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
        layer = pg.Surface((2 * r + 4, 2 * r + 4), pg.SRCALPHA)
        pg.draw.circle(layer, (7, 9, 12, max(alpha, 0)), (r + 2, r + 2), r)
        cx, cy = self._center(h["victim_sq"])
        window.blit(layer, (cx - r - 2, cy - r - 2))
