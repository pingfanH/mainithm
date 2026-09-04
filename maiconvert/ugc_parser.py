"""UGC (CHUNITHM Umiguri Chart) parser.

Reads a ``.ugc`` file into an intermediate list of note objects plus the
metadata needed to place them on a simai timeline (BPMs, beat changes).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

# UGC resolution: a bar always has TICKS * 4 ticks.  @TICKS is ticks per beat
# and there are 4 beats per bar for the purpose of tick indexing.
TICKS_PER_BEAT_DEFAULT = 480
BEATS_PER_BAR_DEFAULT = 4

H36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def h36_to_i(ch: str) -> int:
    return H36.index(ch.lower())


def h36_to_int(s: str) -> int:
    n = 0
    for c in s:
        n = n * 36 + h36_to_i(c)
    return n


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

@dataclass
class UgcMeta:
    title: str = ""
    artist: str = ""
    designer: str = ""
    level: str = ""
    difficulty: str = ""
    songid: str = ""
    wave: str = ""
    jacket: str = ""
    ticks_per_beat: int = TICKS_PER_BEAT_DEFAULT


@dataclass
class BpmChange:
    # chart-time (beats) at which the BPM takes effect
    time: Fraction
    value: float


@dataclass
class Note:
    time: Fraction            # chart-time in beats
    type: str                 # note-type key, see parser
    cell: int
    width: int
    duration: Fraction = Fraction(0)   # in beats
    # optional per-type extras
    height: float = 5.0
    direction: str = ""       # UC/UR/UL/DC/DR/DL for AIR
    color: str = ""           # air / crush color
    extra: str = ""           # chr / flick extra
    interval: Optional[Fraction] = None  # crush interval
    # chain links (slides / air-slides / holds / crushes)
    prev: "Optional[Note]" = None


@dataclass
class UgcChart:
    meta: UgcMeta
    bpms: List[BpmChange] = field(default_factory=list)
    beats: List[Tuple[int, Fraction]] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Header + timeline
# --------------------------------------------------------------------------- #

def _split_directive(line: str) -> Tuple[str, str]:
    parts = line[1:].split("\t", 1)
    tag = parts[0]
    value = parts[1] if len(parts) > 1 else ""
    return tag, value.strip()


def _parse_measure_tick(s: str) -> Tuple[int, int]:
    bar_s, _, tick_s = s.partition("'")
    return int(bar_s), int(tick_s)


def _time_of(chart: UgcChart, bar: int, tick: int) -> Fraction:
    """UGC (bar, tick) -> chart-time in beats."""
    result = Fraction(0)
    beats = chart.beats
    for i, (end_bar, beats_per_bar) in enumerate(beats):
        end = beats[i + 1][0] if i + 1 < len(beats) else 10 ** 9
        count = min(end, bar) - beats[i][0]
        if count <= 0:
            break
        result += count * beats_per_bar
    result += Fraction(tick, chart.meta.ticks_per_beat * 4)
    return result


def parse_ugc(text: str) -> UgcChart:
    """Parse UGC text into an :class:`UgcChart`."""
    chart = UgcChart(UgcMeta())
    chart.beats.append((0, Fraction(BEATS_PER_BAR_DEFAULT, 1)))
    chart.meta.ticks_per_beat = TICKS_PER_BEAT_DEFAULT

    lines = text.replace("\r\n", "\n").split("\n")
    in_header = True
    pending: List[Note] = []
    start_time = Fraction(0)

    def flush_followers(parent: Note, followers: List[Tuple[int, int, int, float, str]]):
        # followers attach a chain to `parent`; each extends by its own interval
        prev = parent
        for tick, cell, width, height, marker in followers:
            seg = Note(
                time=prev.time + Fraction(tick, chart.meta.ticks_per_beat * 4),
                type=parent.type,
                cell=cell if marker == "c" and parent.type in (
                    "air_slide", "slide") else parent.cell,
                width=width if marker == "c" and parent.type in (
                    "air_slide", "slide") else parent.width,
                duration=Fraction(0),
                height=height if height is not None else parent.height,
                color=parent.color,
                prev=prev,
            )
            chart.notes.append(seg)
            prev = seg

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("'"):
            continue
        if in_header:
            if line.startswith("@ENDHEAD"):
                in_header = False
                continue
            if not line.startswith("@"):
                continue
            tag, value = _split_directive(line)
            if tag == "TITLE":
                chart.meta.title = value
            elif tag == "ARTIST":
                chart.meta.artist = value
            elif tag == "DESIGN":
                chart.meta.designer = value
            elif tag == "LEVEL":
                chart.meta.level = value
            elif tag == "DIFF":
                chart.meta.difficulty = value
            elif tag == "SONGID":
                chart.meta.songid = value
            elif tag == "BGM":
                chart.meta.wave = value
            elif tag == "JACKET":
                chart.meta.jacket = value
            elif tag == "TICKS":
                chart.meta.ticks_per_beat = int(value)
            elif tag == "BEAT":
                parts = value.split()
                if len(parts) >= 3:
                    m = int(parts[0])
                    num = int(parts[1])
                    den = int(parts[2])
                    if m == 0 and len(chart.beats) == 1 and chart.beats[0][0] == 0:
                        chart.beats[0] = (0, Fraction(num, den))
                    else:
                        chart.beats.append((m, Fraction(num, den)))
            elif tag == "BPM":
                mp, _, v = value.partition("\t")
                if not v:
                    parts = value.split()
                    if len(parts) == 2:
                        mp, v = parts[0], parts[1]
                try:
                    bar, tick = _parse_measure_tick(mp)
                    chart.bpms.append(BpmChange(
                        _time_of(chart, bar, tick), float(v)))
                except ValueError:
                    pass
            continue

        # Note lines
        colon = line.find(":")
        if colon < 0:
            continue
        prefix = line[:colon]
        code = line[colon + 1:]
        m, o = _parse_measure_tick(prefix.lstrip("#"))
        base = _time_of(chart, m, o)

        # follower lines: #OffsetTick>s ... / >c ...
        m2 = re.match(r"^#(\d+)>(s|c)(.*)$", code)
        if m2:
            # attach to last pending note
            tick = int(m2.group(1))
            marker = m2.group(2)
            rest = m2.group(3)
            cell = h36_to_i(rest[0]) if rest else 0
            width = h36_to_i(rest[1]) if len(rest) > 1 else 0
            height = 5.0
            if len(rest) > 2:
                try:
                    height = h36_to_int(rest[2:]) / 10.0 + 1.0
                except (ValueError, IndexError):
                    pass
            if pending:
                flush_followers(pending[-1], [(tick, cell, width, height, marker)])
            continue

        if pending:
            # a new parent line finalizes the previous chain
            pending.clear()

        n = _parse_note(chart, code, base)
        if n is not None:
            chart.notes.append(n)
            pending = [n]

    chart.bpms.sort(key=lambda b: b.time)
    chart.notes.sort(key=lambda x: x.time)
    chart.beats.sort(key=lambda b: b[0])
    return chart


def _parse_note(chart: UgcChart, code: str, time: Fraction) -> Optional[Note]:
    """Parse a single parent note line (after the ``:``)."""
    t = code[0]
    if t == "t":
        return Note(time, "tap", h36_to_i(code[1]), h36_to_i(code[2]))
    if t == "x":
        n = Note(time, "chr", h36_to_i(code[1]), h36_to_i(code[2]))
        if len(code) > 3:
            n.extra = code[3]
        return n
    if t == "h":
        n = Note(time, "hold", h36_to_i(code[1]), h36_to_i(code[2]))
        return n
    if t == "s":
        n = Note(time, "slide", h36_to_i(code[1]), h36_to_i(code[2]))
        return n
    if t == "S":
        n = Note(time, "air_slide", h36_to_i(code[1]), h36_to_i(code[2]))
        _parse_air_height_color(n, code[3:])
        return n
    if t == "H":
        n = Note(time, "air_hold", h36_to_i(code[1]), h36_to_i(code[2]))
        n.color = code[3] if len(code) > 3 else "N"
        return n
    if t == "a":
        n = Note(time, "air", h36_to_i(code[1]), h36_to_i(code[2]))
        n.direction = code[3:5]
        if len(code) > 5:
            n.color = code[5]
        return n
    if t == "C":
        n = Note(time, "crush", h36_to_i(code[1]), h36_to_i(code[2]))
        _parse_air_height_color(n, code[3:])
        return n
    if t == "d":
        return Note(time, "mine", h36_to_i(code[1]), h36_to_i(code[2]))
    if t == "f":
        n = Note(time, "flick", h36_to_i(code[1]), h36_to_i(code[2]))
        if len(code) > 3:
            n.extra = code[3]
        return n
    if t == "c":
        return Note(time, "click", 0, 0)
    return None


def _parse_air_height_color(n: Note, s: str):
    """Parse the ``height`` + optional color + interval of air/crush notes."""
    pos_of_comma = s.find(",")
    interval = None
    if pos_of_comma >= 0:
        interval_str = s[pos_of_comma + 1:]
        s = s[:pos_of_comma]
        if interval_str == "$":
            interval = Fraction(100, 1)
        else:
            try:
                interval = Fraction(int(interval_str), n.time.denominator)
            except ValueError:
                interval = None
    if not s:
        return
    n.color = s[-1]
    if len(s) > 1:
        try:
            h = h36_to_int(s[:-1])
            n.height = h / 20.0 + 1.0
        except ValueError:
            pass
    n.interval = interval