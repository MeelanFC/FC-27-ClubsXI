"""Scrim scorecard as a standalone page, from an archive export.

    python tools/scrim_scorecard.py ARCHIVE.jsonl OUT.html

The scoring lives in src/clubsxi/scrims.py (read its docstring); the live viewer
shows the same thing at /scrims. Prints the Discord summary of the latest night.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from clubsxi import scrims as sc  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    matches = (json.loads(line)["raw"] for line in open(sys.argv[1], encoding="utf-8"))
    scrims = sc.scored(matches)
    open(sys.argv[2], "w", encoding="utf-8").write(sc.render(scrims))
    nights = sc.by_night(scrims)
    print(f"{len(scrims)} scrims over {len(nights)} nights -> {sys.argv[2]}\n")
    if nights:
        night, ss = next(iter(nights.items()))
        print(sc.discord(night, ss))


if __name__ == "__main__":
    main()
