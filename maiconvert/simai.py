"""simai (maidata.txt) parser."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .model import (
    BPM,
    MODIFIER_CHARS,
    SLIDE_DELAY,
    Chart,
    Hold,
    Slide,
    Tap,
    TouchHold,
    TouchTap,
)


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
                suffix = key[len("&des"):]
                metadata["designers"][suffix[1:] if suffix.startswith("_") else "0"] = value
            elif key == "&wholebpm":
                metadata["wholebpm"] = value
            elif key.startswith("&first"):
                suffix = key[len("&first"):]
                metadata["first"][suffix[1:] if suffix.startswith("_") else "0"] = value
            elif key.startswith("&lv_"):
                metadata["levels"][key[4:]] = value
            elif key.startswith("&inote_"):
                num = key[7:]
                charts[num] = value
                current_chart = num
            elif key in ("&genreid", "&genre"):
                metadata["genreid"] = value
            elif key == "&shortid":
                metadata["shortid"] = value
            elif key == "&freemsg":
                metadata["freemsg"] = value
        elif current_chart is not None and line:
            charts[current_chart] += "\n" + line

    return metadata, charts


def parse_duration(s: str) -> Tuple[float, Optional[float], Optional[Tuple[float, float]]]:
    """Parse a ``[den:num]`` / ``[eqbpm#den:num]`` / ``[prep##move]`` / ``[#sec]`` duration.

    Returns ``(duration_in_measures, equivalent_bpm, seconds)``.

    * ``[den:num]`` -> ``(num/den, None, None)`` measures.
    * ``[eqbpm#den:num]`` -> ``(num/den, eqbpm, None)``.
    * ``[prep##move]`` -> ``(0.0, None, (prep, move))``, both in seconds.
    * ``[#sec]`` -> ``(0.0, None, sec)``, a float of seconds.
    """
    if not s.startswith("["):
        return 0.0, None, None
    end = s.find("]")
    inner = s[1:end] if end >= 0 else s[1:]
    if "##" in inner:
        pre, _, post = inner.partition("##")
        try:
            return 0.0, None, (float(pre), float(post))
        except ValueError:
            return 0.0, None, None
    if inner.startswith("#"):
        # [#sec] = an absolute duration in seconds
        try:
            return 0.0, None, float(inner[1:])
        except ValueError:
            return 0.0, None, None
    equivalent_bpm: Optional[float] = None
    if "#" in inner:
        pre, _, inner = inner.partition("#")
        if pre:
            equivalent_bpm = float(pre)
    den_str, _, num_str = inner.partition(":")
    if not den_str or not num_str:
        return 0.0, equivalent_bpm, None
    den = float(den_str)
    num = float(num_str)
    if den <= 0:
        return 0.0, equivalent_bpm, None
    return num / den, equivalent_bpm, None


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
    seconds = None
    if i < len(s) and s[i] == "[":
        duration, _, seconds = parse_duration(s[i:])
    if is_hold:
        return {"type": "touch_hold", "region": region, "position": position,
                "duration": duration, "seconds": seconds}
    return {"type": "touch_tap", "region": region, "position": position}


def parse_slide(start: int, modifier: str, tail: str) -> List[dict]:
    """Parse a slide (and its chained ``*`` segments).

    ``*`` segments are "shared head" slides: they share the first segment's
    star head, so they are marked ``headless``.  A single slide body may carry
    several ``slideType KEY`` segments (``1>2-5[2:1]``), which collapse into one
    slide from the head to the last segment's end.
    """
    slides: List[dict] = []
    segments = tail.split("*")
    inherit_duration = None
    for idx, seg in enumerate(segments):
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
        # collapse further ``slideType KEY`` segments (e.g. ``-5`` in ``1>2-5``)
        while i < len(seg) and seg[i] in "-^<>szvwpqV":
            sp = seg[i]
            j = i + 1
            if sp in "pq" and j < len(seg) and seg[j] in "pq":
                j += 1
            elif sp == "V":
                j += 1  # skip the reflect key
            if j < len(seg) and seg[j].isdigit():
                end = int(seg[j]) - 1
                i = j + 1
            else:
                break
        seg_modifier = modifier
        while i < len(seg) and seg[i] in MODIFIER_CHARS:
            seg_modifier += seg[i]
            i += 1
        duration = inherit_duration
        equivalent_bpm = None
        seconds = None
        if i < len(seg) and seg[i] == "[":
            duration, equivalent_bpm, seconds = parse_duration(seg[i:])
            close = seg.find("]", i)
            k = close + 1 if close >= 0 else len(seg)
            while k < len(seg) and seg[k] in MODIFIER_CHARS:
                seg_modifier += seg[k]
                k += 1
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
            "seconds": seconds,
            "modifier": seg_modifier,
            "headless": idx > 0,
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
        elif ch in MODIFIER_CHARS:
            modifier += ch
        else:
            break
        i += 1

    if is_hold:
        duration = 0.0
        seconds = None
        if i < len(rest) and rest[i] == "[":
            duration, _, seconds = parse_duration(rest[i:])
        if duration <= 0 and seconds is None:
            return [{"type": "tap", "position": button,
                     "ex": ("x" in modifier or "b" in modifier)}]  # hexagonal "tap"
        return [{"type": "hold", "position": button, "duration": duration,
                 "seconds": seconds}]

    if i < len(rest) and rest[i] in "-^<>szvwpqV":
        return parse_slide(button, modifier, rest[i:])

    return [{"type": "tap", "position": button,
             "ex": ("x" in modifier or "b" in modifier)}]


def parse_note(s: str) -> List[dict]:
    if not s:
        return []
    if s[0] in "CBEAD":
        return [parse_touch(s)]
    if s[0].isdigit():
        if len(s) > 1 and s.isdigit():
            # "123" == simultaneous taps 1, 2, 3
            return [{"type": "tap", "position": int(c) - 1} for c in s]
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
            value = fragment[i + 1:j].strip("()")
            try:
                events.append({"type": "bpm", "value": float(value)})
            except ValueError:
                pass
            i = j + 1
            while i < n and fragment[i] == ")":
                i += 1
        elif c == "{":
            j = fragment.index("}", i)
            content = fragment[i + 1:j].strip("{}")
            if not content.startswith("#"):
                try:
                    events.append({"type": "divisor", "value": float(content)})
                except ValueError:
                    pass
            i = j + 1
            while i < n and fragment[i] == "}":
                i += 1
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
        end_after = fragment.endswith("E")
        if end_after:
            fragment = fragment[:-1]
        for ev in parse_fragment(fragment):
            et = ev["type"]
            if et == "bpm":
                chart.bpms.append(BPM(measure, ev["value"]))
            elif et == "divisor":
                divisor = ev["value"] if ev["value"] != 0 else divisor
            else:
                m = measure
                if et == "tap":
                    chart.notes.append(Tap(m, ev["position"], ev.get("ex", False)))
                elif et == "hold":
                    duration = ev["duration"]
                    seconds = ev.get("seconds")
                    if seconds is not None and not isinstance(seconds, tuple):
                        cur = chart.bpms[-1].value if chart.bpms else (
                            whole_bpm or 120.0)
                        duration = seconds * cur / 240.0
                    chart.notes.append(Hold(m, ev["position"], duration))
                elif et == "slide":
                    duration = ev["duration"]
                    delay = SLIDE_DELAY
                    seconds = ev.get("seconds")
                    if seconds is not None:
                        cur = chart.bpms[-1].value if chart.bpms else (
                            whole_bpm or 120.0)
                        if isinstance(seconds, tuple):
                            delay = seconds[0] * cur / 240.0
                            duration = seconds[1] * cur / 240.0
                        else:
                            # [#sec] -> move duration, keep default delay
                            duration = seconds * cur / 240.0
                    else:
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
                        tapless=(any(ch in ev["modifier"] for ch in "?$!")
                                 or ev.get("headless", False)),
                    ))
                elif et == "touch_tap":
                    chart.notes.append(TouchTap(m, ev["position"], ev["region"]))
                elif et == "touch_hold":
                    duration = ev["duration"]
                    seconds = ev.get("seconds")
                    if seconds is not None and not isinstance(seconds, tuple):
                        cur = chart.bpms[-1].value if chart.bpms else (
                            whole_bpm or 120.0)
                        duration = seconds * cur / 240.0
                    chart.notes.append(
                        TouchHold(m, ev["position"], ev["region"], duration))
        if end_after:
            break
        measure += 1.0 / divisor

    if not chart.bpms:
        chart.bpms.append(BPM(0.0, whole_bpm or 120.0))
    chart.bpms.sort(key=lambda b: b.measure)
    chart.notes.sort(key=lambda n: n.measure)
    return chart
