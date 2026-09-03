"""CHUNITHM UGC (Umiguri) writer."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .model import (
    NOTE_WIDTH,
    Chart,
    Hold,
    Slide,
    Tap,
    TouchHold,
    TouchTap,
    b36_fixed,
    button_lane,
    h36,
    measure_to_bar_tick,
    measure_to_tick,
    touch_lane,
)

# AIR-CRUSH encoding for touch taps: the "purple air" that needs a shake.
# `C{x}{w}{hh}{c},{interval}` + `#OffsetTick:c{x}{w}{hh}`.
AIR_CRUSH_WIDTH = "4"        # note width
AIR_CRUSH_INTERVAL = "240"   # shake interval in ticks (0.5 beat)
AIR_CRUSH_TAP_TICKS = 480    # shake length for a touch tap (1 beat)

# maimai touch region -> air height (C2S 1..5).  The region sits on a different
# band of the touch screen, so give each a different air height.
TOUCH_REGION_HEIGHT = {
    "A": 5,  # top
    "B": 3,  # button ring
    "C": 3,  # center point
    "D": 1,  # bottom
    "E": 4,  # center ring
}

# Color assignment, mirroring maimai: a single touch is purple, and each touch
# in a simultaneous chord gets a distinct color.
AIR_CRUSH_SINGLE_COLOR = "0"  # normal / purple
AIR_CRUSH_CHORD_COLORS = [
    "1",  # red
    "9",  # blue
    "5",  # green
    "3",  # yellow
    "2",  # orange
    "4",  # grass
    "6",  # sky
    "7",  # sky blue
    "8",  # cobalt
    "A",  # violet
    "B",  # pink
    "C",  # white
    "D",  # black
]


def _air_height(c2s_height: int) -> str:
    """Encode a C2S air height (1..5) as a 2-char UGC height."""
    return b36_fixed((c2s_height - 1) * 2 * 10, 2).upper()


def _region_height(region: str) -> int:
    return TOUCH_REGION_HEIGHT.get(region, 3)


def _touch_color_map(chart: Chart) -> Dict[int, str]:
    """Assign an air-crush color to each touch note.

    Single touch -> ``AIR_CRUSH_SINGLE_COLOR`` (purple); a chord of simultaneous
    touches -> distinct ``AIR_CRUSH_CHORD_COLORS`` in note order.
    """
    groups: Dict[float, List] = {}
    for note in chart.notes:
        if isinstance(note, (TouchTap, TouchHold)):
            groups.setdefault(round(note.measure, 6), []).append(note)
    color_map: Dict[int, str] = {}
    for members in groups.values():
        for i, note in enumerate(members):
            color_map[id(note)] = (
                AIR_CRUSH_SINGLE_COLOR if len(members) == 1
                else AIR_CRUSH_CHORD_COLORS[i % len(AIR_CRUSH_CHORD_COLORS)]
            )
    return color_map


def chart_to_ugc(chart: Chart, metadata: dict, level: str,
                 difficulty: int, songid: Optional[str] = None,
                 designer: str = "", wave: Optional[str] = None,
                 jacket: Optional[str] = None) -> str:
    """Render a chart as CHUNITHM UGC (Umiguri) text.

    Note type mapping
    -----------------
    * tap -> TAP (``t``)
    * hold -> HOLD (``h``)
    * slide -> star head TAP + AIR-HOLD on the startup beat, then SLIDE once
      the star starts moving (holdable ground slide).
    * touch (C/B/E/A/D) -> AIR-CRUSH (``C``, the "purple air" that shakes).
      A single touch is purple; simultaneous touches get distinct colors.
    """
    title = metadata.get("title", "Untitled")
    artist = metadata.get("artist", "")

    lines: List[str] = []
    lines.append("' Created with simai_to_ugc")
    lines.append("@VER\t8")
    lines.append("@EXVER\t1")
    lines.append(f"@TITLE\t{title}")
    if artist:
        lines.append(f"@ARTIST\t{artist}")
    if designer:
        lines.append(f"@DESIGN\t{designer}")
    lines.append(f"@DIFF\t{difficulty}")
    lines.append(f"@LEVEL\t{level}")
    lines.append("@CONST\t0.00000")
    lines.append(f"@SONGID\t{songid or 'MuC-0'}")
    if wave:
        lines.append(f"@BGM\t{wave}")
    if jacket:
        lines.append(f"@JACKET\t{jacket}")
    lines.append("@FLAG\tHIPRECISION\tTRUE")
    lines.append("@TICKS\t480")
    lines.append("@BEAT\t0\t4\t4")
    for bpm in chart.bpms:
        bar, tick = measure_to_bar_tick(bpm.measure)
        lines.append(f"@BPM\t{bar}'{tick}\t{bpm.value:.5f}")
    lines.append("@MAINTIL\t0")
    lines.append("@ENDHEAD")
    lines.append("")

    groups: List[Tuple[float, List[str]]] = []

    def add_group(m: float, block: List[str]) -> None:
        groups.append((m, block))

    w = h36(NOTE_WIDTH)
    touch_colors = _touch_color_map(chart)

    for note in sorted(chart.notes, key=lambda n: n.measure):
        if isinstance(note, Tap):
            bar, tick = measure_to_bar_tick(note.measure)
            cell = h36(button_lane(note.position))
            add_group(note.measure, [f"#{bar}'{tick}:t{cell}{w}"])
        elif isinstance(note, Hold):
            bar, tick = measure_to_bar_tick(note.measure)
            cell = h36(button_lane(note.position))
            dur = measure_to_tick(note.duration)
            block = [f"#{bar}'{tick}:h{cell}{w}"]
            if dur > 0:
                block.append(f"#{dur}>s")
            add_group(note.measure, block)
        elif isinstance(note, Slide):
            sc = h36(button_lane(note.start))
            ec = h36(button_lane(note.end))
            d_ticks = measure_to_tick(note.delay)
            m_ticks = measure_to_tick(note.duration)
            if not note.tapless:
                # star head: tap + air hold (startup beat / prepare delay)
                bar, tick = measure_to_bar_tick(note.measure)
                block = [f"#{bar}'{tick}:t{sc}{w}", f"#{bar}'{tick}:H{sc}{w}N"]
                if d_ticks > 0:
                    block.append(f"#{d_ticks}>s")
                add_group(note.measure, block)
            # star: holdable ground slide
            star = note.measure + note.delay
            bar, tick = measure_to_bar_tick(star)
            block2 = [f"#{bar}'{tick}:s{sc}{w}"]
            if m_ticks > 0:
                block2.append(f"#{m_ticks}>s{ec}{w}")
            add_group(star, block2)
        elif isinstance(note, TouchTap):
            bar, tick = measure_to_bar_tick(note.measure)
            cell = h36(touch_lane(note.region, note.position))
            color = touch_colors[id(note)]
            height = _air_height(_region_height(note.region))
            crush = (f"C{cell}{AIR_CRUSH_WIDTH}{height}{color},"
                     f"{AIR_CRUSH_INTERVAL}")
            add_group(note.measure, [
                f"#{bar}'{tick}:{crush}",
                f"#{AIR_CRUSH_TAP_TICKS}>c{cell}{AIR_CRUSH_WIDTH}{height}",
            ])
        elif isinstance(note, TouchHold):
            bar, tick = measure_to_bar_tick(note.measure)
            cell = h36(touch_lane(note.region, note.position))
            height = _air_height(_region_height(note.region))
            dur = measure_to_tick(note.duration)
            block = [f"#{bar}'{tick}:H{cell}{AIR_CRUSH_WIDTH}{height}N"]
            if dur > 0:
                block.append(f"#{dur}>s")
            add_group(note.measure, block)

    for _, block in sorted(groups, key=lambda g: g[0]):
        lines.extend(block)

    return "\n".join(lines) + "\n"
