from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.menu.hero import PlayView
from chessshootout.frontend.menu.history_host import HistoryMenuView
from chessshootout.frontend.menu.options_view import OptionsView
from chessshootout.frontend.menu.profile_view import ProfileView
from chessshootout.frontend.menu.stubs import ArmoryView, BattlePassView, SocialView


__all__ = ["MenuView", "VIEW_ORDER", "build_views"]

VIEW_ORDER = ["play", "battlepass", "armory", "social", "history"]


def build_views(app):
    views = (PlayView(app), BattlePassView(app), ArmoryView(app),
             SocialView(app), HistoryMenuView(app), ProfileView(app), OptionsView(app))
    return {view.name: view for view in views}
