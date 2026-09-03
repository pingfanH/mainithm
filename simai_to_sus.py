#!/usr/bin/env python3
"""Convert maimai simai charts (maidata.txt) to SUS (Sliding Universal Score).

Format references
-----------------
* simai:  https://w.atwiki.jp/simai/ and the MaiConverter project in this repo.
* SUS:    https://gist.github.com/kb10uy/c171c175ba913dc40a73c6ce69da9859
          and https://github.com/mkpoli/sus-io

Usage
-----
    python3 simai_to_sus.py maidata.txt [-o OUT_DIR]

This produces one ``.sus`` file per chart (``&inote_N``) found in the input.

Timing model
------------
* simai measure 0.0 == the first beat of the chart.
* SUS uses ``ticks_per_beat = 480`` and 4/4 bars, so one bar == 1920 ticks.

Lane model
----------
maimai's 8 buttons sit on a 16-lane circular grid, one button every 45 degrees.
Button ``position`` (0..7) maps to lane ``2 * position``; the odd lanes in
between are left free for slide curve control points.  ``POSITION_TO_LANE`` and
``LANE_OFFSET`` below let you retune this if a particular player uses a
different convention.

Known limitations (documented on purpose)
-----------------------------------------
* break / EX / star visual variants collapse into ordinary taps.
* touch notes (C/B/E/A/D) are projected onto the button lanes.
* complex slide shapes (p/q/pp/qq/s/z/w) are approximated as polylines;
  straight ``-``, arc ``^<>`` and ``V``/``v`` slides are exact.
* no directional/flick notes are produced (maimai has none).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

B36 = "0123456789abcdefghijklmnopqrstuvwxyz"

TICKS_PER_BEAT = 480
BAR_LENGTH = 4.0
TICKS_PER_MEASURE = int(TICKS_PER_BEAT * BAR_LENGTH)  # 1920

# Cap the number of subdivisions per bar so a single exotic timing cannot
# balloon a data line to thousands of cells. 192 == 1/192-note resolution.
MAX_SUBDIVISIONS = 192

# button position (0..7) -> SUS lane
POSITION_TO_LANE: Dict[int, int] = {i: 2 * i for i in range(8)}
LANE_OFFSET = 0  # rotate the whole circle by this many lanes

# slide delay in measures (one beat at the current BPM)
SLIDE_DELAY = 0.25


def button_lane(position: int) -> int:
    return (POSITION_TO_LANE[position] + LANE_OFFSET) % 16


def touch_lane(region: str, position: int) -> int:
    if region == "B":
        return button_lane(position)
    return button_lane(0)  # C/A/D fall back to the center lane


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def b36(n: int) -> str:
    return B36[n % 36]


def b36_fixed(n: int, width: int) -> str:
    digits = ""
    while n or len(digits) < width:
        digits = B36[n % 36] + digits
        n //= 36
    return digits[-width:]


def measure_to_tick(measure: float) -> int:
    return int(round(measure * TICKS_PER_MEASURE))


# --------------------------------------------------------------------------- #
# Note model
# --------------------------------------------------------------------------- #

@dataclass
class Tap:
    measure: float
    position: int


@dataclass
class Hold:
    measure: float
    position: int
    duration: float


@dataclass
class Slide:
    measure: float
    start: int
    end: int
    duration: float
    pattern: str
    delay: float
    reflect: Optional[int]
    tapless: bool


@dataclass
class TouchTap:
    measure: float
    position: int
    region: str


@dataclass
class TouchHold:
    measure: float
    position: int
    region: str
    duration: float


@dataclass
class BPM:
    measure: float
    value: float


@dataclass
class Chart:
    notes: List = field(default_factory=list)
    bpms: List[BPM] = field(default_factory=list)

    def bpm_at(self, measure: float) -> float:
        result = self.bpms[0].value
        for bpm in self.bpms:
            if bpm.measure <= measure + 1e-9:
                result = bpm.value
            else:
                break
        return result


# --------------------------------------------------------------------------- #
# simai parsing
# --------------------------------------------------------------------------- #

def parse_maidata(text: str) -> Tuple[dict, Dict[str, str]]:
    """Split a maidata.txt into metadata and raw chart bodies.

    Chart bodies are multi-line: they run until the next ``&...`` directive.
    """
    metadata: dict = {"designers": {}, "levels": {}, "first": {}}
    charts: Dict[str, str] = {}
    current_chart: Optional[str] = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("&"):
            current_chart = None
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key == "&title":
                metadata["title"] = value
            elif key == "&artist":
                metadata["artist"] = value
            elif key.startswith("&des"):
                metadata["designers"][key[4:] or "0"] = value
            elif key == "&wholebpm":
                metadata["wholebpm"] = value
            elif key.startswith("&first"):
                metadata["first"][key[6:] or "0"] = value
            elif key.startswith("&lv_"):
                metadata["levels"][key[4:]] = value
            elif key.startswith("&inote_"):
                num = key[7:]
                charts[num] = value
                current_chart = num
            elif key == "&freemsg":
                metadata["freemsg"] = value
        elif current_chart is not None and line:
            charts[current_chart] += "\n" + line

    return metadata, charts


def parse_duration(s: str) -> Tuple[float, Optional[float]]:
    """Parse a ``[den:num]`` / ``[eqbpm#den:num]`` duration.

    Returns ``(duration_in_measures, equivalent_bpm)``.
    """
    if not s.startswith("["):
        return 0.0, None
    inner = s.strip("[]")
    equivalent_bpm: Optional[float] = None
    if "#" in inner:
        pre, _, inner = inner.partition("#")
        if pre:
            equivalent_bpm = float(pre)
    den_str, _, num_str = inner.partition(":")
    if not den_str or not num_str:
        return 0.0, equivalent_bpm
    den = float(den_str)
    num = float(num_str)
    if den <= 0:
        return 0.0, equivalent_bpm
    return num / den, equivalent_bpm


def parse_touch(s: str) -> dict:
    region = s[0]
    i = 1
    position = 0
    if i < len(s) and s[i].isdigit():
        position = int(s[i]) - 1
        i += 1
    is_hold = False
    while i < len(s) and s[i] in "hfe":
        if s[i] == "h":
            is_hold = True
        i += 1
    duration = 0.0
    if i < len(s) and s[i] == "[":
        duration, _ = parse_duration(s[i:])
    if is_hold:
        return {"type": "touch_hold", "region": region, "position": position,
                "duration": duration}
    return {"type": "touch_tap", "region": region, "position": position}


def parse_slide(start: int, modifier: str, tail: str) -> List[dict]:
    """Parse a slide (and its chained ``*`` segments)."""
    slides: List[dict] = []
    segments = tail.split("*")
    inherit_duration = None
    for seg in segments:
        if not seg:
            continue
        pattern = seg[0]
        i = 1
        reflect: Optional[int] = None
        if seg[0] in "-^<>szvw":
            pass
        elif seg[0] in "pq":
            if i < len(seg) and seg[i] in "pq":
                pattern += seg[i]
                i += 1
        elif seg[0] == "V":
            reflect = int(seg[1]) - 1
            i = 2
        else:
            continue  # unknown pattern
        end = int(seg[i]) - 1
        i += 1
        duration = inherit_duration
        equivalent_bpm = None
        if i < len(seg) and seg[i] == "[":
            duration, equivalent_bpm = parse_duration(seg[i:])
        if duration is None:
            duration = 0.0
        inherit_duration = duration
        slides.append({
            "type": "slide",
            "start": start,
            "end": end,
            "pattern": pattern,
            "reflect": reflect,
            "duration": duration,
            "equivalent_bpm": equivalent_bpm,
            "modifier": modifier,
        })
    return slides


def parse_button_note(s: str) -> List[dict]:
    button = int(s[0]) - 1
    if button < 0:
        return []
    rest = s[1:]
    i = 0
    modifier = ""
    is_hold = False
    while i < len(rest):
        ch = rest[i]
        if ch == "h":
            is_hold = True
        elif ch in "bex$@?!":
            modifier += ch
        else:
            break
        i += 1

    if is_hold:
        duration = 0.0
        if i < len(rest) and rest[i] == "[":
            duration, _ = parse_duration(rest[i:])
        if duration <= 0:
            return [{"type": "tap", "position": button}]  # hexagonal "tap"
        return [{"type": "hold", "position": button, "duration": duration}]

    if i < len(rest) and rest[i] in "-^<>szvwpqV":
        return parse_slide(button, modifier, rest[i:])

    return [{"type": "tap", "position": button}]


def parse_note(s: str) -> List[dict]:
    if not s:
        return []
    if s[0] in "CBEAD":
        return [parse_touch(s)]
    if s[0].isdigit():
        return parse_button_note(s)
    return []


def parse_fragment(fragment: str) -> List[dict]:
    """Parse one simai fragment (the text between two commas).

    ``/`` (EACH) and `` ` `` (pseudo-each) both just separate notes; the
    sub-tick pseudo-each offset is below SUS's resolution and is collapsed
    to simultaneity.
    """
    events: List[dict] = []
    i, n = 0, len(fragment)
    while i < n:
        c = fragment[i]
        if c == "(":
            j = fragment.index(")", i)
            events.append({"type": "bpm", "value": float(fragment[i + 1:j])})
            i = j + 1
        elif c == "{":
            j = fragment.index("}", i)
            events.append({"type": "divisor", "value": float(fragment[i + 1:j])})
            i = j + 1
        elif c in "/`":
            i += 1
        else:
            j = i
            while j < n and fragment[j] not in "/`":
                j += 1
            events.extend(parse_note(fragment[i:j]))
            i = j
    return events


def parse_chart(chart_text: str, whole_bpm: Optional[float] = None) -> Chart:
    lines = [ln for ln in chart_text.splitlines() if "||" not in ln]
    chart_text = "".join(lines).replace(" ", "").replace("\t", "")

    chart = Chart()
    measure = 0.0
    divisor = 4.0
    for fragment in chart_text.split(","):
        if fragment == "" or fragment == "E":
            if fragment == "E":
                break
            continue
        for ev in parse_fragment(fragment):
            et = ev["type"]
            if et == "bpm":
                chart.bpms.append(BPM(measure, ev["value"]))
            elif et == "divisor":
                divisor = ev["value"] if ev["value"] != 0 else divisor
            else:
                m = measure
                if et == "tap":
                    chart.notes.append(Tap(m, ev["position"]))
                elif et == "hold":
                    chart.notes.append(Hold(m, ev["position"], ev["duration"]))
                elif et == "slide":
                    duration = ev["duration"]
                    delay = SLIDE_DELAY
                    eq_bpm = ev["equivalent_bpm"]
                    if eq_bpm is not None:
                        cur = chart.bpms[-1].value if chart.bpms else (
                            whole_bpm or 120.0)
                        mult = cur / eq_bpm
                        duration *= mult
                        delay *= mult
                    chart.notes.append(Slide(
                        measure=m, start=ev["start"], end=ev["end"],
                        duration=duration, pattern=ev["pattern"], delay=delay,
                        reflect=ev["reflect"],
                        tapless=any(ch in ev["modifier"] for ch in "?$!"),
                    ))
                elif et == "touch_tap":
                    chart.notes.append(TouchTap(m, ev["position"], ev["region"]))
                elif et == "touch_hold":
                    chart.notes.append(
                        TouchHold(m, ev["position"], ev["region"], ev["duration"]))
        measure += 1.0 / divisor

    if not chart.bpms:
        chart.bpms.append(BPM(0.0, whole_bpm or 120.0))
    chart.bpms.sort(key=lambda b: b.measure)
    chart.notes.sort(key=lambda n: n.measure)
    return chart


# --------------------------------------------------------------------------- #
# Slide path generation
# --------------------------------------------------------------------------- #

def _arc_positions(start: int, end: int, direction: int) -> List[int]:
    """Buttons visited moving from start to end around the circle.

    ``direction`` is +1 (clockwise) or -1 (counter-clockwise).
    """
    if start == end:
        positions = [start]
        cur = start
        for _ in range(7):
            cur = (cur + direction) % 8
            positions.append(cur)
        return positions
    positions = [start]
    cur = start
    guard = 0
    while cur != end:
        cur = (cur + direction) % 8
        positions.append(cur)
        guard += 1
        if guard > 8:
            break
    return positions


def _waypoints(positions: List[int]) -> List[Tuple[float, int]]:
    total = len(positions) - 1
    if total <= 0:
        return [(0.0, positions[0]), (1.0, positions[-1])]
    return [(i / total, p) for i, p in enumerate(positions)]


def slide_waypoints(slide: Slide) -> List[Tuple[float, int]]:
    """Return ``(progress, button_position)`` waypoints tracing a slide."""
    start, end, pattern = slide.start, slide.end, slide.pattern

    if pattern == "-":
        return [(0.0, start), (1.0, end)]

    if pattern in "^<>":
        if pattern == "<":
            direction = -1
        elif pattern == ">":
            direction = 1
        else:
            if start == end:
                direction = 1
            else:
                cw = (end - start) % 8
                direction = 1 if cw <= 4 else -1
        return _waypoints(_arc_positions(start, end, direction))

    if pattern == "v":
        return [(0.0, start), (0.5, (start + 4) % 8), (1.0, end)]

    if pattern == "V":
        reflect = slide.reflect if slide.reflect is not None else (start + 4) % 8
        return [(0.0, start), (0.5, reflect), (1.0, end)]

    if pattern in "pq":
        direction = -1 if pattern == "p" else 1
        return _loop_and_arc(start, end, direction, 8)

    if pattern in ("pp", "qq"):
        direction = -1 if pattern == "pp" else 1
        return _loop_and_arc(start, end, direction, 12)

    # s/z (zigzag) and w (fan): straight approximation.
    return [(0.0, start), (1.0, end)]


def _loop_and_arc(start: int, end: int, direction: int, loop_steps: int) -> List[Tuple[float, int]]:
    positions = [start]
    cur = start
    for _ in range(loop_steps):
        cur = (cur + direction) % 8
        positions.append(cur)
    guard = 0
    while cur != end:
        cur = (cur + direction) % 8
        positions.append(cur)
        guard += 1
        if guard > 8:
            break
    return _waypoints(positions)


# --------------------------------------------------------------------------- #
# SUS writing
# --------------------------------------------------------------------------- #

def _emit_metadata(lines: List[str], metadata: dict, level: str, difficulty: int,
                   songid: Optional[str]):
    title = metadata.get("title", "Untitled")
    artist = metadata.get("artist", "")
    designers = metadata.get("designers", {})
    designer = designers.get("0") or designers.get("1") or ""
    lines.append(f'#TITLE "{title}"')
    if artist:
        lines.append(f'#ARTIST "{artist}"')
    if designer:
        lines.append(f'#DESIGNER "{designer}"')
    lines.append(f'#PLAYLEVEL "{level}"')
    lines.append(f"#DIFFICULTY {difficulty}")
    if songid:
        lines.append(f'#SONGID "{songid}"')
    lines.append("")
    lines.append(f"#00002: {BAR_LENGTH:g}")
    lines.append("")


class ChannelProvider:
    def __init__(self):
        self.channels: Dict[int, Tuple[int, int]] = {}

    def get(self, start_tick: int, end_tick: int) -> int:
        for cid, (s, e) in self.channels.items():
            if end_tick <= s or start_tick >= e:
                self.channels[cid] = (start_tick, end_tick)
                return cid
        cid = len(self.channels)
        self.channels[cid] = (start_tick, end_tick)
        return cid


def chart_to_sus(chart: Chart, metadata: dict, level: str,
                 difficulty: int, songid: Optional[str] = None) -> str:
    raws: Dict[Tuple[int, str], Dict[int, str]] = {}

    def add_raw(tick: int, info: str, data: str):
        measure = tick // TICKS_PER_MEASURE
        offset = tick % TICKS_PER_MEASURE
        raws.setdefault((measure, info), {})[offset] = data

    # BPM definitions (unique, in order of first appearance)
    bpm_ids: Dict[float, str] = {}
    for bpm in chart.bpms:
        key = round(bpm.value, 4)
        if key not in bpm_ids:
            bpm_ids[key] = b36_fixed(len(bpm_ids) + 1, 2)
        add_raw(measure_to_tick(bpm.measure), "08", bpm_ids[key])

    taps = [n for n in chart.notes if isinstance(n, Tap)]
    holds = [n for n in chart.notes if isinstance(n, Hold)]
    slides = [n for n in chart.notes if isinstance(n, Slide)]
    touches = [n for n in chart.notes if isinstance(n, (TouchTap, TouchHold))]

    for tap in taps:
        add_raw(measure_to_tick(tap.measure), f"1{b36(button_lane(tap.position))}",
                f"1{b36(1)}")

    hold_providers: Dict[int, ChannelProvider] = {}

    def hold_channel(lane: int, start_tick: int, end_tick: int) -> str:
        provider = hold_providers.setdefault(lane, ChannelProvider())
        return b36(provider.get(start_tick, end_tick))

    for hold in holds:
        lane = button_lane(hold.position)
        start_tick = measure_to_tick(hold.measure)
        end_tick = measure_to_tick(hold.measure + hold.duration)
        channel = hold_channel(lane, start_tick, end_tick)
        info = f"2{b36(lane)}{channel}"
        add_raw(start_tick, info, f"1{b36(1)}")
        add_raw(end_tick, info, f"2{b36(1)}")

    for touch in touches:
        lane = touch_lane(touch.region, touch.position)
        if isinstance(touch, TouchHold):
            start_tick = measure_to_tick(touch.measure)
            end_tick = measure_to_tick(touch.measure + touch.duration)
            channel = hold_channel(lane, start_tick, end_tick)
            info = f"2{b36(lane)}{channel}"
            add_raw(start_tick, info, f"1{b36(1)}")
            add_raw(end_tick, info, f"2{b36(1)}")
        else:
            add_raw(measure_to_tick(touch.measure), f"1{b36(lane)}", f"1{b36(1)}")

    # Slide channels are global: a slide's notes span several lanes but share
    # one channel, so any two overlapping slides must get distinct channels.
    slide_provider = ChannelProvider()
    for slide in sorted(slides, key=lambda s: s.measure):
        start_tick = measure_to_tick(slide.measure)
        move_start = slide.measure + slide.delay
        end_tick = measure_to_tick(move_start + slide.duration)
        channel = b36(slide_provider.get(start_tick, end_tick))

        add_raw(start_tick, f"3{b36(button_lane(slide.start))}{channel}", f"1{b36(1)}")

        waypoints = slide_waypoints(slide)
        for progress, position in waypoints:
            if progress <= 0.0 or progress >= 1.0:
                continue
            tick = measure_to_tick(move_start + progress * slide.duration)
            add_raw(tick, f"3{b36(button_lane(position))}{channel}", f"3{b36(1)}")

        add_raw(end_tick, f"3{b36(button_lane(slide.end))}{channel}", f"2{b36(1)}")

    lines: List[str] = []
    _emit_metadata(lines, metadata, level, difficulty, songid)

    for key, value in bpm_ids.items():
        lines.append(f"#BPM{value}: {key:g}")
    lines.append("")

    for (measure, info) in sorted(raws):
        cells = raws[(measure, info)]
        gcd = TICKS_PER_MEASURE
        for offset in cells:
            gcd = math.gcd(offset, gcd)
        if gcd == 0:
            gcd = TICKS_PER_MEASURE
        if TICKS_PER_MEASURE // gcd > MAX_SUBDIVISIONS:
            step = TICKS_PER_MEASURE // MAX_SUBDIVISIONS
            snapped: Dict[int, str] = {}
            for offset, data in cells.items():
                snapped.setdefault((offset + step // 2) // step * step, data)
            cells = snapped
            gcd = step
        parts = [cells.get(i, "00") for i in range(0, TICKS_PER_MEASURE, gcd)]
        lines.append(f"#{measure:03d}{info}: {''.join(parts)}")
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

DIFFICULTY_BY_INDEX = {
    "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 4, "7": 4,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a maimai simai chart (maidata.txt) to SUS format.")
    parser.add_argument("input", help="path to maidata.txt")
    parser.add_argument("-o", "--output", default=None,
                        help="output directory (default: alongside input)")
    parser.add_argument("--songid", default=None, help="optional #SONGID value")
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    metadata, charts = parse_maidata(text)
    out_dir = args.output or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(out_dir, exist_ok=True)

    title = metadata.get("title", "untitled")
    whole_bpm = None
    if metadata.get("wholebpm"):
        try:
            whole_bpm = float(metadata["wholebpm"])
        except ValueError:
            whole_bpm = None

    written = 0
    for num in sorted(charts, key=lambda k: int(k)):
        chart = parse_chart(charts[num], whole_bpm)
        level = metadata.get("levels", {}).get(num, "?")
        difficulty = DIFFICULTY_BY_INDEX.get(num, 4)
        sus = chart_to_sus(chart, metadata, level, difficulty, args.songid)
        safe_title = "".join(c if c.isalnum() or c in "-_" else "_"
                             for c in title).strip("_") or "untitled"
        out_path = os.path.join(out_dir, f"{safe_title}_{num}.sus")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(sus)
        print(f"wrote {out_path} ({len(chart.notes)} notes)")
        written += 1

    if written == 0:
        print("no charts (&inote_N) found in input", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
