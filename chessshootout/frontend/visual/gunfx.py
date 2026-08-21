import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pygame as pg

from chessshootout import paths
from chessshootout.frontend.visual import cache
from chessshootout.frontend.visual.colors import Colors
from chessshootout.frontend.visual.draw import smoothstep


GUN_DRAW_SPINS_LAND = 5
GUN_LEN_RATIO = 0.62
RECOIL_DEFAULT = 5
RAGDOLL_MS = 900
DT_MAX = 0.05


@dataclass(frozen=True)
class GunSpec:
    """
    The feel of one gun: how large it draws, how hard it kicks, and what its
    shots look like and how widely they scatter. Frozen on purpose -- the
    table below is a read-only registry shared by the board fight, the menu
    battle and the skill-check overlays
    """

    scale: float = 1.0
    recoil: float = RECOIL_DEFAULT
    speed: float = 1066.0
    size: float = 5.0
    length: float = 12.0
    pellets: int = 1
    spread: float = 0.0
    color: str = Colors.amber_hi


GUNS = {
    "revolver": GunSpec(scale=0.363, recoil=4,
                        speed=1066, size=5, length=12, color=Colors.amber_hi),
    "lever_action": GunSpec(scale=1.0, recoil=7,
                            speed=1170, size=5, length=17, color=Colors.amber_hi),
    "hand_cannon": GunSpec(scale=0.50, recoil=9,
                           speed=780, size=9, length=13, color=Colors.amber),
    "shotgun": GunSpec(scale=1.0, recoil=10,
                       speed=936, size=4, length=8, pellets=6, spread=0.16,
                       color=Colors.amber_hi),
    "blunderbuss": GunSpec(scale=1.0, recoil=12,
                           speed=728, size=4, length=7, pellets=8, spread=0.26,
                           color=Colors.amber_hi),
    "ray_gun": GunSpec(scale=0.33, recoil=4,
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


def gun_spec(gun: str | None) -> GunSpec:
    """
    Look up how a named gun behaves, falling back to the revolver so a piece
    with an unknown or missing weapon still shoots something

    :param gun: gun name such as revolver or shotgun, or None when the holder
        has no weapon recorded
    :returns: that gun's spec, or the revolver's
    """
    return GUNS.get(gun or "revolver", GUNS["revolver"])


def pellet_spread(spec: GunSpec, base: float,
                  rnd: Callable[[float, float], float]) -> list[tuple[float, float]]:
    """
    Lay out one volley the way its gun scatters: the first pellet flies dead
    straight at full speed and every other one deviates within the gun's
    spread at a slightly varied speed. A single-pellet gun therefore fires
    exactly one straight shot, which is what keeps a pawn's revolver precise
    and a queen's blunderbuss messy

    :param spec: gun spec supplying the pellet count and the spread width
    :param base: aim angle in radians the volley is built around
    :param rnd: uniform random source taking a low and a high bound, injected
        so a seeded caller gets a reproducible volley
    :returns: one (angle in radians, speed factor) pair per pellet, lead first
    """
    out = []
    for i in range(spec.pellets):
        if i == 0:
            out.append((base, 1.0))
        else:
            out.append((base + rnd(-spec.spread, spec.spread), rnd(0.85, 1.1)))
    return out


_BULLET_CACHE = cache.new_size_cache()


def _build_bullet_layer(color: str, size: int, length: int) -> pg.Surface:
    """
    Rasterise one bullet pointing right: a faint tracer behind a bright core,
    capped with a white-hot head. Built once per look and rotated at draw
    time, since bullets are on screen every frame of a shot

    :param color: bullet colour, taken from the firing gun's spec
    :param size: bullet thickness in pixels
    :param length: tracer length in pixels; 1 or less leaves a bare head
    :returns: the bullet sprite, drawn pointing right
    """
    pad = int(size + 4)
    half = int(length + pad)
    dim = 2 * half
    layer = pg.Surface((dim, dim), pg.SRCALPHA)
    center = (half, half)
    tail = (half - length, half)
    rgb = pg.Color(color)[:3]
    if length > 1:
        pg.draw.line(layer, (*rgb, 90), tail, center, max(int(size * 1.6), 3))
        pg.draw.line(layer, (*rgb, 255), tail, center, max(int(size * 0.7), 2))
    pg.draw.circle(layer, (*rgb, 255), center, int(size / 2) + 1)
    pg.draw.circle(layer, (*pg.Color(Colors.text)[:3], 235), center, max(int(size / 3), 1))
    return layer


def draw_bullet(window: pg.Surface, head: tuple[float, float], ux: float, uy: float,
                color: str, size: float, length: float) -> None:
    """
    Draw a bullet in flight, turned onto the direction it is travelling. Size
    and length are rounded before the cache lookup, so the whole game shares a
    handful of bullet sprites instead of rasterising one per frame

    :param window: surface to draw on, normally the app window
    :param head: bullet head position in window pixels
    :param ux: horizontal part of the unit heading
    :param uy: vertical part of the unit heading, screen space (y grows down)
    :param color: bullet colour
    :param size: bullet thickness in pixels
    :param length: tracer length in pixels
    """
    size_q = max(round(size), 2)
    length_q = max(round(length), 0)
    key = (color, size_q, length_q)
    base = cache.memoized_surface(
        _BULLET_CACHE, key, lambda: _build_bullet_layer(color, size_q, length_q))
    angle = math.degrees(math.atan2(-uy, ux))
    img = pg.transform.rotate(base, angle)
    window.blit(img, img.get_rect(center=head))


def aimed(image: pg.Surface, pivot_img: tuple[float, float],
          target_img: tuple[float, float] | None,
          aim: float) -> tuple[pg.Surface, tuple[float, float],
                               tuple[float, float] | None, float]:
    """
    Turn an aim angle into everything needed to draw a gun pointing that way.
    Artwork is drawn facing right, so aiming leftwards mirrors it instead of
    turning it upside down, and the grip and barrel anchors move with the flip

    :param image: gun or muzzle-flash artwork, drawn pointing right
    :param pivot_img: grip position inside the image, in image pixels
    :param target_img: barrel tip inside the image, or None when the caller
        only needs the pivot back
    :param aim: aim angle in radians
    :returns: the possibly mirrored image, its pivot, its target and the
        rotation to apply, in degrees
    """
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


def blit_rotated(window: pg.Surface, image: pg.Surface, pivot_img: tuple[float, float],
                 screen_pivot: tuple[float, float], angle_deg: float) -> None:
    """
    Blit a rotated image so that one chosen point inside it lands exactly on a
    chosen point on screen. This is the trick that keeps a gun's grip glued to
    the piece holding it however far the barrel swings

    :param window: surface to draw on
    :param image: image to rotate
    :param pivot_img: point inside the image to pin, in image pixels
    :param screen_pivot: where that point must land, in window pixels
    :param angle_deg: rotation in degrees, counter-clockwise
    """
    w, h = image.get_size()
    rotated = pg.transform.rotate(image, angle_deg)
    offset = pg.math.Vector2(pivot_img[0] - w / 2, pivot_img[1] - h / 2).rotate(-angle_deg)
    center = (screen_pivot[0] - offset.x, screen_pivot[1] - offset.y)
    window.blit(rotated, rotated.get_rect(center=center))


def blit_aimed(window: pg.Surface, image: pg.Surface, pivot_img: tuple[float, float],
               screen_pivot: tuple[float, float], aim: float) -> None:
    """
    Draw a gun aimed along an angle with its grip pinned to whoever is holding
    it -- the single call every held or fired weapon in the game goes through

    :param window: surface to draw on
    :param image: gun artwork, drawn pointing right
    :param pivot_img: grip position inside the image, in image pixels
    :param screen_pivot: where the grip sits, in window pixels
    :param aim: aim angle in radians
    """
    image, pivot_img, _, angle_deg = aimed(image, pivot_img, None, aim)
    blit_rotated(window, image, pivot_img, screen_pivot, angle_deg)


def aimed_target(image: pg.Surface, pivot_img: tuple[float, float],
                 target_img: tuple[float, float], screen_pivot: tuple[float, float],
                 aim: float) -> tuple[float, float]:
    """
    Work out where a point inside the artwork ends up on screen once the gun
    is aimed. Callers use it for the barrel tip, which is where muzzle flashes
    and bullets have to start if the shot is to leave the gun it came from

    :param image: gun artwork, only its width matters here
    :param pivot_img: grip position inside the image, in image pixels
    :param target_img: point to project, in image pixels, normally the barrel
    :param screen_pivot: where the grip sits, in window pixels
    :param aim: aim angle in radians
    :returns: the projected point in window pixels
    """
    _, pivot_img, target_img, angle_deg = cast(
        tuple[pg.Surface, tuple[float, float], tuple[float, float], float],
        aimed(image, pivot_img, target_img, aim))
    vec = pg.math.Vector2(target_img[0] - pivot_img[0],
                          target_img[1] - pivot_img[1]).rotate(-angle_deg)
    return screen_pivot[0] + vec.x, screen_pivot[1] + vec.y


def draw_flourish(window: pg.Surface, gun_img: pg.Surface, grip: tuple[float, float],
                  screen_pivot: tuple[float, float], aim: float, p: float,
                  spins: int, grow: bool = True) -> None:
    """
    Draw the gun-draw flourish: the weapon spins into the holder's hand and
    lands on its aim, growing in as it spins so a piece can produce a gun it
    plainly did not have a moment ago. Callers that already have a gun in hand
    turn the growth off and get a celebratory twirl instead

    :param window: surface to draw on
    :param gun_img: gun artwork, drawn pointing right
    :param grip: grip position inside the image, in image pixels
    :param screen_pivot: where the grip sits, in window pixels
    :param aim: angle in radians the spin finally lands on
    :param p: 0..1 progress through the flourish
    :param spins: whole turns to spin before landing
    :param grow: False to spin at full size instead of growing in
    """
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


def draw_flash(window: pg.Surface, flash_img: pg.Surface, anchor: tuple[float, float],
               screen_xy: tuple[float, float], aim: float, prog: float) -> None:
    """
    Draw a muzzle flash at the barrel tip, pointing along the shot and fading
    fast so it reads as the one bright frame of a gunshot

    :param window: surface to draw on
    :param flash_img: flash artwork, drawn pointing right
    :param anchor: the flash's origin inside the image, in image pixels
    :param screen_xy: barrel tip in window pixels
    :param aim: aim angle in radians
    :param prog: 0..1 progress through the flash's short life
    """
    img = flash_img
    alpha = int(255 * (1 - prog) ** 0.6)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(max(0, alpha))
    blit_aimed(window, img, anchor, screen_xy, aim)


def _load_png(*parts: str) -> pg.Surface | None:
    """
    Load one battle image from the bundled assets, tolerating a missing or
    unreadable file so a broken asset degrades to a gunless fight instead of
    crashing the game

    :param parts: path parts under the assets/battle_png directory
    :returns: the loaded image, or None when it could not be read
    """
    try:
        return pg.image.load(
            str(paths.resource_path("assets", "battle_png", *parts))).convert_alpha()
    except (pg.error, FileNotFoundError, OSError):
        return None


_BATTLE_ART_CACHE = cache.new_cache()


def load_battle_art() -> dict[str, Any]:
    """
    Hand back the shared gun and muzzle-flash artwork, reading it off disk on
    the first call only. Every board and the menu battle share this one
    bundle, so a game that never fires a shot never pays for the images

    :returns: the battle-art bundle: guns and their flash variants
    """
    return cache.memoized_surface(_BATTLE_ART_CACHE, "art", _build_battle_art)


def _build_battle_art() -> dict[str, Any]:
    """
    Read the battle manifest and load every gun and flash variant it lists,
    skipping anything that will not load. A missing or broken manifest yields
    an empty bundle, which simply means no weapons are ever drawn

    :returns: guns keyed by name with their grip and barrel anchors, plus the
        ordered flash variants for each gun
    """
    data: dict[str, Any] = {"guns": {}, "flashes": {}}
    try:
        manifest = paths.resource_path("assets", "battle_png", "battle_manifest.json")
        with open(manifest, encoding="utf-8") as fh:
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


def scale_image(img: pg.Surface, f: float) -> pg.Surface:
    """
    Scale artwork by a factor, never letting it collapse below one pixel

    :param img: image to scale
    :param f: scale factor
    :returns: the scaled image
    """
    return pg.transform.smoothscale(
        img, (max(int(img.get_width() * f), 1), max(int(img.get_height() * f), 1)))


def gun_base_distance(art: dict[str, Any], gun: str) -> float:
    """
    Measure how far a gun's barrel sits from its grip in the source artwork,
    the yardstick every weapon is scaled against so guns of different drawn
    sizes still reach the same distance on the board

    :param art: battle-art bundle
    :param gun: gun name
    :returns: grip-to-barrel distance in image pixels, 1.0 when unknown
    """
    g = art["guns"].get(gun)
    if g is None:
        return 1.0
    return math.hypot(g["ax"] - g["gx"], g["ay"] - g["gy"]) or 1.0


def weapon_scale(art: dict[str, Any], gun: str, reach: float) -> float:
    """
    Work out the factor that makes a gun reach a wanted length on screen, with
    the per-gun size the art direction asks for folded in, so a hand cannon
    reads chunkier than a revolver at the same reach

    :param art: battle-art bundle
    :param gun: gun name
    :param reach: wanted grip-to-barrel length in window pixels
    :returns: the factor to draw this gun's artwork at
    """
    base = gun_base_distance(art, gun)
    return reach / base * gun_spec(gun).scale if base else 1.0


def build_weapon(art: dict[str, Any], gun: str, reach: float) -> dict[str, Any] | None:
    """
    Build everything needed to draw and fire one gun at one size: the scaled
    image, its grip and barrel anchors, and its scaled muzzle flashes. Callers
    cache the result per gun and cell size, since nothing here may run per
    frame

    :param art: battle-art bundle
    :param gun: gun name
    :param reach: wanted grip-to-barrel length in window pixels
    :returns: the weapon record, or None when this gun has no artwork
    """
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
