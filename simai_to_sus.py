#!/usr/bin/env python3
"""Convert maimai simai charts (maidata.txt) to CHUNITHM UGC (or SUS).

Format references
-----------------
* simai:  https://w.atwiki.jp/simai/ and the MaiConverter project in this repo.
* UGC:    https://umgr.inonote.jp/en/ (CHUNITHM / Umiguri chart format)
* SUS:    https://gist.github.com/kb10uy/c171c175ba913dc40a73c6ce69da9859
          and https://github.com/mkpoli/sus-io

Usage
-----
    python3 simai_to_sus.py maidata.txt [-o OUT_DIR]   # one chart set -> .ugc
    python3 simai_to_sus.py songs_dir  [-o OUT_DIR]    # batch: scan every maidata.txt
    python3 simai_to_sus.py maidata.txt --format sus   # emit .sus instead

For each chart (``&inote_N``) it emits one ``.ugc`` file with ``@TITLE``,
``@ARTIST``, ``@DESIGN``, ``@DIFF``, ``@LEVEL``, ``@SONGID``, ``@BGM`` and
``@JACKET``.  ``@BGM`` / ``@JACKET`` point to the audio and cover image found
next to the maidata.txt (``track.*`` and ``bg.*`` / ``jacket.*`` by default).

Timing model
------------
* simai measure 0.0 == the first beat of the chart.
* UGC/SUS use ``ticks_per_beat = 480`` and 4/4 bars, so one bar == 1920 ticks.

Lane model
----------
maimai's 8 buttons sit on a 16-lane circular grid, one button every 45 degrees.
Button ``position`` (0..7) maps to lane ``2 * position``; the odd lanes in
between are left free for slide curve control points.

Note type mapping
-----------------
UGC (default):
* tap -> TAP (``t``); hold -> HOLD (``h``).
* slide -> star head TAP + AIR-HOLD (``H``) on the startup beat, then a
  holdable ground SLIDE (``s``).
* touch (C/B/E/A/D) -> TAP/HOLD + AIR (down, purple).

SUS (``--format sus``):
* tap -> SUS tap (``1x``); hold -> SUS hold (``2xy``).
* slide -> SUS slide 2 (``4xy``).
* touch (C/B/E/A/D) -> SUS directional (``5x``).

Known limitations (documented on purpose)
-----------------------------------------
* break / EX / star visual variants collapse into ordinary taps.
* complex slide shapes (p/q/pp/qq/s/z/w) are approximated as polylines;
  straight ``-``, arc ``^<>`` and ``V``/``v`` slides are exact.
"""

from maiconvert.cli import main

if __name__ == "__main__":
    import sys

    sys.exit(main())
