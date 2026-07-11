import pygame as pg

from chessshootout.frontend.screens.base import Screen


class GameScreen(Screen):

    name = "game"

    def draw(self):
        app = self.app
        now = pg.time.get_ticks()
        if app.current_result() is not None and app.focus_mode:
            if app.focus_transition is None:
                app._toggle_focus(False)
            elif app.focus_transition.collapsing:
                app._force_focus_off_instant()
        if app.focus_transition is not None:
            tr = app.focus_transition
            tr.draw(now)
            if app._focus_show() == "line" and tr.cur_board_rect is not None:
                alpha = tr.cur_e if tr.collapsing else 1.0 - tr.cur_e
                app._draw_time_lines(tr.cur_board_rect, alpha)
            if tr.done(now):
                app._finalize_focus_transition()
        elif app.focus_mode:
            show = app._focus_show()
            app._draw_game_scene(
                show_panel=False, show_strips=(show == "strips"),
                arrow_hook=lambda: app._draw_focus_edge_arrow(now),
                after_board=app._draw_time_lines if show == "line" else None)
            app.board.draw_drag_overlay()
            if app.board.effects.has_takeover():
                app.board.effects.draw_takeover(app.window, now)
            app.result_flow._update_result_pending()
        else:
            app._draw_game_scene(
                show_panel=True, show_strips=True,
                arrow_hook=lambda: app._update_focus_arrow_off(now))
            app.board.draw_drag_overlay()
            app.result_flow._update_result_pending()
            if not app.match_found_modal.is_visible():
                show_modal = app._result_modal_should_show() and not app.pgn_review
                if not show_modal and app.board.effects.has_takeover():
                    app.board.effects.draw_takeover(app.window, now)
                else:
                    app._draw_result_fade_overlay()
                if show_modal:
                    app.board.effects.clear_takeover()
                    app.result_flow._feed_result_menu()
                    app.result_menu.draw()
