"""The cards page as a standalone file. The page lives in src/clubsxi/formation.py;
the live viewer shows the same thing on its Squad tab.

    python tools/formation_preview.py ARCHIVE.jsonl LEAGUE.json OUT.html [PINS.txt]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from clubsxi import formation  # noqa: E402

formation.main()
