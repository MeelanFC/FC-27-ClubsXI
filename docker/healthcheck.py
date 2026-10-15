"""Healthy means a poll cycle finished recently enough."""
import os
import sqlite3
import sys
import time

db_path = os.environ.get("CLUBSXI_DB", "/data/clubsxi.sqlite3")
poll_minutes = int(os.environ.get("CLUBSXI_POLL_MINUTES", "30"))
# Allow three missed cycles before calling it unhealthy. EA has outages.
allowed_gap = poll_minutes * 60 * 3

try:
    conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True, timeout=10)
    last = conn.execute("SELECT MAX(finished_at) FROM poll_log").fetchone()[0]
except Exception as exc:
    print("cannot read poll log: " + str(exc))
    sys.exit(1)

if not last:
    print("no completed poll yet")
    sys.exit(1)

age = int(time.time()) - int(last)
print("last poll finished " + str(age) + "s ago")
sys.exit(0 if age < allowed_gap else 1)
