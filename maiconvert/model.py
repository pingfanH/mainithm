"""Note model and shared constants/helpers for the simai -> SUS/UGC converter."""
from __future__ import annotations

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

# button position (0..7) -> lane
POSITION_TO_LANE: Dict[int, int] = {i: 2 * i for i in range(8)}
LANE_OFFSET = 0  # rotate the whole circle by this many lanes

# slide delay in measures (one beat at the current BPM)
SLIDE_DELAY = 0.25

# note width in lanes (maimai buttons are rendered two lanes wide here).
NOTE_WIDTH = 2

# maimai 8-button layout (0-indexed position -> left/center/right column):
#   1(0)  2(1)  3(2)
#   4(3)        5(4)
#   6(5)  7(6)  8(7)
# CHUNITHM air notes only have 6 directions, so the two middle buttons map to
# left/right and there is no pure "left"/"right" direction.
AIR_HORIZONTAL = ["L", "C", "R", "L", "R", "L", "C", "R"]

# simai note modifiers (b=break, x=ex, f=fake, $=tap-to-star, @=star-to-tap,
# ?/!=no-star).  "e" is kept for legacy charts.
MODIFIER_CHARS = "bexf$@?!"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def button_lane(position: int) -> int:
    return (POSITION_TO_LANE[position] + LANE_OFFSET) % 16


def touch_lane(region: str, position: int) -> int:
    return button_lane(position)


def air_direction(up: bool, position: int) -> str:
    """CHUNITHM air direction code: ``U``/``D`` + ``L``/``C``/``R``."""
    return ("U" if up else "D") + AIR_HORIZONTAL[position % 8]


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


def h36(n: int) -> str:
    return B36[n % 36].upper()


def measure_to_bar_tick(measure: float) -> Tuple[int, int]:
    bar = int(measure)
    tick = int(round((measure - bar) * TICKS_PER_MEASURE))
    return bar, tick


def map_level(level: str) -> str:
    """Map a decimal simai level to a display level.

    ``13.1`` -> ``13``, ``13.8`` -> ``13+`` (first decimal digit >= 6 bumps it).
    A level without a decimal (or with an existing ``+``) is returned as-is.
    """
    s = str(level).strip()
    if "." in s:
        base, _, frac = s.partition(".")
        base = base.rstrip("+")
        first = frac[0] if frac else "0"
        if first.isdigit() and int(first) >= 6:
            return f"{base}+"
        return base
    return s


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
