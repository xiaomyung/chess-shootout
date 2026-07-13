from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.menu.hero import PlayView
from chessshootout.frontend.menu.history_host import HistoryMenuView
from chessshootout.frontend.menu.stubs import ArmoryView, BattlePassView, SocialView


__all__ = ["MenuView", "VIEW_ORDER", "build_views"]

VIEW_ORDER = ["play", "battlepass", "armory", "social", "history"]


def build_views(app):
    views = {}
    for view in (PlayView(app), BattlePassView(app), ArmoryView(app),
                 SocialView(app), HistoryMenuView(app)):
        views[view.name] = view
    return views
