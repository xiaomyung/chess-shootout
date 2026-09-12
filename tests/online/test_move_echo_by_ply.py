"""A move_applied is recognised as this client's own echo by PLY NUMBER and
squares, never by SAN alone.

Consecutive identical SANs are ordinary chess: a recapture on the same square
(Qxd5 Qxd5, exd5 exd5, Nxe5 Nxe5) is most trades. Online, captures go through
the skill-check gate, so neither client pre-applies them -- the old "same SAN
as the last ply == echo" guard dropped the recapture on BOTH clients, left both
a ply behind with the wrong side to move, and the server's heartbeat then
issued a resync directive to each of them (the live-game log that opened
v2.13.1). The server is faked; the game screen's ingest path is driven for
real, mover and receiver alike.
"""

from tests.conftest import pygame_display
from chessshootout.backend.pieces import PieceType
from chessshootout.frontend.online_coordinator import ResyncCause
from tests.helpers import (
    BLACK, K, N, P, Q, WHITE, make_backend, move_applied, online_app, piece, sq)
from tests.online.online_helpers import drive_verdict_hold, required_payload


_pygame_init = pygame_display(1000, 800)


def _record_resyncs(app, monkeypatch):
    causes = []
    real = app.coordinator._begin_resync

    def spy(cause):
        causes.append(cause)
        real(cause)

    monkeypatch.setattr(app.coordinator, "_begin_resync", spy)
    return causes


def _queen_trade_board(app, turn):
    """White Qd1 + Nd5, Black Qd8: Qd8xd5 then Qd1xd5 -- both plies are "Qxd5"."""
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(7, 3): piece(Q, WHITE), sq(3, 3): piece(N, WHITE),
        sq(0, 3): piece(Q, BLACK),
    }, turn=turn)
    return sq(0, 3), sq(7, 3), sq(3, 3)


def _pawn_trade_board(app):
    """White Pe4, Black Pd5 + Pe6: e4xd5 then e6xd5 -- both plies are "exd5"."""
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 4): piece(K, BLACK),
        sq(4, 4): piece(P, WHITE), sq(3, 3): piece(P, BLACK), sq(2, 4): piece(P, BLACK),
    }, turn=WHITE)
    return sq(4, 4), sq(2, 4), sq(3, 3)


def _win_own_capture(app, frm, to, ply):
    """Drive the mover's real path: gate holds the move, the server opens a check,
    move_applied(won) parks the apply behind the verdict hold, the hold plays out."""
    app.game.skillcheck_session.skillcheck_gate(frm, to)
    app.coordinator._handle_skill_check_required(required_payload(frm, to))
    app.coordinator._handle_remote_move_applied(
        move_applied(frm, to, ply, kind="wheel", won=True))
    drive_verdict_hold(app)


def test_mover_recapture_with_the_same_san_lands_after_own_won_capture(monkeypatch):
    """Black wins the check on Qxd5 (the mover never pre-applies, the verdict
    hold applies it), then white's Qxd5 recapture arrives as ply 2. It is a
    new ply, not an echo, and it lands without a resync."""
    app = online_app("black")
    causes = _record_resyncs(app, monkeypatch)
    black_q, white_q, d5 = _queen_trade_board(app, BLACK)
    _win_own_capture(app, black_q, d5, 1)
    assert len(app.game.match.move_history) == 1
    assert app.game.match.piece_at(d5).color == BLACK

    app.coordinator._handle_remote_move_applied(
        move_applied(white_q, d5, 2, kind="wheel", won=True))
    assert len(app.game.match.move_history) == 2, "the recapture is a new ply"
    assert app.game.match.piece_at(d5).color == WHITE
    assert [e.san for e in app.game.match.move_history] == ["Qxd5", "Qxd5"]
    assert causes == []
    assert app.coordinator._resyncing is False


def test_receiver_recapture_with_the_same_san_lands_after_the_opponents(monkeypatch):
    """The other seat: black's Qxd5 arrives as the opponent's move, then white
    wins its own check on the Qxd5 recapture. The verdict hold's apply must not
    be mistaken for an echo of black's identical SAN."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    black_q, white_q, d5 = _queen_trade_board(app, BLACK)
    app.coordinator._handle_remote_move_applied(
        move_applied(black_q, d5, 1, kind="wheel", won=True))
    assert len(app.game.match.move_history) == 1

    _win_own_capture(app, white_q, d5, 2)
    assert len(app.game.match.move_history) == 2
    assert app.game.match.piece_at(d5).color == WHITE
    assert [e.san for e in app.game.match.move_history] == ["Qxd5", "Qxd5"]
    assert causes == []
    assert app.coordinator._resyncing is False


def test_pawn_recapture_with_the_same_san_lands(monkeypatch):
    """exd5 exd5 -- the most common trade in the opening -- arrives as two
    server-confirmed plies and both land."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    white_p, black_p, d5 = _pawn_trade_board(app)
    app.coordinator._handle_remote_move_applied(
        move_applied(white_p, d5, 1, kind="wheel", won=True, san="exd5"))
    app.coordinator._handle_remote_move_applied(
        move_applied(black_p, d5, 2, kind="wheel", won=True, san="exd5"))
    assert [e.san for e in app.game.match.move_history] == ["exd5", "exd5"]
    assert app.game.match.piece_at(d5).color == BLACK
    assert causes == []


def test_own_quiet_move_echo_is_recognised_by_ply_and_squares(monkeypatch):
    """A quiet move applies locally at once; its echo carries the ply the
    client already holds and the same squares, so it is a clock update only."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    app.game.match.try_move(sq(6, 4), sq(4, 4))
    app.coordinator._handle_remote_move_applied(move_applied(sq(6, 4), sq(4, 4), 1, san="e4"))
    assert len(app.game.match.move_history) == 1
    assert causes == []


def test_an_echo_without_a_ply_falls_back_to_san_and_squares(monkeypatch):
    """A message with no ply number cannot be judged by ply, so the old
    SAN-plus-squares match still names it an echo rather than a gap."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    app.game.match.try_move(sq(6, 4), sq(4, 4))
    payload = move_applied(sq(6, 4), sq(4, 4), None, san="e4")
    app.coordinator._handle_remote_move_applied(payload)
    assert len(app.game.match.move_history) == 1
    assert causes == []


def test_same_ply_different_squares_is_a_gap_not_an_echo(monkeypatch):
    """The server confirming a DIFFERENT move at the ply this client holds
    means the two histories have forked; that is a resync, not a clock snap."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    app.game.match.try_move(sq(6, 4), sq(4, 4))
    app.coordinator._handle_remote_move_applied(move_applied(sq(6, 3), sq(4, 3), 1, san="d4"))
    assert len(app.game.match.move_history) == 1
    assert causes == [ResyncCause.MOVE_PLY_GAP]
    assert app.coordinator._resyncing is True


def _promotion_board(app):
    app.game.match.backend = make_backend({
        sq(7, 4): piece(K, WHITE), sq(0, 0): piece(K, BLACK), sq(1, 4): piece(P, WHITE),
    }, turn=WHITE)
    return sq(1, 4), sq(0, 4)


def test_own_promotion_echo_matches_the_promoted_piece(monkeypatch):
    """A promotion echo names the piece; the same squares with the same piece
    is the echo, and the same squares with a different piece is a fork."""
    app = online_app("white")
    causes = _record_resyncs(app, monkeypatch)
    frm, to = _promotion_board(app)
    assert app.game.match.try_move(frm, to).promotion_required
    app.game.match.promote(to, PieceType.QUEEN)
    assert len(app.game.match.move_history) == 1

    echo = move_applied(frm, to, 1, san="e8=Q")
    echo["promotion"] = "q"
    app.coordinator._handle_remote_move_applied(echo)
    assert len(app.game.match.move_history) == 1
    assert causes == []

    forked = move_applied(frm, to, 1, san="e8=R")
    forked["promotion"] = "r"
    app.coordinator._handle_remote_move_applied(forked)
    assert causes == [ResyncCause.MOVE_PLY_GAP]


def test_the_echo_of_a_won_capture_still_applies_only_once():
    """The verdict hold applies the won move; a re-delivered move_applied for
    that same ply (reconnect replay) is an echo by ply and lands nothing."""
    app = online_app("black")
    black_q, _white_q, d5 = _queen_trade_board(app, BLACK)
    _win_own_capture(app, black_q, d5, 1)
    app.coordinator._handle_remote_move_applied(
        move_applied(black_q, d5, 1, kind="wheel", won=True))
    assert len(app.game.match.move_history) == 1
    assert not app.game.skillcheck_overlay.is_active()
