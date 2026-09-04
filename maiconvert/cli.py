"""Command-line interface and chart/song file discovery."""
from __future__ import annotations

import argparse
import glob
import os
import random
import shutil
import string
import sys
from typing import List, Optional

from .simai import parse_chart, parse_maidata
from .sus import chart_to_sus
from .ugc import chart_to_ugc
from .model import map_level

DIFFICULTY_BY_INDEX = {
    "1": 0, "2": 1, "3": 2, "4": 2, "5": 3, "6": 5, "7": 6,
}

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
WAVE_NAMES = ["track.mp3", "track.wav", "track.ogg", "music.mp3", "audio.mp3",
              "bgm.mp3"]
JACKET_NAMES = ["bg.png", "bg.jpg", "bg.jpeg", "jacket.png", "jacket.jpg",
                "cover.png", "cover.jpg"]


def generate_songid(metadata: dict, random_suffix: bool = True) -> str:
    """Build a #SONGID: ``&shortid`` (or ``105``) + a random suffix.

    ``random_suffix`` disabled -> return just the base id without the random
    suffix (used with ``--skip-random-id``).
    """
    shortid = (metadata.get("shortid") or "").strip()
    base = shortid if shortid else "105"
    if not random_suffix:
        return base
    suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(4))
    return f"{base}{suffix}"


def _find_file(directory: str, preferred: List[str],
               extensions: set) -> Optional[str]:
    try:
        entries = os.listdir(directory)
    except OSError:
        return None
    lower = {name.lower(): name for name in entries}
    for name in preferred:
        if name in lower:
            return lower[name]
    for name in sorted(entries):
        if os.path.splitext(name.lower())[1] in extensions:
            return name
    return None


def find_wave(directory: str) -> Optional[str]:
    return _find_file(directory, WAVE_NAMES, AUDIO_EXTS)


def find_jacket(directory: str) -> Optional[str]:
    return _find_file(directory, JACKET_NAMES, IMAGE_EXTS)


def process_song(path: str, out_dir: str,
                 songid_override: Optional[str], fmt: str = "ugc",
                 touch_multi_height: bool = False,
                 no_songid: bool = False,
                 skip_random_id: bool = False,
                 title_prefix: str = "",
                 title_suffix: str = "") -> int:
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    metadata, charts = parse_maidata(text)
    songdir = os.path.dirname(os.path.abspath(path))

    title = metadata.get("title", "untitled")
    if title_prefix or title_suffix:
        title = f"{title_prefix}{title}{title_suffix}"
        metadata["title"] = title
    whole_bpm = None
    if metadata.get("wholebpm"):
        try:
            whole_bpm = float(metadata["wholebpm"])
        except ValueError:
            whole_bpm = None

    if songid_override:
        songid = songid_override
    elif no_songid:
        songid = None
    else:
        songid = generate_songid(metadata,
                                 random_suffix=not skip_random_id)

    wave = find_wave(songdir)
    jacket = find_jacket(songdir)

    os.makedirs(out_dir, exist_ok=True)

    # Copy the audio / cover next to the generated chart and reference them by
    # bare filename so the output folder is self-contained.
    for asset in (wave, jacket):
        if not asset:
            continue
        src = os.path.join(songdir, asset)
        dst = os.path.join(out_dir, asset)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
    wave_name = os.path.basename(wave) if wave else None
    jacket_name = os.path.basename(jacket) if jacket else None

    safe_title = "".join(c if c.isalnum() or c in "-_" else "_"
                         for c in title).strip("_") or "untitled"

    print(f"[{title}] songid={songid} wave={wave} jacket={jacket}")

    written = 0
    designers = metadata.get("designers", {})
    if fmt == "sus":
        generator = chart_to_sus
        ext = "sus"
    else:
        generator = chart_to_ugc
        ext = "ugc"
    for num in sorted(charts, key=lambda k: int(k)):
        chart = parse_chart(charts[num], whole_bpm)
        level = map_level(metadata.get("levels", {}).get(num, "?"))
        difficulty = DIFFICULTY_BY_INDEX.get(num, 4)
        designer = designers.get(num) or designers.get("0") or ""
        if fmt == "ugc":
            out_text = generator(chart, metadata, level, difficulty,
                                 songid=songid, designer=designer,
                                 wave=wave_name, jacket=jacket_name,
                                 touch_multi_height=touch_multi_height)
        else:
            out_text = generator(chart, metadata, level, difficulty,
                                 songid=songid, designer=designer,
                                 wave=wave_name, jacket=jacket_name)
        out_path = os.path.join(out_dir, f"{safe_title}_{num}.{ext}")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"  wrote {out_path} ({len(chart.notes)} notes)")
        written += 1
    return written


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert maimai simai charts (maidata.txt) to CHUNITHM UGC "
                    "or SUS format.")
    parser.add_argument("input", help="maidata.txt file or a directory to scan")
    parser.add_argument("-o", "--output", default=None,
                        help="output directory (default: alongside each chart)")
    parser.add_argument("--songid", default=None,
                        help="override the generated #SONGID")
    parser.add_argument("--no-songid", action="store_true",
                        help="do not generate / emit a #SONGID at all")
    parser.add_argument("--skip-random-id", action="store_true",
                        help="generate the songid without the random suffix "
                             "(base id only)")
    parser.add_argument("--format", choices=["ugc", "sus"], default="ugc",
                        help="output format (default: ugc)")
    parser.add_argument("--touch-multi-height", action="store_true",
                        help="render each touch as several crushes at the base "
                             "height and its neighbours (H-1/H/H+1), each with "
                             "its own 踩音 (UGC only)")
    parser.add_argument("--title-prefix", default="",
                        help="prepend a string to the song title")
    parser.add_argument("--title-suffix", default="",
                        help="append a string to the song title")
    args = parser.parse_args(argv)

    input_path = os.path.abspath(args.input)
    if os.path.isdir(input_path):
        paths = sorted(glob.glob(
            os.path.join(input_path, "**", "maidata.txt"), recursive=True))
        root = input_path
    else:
        paths = [input_path]
        root = os.path.dirname(input_path)

    if not paths:
        print("no maidata.txt found", file=sys.stderr)
        return 1

    total = 0
    for path in paths:
        songdir = os.path.dirname(path)
        if args.output:
            out_dir = os.path.normpath(os.path.join(
                os.path.abspath(args.output), os.path.relpath(songdir, root)))
        else:
            out_dir = songdir
        total += process_song(path, out_dir, args.songid, args.format,
                           touch_multi_height=args.touch_multi_height,
                           no_songid=args.no_songid,
                           skip_random_id=args.skip_random_id,
                           title_prefix=args.title_prefix,
                           title_suffix=args.title_suffix)

    if total == 0:
        print("no charts (&inote_N) found", file=sys.stderr)
        return 1
    return 0
