#!/usr/bin/env python3
"""Offline sound-processing pipeline for Chess Shootout.

Registry-driven: the single source of truth for every slot is
``chessshootout/frontend/audio/slots.py`` (imported below). Each slot maps a
staging directory (``assets/sounds/_staging/prefinal/<src>/``) to a final asset
directory (``assets/sounds/<dst>/``). Every slot is a *directory* of ``NN.ogg``
variants -- 0 files -> nothing shipped (silent no-op at runtime), 1 -> single,
N -> the runtime random pool. There is no one-shot/pool distinction here.

Per file the pipeline:
  1. trims leading/trailing silence (skipped for seamless loops),
  2. loudness-normalizes -- short SFX to a -1.5 dBTP peak, sustained clips / loops
     to -16 LUFS (two-pass),
  3. resamples to 44.1 kHz and downmixes to mono (SFX) or keeps stereo (voice/music),
  4. encodes to OGG Vorbis at qscale 6 and drops it at ``<dst>/NN.ogg``.

After a full run it validates every output (rate / channels / duration / no
clipping) and prints a per-slot summary; any FAIL exits non-zero. It also
regenerates the ``## Sounds`` section of the repo-root ``ATTRIBUTION.md`` from the
structured credit tables below (the two required CC-BY credits + the CC0
courtesy list).

Usage
-----
  python packaging/process_sounds.py --list          # slots + targets
  python packaging/process_sounds.py                 # full clean rebuild + validate + attribution
  python packaging/process_sounds.py move_queen gun_shotgun # rebuild only these slots
  python packaging/process_sounds.py --split raw.wav gun_revolver
  python packaging/process_sounds.py --attribution   # only regenerate ATTRIBUTION.md
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from chessshootout.frontend.audio.slots import SLOTS, SHORT, SUSTAINED, LOOP  # noqa: E402

ASSETS = REPO_ROOT / "assets" / "sounds"
STAGING = ASSETS / "_staging" / "prefinal"
ATTRIBUTION_PATH = REPO_ROOT / "ATTRIBUTION.md"

SAMPLE_RATE = 44100
SUSTAINED_LUFS = -16.0
PEAK_TP = -1.5            # dBTP ceiling for short SFX and the LUFS true-peak cap
LRA = 11.0
TRIM_THRESHOLD = "-50dB"
SPLIT_SILENCE_DB = "-40dB"
SPLIT_MIN_SILENCE = 0.18
SPLIT_MIN_CLIP = 0.05
VORBIS_QSCALE = "6"

LOUDNORM_BASE = f"loudnorm=I={SUSTAINED_LUFS}:TP={PEAK_TP}:LRA={LRA}"
SOURCE_EXTS = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a", ".opus")

# validation tolerances
QUIET_PEAK_DB = -9.0     # short outputs quieter than this after peak-norm are suspicious
CLIP_PEAK_DB = 0.0

DRY_RUN = False


# --------------------------------------------------------------------------
# attribution (structured -- NOT parsed from prose)
# --------------------------------------------------------------------------

ATTRIBUTION_CC_BY = [
    dict(who="jkerman", title="Old-school arena FPS announcer voice lines",
         url="https://freesound.org/s/718360/", lic="CC BY 4.0",
         used="announcer kill-streak calls; game-start / you-lose / you-win voice"),
    dict(who="JavierZumer", title="retro shot blaster",
         url="https://freesound.org/s/257232/", lic="CC BY 4.0",
         used="king ray-gun capture (guns/ray_gun)"),
]

ATTRIBUTION_CC0 = [
    dict(who="Kenney", title="Audio packs (Interface / UI / Impact / Digital / Sci-Fi / Voiceover)",
         url="https://kenney.nl/assets/category:Audio",
         used="piece moves, skill-check cues, UI clicks, ray-gun lasers, you-win callouts"),
    dict(who="Dustyroom", title="Casual Game Sounds",
         url="https://dustyroom.com/free-casual-game-sounds/", used="UI / feedback one-shots"),
    dict(who="Ben Jaszczak, Brian Nelson, Kevin Heras, Matthew Nanney (submitted by bart)",
         title="The Free Firearm Sound Library",
         url="https://opengameart.org/content/the-free-firearm-sound-library",
         used="pistol / cannon / rifle capture shots"),
    dict(who="Signature Sounds", title="Bullet / Gun SFX (CC0)",
         url="https://signaturesounds.org/store/p/bulletgun-sfx-cc0", used="foley / reload layers"),
    dict(who="qubodup (Iwan Gabovitch)", title="Door Open, Door Close Set",
         url="https://opengameart.org/content/door-open-door-close-set",
         used="castle (open+close)"),
    dict(who="bart", title="Heartbeat Sounds",
         url="https://opengameart.org/content/heartbeat-sounds", used="low-time heartbeat loops"),
    dict(who="thenotcheeseman", title="metal pipe fall",
         url="https://freesound.org/s/679206/", used="checkmate"),
    dict(who="craigsmith", title="R11-58 Loud Shotgun Blasts",
         url="https://freesound.org/s/486060/", used="rook shotgun capture"),
    dict(who="Zott820", title="Pump Action Shotgun Cycle",
         url="https://freesound.org/s/370344/", used="check reload"),
    dict(who="unfa", title="Oof (original)",
         url="https://freesound.org/s/719053/", used="capture hit oof"),
    dict(who="iampatrick", title="Video Game Character Grunt",
         url="https://freesound.org/s/839522/", used="capture hit oof"),
    dict(who="tonsil5", title="Grunt2 - Death Pain",
         url="https://freesound.org/s/416838/", used="capture hit oof"),
    dict(who="MadamVicious (mvVoiceActing)", title="Girl Taking Damage",
         url="https://freesound.org/s/218190/", used="queen capture oof (female)"),
]


def _attribution_section():
    lines = ["## Sounds", ""]
    lines.append("Sound effects are CC0 unless listed under **Attribution required** below.")
    lines.append("")
    lines.append("### Attribution required (CC BY 4.0)")
    lines.append("")
    for e in ATTRIBUTION_CC_BY:
        lines.append(f"- **{e['title']}** by {e['who']} -- {e['url']}")
        lines.append(f"  License: {e['lic']} (https://creativecommons.org/licenses/by/4.0/). "
                     f"Used for: {e['used']}.")
    lines.append("")
    lines.append("### Public domain (CC0 -- credited as a courtesy, not required)")
    lines.append("")
    for e in ATTRIBUTION_CC0:
        lines.append(f"- **{e['title']}** by {e['who']} -- {e['url']} ({e['used']})")
    lines.append("")
    return "\n".join(lines)


def write_attribution():
    """Replace the ``## Sounds`` section (to EOF) of the repo-root ATTRIBUTION.md."""
    section = _attribution_section()
    if ATTRIBUTION_PATH.exists():
        text = ATTRIBUTION_PATH.read_text()
        head = text.split("## Sounds", 1)[0].rstrip()
        new_text = f"{head}\n\n{section}\n"
    else:
        new_text = f"# Attribution\n\n{section}\n"
    if DRY_RUN:
        print(f"  would write ATTRIBUTION.md ({len(ATTRIBUTION_CC_BY)} CC-BY, "
              f"{len(ATTRIBUTION_CC0)} CC0)")
        return
    ATTRIBUTION_PATH.write_text(new_text)
    print(f"[attr] ATTRIBUTION.md updated ({len(ATTRIBUTION_CC_BY)} CC-BY + "
          f"{len(ATTRIBUTION_CC0)} CC0)")


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------

def run(cmd, capture=False):
    if DRY_RUN:
        print("  $", " ".join(str(c) for c in cmd))
        return ""
    result = subprocess.run(cmd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE)
    return result.stdout if capture else ""


def ffprobe_json(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=sample_rate,channels:format=duration",
         "-of", "json", str(path)],
        check=True, text=True, stdout=subprocess.PIPE).stdout
    return json.loads(out)


def _duration_from(data):
    try:
        return float(data["format"]["duration"])
    except (KeyError, ValueError):
        return 0.0


def ffprobe_duration(path):
    return _duration_from(ffprobe_json(path))


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


def _encode_ogg(in_path, out_path, af, channels):
    cmd = ["ffmpeg", "-y", "-i", str(in_path)]
    if af:
        cmd += ["-af", af]
    cmd += ["-ac", str(channels), "-ar", str(SAMPLE_RATE),
            "-c:a", "libvorbis", "-qscale:a", VORBIS_QSCALE, str(out_path)]
    run(cmd)


def process_one(src, out_path, profile, stereo):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    channels = 2 if stereo else 1
    trim = "" if profile == LOOP else _trim_filter()

    if profile in (SUSTAINED, LOOP):
        prefix = f"{trim}," if trim else ""
        if DRY_RUN:
            _encode_ogg(src, out_path, f"{prefix}{LOUDNORM_BASE}", channels)
            return
        s = _measure_loudnorm(src, prefix)
        measured = ""
        if s:
            measured = (f":measured_I={s['input_i']}:measured_TP={s['input_tp']}"
                        f":measured_LRA={s['input_lra']}:measured_thresh={s['input_thresh']}"
                        f":offset={s['target_offset']}:linear=true")
        _encode_ogg(src, out_path, f"{prefix}{LOUDNORM_BASE}{measured}", channels)
        return

    # short: trim, then peak-normalize the trimmed audio to PEAK_TP.
    with tempfile.TemporaryDirectory() as td:
        trimmed = Path(td) / "trim.wav"
        run(["ffmpeg", "-y", "-i", str(src), "-af", trim, str(trimmed)])
        if DRY_RUN:
            _encode_ogg(src, out_path, trim, channels)
            return
        peak = _measure_peak_db(trimmed)
        gain = PEAK_TP - peak
        _encode_ogg(trimmed, out_path, f"volume={gain:.2f}dB", channels)


# --------------------------------------------------------------------------
# slot processing
# --------------------------------------------------------------------------

def staged_files(slot_dir):
    return sorted(p for p in slot_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in SOURCE_EXTS)


def clean_assets():
    """Remove every child of assets/sounds except _staging (never rmtree ASSETS)."""
    assert ASSETS.name == "sounds", ASSETS
    for child in ASSETS.iterdir():
        if child.name == "_staging":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def process_slot(slot_id):
    spec = SLOTS[slot_id]
    slot_dir = STAGING / spec.src
    out_dir = ASSETS / spec.dst
    if out_dir.exists():
        shutil.rmtree(out_dir)
    if not slot_dir.is_dir():
        print(f"[skip] {slot_id}: no staging dir ({spec.src}/)")
        return []
    files = staged_files(slot_dir)
    if not files:
        print(f"[skip] {slot_id}: staging dir empty")
        return []
    print(f"[slot] {slot_id:24s} {spec.src}/ -> {spec.dst}/ "
          f"({len(files)} file{'s' if len(files) != 1 else ''}, "
          f"{spec.profile}, {'stereo' if spec.stereo else 'mono'})")
    outputs = []
    for i, src in enumerate(files, start=1):
        out_path = out_dir / f"{i:02d}.ogg"
        process_one(src, out_path, spec.profile, spec.stereo)
        outputs.append((slot_id, out_path))
    return outputs


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def validate(outputs):
    """ffprobe every output; return (rows, failures)."""
    rows = []
    failures = 0
    for slot_id, out_path in outputs:
        spec = SLOTS[slot_id]
        want_ch = 2 if spec.stereo else 1
        problems = []
        data = ffprobe_json(out_path)
        streams = data.get("streams", [{}])
        rate = int(streams[0].get("sample_rate", 0)) if streams else 0
        ch = int(streams[0].get("channels", 0)) if streams else 0
        dur = _duration_from(data)
        if rate != SAMPLE_RATE:
            problems.append(f"rate={rate}")
        if ch != want_ch:
            problems.append(f"ch={ch}!={want_ch}")
        if dur <= 0:
            problems.append("dur=0")
        peak = _measure_peak_db(out_path)
        if peak > CLIP_PEAK_DB:
            problems.append(f"clip@{peak:.1f}")
        if spec.profile == SHORT and peak < QUIET_PEAK_DB:
            problems.append(f"quiet@{peak:.1f}")
        status = "OK" if not problems else "FAIL " + ",".join(problems)
        if problems:
            failures += 1
        rows.append((slot_id, out_path.name, rate, ch, round(dur, 3), round(peak, 1), status))
    return rows, failures


def print_validation(rows, failures):
    print("\n=== validation ===")
    by_slot = {}
    for slot_id, name, rate, ch, dur, peak, status in rows:
        by_slot.setdefault(slot_id, []).append((name, rate, ch, dur, peak, status))
    for slot_id in sorted(by_slot):
        entries = by_slot[slot_id]
        bad = [e for e in entries if e[5] != "OK"]
        mark = "OK" if not bad else "FAIL"
        print(f"  [{mark:4s}] {slot_id:24s} {len(entries)} file(s)")
        for name, rate, ch, dur, peak, status in entries:
            if status != "OK":
                print(f"          {name}: {status} (rate={rate} ch={ch} dur={dur} peak={peak})")
    print(f"\n{len(rows)} output(s), {failures} failure(s).")


# --------------------------------------------------------------------------
# split (multi-sample source -> staging clips)
# --------------------------------------------------------------------------

def split_file(src, slot_id):
    if slot_id not in SLOTS:
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
    ends.append(ffprobe_duration(src))
    segments = [(s, e) for s, e in zip(starts, ends) if e - s >= SPLIT_MIN_CLIP]

    dest = STAGING / SLOTS[slot_id].src
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[split] {src.name} -> {len(segments)} clips in {dest.relative_to(REPO_ROOT)}/")
    for i, (s, e) in enumerate(segments, start=1):
        out = dest / f"{src.stem}_{i:02d}.wav"
        run(["ffmpeg", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", str(src), str(out)])


def cmd_list():
    print(f"staging root: {STAGING}")
    print(f"assets root:  {ASSETS}\n")
    for slot_id, spec in SLOTS.items():
        chan = "stereo" if spec.stereo else "mono"
        print(f"  {slot_id:24s} {spec.profile:9s} {chan:6s} {spec.src}/ -> {spec.dst}/")


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Process staged sounds into game OGG assets.")
    ap.add_argument("slots", nargs="*", help="slot ids to process (default: full clean rebuild)")
    ap.add_argument("--list", action="store_true", help="list slots and their targets")
    ap.add_argument("--dry-run", action="store_true", help="print actions without running ffmpeg")
    ap.add_argument("--no-validate", action="store_true", help="skip post-processing validation")
    ap.add_argument("--attribution", action="store_true", help="only regenerate ATTRIBUTION.md")
    ap.add_argument("--split", nargs=2, metavar=("FILE", "SLOT"),
                    help="cut a multi-sample FILE into SLOT's staging dir on silence")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg/ffprobe not found on PATH")

    if args.list:
        cmd_list()
        return
    if args.attribution:
        write_attribution()
        return
    if args.split:
        split_file(Path(args.split[0]), args.split[1])
        return

    full_run = not args.slots
    targets = args.slots or list(SLOTS.keys())
    unknown = [s for s in targets if s not in SLOTS]
    if unknown:
        sys.exit(f"unknown slot(s): {', '.join(unknown)}")

    if full_run and not DRY_RUN:
        clean_assets()

    outputs = []
    for slot_id in targets:
        outputs += process_slot(slot_id)
    print(f"\nProcessed {len(outputs)} file(s) across {len(targets)} slot(s).")

    failures = 0
    if outputs and not args.no_validate and not DRY_RUN:
        rows, failures = validate(outputs)
        print_validation(rows, failures)

    if full_run:
        write_attribution()

    if failures:
        sys.exit(f"{failures} validation failure(s).")


if __name__ == "__main__":
    main()
