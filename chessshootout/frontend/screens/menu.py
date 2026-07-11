import pygame as pg

from chessshootout.frontend.menu.menu_page import PAGE_CARD
from chessshootout.frontend.screens.base import Screen


class MenuScreen(Screen):

    name = "menu"
    uses_battle_backdrop = True

    def draw(self):
        app = self.app
        now = pg.time.get_ticks()
        if app._entering_menu and app.menu_page.page == PAGE_CARD:
            app.menu_battle.begin_intro()
        app.menu_battle.set_avoid_rect(app.menu_page.avoid_rect())
        app.menu_battle.set_logo_rect(app.menu_page.logo_rect())
        app.menu_battle.update(now)
        app.menu_battle.draw(app.window)
        app.menu_battle.draw_scrim(app.window)
        if not app._menu_overlay_active():
            app.menu_page.draw_foreground()
        app.menu_battle.draw_intro_overlay(app.window)
