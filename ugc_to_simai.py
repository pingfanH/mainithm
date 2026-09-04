"""Convert a CHUNITHM UGC chart to a maimai simai (maidata.txt) file.

Usage:
    python ugc_to_simai.py input.ugc [-o output.txt]
"""
from __future__ import annotations

import argparse
import os
import sys

from maiconvert.ugc_parser import parse_ugc
from maiconvert.simai_writer import chart_to_simai


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a CHUNITHM UGC chart to maimai simai (maidata.txt).")
    parser.add_argument("input", help="input .ugc file")
    parser.add_argument("-o", "--output", default=None,
                        help="output maidata.txt path (default: alongside input)")
    args = parser.parse_args(argv)

    in_path = os.path.abspath(args.input)
    with open(in_path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    chart = parse_ugc(text)
    out_text = chart_to_simai(chart)

    out_path = args.output or (
        os.path.splitext(in_path)[0] + "_simai.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)

    print(f"Parsed {len(chart.notes)} UGC notes, wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())