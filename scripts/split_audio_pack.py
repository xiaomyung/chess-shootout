"""Split a multi-clip mp3 into individual variant files, peak-normalised to a
target dBFS so loudness matches the rest of the capture/move/reload library.

Used to build random-pick variant packs (see SoundManager._load_variant_pack).
The convention -1.5 dBTP is set by commit 1a6ab27 (`sounds: equalize loudness`).

Example:
    .venv/bin/python scripts/split_audio_pack.py \\
        assets/sounds/capture_sounds/king_capture/king_capture.mp3 \\
        assets/sounds/capture_sounds/king_capture/ \\
        --expected 9
"""
import argparse
import sys
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_nonsilent


def split_and_normalize(source, out_dir, expected, min_silence_ms,
                        target_peak_dbfs, bitrate, force):
    audio = AudioSegment.from_mp3(str(source))
    threshold = audio.dBFS - 16
    ranges = detect_nonsilent(audio, min_silence_len=min_silence_ms,
                              silence_thresh=threshold)
    if expected is not None and len(ranges) != expected:
        sys.exit(f"detected {len(ranges)} segments, expected {expected}; "
                 f"adjust --min-silence-ms (current {min_silence_ms}) and retry")
    if not ranges:
        sys.exit("no non-silent segments detected")

    out_dir.mkdir(parents=True, exist_ok=True)
    first = out_dir / "01.mp3"
    if first.exists() and not force:
        sys.exit(f"{first} already exists; pass --force to overwrite")

    written = []
    for i, (start_ms, end_ms) in enumerate(ranges, start=1):
        seg = audio[start_ms:end_ms]
        seg = seg.apply_gain(target_peak_dbfs - seg.max_dBFS)
        path = out_dir / f"{i:02d}.mp3"
        seg.export(str(path), format="mp3", bitrate=bitrate)
        written.append((path, len(seg) / 1000.0, seg.max_dBFS))

    if source.parent == out_dir:
        source.unlink()

    for path, dur, peak in written:
        print(f"{path.name}  {dur:5.3f}s  peak={peak:+.2f} dBFS")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", type=Path, help="multi-clip mp3 to split")
    p.add_argument("out_dir", type=Path, help="directory to write NN.mp3 into")
    p.add_argument("--expected", type=int, default=None,
                   help="abort if detected segment count differs")
    p.add_argument("--min-silence-ms", type=int, default=400,
                   help="silence run length that splits clips (default 400)")
    p.add_argument("--target-peak-dbfs", type=float, default=-1.5,
                   help="peak-normalise each clip to this dBFS (default -1.5)")
    p.add_argument("--bitrate", default="128k",
                   help="mp3 export bitrate (default 128k)")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing 01.mp3 in out_dir")
    args = p.parse_args()

    if not args.source.is_file():
        sys.exit(f"source not found: {args.source}")
    split_and_normalize(args.source, args.out_dir, args.expected,
                        args.min_silence_ms, args.target_peak_dbfs,
                        args.bitrate, args.force)


if __name__ == "__main__":
    main()
