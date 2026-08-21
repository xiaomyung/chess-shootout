import random
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pygame as pg

from chessshootout.backend.pieces import PieceType
from chessshootout.infra import env
from chessshootout.frontend.visual.clock_visual import LOW_TIME_FRACTION
from chessshootout.frontend.audio.slots import SLOTS, move_slot, gun_slot, hit_slot


@dataclass
class HeartbeatConfig:
    """
    How the low-time heartbeat behaves: when it starts, when it doubles its
    pace, and the volume range it swells through as the clock runs out. The
    defaults are the tuned feel; tests build their own to force a transition
    """

    start_fraction: float = LOW_TIME_FRACTION
    fast_fraction: float = 0.05
    min_volume: float = 0.10
    max_volume: float = 1.0
    fade_in_ms: int = 400
    fade_out_ms: int = 300


STATE_OFF = "off"
STATE_SLOW = "slow"
STATE_FAST = "fast"

ONESHOT_FADE_MS = 20


def _clamp_volume(value: float) -> float:
    """
    Keep a volume inside the range the mixer will accept, so that a stored
    setting or a dragged slider can never hand pygame a level it refuses

    :param value: the wanted level, anything numeric
    :returns: that level held between 0.0 silent and 1.0 full
    """
    return max(0.0, min(1.0, float(value)))


class SoundManager:
    """
    Everything the game can be heard doing. One instance lives on the app shell
    and every screen plays through it by naming an event rather than a file --
    a move, a capture, a kill streak, a button. Each sound is a folder loaded
    on first use, so a machine whose mixer never started, or a folder left
    empty on purpose, simply plays nothing instead of failing
    """

    def __init__(self, sounds_dir: str | Path, *, enabled: bool = True,
                 heartbeat: HeartbeatConfig | None = None,
                 heartbeat_channel: pg.mixer.Channel | None = None,
                 master_volume: float | None = None,
                 menu_volume: float | None = None) -> None:
        """
        Set the game's audio up: remember where the sound folders live, take
        the volumes the player last settled on unless they are passed in, and
        claim the one mixer channel the looping heartbeat owns. Nothing is read
        off disk here

        :param sounds_dir: folder the processed sound folders sit under
        :param enabled: False when the mixer failed to start or the player has
            sound switched off, which makes every play call a no-op
        :param heartbeat: low-time heartbeat tuning, None for the tuned
            defaults
        :param heartbeat_channel: mixer channel the heartbeat loop owns, None
            to claim one; tests pass a stand-in
        :param master_volume: level everything plays at, None to take the
            saved one
        :param menu_volume: extra level for the menu's background gunfight,
            None to take the saved one
        """
        self.enabled = enabled
        self.master_volume = (
            env.get_master_volume() if master_volume is None
            else _clamp_volume(master_volume)
        )
        self.menu_volume = (
            env.get_menu_volume() if menu_volume is None
            else _clamp_volume(menu_volume)
        )
        self.heartbeat = heartbeat or HeartbeatConfig()
        self._state = STATE_OFF
        self._slots: dict[str, list[pg.mixer.Sound]] = {}

        self._sounds_dir = Path(sounds_dir)

        if not self.enabled:
            self._heartbeat_channel = None
            return

        self._heartbeat_channel = (
            heartbeat_channel if heartbeat_channel is not None
            else self._reserve_channel(0)
        )

    def preload(self) -> None:
        """
        Load every sound folder up front, run once at launch as soon as the
        window is up. Sounds are otherwise loaded the first time they are
        played, which would make the first shot of a game wait on the disk --
        this pays that cost while the menu is still opening
        """
        for name in SLOTS:
            self._slot_pool(name)

    def _slot_pool(self, name: str) -> list[pg.mixer.Sound]:
        """
        The loaded sounds behind one name, read off disk the first time they
        are asked for and kept from then on. A name with no folder and a folder
        with no files both give nothing back, which is how a sound left out on
        purpose stays a proper silence rather than an error

        :param name: slot name from the registry
        :returns: that slot's sounds, empty when there is nothing to play
        """
        if not self.enabled:
            return []
        pool = self._slots.get(name)
        if pool is None:
            spec = SLOTS.get(name)
            pool = self._load_pool(self._sounds_dir / spec.dst) if spec else []
            self._slots[name] = pool
        return pool

    def _load_pool(self, dir_path: Path) -> list[pg.mixer.Sound]:
        """
        Read one slot's folder into memory, in filename order so that the
        numbered files of a ladder line up with the step each one belongs to. A
        missing folder or an unreadable file is done without rather than raised

        :param dir_path: folder holding that slot's .ogg files
        :returns: the sounds that loaded, in filename order
        """
        if not dir_path.is_dir():
            return []
        return [s for p in sorted(dir_path.glob("*.ogg"))
                if (s := self._safe_load(p)) is not None]

    @staticmethod
    def _safe_load(path: Path) -> pg.mixer.Sound | None:
        """
        Load one sound file, treating a missing or broken one as something to
        do without rather than a reason to stop -- the game stays playable in
        silence

        :param path: the .ogg file to load
        :returns: the loaded sound, or None when it could not be read
        """
        try:
            return pg.mixer.Sound(str(path))
        except (pg.error, FileNotFoundError):
            return None

    @staticmethod
    def _reserve_channel(idx: int) -> pg.mixer.Channel | None:
        """
        Claim one mixer channel for the game's own use and keep pygame's
        automatic channel picking off it, so that the looping heartbeat can
        never be cut short by an ordinary sound landing on top of it

        :param idx: channel number to claim
        :returns: the reserved channel, or None when the mixer has none to give
        """
        try:
            channel = pg.mixer.Channel(idx)
            pg.mixer.set_reserved(idx + 1)
            return channel
        except pg.error:
            return None

    def set_master_volume(self, value: float) -> None:
        """
        Set the level everything plays at, behind the volume control on the
        rail and the one in Options. It applies to the next sound played rather
        than to anything already sounding

        :param value: wanted level, held to 0.0 silent through 1.0 full
        """
        self.master_volume = _clamp_volume(value)

    def set_menu_volume(self, value: float) -> None:
        """
        Set the extra level for the menu's background gunfight, so the backdrop
        can be turned right down without quieting the game itself

        :param value: wanted level, held to 0.0 silent through 1.0 full
        """
        self.menu_volume = _clamp_volume(value)

    def set_enabled(self, value: bool) -> None:
        """
        Turn the game's sound on or off, behind the speaker button on the rail
        and the switch in Options. Switching it off also fades the looping
        heartbeat out, which would otherwise carry on unheard

        :param value: True for sound, False for silence
        """
        new_enabled = bool(value)
        if not new_enabled and self.enabled:
            self.stop_all()
        self.enabled = new_enabled

    def _play_at(self, sound: pg.mixer.Sound, volume: float) -> None:
        """
        Play one sound at a given level, the single place playback actually
        happens. Every one-shot gets a very short fade in, which is what keeps
        a hard start from clicking

        :param sound: the loaded sound to play
        :param volume: level to play it at, 0.0 through 1.0
        """
        sound.set_volume(volume)
        sound.play(fade_ms=ONESHOT_FADE_MS)

    def _play_with_master(self, sound: pg.mixer.Sound) -> None:
        """
        Play one sound at the master volume, which is the level almost
        everything in the game uses

        :param sound: the loaded sound to play
        """
        self._play_at(sound, self.master_volume)

    def _play_random_at(self, sounds: list[pg.mixer.Sound], volume: float) -> None:
        """
        Play one of a slot's takes at a given level, picked at random so a
        sound heard again and again does not come out identical every time.
        Silence when sound is off or the slot holds nothing

        :param sounds: that slot's loaded takes, possibly empty
        :param volume: level to play at, 0.0 through 1.0
        """
        if not self.enabled or not sounds:
            return
        self._play_at(random.choice(sounds), volume)

    def _play_random(self, sounds: list[pg.mixer.Sound]) -> None:
        """
        Play one of a slot's takes at the master volume, picked at random.
        Silence when sound is off or the slot holds nothing

        :param sounds: that slot's loaded takes, possibly empty
        """
        if not self.enabled or not sounds:
            return
        self._play_with_master(random.choice(sounds))

    def _play(self, slot: str) -> None:
        """
        Play a slot by name, the route almost every play method here takes:
        load the folder if it has not been loaded yet, then pick one of its
        takes at random

        :param slot: slot name from the registry
        """
        self._play_random(self._slot_pool(slot))

    def _play_indexed(self, slot: str, index: int) -> None:
        """
        Play one exact step of a slot, used where the files in a folder are an
        ordered ladder rather than interchangeable takes -- the rising hit
        sounds a whack or combo streak climbs. Past the last step it keeps
        playing the top one, so a long streak never runs out of ladder

        :param slot: slot name whose files are an ordered ladder
        :param index: step to play, counted from 0 and clamped to the ladder
        """
        pool = self._slot_pool(slot)
        if not self.enabled or not pool:
            return
        self._play_with_master(pool[max(0, min(int(index), len(pool) - 1))])

    def play_move(self, piece_type: PieceType | None = None) -> None:
        """
        Sound a piece landing on its square, chosen by what kind of piece it is
        so a rook does not land like a pawn

        :param piece_type: the piece that moved, None to stay silent
        """
        if piece_type is None:
            return
        self._play(move_slot(piece_type.value))

    def play_premove_queued(self, piece_type: PieceType | None = None) -> None:
        """
        Sound a premove being lined up, so an order given during the opponent's
        turn is acknowledged at once instead of waiting for their move. It
        borrows the piece's own move sound

        :param piece_type: the piece being premoved, None to stay silent
        """
        self.play_move(piece_type)

    def play_capture(self, piece_type: PieceType | None = None) -> None:
        """
        Fire the capturing piece's weapon -- the bang of a Shootout capture,
        with every kind of piece carrying a different gun

        :param piece_type: the piece doing the capturing, None to stay silent
        """
        if piece_type is None:
            return
        self._play(gun_slot(piece_type.value))

    def play_menu_gun(self, gun: str) -> None:
        """
        Fire one shot in the menu's background gunfight. It plays at the master
        volume scaled by the menu level, so the backdrop can be kept quieter
        than the game itself

        :param gun: weapon name from the piece-to-weapon table
        """
        self._play_random_at(self._slot_pool(f"gun_{gun}"),
                             self.master_volume * self.menu_volume)

    def play_check(self) -> None:
        """
        Rack a weapon when a move gives check, the game's sound for a king
        under threat. It plays alongside the check gun the board draws
        """
        self._play("reload_check")

    def play_announcer(self, key: str) -> None:
        """
        Call a kill streak out in the arena-shooter announcer voice, from first
        blood up to godlike. The game screen keeps this quiet once a result is
        in, so a mating capture is never talked over

        :param key: streak name, the tail of the announcer slot to play
        """
        self._play(f"announcer_{key}")

    def play_hit(self, victim: PieceType | None = None) -> None:
        """
        Grunt for the piece just shot off the board, the moment the bullet
        lands. A captured queen has a voice of her own; every other piece
        shares one

        :param victim: the piece that was taken, None for the shared voice
        """
        slot = hit_slot(victim.value) if victim is not None else "announcer_hits"
        self._play(slot)

    def play_checkmate(self) -> None:
        """
        Sound the game being won outright, played instead of the moving piece's
        own sound on the mating move
        """
        self._play("checkmate")

    def play_castle(self) -> None:
        """
        Sound the king tucking away behind his rook, played instead of the
        ordinary move sound whenever a castle lands
        """
        self._play("castle")

    def play_undo(self) -> None:
        """
        Sound a move being taken back, whether by the undo button in a local
        game or by a takeback the opponent agreed to online
        """
        self._play("undo")

    def play_game_start(self) -> None:
        """
        Announce a new game beginning, played as the board opens for a local
        game and for a rematch
        """
        self._play("game_start")

    def play_online_game_start(self) -> None:
        """
        Announce an online game beginning -- its own call, since finding a real
        opponent is worth more than starting a game against the person next to
        you
        """
        self._play("online_game_start")

    def play_give_time(self) -> None:
        """
        Sound seconds being handed to the opponent, played to both players so
        each hears the gift land on the clock
        """
        self._play("give_time")

    def play_you_win(self) -> None:
        """
        Call the player's own victory as the result comes up, the win half of
        the announcer's verdict on the game
        """
        self._play("you_win")

    def play_you_lose(self) -> None:
        """
        Call the player's own defeat as the result comes up, the loss half of
        the announcer's verdict on the game
        """
        self._play("you_lose")

    def play_flag_fall(self) -> None:
        """
        Sound a clock running out. Online only the player who flagged hears it,
        since the opponent is given the victory call instead, and it borrows
        the defeat call because that is what a fallen flag amounts to
        """
        self._play("you_lose")

    def play_draw(self) -> None:
        """
        Call a drawn game as the result comes up, for every way a game can end
        level -- agreement, stalemate, repetition or too little material
        """
        self._play("draw")

    def play_resign(self) -> None:
        """
        Sound a player giving the game up, played as the surrender flag goes
        up on the board
        """
        self._play("resign")

    def play_toast(self) -> None:
        """
        Chirp as a new message appears in the toast bar, so a line that arrives
        while the player is looking at the board is still noticed
        """
        self._play("toast")

    def play_flip(self) -> None:
        """
        Sound the board being turned around, behind the flip button on the game
        and review screens
        """
        self._play("board_flip")

    def play_pickup(self) -> None:
        """
        Sound a piece being lifted off its square as a drag begins, the start
        of the handling feel a move has
        """
        self._play("pickup")

    def play_drop(self) -> None:
        """
        Sound a dragged piece being let go of, played when a drag ends without
        a move -- a landed move gets the piece's own move sound instead
        """
        self._play("drop")

    def play_swear(self) -> None:
        """
        Mutter under the shooter's breath when a steady-aim shot goes wide, the
        game's own reaction to a miss
        """
        self._play("swear")

    def play_ui_click(self) -> None:
        """
        The click a button in the interface makes, the game's standard press
        sound wherever nothing more specific fits
        """
        self._play("ui_click")

    def play_ui_tick(self) -> None:
        """
        The tick a slider makes as it passes a step, so a volume being dragged
        can be heard moving as well as seen
        """
        self._play("ui_tick")

    def play_give_ratchet(self) -> None:
        """
        The ratchet that counts up while the give-time button is held down, so
        the seconds about to be handed over can be heard being wound on
        """
        self._play("give_ratchet")

    def play_drum_tick(self) -> None:
        """
        The tick of the time picker's revolver drum as it turns through a
        setting, the menu's sound for choosing a time control
        """
        self._play("drum_tick")

    def play_turret_ratchet(self) -> None:
        """
        The heavier ratchet of the time picker's turret coming round to a new
        stop, the step above the drum's own tick
        """
        self._play("turret_ratchet")

    def play_card_toggle(self) -> None:
        """
        Sound a card on the menu's right rail opening or closing, so the
        accordion is heard moving as one card gives way to another
        """
        self._play("card_toggle")

    def play_rail_click(self) -> None:
        """
        Sound moving between views on the menu's command rail, the click of
        changing what the menu is showing
        """
        self._play("rail_click")

    def play_section_toggle(self) -> None:
        """
        Sound a section of the in-game rail folding open or shut, the game
        screen's counterpart to the menu's card toggle
        """
        self._play("section_toggle")

    def play_chip_toggle(self) -> None:
        """
        Sound one of the rail's signal chips being switched, the small press of
        turning a setting on or off in place
        """
        self._play("chip_toggle")

    def play_cap_press(self) -> None:
        """
        Sound one of the rail's cap buttons being pressed, the heavier press of
        the actions that sit along the top of the rail
        """
        self._play("cap_press")

    def play_vol_notch(self) -> None:
        """
        The notch the rail's volume control lands on as it is nudged, so a
        change in level is confirmed at the new level
        """
        self._play("vol_notch")

    def play_chat_receive(self) -> None:
        """
        Sound a quick-chat line arriving from the opponent, so something said
        during a game is noticed even mid-move
        """
        self._play("chat_receive")

    def play_focus_action(self) -> None:
        """
        Sound the interface collapsing into focus mode, where everything but
        the board is folded away
        """
        self._play("focus_action")

    def play_focus_action_off(self) -> None:
        """
        Sound focus mode being left and the full interface coming back around
        the board
        """
        self._play("focus_action_off")

    def play_skillcheck_appear(self) -> None:
        """
        Sound a skill check arriving on the board, the cue that a capture now
        has to be earned and the clock on it has started
        """
        self._play("sc_appear")

    def play_skillcheck_win(self) -> None:
        """
        Sound a skill check being passed, which is what lets the capture
        actually land
        """
        self._play("sc_win")

    def play_skillcheck_miss(self) -> None:
        """
        Sound a skill check being failed, which locks that capture away for the
        rest of the turn
        """
        self._play("sc_miss")

    def play_wheel_tick(self) -> None:
        """
        The tick of the wheel check's marker sweeping round, the pulse the
        player times their tap against
        """
        self._play("wheel_tick")

    def play_aim_lock(self) -> None:
        """
        Sound the steady-aim check locking onto its target, the moment the
        shooter has the shot lined up
        """
        self._play("aim_lock")

    def play_aim_beep(self) -> None:
        """
        The beep the steady-aim reticle gives as it crosses the target, the cue
        the player fires on
        """
        self._play("aim_beep")

    def play_mole_fall(self) -> None:
        """
        Sound the captured piece dropping into the whack-a-mole burrow, which
        is how that check opens
        """
        self._play("mole_fall")

    def play_mole_telegraph(self) -> None:
        """
        Sound a mole about to come up, the warning that gives the player just
        enough time to swing towards the hole
        """
        self._play("mole_telegraph")

    def play_mole_pop(self) -> None:
        """
        Sound a mole popping up out of a hole and becoming a target worth
        shooting at
        """
        self._play("mole_pop")

    def play_mole_heal(self) -> None:
        """
        Sound the mole healing back some of the damage done to it, the setback
        that can put a hit quota back out of reach
        """
        self._play("mole_heal")

    def play_whack_hit(self, index: int = 0) -> None:
        """
        Sound a mole being hit, climbing an ordered ladder of sounds so each
        hit in a run lands harder than the last and the top one is held once
        the ladder runs out

        :param index: how many hits have landed so far, counted from 0
        """
        self._play_indexed("whack_hit", index)

    def play_whack_kill(self) -> None:
        """
        Sound the shot that finishes the mole off and wins the whack check
        """
        self._play("whack_kill")

    def play_whack_dry(self) -> None:
        """
        Sound a trigger pull with nothing to fire, the dry click of shooting
        the whack gun when it has no shot to give
        """
        self._play("whack_dry")

    def play_mole_taunt(self) -> None:
        """
        Sound the mole jeering at the player, the game's way of rubbing a
        failed whack check in
        """
        self._play("mole_taunt")

    def play_whiff_ricochet(self) -> None:
        """
        Sound a whack shot going wide and bouncing off, the sound of one of the
        three whiffs that lose the check
        """
        self._play("whiff_ricochet")

    def play_combo_hit(self, index: int = 0) -> None:
        """
        Sound a correct press in the combo check, climbing an ordered ladder so
        a run of them builds and the top rung is held once the ladder runs out

        :param index: how many correct presses have landed, counted from 0
        """
        self._play_indexed("combo_hit", index)

    def play_combo_wrong(self) -> None:
        """
        Sound a wrong press in the combo check, one of the three that lose it
        """
        self._play("combo_wrong")

    def play_combo_complete(self) -> None:
        """
        Sound the whole combo being played through correctly, the flourish for
        winning that check
        """
        self._play("combo_complete")

    def play_combo_fail(self) -> None:
        """
        Sound the combo check being lost, whether by wrong presses or by
        running out of time
        """
        self._play("combo_fail")

    def play_combo_streak(self) -> None:
        """
        Sound a combo run catching fire, the extra flourish for pressing a long
        stretch of the prompts cleanly
        """
        self._play("combo_streak")

    def update_heartbeat(self, fraction_remaining: float | None, paused: bool) -> None:
        """
        Drive the heartbeat that quickens as a game runs out of road -- the
        tension under the last seconds, fed by whichever countdown is closest
        to ending: the clock, a disconnect grace period or an idle window. It
        starts slow, doubles its pace near the very end, and swells in volume
        the closer the countdown gets to nothing

        :param fraction_remaining: how much of that countdown is left, 1.0 down
            to 0.0, or None when nothing is counting down
        :param paused: True when the board is not live, which silences it
        """
        if not self.enabled:
            return
        desired = self._desired_state(fraction_remaining, paused)
        self._transition_to(desired)
        if desired in (STATE_SLOW, STATE_FAST) and self._heartbeat_channel is not None:
            self._heartbeat_channel.set_volume(
                self._heartbeat_volume(cast(float, fraction_remaining)))

    def _desired_state(self, fraction: float | None, paused: bool) -> str:
        """
        Decide which heartbeat ought to be sounding right now -- none, the slow
        one or the fast one. This is the only place the two thresholds are read

        :param fraction: how much of the countdown is left, or None for none
        :param paused: True when the board is not live
        :returns: off, slow or fast
        """
        cfg = self.heartbeat
        if paused or fraction is None or fraction > cfg.start_fraction:
            return STATE_OFF
        if fraction > cfg.fast_fraction:
            return STATE_SLOW
        return STATE_FAST

    def _transition_to(self, desired: str) -> None:
        """
        Move the heartbeat to the state asked for, doing nothing at all when it
        is already there. Stopping fades out rather than cutting off, and
        changing pace restarts the loop on the other recording

        :param desired: off, slow or fast
        """
        if desired == self._state:
            return
        cfg = self.heartbeat
        if desired == STATE_OFF:
            if self._heartbeat_channel is not None:
                self._heartbeat_channel.fadeout(cfg.fade_out_ms)
        else:
            self._start_heartbeat(desired)
        self._state = desired

    def _start_heartbeat(self, state: str) -> None:
        """
        Start the looping heartbeat on its own reserved channel, faded in so
        that it arrives rather than snaps on. A missing channel or an empty
        folder simply leaves the game quiet

        :param state: slow or fast, which picks the recording to loop
        """
        channel = self._heartbeat_channel
        if channel is None:
            return
        slot = "heartbeat_fast" if state == STATE_FAST else "heartbeat_slow"
        pool = self._slot_pool(slot)
        if not pool:
            return
        channel.play(random.choice(pool), loops=-1, fade_ms=self.heartbeat.fade_in_ms)

    def _heartbeat_volume(self, fraction: float) -> float:
        """
        Work out how loud the heartbeat should be at this instant: quiet as the
        countdown first crosses into low time, full by the moment it runs out,
        with the whole ramp scaled by the master volume

        :param fraction: how much of the countdown is left, 1.0 down to 0.0
        :returns: the level to set the heartbeat channel to
        """
        cfg = self.heartbeat
        if cfg.start_fraction <= 0:
            return cfg.max_volume * self.master_volume
        progress = (cfg.start_fraction - fraction) / cfg.start_fraction
        progress = max(0.0, min(progress, 1.0))
        base = cfg.min_volume + (cfg.max_volume - cfg.min_volume) * progress
        return base * self.master_volume

    def stop_all(self) -> None:
        """
        Fade the looping heartbeat out and forget its state, called whenever a
        game ends or a new one is set up so that tension left over from the
        last game never carries into the next
        """
        if not self.enabled:
            return
        cfg = self.heartbeat
        if self._heartbeat_channel is not None:
            self._heartbeat_channel.fadeout(cfg.fade_out_ms)
        self._state = STATE_OFF
