"""Test settings. Every test file imports this first, so the tests need no
setup with pytest or with  python -m unittest discover -s tests.

The fixtures use made-up club ids:

100001  main club (this season)
100002  practice club (this season)
100003  main club under last season's id (history only)
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

os.environ["CLUBSXI_CLUB_IDS"] = "100001,100002,100003"
os.environ["CLUBSXI_SEASON_CLUB_IDS"] = "100001,100002"
os.environ["CLUBSXI_PRACTICE_CLUB"] = "100002"
os.environ["CLUBSXI_SEASON_START"] = "0"
os.environ["CLUBSXI_TIMEZONE"] = "UTC"
os.environ["CLUBSXI_SAME_PERSON"] = str(HERE / "fixtures" / "same_person.txt")

src = str(HERE.parent / "src")
if src not in sys.path:
    sys.path.insert(0, src)
