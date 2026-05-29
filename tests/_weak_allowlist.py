"""Tests grandfathered past the weak-test guard while the suite is strengthened.

Each entry is a test that exercises no real behavior yet (renders/calls without
asserting anything). They are being rewritten to assert real behavior; as each is
fixed, remove it here — the guard fails on stale entries, so this drains to empty.
"""

_SMOKE = "renders/calls without a behavioral assertion"

WEAK_ALLOWLIST = {
    "test_annotations.py": {
        "test_draw_annotation_highlights_does_not_crash": _SMOKE,
        "test_draw_arrows_does_not_crash": _SMOKE,
        "test_draw_drag_preview_arrow_no_drag_is_noop": _SMOKE,
        "test_draw_drag_preview_arrow_with_active_drag": _SMOKE,
        "test_draw_full_board_with_annotations_no_crash": _SMOKE,
        "test_draw_knight_arrows_does_not_crash": _SMOKE,
    },
    "test_game_end_polish.py": {
        "test_fade_overlay_no_op_when_no_result": _SMOKE,
    },
    "test_online_ux.py": {
        "test_reconnecting_modal_subtitle_renders_without_crash": _SMOKE,
    },
    "test_player_strip.py": {
        "test_badge_clips_captures_max_x": _SMOKE,
        "test_draw_at_multiple_sizes_does_not_crash": _SMOKE,
        "test_draw_smoke_active_with_clock": _SMOKE,
        "test_draw_smoke_inactive_with_clock": _SMOKE,
        "test_draw_smoke_no_clock": _SMOKE,
        "test_draw_smoke_with_badge_does_not_raise": _SMOKE,
        "test_draw_smoke_with_low_time_fraction_and_flash": _SMOKE,
        "test_draw_smoke_without_badge_still_works": _SMOKE,
    },
    "test_ux_polish.py": {
        "test_last_move_highlight_renders_when_history_nonempty": _SMOKE,
        "test_player_strip_advantage_negative_not_rendered": _SMOKE,
        "test_player_strip_draws_with_captures_smoke": _SMOKE,
    },
}
