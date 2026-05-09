import pygame as pg

from frontend import env
from frontend.colors import Colors
from frontend.widgets import draw_button


SLIDER_FRACTION = 0.75
SLIDER_GAP_PX = 6


class AudioPanel:

    def __init__(self, window, sound_manager):
        self.window = window
        self.sound_manager = sound_manager
        self.rect = pg.Rect(0, 0, 0, 0)
        self.slider_rect = pg.Rect(0, 0, 0, 0)
        self.mute_rect = pg.Rect(0, 0, 0, 0)
        self.button_font = pg.font.SysFont("Arial", 14, bold=True)
        self.button_font_factor = 28
        self._dragging_slider = False

    def set_rect(self, rect):
        self.rect = pg.Rect(rect)
        slider_w = int((rect.width - SLIDER_GAP_PX) * SLIDER_FRACTION)
        mute_w = rect.width - SLIDER_GAP_PX - slider_w
        self.slider_rect = pg.Rect(rect.x, rect.y, slider_w, rect.height)
        self.mute_rect = pg.Rect(rect.x + slider_w + SLIDER_GAP_PX, rect.y,
                                 mute_w, rect.height)
        self.button_font = pg.font.SysFont(
            "Arial", max(int(rect.width / self.button_font_factor), 10), bold=True,
        )

    def draw(self):
        if self.rect.width <= 0 or self.rect.height <= 0:
            return
        self._draw_slider()
        self._draw_mute()

    def _draw_slider(self):
        track = self._track_rect()
        pg.draw.rect(self.window, Colors.dark_menu, self.slider_rect, border_radius=4)
        pg.draw.rect(self.window, Colors.button_border, self.slider_rect, 1,
                     border_radius=4)
        pg.draw.rect(self.window, Colors.light_grey_menu, track, border_radius=2)
        volume = self.sound_manager.master_volume
        fill_w = int(track.width * volume)
        if fill_w > 0:
            fill_rect = pg.Rect(track.x, track.y, fill_w, track.height)
            pg.draw.rect(self.window, Colors.button_hover, fill_rect, border_radius=2)
        knob_x = track.x + fill_w
        knob_radius = max(track.height, 6)
        pg.draw.circle(self.window, Colors.white,
                       (knob_x, self.slider_rect.centery), knob_radius)
        pg.draw.circle(self.window, Colors.button_border,
                       (knob_x, self.slider_rect.centery), knob_radius, 1)

    def _draw_mute(self):
        label = "Unmute" if not self.sound_manager.enabled else "Mute"
        draw_button(self.window, self.mute_rect, label, self.button_font)

    def _track_rect(self):
        track_h = max(int(self.slider_rect.height * 0.25), 4)
        margin = max(int(self.slider_rect.height * 0.4), 8)
        track_w = max(self.slider_rect.width - 2 * margin, 0)
        return pg.Rect(
            self.slider_rect.x + margin,
            self.slider_rect.centery - track_h // 2,
            track_w,
            track_h,
        )

    def handle_click(self, pos):
        if self.mute_rect.collidepoint(pos):
            self.sound_manager.set_enabled(not self.sound_manager.enabled)
            return True
        if self.slider_rect.collidepoint(pos):
            self._update_volume_from_pos(pos)
            self._dragging_slider = True
            return True
        return False

    def handle_drag(self, pos, button_pressed):
        if not button_pressed:
            self._dragging_slider = False
            return False
        if not self._dragging_slider:
            return False
        self._update_volume_from_pos(pos)
        return True

    def end_drag(self):
        if self._dragging_slider:
            env.set_master_volume(self.sound_manager.master_volume)
        self._dragging_slider = False

    def _update_volume_from_pos(self, pos):
        track = self._track_rect()
        if track.width <= 0:
            return
        x = max(track.x, min(pos[0], track.right))
        ratio = (x - track.x) / track.width
        self.sound_manager.set_master_volume(ratio)
