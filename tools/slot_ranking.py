"""Ranking printout. The engine lives in src/clubsxi/slot_ranking.py (read its docstring).

    python tools/slot_ranking.py ARCHIVE.jsonl [LEAGUE.json]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from clubsxi import slot_ranking  # noqa: E402

slot_ranking.main()
