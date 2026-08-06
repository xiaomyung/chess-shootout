import asyncio
import json
import secrets
import time

from pydantic import ValidationError

from chessshootout.backend.fen import export_fen
from chessshootout.backend.pieces import PieceColor
from chessshootout.backend.utils import (
    PROMO_TYPE_BY_LETTER, coord_from_square, square_from_coord,
)
from chessshootout.server import logging_setup
from chessshootout.server.connections import broadcast, send
from chessshootout.server.broadcasts import (
    broadcast_game_start, finalize_and_broadcast, resolve_skillcheck_fail)
from chessshootout.server.protocol import (
    AnnotationDeltaMessage, AnnotationsBlockedMessage, AnnotationsStateMessage,
    ArrowWire, ClockSnapshot, ConnectionStatusMessage,
    DrawOfferedMessage, DrawResponseMessage,
    ErrorMessage, GIVE_TIME_SECONDS, GIVE_TIME_TICK_MS, GiveTimeMessage,
    MAX_SHARED_ARROWS, MAX_SHARED_HIGHLIGHTS, MODERATION_TRIP_LIMIT,
    MoveAppliedMessage, MoveMessage,
    PingMessage, PongMessage, QuickChatMessage, QuickChatReceivedMessage, Reason,
    RematchRequestMessage, RematchResponseMessage, RematchUpdateMessage,
    ResyncDirectiveMessage, SetMarksVisibilityMessage,
    SkillCheckRequiredMessage, SkillCheckShotMessage, SkillCheckSpectateMessage,
    SkillCheckSpectateShotMessage,
    TakebackAppliedMessage, TakebackOfferedMessage,
    TakebackResponseMessage, TimeGrantedMessage,
)
from chessshootout.server.moderation import detector
from chessshootout.server.moderation.load import ModerationLoad
from chessshootout.server.rooms import PendingSkillCheck
from chessshootout.server.sweep import RESULT_REASON_BY_GAME_RESULT
from chessshootout.skillcheck import mole, online
from chessshootout.skillcheck.triggers import compute_facts
from chessshootout.skillcheck.types import SkillCheckKind, SkillCheckOutcome


log = logging_setup.get_logger("chess.server.app")

RESYNC_NOTIFY_MIN_INTERVAL_SECONDS = 5.0
RESYNC_NOTIFY_FLAP_FLOOR_SECONDS = 1.0
RESYNC_DIRECTIVE_MIN_INTERVAL_SECONDS = 1.0
RESYNC_GATE_PRUNE_THRESHOLD = 512

RESYNC_NOTIFY = "notify"
RESYNC_DIRECTIVE = "directive"


class _ResyncGate:

    def __init__(self):
        self._open_at = {}

    def allow(self, key, now, interval):
        if now < self._open_at.get(key, now):
            return False
        if len(self._open_at) >= RESYNC_GATE_PRUNE_THRESHOLD:
            self._prune(now)
        self._open_at[key] = now + interval
        return True

    def reopen(self, key, now, delay):
        if key in self._open_at:
            self._open_at[key] = min(self._open_at[key], now + delay)

    def _prune(self, now):
        for key, at in list(self._open_at.items()):
            if at <= now:
                del self._open_at[key]


def _app_state_singleton(app, name, factory):
    value = getattr(app.state, name, None)
    if value is None:
        value = factory()
        setattr(app.state, name, value)
    return value


def _resync_gate(app):
    return _app_state_singleton(app, "resync_gate", _ResyncGate)


def _moderation_load(app):
    return _app_state_singleton(app, "moderation_load", ModerationLoad)


def _color_to_move(backend):
    return "white" if backend.current_turn() == PieceColor.WHITE else "black"


def _clock_snapshot(clock):
    if clock is None:
        return ClockSnapshot(white_remaining=0.0, black_remaining=0.0, running_for=None)
    running = None
    if clock.running_for is not None:
        running = "white" if clock.running_for == PieceColor.WHITE else "black"
    return ClockSnapshot(
        white_remaining=clock.white_remaining,
        black_remaining=clock.black_remaining,
        running_for=running,
    )


def _arrow_wires(pairs):
    return [ArrowWire(from_sq=a[0], to_sq=a[1]) for a in pairs]


def peek_type(raw):
    try:
        return json.loads(raw).get("type")
    except (json.JSONDecodeError, ValueError):
        return None


async def dispatch(app, websocket, room, color, raw):
    msg_type = peek_type(raw)
    handler = HANDLERS.get(msg_type)
    if handler is None:
        await send(websocket, ErrorMessage(reason=Reason.INVALID_MESSAGE))
        return msg_type, "invalid_message"
    return msg_type, await handler(app, websocket, room, color, raw)


async def handle_move(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.backend is None:
        return "no_backend"
    if room.result is not None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.GAME_ALREADY_OVER, msg_type="move"))
        return "already_over"
    pending = room.pending_skillcheck
    if pending is not None and pending.is_dead(app.state.now_ms()):
        await resolve_skillcheck_fail(rooms, connections, room)
        if room.result is not None:
            return "already_over"
        pending = None
    if pending is not None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.SKILLCHECK_PENDING, msg_type="move"))
        return "pending"
    try:
        msg = MoveMessage.model_validate_json(raw)
        from_sq = square_from_coord(msg.from_sq)
        to_sq = square_from_coord(msg.to_sq)
    except (ValidationError, ValueError):
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "invalid_move_format"
    expected = _color_to_move(room.backend)
    if expected != color:
        log.info("move rejected room=%s mover=%s expected=%s reason=not_your_turn",
                 room.room_id, color, expected)
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NOT_YOUR_TURN, msg_type="move"))
        return "not_your_turn"
    if (from_sq, to_sq) in room.skillcheck_locks:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.MOVE_LOCKED, msg_type="move"))
        return "locked"
    facts = compute_facts(room.backend, from_sq, to_sq, room.skillcheck_locks)
    if facts is None:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "illegal"
    kind = online.select_kind(room.skillcheck_secret, room.plies_ever, room.backend,
                              from_sq, to_sq, room.skillcheck_locks, facts)
    if kind == SkillCheckKind.NONE:
        return await _apply_move(app, room, color, from_sq, to_sq, msg.promotion,
                                 skill_kind=None, skill_won=None)
    return await _arm_skillcheck(app, room, color, kind, from_sq, to_sq,
                                 msg.promotion, facts)


async def _arm_skillcheck(app, room, color, kind, from_sq, to_sq, promotion, facts):
    connections = app.state.connections
    value_diff = online.value_diff_for(facts, promotion)
    seed = secrets.token_hex(16)
    start_ms = app.state.now_ms()
    deadline_ms = online.skillcheck_deadline_ms(room.time_minutes * 60)
    holes = ()
    if kind == SkillCheckKind.WHACK:
        holes = mole.holes_for(seed, facts.captured_value, (to_sq.row, to_sq.col),
                               room.backend.state, room.backend.SIZE)
    room.pending_skillcheck = PendingSkillCheck(
        color=color, from_sq=from_sq, to_sq=to_sq, promotion=promotion,
        kind=kind, seed=seed, value_diff=value_diff,
        start_ms=start_ms, expires_at_ms=start_ms + deadline_ms, deadline_ms=deadline_ms,
        captured_value=facts.captured_value, holes=holes,
    )
    log.info("skillcheck fired room=%s mover=%s kind=%s", room.room_id, color, kind.value)
    geometry = dict(
        kind=kind.value, seed=seed, value_diff=value_diff, deadline_ms=deadline_ms,
        captured_value=facts.captured_value,
        from_sq=coord_from_square(from_sq), to_sq=coord_from_square(to_sq),
        promotion=promotion)
    await send(connections.get_for_color(room, color),
               SkillCheckRequiredMessage(**geometry))
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, SkillCheckSpectateMessage(**geometry))
    return f"skillcheck:{kind.value}"


async def _apply_move(app, room, color, from_sq, to_sq, promotion,
                      *, skill_kind, skill_won):
    rooms = app.state.rooms
    connections = app.state.connections
    result = room.backend.try_move(from_sq, to_sq)
    if not result.legal:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.INVALID_MOVE_FORMAT))
        return "illegal"
    if result.promotion_required:
        room.backend.promote(to_sq, PROMO_TYPE_BY_LETTER[promotion or "q"])
    room.plies_ever += 1
    room.skillcheck_locks.clear()
    room.annotations_white.clear_marks()
    room.annotations_black.clear_marks()
    if room.first_move_at is None:
        room.first_move_at = app.state.now()
    await clear_resyncing(app, room, color)
    room.draw_offered_by = None
    room.takeback_offered_by = None
    san = room.backend.move_history[-1].san
    if skill_kind is not None:
        room.skillcheck_log.append(SkillCheckOutcome(
            len(room.backend.move_history), skill_kind, skill_won, san))
    log.info("move applied room=%s mover=%s san=%s", room.room_id, color, san)
    applied = MoveAppliedMessage(
        from_sq=coord_from_square(from_sq), to_sq=coord_from_square(to_sq),
        promotion=promotion, san=san, clock=_clock_snapshot(room.backend.clock),
        ply=len(room.backend.move_history),
        skill_check_kind=skill_kind, skill_check_won=skill_won,
    )
    await broadcast(rooms, connections, room, applied)
    game_result = room.backend.game_result()
    if game_result in RESULT_REASON_BY_GAME_RESULT:
        reason, winner = RESULT_REASON_BY_GAME_RESULT[game_result]
        await finalize_and_broadcast(rooms, connections, room, reason, winner_color=winner)
        return f"applied+result:{reason}"
    return "applied"


def _shot_payload_ok(pending, msg):
    if pending.kind == SkillCheckKind.COMBO:
        return msg.direction is not None
    if pending.kind == SkillCheckKind.WHACK:
        return msg.target_row is not None and msg.target_col is not None
    return True


def _adjudicate_shot(pending, msg, elapsed):
    is_whack = pending.kind == SkillCheckKind.WHACK
    challenge = pending.challenge
    hit = online.shot_wins(pending.kind, challenge, elapsed, pending.miss_count,
                           pending.deadline_ms, progress=pending.progress,
                           direction=msg.direction,
                           target=(msg.target_row, msg.target_col) if is_whack else None,
                           hole_squares=pending.holes if is_whack else None,
                           last_hit_pop=pending.last_hit_pop,
                           flipped=pending.color == "black")
    won = hit and pending.progress + 1 >= online.hits_required(pending.kind, challenge)
    return challenge, hit, won


async def handle_skill_check_shot(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    pending = room.pending_skillcheck
    if room.result is not None or pending is None or color != pending.color:
        return "noop"
    try:
        msg = SkillCheckShotMessage.model_validate_json(raw)
    except ValidationError:
        return "noop"
    if not _shot_payload_ok(pending, msg):
        return "noop"
    is_whack = pending.kind == SkillCheckKind.WHACK
    recv_ms = app.state.now_ms()
    raw_elapsed = recv_ms - pending.start_ms
    elapsed = online.adjudicated_elapsed_ms(msg.client_elapsed_ms, recv_ms, pending.start_ms)
    gap = online.min_inter_input_ms(pending.kind)
    if gap > 0 and pending.last_input_ms >= 0 and elapsed - pending.last_input_ms < gap:
        return "noop"
    challenge, hit, won = _adjudicate_shot(pending, msg, elapsed)
    progress_after = pending.progress + (1 if hit else 0)
    log.debug("skillcheck shot room=%s kind=%s raw_ms=%.1f client=%.1f effective=%d "
              "miss=%d subfloor=%s", room.room_id, pending.kind.value,
              raw_elapsed, msg.client_elapsed_ms, elapsed,
              pending.miss_count, elapsed < online.SKILLCHECK_HUMAN_FLOOR_MS)
    if won:
        room.pending_skillcheck = None
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, SkillCheckSpectateShotMessage(
            elapsed_ms=elapsed, miss_count=pending.miss_count, won=won,
            progress=progress_after, direction=msg.direction,
            target_row=msg.target_row, target_col=msg.target_col))
    if won:
        if room.result is not None:
            return "already_over"
        log.info("skillcheck won room=%s mover=%s kind=%s", room.room_id, color,
                 pending.kind.value)
        return await _apply_move(app, room, color, pending.from_sq, pending.to_sq,
                                 pending.promotion, skill_kind=pending.kind.value,
                                 skill_won=True)
    if room.pending_skillcheck is not pending:
        return "noop"
    if hit:
        pending.progress = progress_after
        if is_whack:
            pending.last_hit_pop = challenge.pop_up_at(elapsed)
        pending.last_input_ms = elapsed
        return "skillcheck_hit"
    if pending.kind == SkillCheckKind.WHEEL \
            or online.is_past_deadline(elapsed, pending.deadline_ms) \
            or online.check_expired(pending.kind, challenge, elapsed,
                                    pending.miss_count + 1, pending.progress,
                                    pending.last_hit_pop):
        log.info("skillcheck failed room=%s mover=%s kind=%s", room.room_id, color,
                 pending.kind.value)
        await resolve_skillcheck_fail(rooms, connections, room)
        return "skillcheck_fail"
    pending.miss_count += 1
    pending.last_input_ms = elapsed
    return "skillcheck_miss"


async def handle_resign(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None:
        return "already_over"
    winner = room.opp_color(color)
    log.info("resign room=%s loser=%s winner=%s", room.room_id, color, winner)
    await finalize_and_broadcast(rooms, connections, room, Reason.RESIGNATION,
                                 winner_color=winner)
    return "resigned"


async def handle_draw_offer(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
    if room.draw_offered_by is not None and room.draw_offered_by != color:
        log.info("draw mutual room=%s", room.room_id)
        room.draw_offered_by = None
        await finalize_and_broadcast(rooms, connections, room, Reason.DRAW_AGREEMENT)
        return "agreed"
    log.info("draw offered room=%s by=%s", room.room_id, color)
    room.draw_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await send(opp_ws, DrawOfferedMessage())
    return "offered"


async def handle_draw_response(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.draw_offered_by is None:
        return "noop"
    try:
        msg = DrawResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if room.draw_offered_by == color:
        return "self"
    if msg.accept:
        log.info("draw accepted room=%s by=%s", room.room_id, color)
        room.draw_offered_by = None
        await finalize_and_broadcast(rooms, connections, room, Reason.DRAW_AGREEMENT)
        return "accepted"
    log.info("draw declined room=%s by=%s", room.room_id, color)
    room.draw_offered_by = None
    return "declined"


async def _restart_rematch(app, room, color):
    rooms = app.state.rooms
    connections = app.state.connections
    if not rooms.reset_for_rematch(room.room_id):
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.REMATCH_UNAVAILABLE,
                                    msg_type="rematch_response"))
        return "unavailable"
    log.info("rematch restart room=%s", room.room_id)
    await broadcast_game_start(connections, room, app.state.now, rematch=True)
    return "restarted"


async def handle_rematch_request(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return "noop"
    slot = room.slot(color)
    if slot is None or not slot.at_result:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.REMATCH_UNAVAILABLE,
                                    msg_type="rematch_request"))
        return "unavailable"
    if color in room.rematch_offered_by:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.REMATCH_ALREADY_PENDING,
                                    msg_type="rematch_request"))
        return "duplicate"
    room.rematch_offered_by.add(color)
    rooms.mark_rematch_activity(room)
    if len(room.rematch_offered_by) == 2:
        return await _restart_rematch(app, room, color)
    log.info("rematch requested room=%s by=%s", room.room_id, color)
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, RematchRequestMessage())
        if color not in room.rematch_offered_by:
            await send(opp_ws, RematchUpdateMessage(event="cancelled"))
    return "offered"


async def handle_rematch_response(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is None:
        return "noop"
    try:
        msg = RematchResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if not room.rematch_offered_by:
        return "noop"
    if color in room.rematch_offered_by:
        return "noop"
    if msg.accept:
        log.info("rematch accepted room=%s by=%s", room.room_id, color)
        rooms.mark_rematch_activity(room)
        return await _restart_rematch(app, room, color)
    log.info("rematch declined room=%s by=%s", room.room_id, color)
    for slot_color in ("white", "black"):
        ws = connections.get_for_color(room, slot_color)
        if ws is not None:
            await send(ws, RematchUpdateMessage(
                event="window_expired" if slot_color == color else "declined"))
    room.rematch_offered_by.clear()
    rooms.drop_room_now(room.room_id)
    return "declined"


async def handle_left_result(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is None:
        return "noop"
    slot = room.slot(color)
    if slot is None:
        return "noop"
    slot.at_result = False
    if color in room.rematch_offered_by:
        room.rematch_offered_by.discard(color)
        opp_ws = connections.get_for_color(room, room.opp_color(color))
        if opp_ws is not None:
            await send(opp_ws, RematchUpdateMessage(event="cancelled"))
    return "left_result"


async def handle_takeback_request(app, websocket, room, color, raw):
    connections = app.state.connections
    if room.result is not None or room.backend is None:
        return "noop"
    if room.pending_skillcheck is not None:
        return "pending"
    expected = _color_to_move(room.backend)
    if color == expected:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NOT_YOUR_TURN,
                                    msg_type="takeback_request"))
        return "not_your_turn"
    if not room.backend.move_history:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.NO_TAKEBACK_AVAILABLE,
                                    msg_type="takeback_request"))
        return "no_moves"
    log.info("takeback requested room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = color
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    await send(opp_ws, TakebackOfferedMessage())
    return "offered"


async def handle_takeback_response(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.takeback_offered_by is None:
        return "noop"
    if room.pending_skillcheck is not None:
        return "pending"
    try:
        msg = TakebackResponseMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if room.takeback_offered_by == color:
        return "self"
    if msg.accept:
        log.info("takeback accepted room=%s by=%s", room.room_id, color)
        popped_ply = len(room.backend.move_history)
        room.backend.undo()
        room.skillcheck_log = [e for e in room.skillcheck_log if e.ply < popped_ply]
        room.takeback_offered_by = None
        room.annotations_white.clear_marks()
        room.annotations_black.clear_marks()
        await broadcast(rooms, connections, room, TakebackAppliedMessage(
            fen=export_fen(room.backend),
            clock=_clock_snapshot(room.backend.clock),
            ply=len(room.backend.move_history),
        ))
        return "accepted"
    log.info("takeback declined room=%s by=%s", room.room_id, color)
    room.takeback_offered_by = None
    return "declined"


async def handle_give_time(app, websocket, room, color, raw):
    rooms = app.state.rooms
    connections = app.state.connections
    if room.result is not None or room.backend is None or room.backend.clock is None:
        return "noop"
    try:
        hold_ms = GiveTimeMessage.model_validate_json(raw).hold_ms
    except ValidationError:
        return "invalid"
    ticks = max(1, hold_ms // GIVE_TIME_TICK_MS)
    opp_color_str = room.opp_color(color)
    opp_piece_color = (
        PieceColor.WHITE if opp_color_str == "white" else PieceColor.BLACK
    )
    added = room.backend.clock.add_time(opp_piece_color, GIVE_TIME_SECONDS * ticks)
    log.info("give_time room=%s by=%s hold_ms=%d ticks=%d added=%.2f",
             room.room_id, color, hold_ms, ticks, added)
    await broadcast(rooms, connections, room, TimeGrantedMessage(
        granted_by=color, seconds_added=added,
        clock=_clock_snapshot(room.backend.clock),
    ))
    return "granted" if added > 0 else "capped"


async def _notify_opp_state(connections, room, color, state):
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, ConnectionStatusMessage(opp_state=state))


async def set_resyncing(connections, room, color):
    slot = room.slot(color)
    if slot is not None and not slot.desync_active:
        slot.desync_active = True
        await _notify_opp_state(connections, room, color, "resyncing")


async def clear_resyncing(app, room, color):
    slot = room.slot(color)
    if slot is None or not slot.desync_active:
        return
    slot.desync_active = False
    _resync_gate(app).reopen((room.room_id, color, RESYNC_NOTIFY), app.state.now(),
                             RESYNC_NOTIFY_FLAP_FLOOR_SECONDS)
    await _notify_opp_state(app.state.connections, room, color, "connected")


async def handle_ping(app, websocket, room, color, raw):
    connections = app.state.connections
    try:
        msg = PingMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid_ping"
    await send(connections.get_for_color(room, color), PongMessage())
    if room.result is not None or room.backend is None:
        return "ping"
    if room.pending_skillcheck is not None:
        return "ping_pending"
    if msg.ply == len(room.backend.move_history):
        await clear_resyncing(app, room, color)
        return "ping"
    gate = _resync_gate(app)
    now = app.state.now()
    slot = room.slot(color)
    if (slot is not None and not slot.desync_active
            and gate.allow((room.room_id, color, RESYNC_NOTIFY), now,
                           RESYNC_NOTIFY_MIN_INTERVAL_SECONDS)):
        await set_resyncing(connections, room, color)
    if gate.allow((room.room_id, color, RESYNC_DIRECTIVE), now,
                  RESYNC_DIRECTIVE_MIN_INTERVAL_SECONDS):
        await send(connections.get_for_color(room, color), ResyncDirectiveMessage())
    return "ping"


async def _relay_guard(websocket, room, color, limiter, msg_type):
    if room.backend is None or room.result is not None:
        return "noop"
    if not limiter.hit(room.slot(color).client_uuid):
        await send(websocket, ErrorMessage(reason=Reason.RATE_LIMITED, msg_type=msg_type))
        return "rate_limited"
    return None


async def handle_annotations_state(app, websocket, room, color, raw):
    connections = app.state.connections
    verdict = await _relay_guard(websocket, room, color,
                                 app.state.annotation_limiter, "annotations_state")
    if verdict is not None:
        return verdict
    try:
        msg = AnnotationsStateMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    store = room.annotations_for(color)
    if msg.sharing and store.share_muted and app.state.moderation_enabled:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.SHARE_MUTED, msg_type="annotations_state"))
        return "muted"
    if msg.sharing and _over_moderation_budget(app, room, color):
        return await _suppress_sharing(app, room, color, "annotations_state")
    was_sharing = store.sharing
    if msg.sharing != store.sharing:
        log.info("annotations sharing room=%s by=%s on=%s",
                 room.room_id, color, msg.sharing)
    store.sharing = msg.sharing
    if not msg.sharing:
        store.clear_marks()
        await _relay_plain(connections, room, color,
                           AnnotationsStateMessage(sharing=False, highlights=[], arrows=[]))
        return "relayed"
    if not was_sharing:
        store.opp_hidden_notice_sent = False
    store.highlights = set(msg.highlights)
    store.arrows = [(a.from_sq, a.to_sq) for a in msg.arrows]
    return await _relay_or_moderate(app, room, color, msg, None, "annotations_state")


async def handle_annotation_delta(app, websocket, room, color, raw):
    connections = app.state.connections
    verdict = await _relay_guard(websocket, room, color,
                                 app.state.annotation_limiter, "annotation_delta")
    if verdict is not None:
        return verdict
    try:
        msg = AnnotationDeltaMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    if msg.kind == "highlight":
        if msg.square is None:
            return "invalid"
    else:
        if msg.from_sq is None or msg.to_sq is None or msg.from_sq == msg.to_sq:
            return "invalid"
    store = room.annotations_for(color)
    if store.share_muted and app.state.moderation_enabled:
        await send(connections.get_for_color(room, color),
                     ErrorMessage(reason=Reason.SHARE_MUTED, msg_type="annotation_delta"))
        return "muted"
    if _over_moderation_budget(app, room, color):
        return await _suppress_sharing(app, room, color, "annotation_delta")
    if msg.kind == "highlight":
        if msg.action == "add":
            if (msg.square not in store.highlights
                    and len(store.highlights) >= MAX_SHARED_HIGHLIGHTS):
                return "capped"
            store.highlights.add(msg.square)
        else:
            store.highlights.discard(msg.square)
        changed = msg.square if msg.action == "add" else None
    else:
        pair = (msg.from_sq, msg.to_sq)
        if msg.action == "add":
            if pair not in store.arrows:
                if len(store.arrows) >= MAX_SHARED_ARROWS:
                    return "capped"
                store.arrows.append(pair)
        elif pair in store.arrows:
            store.arrows.remove(pair)
        changed = pair if msg.action == "add" else None
    return await _relay_or_moderate(app, room, color, msg, changed, "annotation_delta")


def _last_move_context(room):
    if not room.backend.move_history:
        return ()
    move = room.backend.move_history[-1].move
    return (coord_from_square(move.from_sq), coord_from_square(move.to_sq))


def _moderation_inputs(room, color):
    store = room.annotations_for(color)
    opp_store = room.annotations_for(room.opp_color(color))
    return (list(store.arrows), set(store.highlights),
            list(opp_store.arrows), set(opp_store.highlights),
            _last_move_context(room))


def _over_moderation_budget(app, room, color):
    if not app.state.moderation_enabled:
        return False
    return _moderation_load(app).over_budget(room.room_id, color, app.state.now())


async def _suppress_sharing(app, room, color, msg_type):
    connections = app.state.connections
    store = room.annotations_for(color)
    stopped = store.sharing
    store.sharing = False
    store.clear_marks()
    if stopped:
        log.warning("annotations load-suppressed room=%s color=%s", room.room_id, color)
        await _relay_plain(connections, room, color,
                           AnnotationsStateMessage(sharing=False, highlights=[], arrows=[]))
    await send(connections.get_for_color(room, color),
               ErrorMessage(reason=Reason.RATE_LIMITED, msg_type=msg_type))
    return "load_suppressed"


def _moderate(own_arrows, own_highlights, opp_arrows, opp_highlights, context, changed):
    own = detector.detect(own_arrows, own_highlights, changed=changed, context=context)
    if own.kind == detector.BLOCKED:
        return own, False
    union_arrows, union_highlights = detector.union_sides(
        own_arrows, own_highlights, opp_arrows, opp_highlights)
    union = detector.detect(union_arrows, union_highlights,
                            changed=changed, context=context)
    if union.kind == detector.BLOCKED:
        return union, True
    if own.kind == detector.SUSPECT:
        return own, False
    return None, False


def _own_matched(store, verdict):
    arrows = [a for a in verdict.matched_arrows if (a[0], a[1]) in store.arrows]
    highlights = [h for h in verdict.matched_highlights if h in store.highlights]
    return arrows, highlights


async def _relay_or_moderate(app, room, color, msg, changed, msg_type):
    if not app.state.moderation_enabled:
        await _relay_to_opp(app, room, color, msg, msg_type)
        return "relayed"
    return await _moderate_relay(app, room, color, msg, changed, msg_type)


def _timed_moderate(*args):
    started = time.thread_time()
    return _moderate(*args), time.thread_time() - started


async def _moderate_relay(app, room, color, relay_msg, changed, msg_type):
    load = _moderation_load(app)
    inputs = _moderation_inputs(room, color)
    try:
        await asyncio.wait_for(load.semaphore.acquire(), load.admission_timeout)
    except asyncio.TimeoutError:
        log.warning("moderation admission timed out room=%s color=%s", room.room_id, color)
        return await _suppress_sharing(app, room, color, msg_type)
    try:
        outcome, cpu_seconds = await asyncio.to_thread(_timed_moderate, *inputs, changed)
    finally:
        load.semaphore.release()
    load.charge(room.room_id, color, cpu_seconds, app.state.now())
    verdict, is_union = outcome
    if room.backend is None or room.result is not None:
        return "noop"
    if verdict is None:
        await _relay_to_opp(app, room, color, relay_msg, msg_type)
        return "relayed"
    if verdict.kind == detector.BLOCKED:
        await _handle_block(app, room, color, verdict, is_union)
        return "blocked"
    await _relay_to_opp(app, room, color, relay_msg, msg_type)
    log.warning("marks suspect room=%s color=%s pattern=%s",
                room.room_id, color, str(verdict.pattern_id))
    store = room.annotations_for(color)
    sus_arrows, sus_highlights = _own_matched(store, verdict)
    await send(app.state.connections.get_for_color(room, color),
                 AnnotationsBlockedMessage(
                     action="suspect",
                     highlights=sus_highlights,
                     arrows=_arrow_wires(sus_arrows),
                     share_muted=store.share_muted))
    return "suspect"


async def _handle_block(app, room, color, verdict, is_union):
    connections = app.state.connections
    store = room.annotations_for(color)
    opp_color = room.opp_color(color)
    own_arrows, own_highlights = _own_matched(store, verdict)
    store.strip(verdict.matched_arrows, verdict.matched_highlights)
    if is_union:
        room.annotations_for(opp_color).strip(
            verdict.matched_arrows, verdict.matched_highlights)
    muted = store.register_trip(MODERATION_TRIP_LIMIT)
    log.warning("marks blocked room=%s color=%s pattern=%s trip=%d muted=%s",
                room.room_id, color, str(verdict.pattern_id),
                store.trip_count, muted)
    await _corrective_snapshot(app, room, color)
    if is_union:
        await _corrective_snapshot(app, room, opp_color)
    await send(connections.get_for_color(room, color),
                 AnnotationsBlockedMessage(
                     action="blocked",
                     highlights=own_highlights,
                     arrows=_arrow_wires(own_arrows),
                     share_muted=muted))


async def _corrective_snapshot(app, room, source_color):
    connections = app.state.connections
    target_color = room.opp_color(source_color)
    if room.hides_opponent_marks(target_color):
        return
    target_ws = connections.get_for_color(room, target_color)
    if target_ws is None:
        return
    store = room.annotations_for(source_color)
    await send(target_ws, AnnotationsStateMessage(
        sharing=True, highlights=sorted(store.highlights),
        arrows=_arrow_wires(store.arrows)))


async def _relay_plain(connections, room, color, msg):
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, msg)


async def _relay_to_opp(app, room, color, msg, msg_type):
    connections = app.state.connections
    opp_color = room.opp_color(color)
    if room.hides_opponent_marks(opp_color):
        store = room.annotations_for(color)
        if not store.opp_hidden_notice_sent:
            store.opp_hidden_notice_sent = True
            await send(connections.get_for_color(room, color),
                         ErrorMessage(reason=Reason.OPP_HIDES_MARKS, msg_type=msg_type))
        return
    opp_ws = connections.get_for_color(room, opp_color)
    if opp_ws is not None:
        await send(opp_ws, msg)


async def handle_set_marks_visibility(app, websocket, room, color, raw):
    connections = app.state.connections
    try:
        msg = SetMarksVisibilityMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    slot = room.slot(color)
    if slot is None or slot.hide_opp_marks == msg.hide_opp:
        return "noop"
    slot.hide_opp_marks = msg.hide_opp
    log.info("marks visibility room=%s color=%s hide_opp=%s",
             room.room_id, color, msg.hide_opp)
    if msg.hide_opp:
        return "hidden"
    opp_store = room.annotations_for(room.opp_color(color))
    await send(connections.get_for_color(room, color), AnnotationsStateMessage(
        sharing=opp_store.sharing, highlights=sorted(opp_store.highlights),
        arrows=_arrow_wires(opp_store.arrows)))
    return "shown"


async def handle_quick_chat(app, websocket, room, color, raw):
    connections = app.state.connections
    verdict = await _relay_guard(websocket, room, color,
                                 app.state.chat_limiter, "quick_chat")
    if verdict is not None:
        return verdict
    try:
        msg = QuickChatMessage.model_validate_json(raw)
    except ValidationError:
        return "invalid"
    log.info("quick chat room=%s by=%s preset=%d", room.room_id, color, msg.preset)
    opp_ws = connections.get_for_color(room, room.opp_color(color))
    if opp_ws is not None:
        await send(opp_ws, QuickChatReceivedMessage(preset=msg.preset, sender=color))
    return "relayed"


HANDLERS = {
    "move": handle_move,
    "resign": handle_resign,
    "draw_offer": handle_draw_offer,
    "draw_response": handle_draw_response,
    "rematch_request": handle_rematch_request,
    "rematch_response": handle_rematch_response,
    "left_result": handle_left_result,
    "takeback_request": handle_takeback_request,
    "takeback_response": handle_takeback_response,
    "give_time": handle_give_time,
    "ping": handle_ping,
    "skill_check_shot": handle_skill_check_shot,
    "annotations_state": handle_annotations_state,
    "annotation_delta": handle_annotation_delta,
    "set_marks_visibility": handle_set_marks_visibility,
    "quick_chat": handle_quick_chat,
}
