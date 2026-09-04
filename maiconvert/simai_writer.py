"""simai (maidata.txt) writer for UGC charts.

Converts a parsed :class:`UgcChart` into maimai simai text.  Note types that
have no maimai equivalent are mapped to the closest simai representation.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from .ugc_parser import Note, UgcChart

BEATS_PER_BAR_DEFAULT = Fraction(4, 1)

# CHUNITHM air direction -> maimai touch region (best-effort)
AIR_TO_TOUCH = {
    "UC": "C", "DC": "C",
    "UR": "B", "DR": "B",
    "UL": "B", "DL": "B",
}


def _cell_to_button(cell: int) -> int:
    """CHUNITHM lane (0..15) -> maimai button (1..8)."""
    return (cell // 2) % 8 + 1


def _touch_region(cell: int, direction: str, height: float) -> str:
    """Map a CHUNITHM air/crush note to a maimai touch region."""
    if direction:
        return AIR_TO_TOUCH.get(direction, "C")
    if height <= 1.5:
        return "D"
    if height <= 3.0:
        return "C"
    return "A"


def _lcm(a: int, b: int) -> int:
    import math
    return a * b // math.gcd(a, b)


class SimaiWriter:
    """Emits simai text from a :class:`UgcChart`.

    Timing is built on the simai model used by ``parse_chart``: a measure
    (bar) is subdivided by a ``{divisor}`` and each comma advances one slot.
    Each note therefore lands at ``bar + fraction`` where fraction is the
    in-bar slot / divisor.
    """

    def __init__(self, chart: UgcChart):
        self.chart = chart
        self.tl = _Timeline(chart.beats)
        # bar index -> [(fraction-of-bar, fragment)]
        self.bar_notes: Dict[int, List[Tuple[Fraction, str]]] = {}
        # bar index -> [(fraction-of-bar, bpm marker)]
        self.bar_bpms: Dict[int, List[Tuple[Fraction, str]]] = {}

    # ------------------------------------------------------------------ #
    # note -> simai fragment
    # ------------------------------------------------------------------ #

    def _note_fragment(self, n: Note) -> Optional[str]:
        t = n.type
        if t == "tap":
            return f"{_cell_to_button(n.cell)}"
        if t == "chr":
            return f"{_cell_to_button(n.cell)}x"
        if t == "hold":
            return f"{_cell_to_button(n.cell)}h[{self._dur_str(n)}]"
        if t == "slide":
            return self._slide_fragment(n)
        if t == "air_slide":
            return self._slide_fragment(n)
        if t == "air":
            return f"{_touch_region(n.cell, n.direction, n.height)}"
        if t == "air_hold":
            region = _touch_region(n.cell, n.direction, n.height)
            return f"{region}h[{self._dur_str(n)}]"
        if t == "crush":
            return f"{_touch_region(n.cell, n.direction, n.height)}"
        if t == "mine":
            return f"{_cell_to_button(n.cell)}f"  # fake tap
        if t == "flick":
            return f"{_cell_to_button(n.cell)}b"  # break tap
        if t == "click":
            return f"{_cell_to_button(n.cell)}"
        return None

    def _dur_str(self, n: Note) -> str:
        span = self.tl.beats_span(self.tl.bar_of(n.time)[0])
        bars = n.duration / span  # duration in bars
        return f"{bars.denominator}:{bars.numerator}"

    def _slide_fragment(self, n: Note) -> str:
        start = _cell_to_button(n.cell)
        end = _cell_to_button(self._chain_end(n).cell)
        if start == end:
            # zero-length slide is not valid simai; emit a straight line anyway
            return f"{start}-{end}"
        return f"{start}-{end}"

    def _chain_end(self, n: Note) -> Note:
        cur = n
        while cur.prev is not None:
            cur = cur.prev
        return cur

    # ------------------------------------------------------------------ #
    # rendering
    # ------------------------------------------------------------------ #

    def render(self) -> str:
        # collect heads and chain followers into the same slot
        heads: Dict[int, Note] = {}
        for n in self.chart.notes:
            if n.prev is None:
                heads[id(n)] = n

        for n in self.chart.notes:
            frag = self._note_fragment(n)
            if frag is None:
                continue
            bar, frac = self.tl.bar_of(n.time)
            if n.prev is None:
                self.bar_notes.setdefault(bar, []).append((frac, frag))
            else:
                # follower: append its slide body to the head fragment
                head = self._chain_head(n)
                self._extend_slide(head, n)

        for bpm in self.chart.bpms:
            bar, frac = self.tl.bar_of(bpm.time)
            self.bar_bpms.setdefault(bar, []).append(
                (frac, f"({bpm.value:.6g})"))

        lines: List[str] = []
        self._emit_metadata(lines)

        chart_parts: List[str] = []
        self._emit_chart(chart_parts)
        lines.append(f"&inote_0={''.join(chart_parts)}")
        return "\n".join(lines) + "\n"

    def _chain_head(self, n: Note) -> Note:
        cur = n
        while cur.prev is not None:
            cur = cur.prev
        return cur

    def _extend_slide(self, head: Note, seg: Note):
        # extend the head's slide body with the segment's end button
        frag = f"-{_cell_to_button(seg.cell)}"
        bar, frac = self.tl.bar_of(head.time)
        for i, (f, body) in enumerate(self.bar_notes.get(bar, [])):
            if f == frac:
                self.bar_notes[bar][i] = (f, body + frag)
                return

    def _emit_metadata(self, lines: List[str]):
        m = self.chart.meta
        lines.append(f"&title={m.title or 'Untitled'}")
        if m.artist:
            lines.append(f"&artist={m.artist}")
        if m.designer:
            lines.append(f"&des_0={m.designer}")
        lines.append(f"&lv_0={m.level or '?'}")
        if m.songid:
            lines.append(f"&shortid={m.songid}")
        if self.chart.bpms:
            lines.append(f"&wholebpm={self.chart.bpms[0].value:.6g}")

    def _emit_chart(self, parts: List[str]):
        all_bars = sorted(set(list(self.bar_notes.keys()) +
                               list(self.bar_bpms.keys())))
        cursor_measure = Fraction(0)  # last emitted measure position (bars)
        cur_divisor = 4

        for bar in all_bars:
            events: List[Tuple[Fraction, str]] = []
            for f, frag in self.bar_notes.get(bar, []):
                events.append((f, frag))
            for f, frag in self.bar_bpms.get(bar, []):
                events.append((f, frag))
            events.sort(key=lambda x: (x[0], 1 if x[1].startswith("(") else 0))

            # divisor for this bar = LCM of event denominators (min 4)
            dens = [e[0].denominator for e in events if e[0] > 0] or [4]
            div = 4
            for d in dens:
                div = _lcm(div, d)
            div = max(4, div)

            # skip from cursor to this bar's start (bar is an integer)
            target_bar_start = Fraction(bar, 1)
            if target_bar_start > cursor_measure:
                gap_bars = target_bar_start - cursor_measure
                if div != cur_divisor:
                    parts.append(f"{{{div}}}")
                    cur_divisor = div
                slots = int((gap_bars * cur_divisor).numerator)
                parts.append("," * slots)
                cursor_measure = target_bar_start

            for f, frag in events:
                target = Fraction(bar, 1) + f
                gap = target - cursor_measure
                if gap > 0:
                    slots = int((gap * cur_divisor).numerator)
                    if slots > 0:
                        parts.append("," * slots)
                        cursor_measure = target
                parts.append(frag)
                # cursor moves past the note
                cursor_measure = target

            # ensure we end this bar at the next integer so the following
            # bar starts cleanly
            bar_end = Fraction(bar + 1, 1)
            gap = bar_end - cursor_measure
            if gap > 0:
                slots = int((gap * cur_divisor).numerator)
                if slots > 0:
                    parts.append("," * slots)
                    cursor_measure = bar_end

        parts.append("E")


class _Timeline:
    """Converts chart-time (beats) to (bar index, fraction-of-bar)."""

    def __init__(self, beats: List[Tuple[int, Fraction]]):
        self.beats = beats or [(0, BEATS_PER_BAR_DEFAULT)]
        self.bar_times: List[Fraction] = []
        t = Fraction(0)
        for i, (start_bar, bpb) in enumerate(self.beats):
            end_bar = self.beats[i + 1][0] if i + 1 < len(self.beats) else 10 ** 9
            for _ in range(end_bar - start_bar):
                self.bar_times.append(t)
                t += bpb

    def beats_span(self, bar: int) -> Fraction:
        for i, (start_bar, bpb) in enumerate(self.beats):
            end_bar = self.beats[i + 1][0] if i + 1 < len(self.beats) else 10 ** 9
            if start_bar <= bar < end_bar:
                return bpb
        return BEATS_PER_BAR_DEFAULT

    def bar_of(self, time: Fraction) -> Tuple[int, Fraction]:
        bar = 0
        for b in range(len(self.bar_times) - 1):
            if time >= self.bar_times[b + 1]:
                bar = b + 1
            else:
                break
        span = self.beats_span(bar)
        frac = (time - self.bar_times[bar]) / span
        return bar, frac


def chart_to_simai(chart: UgcChart) -> str:
    return SimaiWriter(chart).render()