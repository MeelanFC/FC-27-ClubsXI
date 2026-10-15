"""SQLite setup and the few helpers the rest of the collector needs."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "2"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(matches)")}
    for name, definition in (("source", "TEXT NOT NULL DEFAULT 'own'"),
                             ("seed_club_id", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {name} {definition}")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def store_raw_response(conn: sqlite3.Connection, endpoint: str,
                       params: dict[str, Any], url: str, http_status: int,
                       body: str, error: str | None,
                       raw_dump_dir: Path | None = None) -> int:
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO raw_responses "
        "(fetched_at, url, endpoint, params_json, http_status, error, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, url, endpoint, json.dumps(params, sort_keys=True),
         http_status, error, body),
    )
    raw_id = int(cursor.lastrowid)

    if raw_dump_dir is not None:
        raw_dump_dir.mkdir(parents=True, exist_ok=True)
        safe = endpoint.strip("/").replace("/", "_")
        (raw_dump_dir / f"{now}_{raw_id}_{safe}.json").write_text(
            body, encoding="utf-8")

    return raw_id


def known_match_ids(conn: sqlite3.Connection, match_ids: list[str]) -> set[str]:
    if not match_ids:
        return set()
    placeholders = ",".join("?" for _ in match_ids)
    rows = conn.execute(
        f"SELECT match_id FROM matches WHERE match_id IN ({placeholders})",
        match_ids,
    ).fetchall()
    return {row["match_id"] for row in rows}


def start_poll(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO poll_log (started_at) VALUES (?)", (int(time.time()),))
    conn.commit()
    return int(cursor.lastrowid)


def finish_poll(conn: sqlite3.Connection, poll_id: int, *, calls_made: int,
                calls_failed: int, matches_seen: int, matches_new: int,
                matches_duplicate: int, errors: list[str]) -> None:
    conn.execute(
        "UPDATE poll_log SET finished_at = ?, calls_made = ?, calls_failed = ?, "
        "matches_seen = ?, matches_new = ?, matches_duplicate = ?, errors = ? "
        "WHERE id = ?",
        (int(time.time()), calls_made, calls_failed, matches_seen, matches_new,
         matches_duplicate, "\n".join(errors) or None, poll_id),
    )
    conn.commit()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "matches": one("SELECT COUNT(*) FROM matches"),
        "match_clubs": one("SELECT COUNT(*) FROM match_clubs"),
        "players": one("SELECT COUNT(*) FROM players"),
        "player_match_stats": one("SELECT COUNT(*) FROM player_match_stats"),
        "raw_responses": one("SELECT COUNT(*) FROM raw_responses"),
    }
