"""SUS (Sliding Universal Score) writer."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .model import (
    BAR_LENGTH,
    MAX_SUBDIVISIONS,
    NOTE_WIDTH,
    TICKS_PER_MEASURE,
    Chart,
    Hold,
    Slide,
    Tap,
    TouchHold,
    TouchTap,
    b36,
    b36_fixed,
    button_lane,
    measure_to_tick,
    touch_lane,
)


def _emit_metadata(lines: List[str], metadata: dict, level: str, difficulty: int,
                   songid: Optional[str], designer: str = "",
                   wave: Optional[str] = None, jacket: Optional[str] = None):
    title = metadata.get("title", "Untitled")
    artist = metadata.get("artist", "")
    lines.append(f'#TITLE "{title}"')
    if artist:
        lines.append(f'#ARTIST "{artist}"')
    if designer:
        lines.append(f'#DESIGNER "{designer}"')
    lines.append(f"#PLAYLEVEL {level}")
    lines.append(f"#DIFFICULTY {difficulty}")
    if songid:
        lines.append(f'#SONGID "{songid}"')
    if wave:
        lines.append(f'#WAVE "{wave}"')
        lines.append("#WAVEOFFSET 0")
    if jacket:
        lines.append(f'#JACKET "{jacket}"')
    lines.append("")
    lines.append('#REQUEST "ticks_per_beat 480"')
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


def chart_to_sus(chart: Chart, metadata: dict, level: str,
                 difficulty: int, songid: Optional[str] = None,
                 designer: str = "", wave: Optional[str] = None,
                 jacket: Optional[str] = None) -> str:
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
                f"1{b36(NOTE_WIDTH)}")

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
        add_raw(start_tick, info, f"1{b36(NOTE_WIDTH)}")
        add_raw(end_tick, info, f"2{b36(NOTE_WIDTH)}")

    for touch in touches:
        lane = touch_lane(touch.region, touch.position)
        if isinstance(touch, TouchHold):
            start_tick = measure_to_tick(touch.measure)
            end_tick = measure_to_tick(touch.measure + touch.duration)
            channel = hold_channel(lane, start_tick, end_tick)
            info = f"2{b36(lane)}{channel}"
            add_raw(start_tick, info, f"1{b36(NOTE_WIDTH)}")
            add_raw(end_tick, info, f"2{b36(NOTE_WIDTH)}")
        else:
            add_raw(measure_to_tick(touch.measure), f"5{b36(lane)}", f"1{b36(NOTE_WIDTH)}")

    # Slide channels are global: a slide's notes span several lanes but share
    # one channel, so any two overlapping slides must get distinct channels.
    slide_provider = ChannelProvider()
    for slide in sorted(slides, key=lambda s: s.measure):
        start_tick = measure_to_tick(slide.measure)
        move_start = slide.measure + slide.delay
        end_tick = measure_to_tick(move_start + slide.duration)
        channel = b36(slide_provider.get(start_tick, end_tick))

        if not slide.tapless:
            add_raw(start_tick, f"4{b36(button_lane(slide.start))}{channel}",
                    f"1{b36(NOTE_WIDTH)}")

        waypoints = slide_waypoints(slide)
        for progress, position in waypoints:
            if progress <= 0.0 or progress >= 1.0:
                continue
            tick = measure_to_tick(move_start + progress * slide.duration)
            add_raw(tick, f"4{b36(button_lane(position))}{channel}", f"3{b36(NOTE_WIDTH)}")

        add_raw(end_tick, f"4{b36(button_lane(slide.end))}{channel}", f"2{b36(NOTE_WIDTH)}")

    lines: List[str] = []
    _emit_metadata(lines, metadata, level, difficulty, songid, designer, wave, jacket)

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
        lines.append(f"#{b36_fixed(measure, 3)}{info}: {''.join(parts)}")
    lines.append("")

    return "\n".join(lines)
