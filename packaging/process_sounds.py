#!/usr/bin/env python3
"""Offline sound-processing pipeline for Chess Shootout.

Takes raw downloads (any format ffmpeg reads) and produces the final, normalized
OGG assets under ``assets/sounds/`` exactly where SoundManager expects them.

Per file the pipeline:
  1. trims leading/trailing silence (skipped for seamless loops),
  2. loudness-normalizes  -- short SFX to a -1.5 dBTP peak, sustained clips/loops
     to -16 LUFS (two-pass) -- matching the existing shipped set,
  3. encodes to OGG Vorbis and drops it at the right path.

Multi-sample source files (e.g. a recording with several gunshots) can be cut
into separate clips first with ``--split``.

Workflow
--------
1. Drop raw downloads into ``sound_staging/<slot>/`` (one folder per slot id;
   any filename, any format). For pool slots add as many files as you want --
   they become 01.ogg, 02.ogg, ... For one-shot slots the first file wins.
2. ``python packaging/process_sounds.py --list``        # show slots + targets
3. ``python packaging/process_sounds.py --split raw.wav gun_revolver_pawn``
                                                          # cut a multi-shot file
4. ``python packaging/process_sounds.py``                # process every staged slot
   or ``python packaging/process_sounds.py gun_revolver_pawn move_queen``

``sound_staging/`` is gitignored; only the finished assets are committed.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets" / "sounds"
STAGING = REPO_ROOT / "sound_staging"

SUSTAINED_LUFS = -16.0
PEAK_TP = -1.5            # dBTP ceiling for short SFX and the LUFS true-peak cap
LRA = 11.0
TRIM_THRESHOLD = "-50dB"
SPLIT_SILENCE_DB = "-40dB"
SPLIT_MIN_SILENCE = 0.18  # seconds of silence that separates two samples
SPLIT_MIN_CLIP = 0.05     # discard fragments shorter than this
VORBIS_QSCALE = "6"

LOUDNORM_BASE = f"loudnorm=I={SUSTAINED_LUFS}:TP={PEAK_TP}:LRA={LRA}"

SOURCE_EXTS = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a", ".opus")

# kind: "pool" -> out is a directory, files become NN.ogg
#       "oneshot" -> out is a file path
# profile: "short" (peak-normalize) | "sustained" (-16 LUFS) | "loop" (-16 LUFS, no trim)


@dataclass(frozen=True)
class Slot:
    out: str
    kind: str
    profile: str


GUN_SLOTS = {
    "gun_revolver_pawn": "revolver",
    "gun_handcannon_knight": "hand_cannon",
    "gun_sniper_bishop": "lever_action",
    "gun_shotgun_rook": "shotgun",
    "gun_blunderbuss_queen": "blunderbuss",
}

MOVE_PIECES = ("pawn", "knight", "bishop", "rook", "queen", "king")

ANNOUNCER_PHRASES = (
    "first_blood", "double_kill", "triple_kill", "quadra_kill",
    "rampage", "unstoppable", "godlike",
)


def _build_manifest():
    m = {}
    for slot, gun in GUN_SLOTS.items():
        m[slot] = Slot(f"guns/{gun}", "pool", "short")
    m["reload_check"] = Slot("guns/shotgun_reloads", "pool", "short")
    for piece in MOVE_PIECES:
        m[f"move_{piece}"] = Slot(f"piece_moves/{piece}", "pool", "short")
    # special / lifecycle
    m["castle"] = Slot("castle_sound.ogg", "oneshot", "short")
    m["checkmate"] = Slot("metal_pipe_falling.ogg", "oneshot", "short")
    m["undo"] = Slot("rewind.ogg", "oneshot", "short")
    m["game_start"] = Slot("game_start.ogg", "oneshot", "sustained")
    m["resign"] = Slot("surrender.ogg", "oneshot", "sustained")
    m["draw"] = Slot("draw.ogg", "oneshot", "sustained")
    m["you_lose"] = Slot("you_lose.ogg", "oneshot", "sustained")
    # time
    m["heartbeat"] = Slot("heartbeat.ogg", "oneshot", "loop")
    m["give_time"] = Slot("give_time.ogg", "oneshot", "short")
    # announcer
    for phrase in ANNOUNCER_PHRASES:
        m[f"announcer_{phrase}"] = Slot(f"announcer/{phrase}.ogg", "oneshot", "sustained")
    m["announcer_hits"] = Slot("announcer/hits", "pool", "short")
    # skill-check feedback
    m["sc_appear"] = Slot("skillcheck_appear.ogg", "oneshot", "short")
    m["wheel_tick"] = Slot("wheel_tick.ogg", "oneshot", "short")
    m["sc_win"] = Slot("skillcheck_win.ogg", "oneshot", "short")
    m["sc_miss"] = Slot("skillcheck_miss.ogg", "oneshot", "short")
    m["aim_lock"] = Slot("aim_lock.ogg", "oneshot", "short")
    m["aim_beep"] = Slot("aim_beep.ogg", "oneshot", "short")
    m["swear"] = Slot("swears", "pool", "short")
    # ui / board  (both ui_click candidates kept side by side for A/B; rename the
    # winner to ui_click.ogg once chosen)
    m["ui_click_typewriter"] = Slot("ui_click_typewriter.ogg", "oneshot", "short")
    m["ui_click_hammer"] = Slot("ui_click_hammer.ogg", "oneshot", "short")
    m["toast_pop"] = Slot("toast_pop.ogg", "oneshot", "short")
    m["board_flip"] = Slot("flip_whoosh.ogg", "oneshot", "short")
    m["pickup"] = Slot("pickup.ogg", "oneshot", "short")
    m["drop"] = Slot("drop.ogg", "oneshot", "short")
    return m


MANIFEST = _build_manifest()

DRY_RUN = False


def run(cmd, capture=False):
    if DRY_RUN:
        print("  $", " ".join(str(c) for c in cmd))
        return ""
    result = subprocess.run(cmd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE)
    return result.stdout if capture else ""


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _trim_filter():
    one = ("silenceremove=start_periods=1:start_silence=0:"
           f"start_threshold={TRIM_THRESHOLD}:detection=peak")
    return f"{one},areverse,{one},areverse"


def _measure_peak_db(path):
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        check=True, text=True, stderr=subprocess.PIPE)
    match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", proc.stderr)
    return float(match.group(1)) if match else 0.0


def _measure_loudnorm(path, af_prefix):
    af = f"{af_prefix}{LOUDNORM_BASE}:print_format=json"
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", af, "-f", "null", "-"],
        check=True, text=True, stderr=subprocess.PIPE)
    block = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.DOTALL)
    return json.loads(block.group(0)) if block else {}


def _encode_ogg(in_path, out_path, af):
    cmd = ["ffmpeg", "-y", "-i", str(in_path)]
    if af:
        cmd += ["-af", af]
    cmd += ["-c:a", "libvorbis", "-qscale:a", VORBIS_QSCALE, str(out_path)]
    run(cmd)


def process_one(src, out_path, profile):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trim = "" if profile == "loop" else _trim_filter()

    if profile in ("sustained", "loop"):
        prefix = f"{trim}," if trim else ""
        if DRY_RUN:
            print(f"  measure loudnorm + encode {out_path.name}")
            _encode_ogg(src, out_path, f"{prefix}{LOUDNORM_BASE}")
            return
        s = _measure_loudnorm(src, prefix)
        measured = ""
        if s:
            measured = (f":measured_I={s['input_i']}:measured_TP={s['input_tp']}"
                        f":measured_LRA={s['input_lra']}:measured_thresh={s['input_thresh']}"
                        f":offset={s['target_offset']}:linear=true")
        _encode_ogg(src, out_path, f"{prefix}{LOUDNORM_BASE}{measured}")
        return

    # short: trim, then peak-normalize the trimmed audio to PEAK_TP.
    with tempfile.TemporaryDirectory() as td:
        trimmed = Path(td) / "trim.wav"
        run(["ffmpeg", "-y", "-i", str(src), "-af", trim, str(trimmed)])
        if DRY_RUN:
            print(f"  peak-normalize + encode {out_path.name}")
            _encode_ogg(src, out_path, trim)
            return
        peak = _measure_peak_db(trimmed)
        gain = PEAK_TP - peak
        _encode_ogg(trimmed, out_path, f"volume={gain:.2f}dB")


def staged_files(slot_dir):
    return sorted(p for p in slot_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in SOURCE_EXTS)


def process_slot(slot_id):
    slot = MANIFEST[slot_id]
    slot_dir = STAGING / slot_id
    if not slot_dir.is_dir():
        print(f"[skip] {slot_id}: no staging dir ({slot_dir.relative_to(REPO_ROOT)})")
        return 0
    files = staged_files(slot_dir)
    if not files:
        print(f"[skip] {slot_id}: staging dir empty")
        return 0

    if slot.kind == "pool":
        out_dir = ASSETS / slot.out
        print(f"[pool] {slot_id} -> {slot.out}/ ({len(files)} files)")
        for i, src in enumerate(files, start=1):
            process_one(src, out_dir / f"{i:02d}.ogg", slot.profile)
        return len(files)

    out_path = ASSETS / slot.out
    if len(files) > 1:
        print(f"[note] {slot_id}: {len(files)} staged, using first ({files[0].name})")
    print(f"[one ] {slot_id} -> {slot.out}")
    process_one(files[0], out_path, slot.profile)
    return 1


def split_file(src, slot_id):
    """Cut a multi-sample recording into the slot's staging dir on silence."""
    if slot_id not in MANIFEST:
        sys.exit(f"unknown slot: {slot_id}")
    proc = subprocess.run(
        ["ffmpeg", "-i", str(src), "-af",
         f"silencedetect=noise={SPLIT_SILENCE_DB}:d={SPLIT_MIN_SILENCE}", "-f", "null", "-"],
        check=True, text=True, stderr=subprocess.PIPE)
    starts = [0.0]
    ends = []
    for m in re.finditer(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)", proc.stderr):
        kind, t = m.group(1), float(m.group(2))
        if kind == "start":
            ends.append(t)
        else:
            starts.append(t)
    total = ffprobe_duration(src)
    ends.append(total)
    segments = [(s, e) for s, e in zip(starts, ends) if e - s >= SPLIT_MIN_CLIP]

    dest = STAGING / slot_id
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[split] {src.name} -> {len(segments)} clips in {dest.relative_to(REPO_ROOT)}/")
    for i, (s, e) in enumerate(segments, start=1):
        out = dest / f"{src.stem}_{i:02d}.wav"
        run(["ffmpeg", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", str(src), str(out)])


def cmd_list():
    print(f"staging root: {STAGING}")
    print(f"assets root:  {ASSETS}\n")
    for slot_id, slot in MANIFEST.items():
        tag = "pool" if slot.kind == "pool" else "one "
        print(f"  {slot_id:28s} [{tag}] {slot.profile:9s} -> {slot.out}")


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Process raw sound downloads into game OGG assets.")
    ap.add_argument("slots", nargs="*", help="slot ids to process (default: all staged)")
    ap.add_argument("--list", action="store_true", help="list slots and their targets")
    ap.add_argument("--dry-run", action="store_true", help="print actions without running ffmpeg")
    ap.add_argument("--split", nargs=2, metavar=("FILE", "SLOT"),
                    help="cut a multi-sample FILE into SLOT's staging dir on silence")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg/ffprobe not found on PATH")

    if args.list:
        cmd_list()
        return
    if args.split:
        split_file(Path(args.split[0]), args.split[1])
        return

    targets = args.slots or list(MANIFEST.keys())
    unknown = [s for s in targets if s not in MANIFEST]
    if unknown:
        sys.exit(f"unknown slot(s): {', '.join(unknown)}")

    total = 0
    for slot_id in targets:
        total += process_slot(slot_id)
    print(f"\nDone. {total} file(s) processed.")


if __name__ == "__main__":
    main()
