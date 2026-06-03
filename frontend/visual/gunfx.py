import json
import math
from dataclasses import dataclass

import pygame as pg

import paths
from frontend.visual.colors import Colors


GUN_DRAW_SPINS_LAND = 5
GUN_LEN_RATIO = 0.62
RECOIL_DEFAULT = 5


@dataclass(frozen=True)
class GunSpec:
    name: str
    scale: float = 1.0
    recoil: float = RECOIL_DEFAULT
    style: str = "bullet"
    speed: float = 1066.0
    size: float = 5.0
    length: float = 12.0
    pellets: int = 1
    spread: float = 0.0
    color: str = Colors.amber_hi


GUNS = {
    "revolver": GunSpec("revolver", scale=0.363, recoil=4, style="bullet",
                        speed=1066, size=5, length=12, color=Colors.amber_hi),
    "lever_action": GunSpec("lever_action", scale=1.0, recoil=7, style="bullet",
                            speed=1170, size=5, length=17, color=Colors.amber_hi),
    "hand_cannon": GunSpec("hand_cannon", scale=0.50, recoil=9, style="slug",
                           speed=780, size=9, length=13, color=Colors.amber),
    "shotgun": GunSpec("shotgun", scale=1.0, recoil=10, style="pellet",
                       speed=936, size=4, length=8, pellets=6, spread=0.16,
                       color=Colors.amber_hi),
    "blunderbuss": GunSpec("blunderbuss", scale=1.0, recoil=12, style="pellet",
                           speed=728, size=4, length=7, pellets=8, spread=0.26,
                           color=Colors.amber_hi),
    "ray_gun": GunSpec("ray_gun", scale=0.33, recoil=4, style="bolt",
                       speed=1300, size=6, length=28, color=Colors.accent),
}

PIECE_GUN = {
    "pawn": "revolver",
    "knight": "hand_cannon",
    "bishop": "lever_action",
    "rook": "shotgun",
    "queen": "blunderbuss",
    "king": "ray_gun",
}


def gun_spec(gun):
    return GUNS.get(gun, GUNS["revolver"])


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def aimed(image, pivot_img, target_img, aim):
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


def blit_rotated(window, image, pivot_img, screen_pivot, angle_deg):
    w, h = image.get_size()
    rotated = pg.transform.rotate(image, angle_deg)
    offset = pg.math.Vector2(pivot_img[0] - w / 2, pivot_img[1] - h / 2).rotate(-angle_deg)
    center = (screen_pivot[0] - offset.x, screen_pivot[1] - offset.y)
    window.blit(rotated, rotated.get_rect(center=center))


def blit_aimed(window, image, pivot_img, screen_pivot, aim):
    image, pivot_img, _, angle_deg = aimed(image, pivot_img, None, aim)
    blit_rotated(window, image, pivot_img, screen_pivot, angle_deg)


def aimed_target(image, pivot_img, target_img, screen_pivot, aim):
    _, pivot_img, target_img, angle_deg = aimed(image, pivot_img, target_img, aim)
    vec = pg.math.Vector2(target_img[0] - pivot_img[0],
                          target_img[1] - pivot_img[1]).rotate(-angle_deg)
    return screen_pivot[0] + vec.x, screen_pivot[1] + vec.y


def draw_flourish(window, gun_img, grip, screen_pivot, aim, p, spins, grow=True):
    gscale = smoothstep(p) if grow else 1.0
    if gscale <= 0.02:
        return
    img = pg.transform.smoothscale(
        gun_img, (max(int(gun_img.get_width() * gscale), 1),
                  max(int(gun_img.get_height() * gscale), 1)))
    scaled_grip = (grip[0] * gscale, grip[1] * gscale)
    img, pivot_img, _, angle_deg = aimed(img, scaled_grip, None, aim)
    spin = spins * 360.0 * (1.0 - p)
    blit_rotated(window, img, pivot_img, screen_pivot, angle_deg - spin)


def draw_flash(window, flash_img, anchor, screen_xy, aim, prog):
    img = flash_img
    alpha = int(255 * (1 - prog) ** 0.6)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(max(0, alpha))
    blit_aimed(window, img, anchor, screen_xy, aim)


def _load_png(*parts):
    try:
        return pg.image.load(
            str(paths.resource_path("assets", "battle_png", *parts))).convert_alpha()
    except (pg.error, FileNotFoundError, OSError):
        return None


def load_battle_art():
    data = {"guns": {}, "flashes": {}}
    try:
        manifest = paths.resource_path("assets", "battle_png", "battle_manifest.json")
        with open(manifest) as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        return data
    for gun, gm in man.get("guns", {}).items():
        img = _load_png("guns", f"{gun}.png")
        if img is not None:
            data["guns"][gun] = {"img": img, "ax": gm["ax"], "ay": gm["ay"],
                                 "gx": gm["gx"], "gy": gm["gy"]}
    for gun, variants in man.get("flashes", {}).items():
        flashes = []
        for i, fm in enumerate(variants):
            img = _load_png("flashes", f"flashes_{gun}", f"flash_{i + 1}.png")
            if img is not None:
                flashes.append({"img": img, "ax": fm["ax"], "ay": fm["ay"]})
        if flashes:
            data["flashes"][gun] = flashes
    return data


def scale_image(img, f):
    return pg.transform.smoothscale(
        img, (max(int(img.get_width() * f), 1), max(int(img.get_height() * f), 1)))


def gun_base_distance(art, gun):
    g = art["guns"].get(gun)
    if g is None:
        return 1.0
    return math.hypot(g["ax"] - g["gx"], g["ay"] - g["gy"]) or 1.0


def weapon_scale(art, gun, reach):
    base = gun_base_distance(art, gun)
    return reach / base * gun_spec(gun).scale if base else 1.0


def build_weapon(art, gun, reach):
    g = art["guns"].get(gun)
    if g is None:
        return None
    f = weapon_scale(art, gun, reach)
    return {
        "gun": scale_image(g["img"], f),
        "grip": (g["gx"] * f, g["gy"] * f),
        "barrel": (g["ax"] * f, g["ay"] * f),
        "scale": f,
        "flashes": [{"img": scale_image(fl["img"], f), "anchor": (fl["ax"] * f, fl["ay"] * f)}
                    for fl in art["flashes"].get(gun, [])],
    }
