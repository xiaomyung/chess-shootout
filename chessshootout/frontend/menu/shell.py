from typing import Any

from chessshootout.frontend.menu.view import MenuView
from chessshootout.frontend.menu.play_view import PlayView
from chessshootout.frontend.menu.history_host import HistoryMenuView
from chessshootout.frontend.menu.options_view import OptionsView
from chessshootout.frontend.menu.profile_view import ProfileView
from chessshootout.frontend.menu.stubs import ArmoryView, BattlePassView, SocialView


__all__ = ["MenuView", "VIEW_ORDER", "build_views"]

VIEW_ORDER = ["play", "battlepass", "armory", "social", "history"]


def build_views(app: Any) -> dict[str, MenuView]:
    """
    Build every menu sub-view once at startup and hand them back keyed by
    name. This is the single registration point for the sub-views: adding one
    means adding it here and nowhere else, and because the menu screen looks
    them up by name it never has to know a concrete view exists

    :param app: the Frontend shell every sub-view is bound to
    :returns: the sub-views keyed by their name, Profile included even though
        no rail row leads to it -- it is opened from the right-hand profile
        card
    """
    views = (PlayView(app), BattlePassView(app), ArmoryView(app),
             SocialView(app), HistoryMenuView(app), ProfileView(app), OptionsView(app))
    return {view.name: view for view in views}
