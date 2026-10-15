"""Turns one raw EA match object into database rows.

Two rules run through everything here:
  1. Nothing is thrown away. Unknown fields land in extras_json, the whole
     object lands in raw_json.
  2. Nothing is deleted. Bad games and non-appearances are flagged.

Ingest is deterministic: the same match object always produces the same rows.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

# Fields we lift into real columns. Everything else on a player object goes to
# extras_json so a future us can still find it.
_PLAYER_COLUMN_SOURCE = {
    "pos": "pos",
    "archetype_id": "archetypeid",
    "seconds_played": "secondsPlayed",
    "game_time": "gameTime",
    "rating": "rating",
    "goals": "goals",
    "assists": "assists",
    "shots": "shots",
    "passes_made": "passesmade",
    "pass_attempts": "passattempts",
    "tackles_made": "tacklesmade",
    "tackle_attempts": "tackleattempts",
    "saves": "saves",
    "goals_conceded": "goalsconceded",
    "clean_sheets_any": "cleansheetsany",
    "clean_sheets_def": "cleansheetsdef",
    "clean_sheets_gk": "cleansheetsgk",
    "red_cards": "redcards",
    "mom": "mom",
    "wins": "wins",
    "losses": "losses",
    "user_result": "userResult",
    "vpro_hack_reason": "vprohackreason",
    "event_aggregate_0": "match_event_aggregate_0",
    "event_aggregate_1": "match_event_aggregate_1",
    "event_aggregate_2": "match_event_aggregate_2",
    "event_aggregate_3": "match_event_aggregate_3",
}

_INT_COLUMNS = {
    "seconds_played", "game_time", "goals", "assists", "shots", "passes_made",
    "pass_attempts", "tackles_made", "tackle_attempts", "saves",
    "goals_conceded", "clean_sheets_any", "clean_sheets_def", "clean_sheets_gk",
    "red_cards", "mom", "wins", "losses",
}

# Review rule D6. A row counts as a near-complete recorded appearance only
# if it reaches this share of the LONGEST appearance in the same match.
#
# The longest human appearance is the only duration proxy the payload gives us.
# There is no match clock. Anything below the bar is participation evidence, not
# grounds for attributing a whole-match result to that player.
NEAR_COMPLETE_RATIO = 0.9

# Kept as the old name so nothing breaks if something still imports it.
SHORT_APPEARANCE_RATIO = NEAR_COMPLETE_RATIO


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def classify_match(match: dict) -> tuple[str, list[str]]:
    """Returns (validity, notes)."""
    notes: list[str] = []
    clubs = match.get("clubs") or {}
    players = match.get("players") or {}

    broken = False
    if len(clubs) != 2:
        notes.append("expected 2 clubs, found " + str(len(clubs)))
        broken = True
    if not players:
        notes.append("no player block")
        broken = True
    for club_id, club in clubs.items():
        if club.get("goals") is None or club.get("goalsAgainst") is None:
            notes.append("club " + str(club_id) + " missing score")
            broken = True

    dnf = any(_to_int(c.get("winnerByDnf")) not in (0, None)
              for c in clubs.values())
    if dnf:
        notes.append("winnerByDnf set")

    hacked = any(
        _to_int(p.get("vprohackreason")) not in (0, None)
        for club_players in players.values()
        for p in club_players.values()
    )
    if hacked:
        notes.append("vprohackreason not zero")

    if broken:
        return "incomplete", notes
    if hacked:
        return "suspicious", notes
    if dnf:
        return "dnf", notes
    return "ok", notes


def classify_appearance(seconds: int | None, longest: int) -> tuple[str, bool]:
    """Returns (appearance_class, is_real_appearance).

    ghost - EA reported zero seconds. Never a real appearance.
    short - played, but under 90 percent of the longest appearance in the match.
            Real, counts as participation, not near-complete.
    full  - a near-complete recorded appearance.
    """
    if seconds is None or seconds <= 0:
        return "ghost", False
    if longest > 0 and seconds < longest * NEAR_COMPLETE_RATIO:
        return "short", True
    return "full", True


def _outcome(goals_for: int | None, goals_against: int | None) -> str:
    if goals_for is None or goals_against is None:
        return "unknown"
    if goals_for > goals_against:
        return "win"
    if goals_for < goals_against:
        return "loss"
    return "draw"


def _upsert_player(conn: sqlite3.Connection, player_id: str, name: str | None,
                   seen_at: int) -> None:
    conn.execute(
        "INSERT INTO players (player_id, latest_name, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (player_id) DO UPDATE SET "
        "  latest_name = COALESCE(excluded.latest_name, players.latest_name), "
        "  first_seen  = MIN(players.first_seen, excluded.first_seen), "
        "  last_seen   = MAX(players.last_seen, excluded.last_seen)",
        (player_id, name, seen_at, seen_at),
    )
    if name:
        conn.execute(
            "INSERT INTO player_names (player_id, name, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (player_id, name) DO UPDATE SET "
            "  first_seen = MIN(player_names.first_seen, excluded.first_seen), "
            "  last_seen  = MAX(player_names.last_seen, excluded.last_seen)",
            (player_id, name, seen_at, seen_at),
        )


def _insert_player_row(conn: sqlite3.Connection, match_id: str, club_id: str,
                       player_id: str, player: dict, appearance: str,
                       is_real: bool) -> None:
    values: dict[str, Any] = {}
    for column, source in _PLAYER_COLUMN_SOURCE.items():
        raw = player.get(source)
        if column in _INT_COLUMNS:
            values[column] = _to_int(raw)
        elif column == "rating":
            values[column] = _to_float(raw)
        else:
            values[column] = None if raw is None else str(raw)

    known_sources = set(_PLAYER_COLUMN_SOURCE.values()) | {"playername"}
    extras = {k: v for k, v in player.items() if k not in known_sources}

    columns = (["match_id", "club_id", "player_id", "player_name"]
               + list(_PLAYER_COLUMN_SOURCE)
               + ["appearance_class", "is_real_appearance",
                  "extras_json", "raw_json"])
    row = ([match_id, club_id, player_id, player.get("playername")]
           + [values[c] for c in _PLAYER_COLUMN_SOURCE]
           + [appearance, 1 if is_real else 0, _json(extras), _json(player)])

    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join("?" for _ in columns)
    conn.execute(
        "INSERT INTO player_match_stats (" + column_sql + ") "
        "VALUES (" + placeholder_sql + ")",
        row,
    )


def ingest_match(conn: sqlite3.Connection, match: dict, *, match_type: str,
                 our_club_ids: set[str], raw_response_id: int | None = None,
                 snapshot_ids: dict[str, int] | None = None,
                 source: str = "own", seed_club_id: str | None = None) -> bool:
    """Inserts one match. Returns True if it was new, False if already stored."""
    match_id = str(match.get("matchId") or "").strip()
    if not match_id:
        raise ValueError("match object has no matchId")

    already = conn.execute(
        "SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone()
    if already:
        return False

    snapshot_ids = snapshot_ids or {}
    now = int(time.time())
    clubs = match.get("clubs") or {}
    players = match.get("players") or {}
    validity, notes = classify_match(match)

    conn.execute(
        "INSERT INTO matches (match_id, match_timestamp, match_type, "
        "winner_by_dnf, club_count, validity, validity_notes, first_seen_at, "
        "raw_response_id, raw_json, source, seed_club_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            _to_int(match.get("timestamp")),
            match_type,
            1 if "winnerByDnf set" in notes else 0,
            len(clubs),
            validity,
            "; ".join(notes) or None,
            now,
            raw_response_id,
            _json(match),
            source,
            seed_club_id,
        ),
    )

    for club_key, club in clubs.items():
        club_id = str(club_key)
        club_players = players.get(club_id) or {}
        longest = max(
            (_to_int(p.get("secondsPlayed")) or 0 for p in club_players.values()),
            default=0,
        )

        real_count = 0
        for player_key, player in club_players.items():
            player_id = str(player_key)
            seconds = _to_int(player.get("secondsPlayed"))
            appearance, is_real = classify_appearance(seconds, longest)
            if is_real:
                real_count += 1
            _upsert_player(conn, player_id, player.get("playername"), now)
            _insert_player_row(conn, match_id, club_id, player_id, player,
                               appearance, is_real)

        goals_for = _to_int(club.get("goals"))
        goals_against = _to_int(club.get("goalsAgainst"))
        details = club.get("details") or {}

        conn.execute(
            "INSERT INTO match_clubs (match_id, club_id, club_name, is_our_club, "
            "goals_for, goals_against, outcome, ea_result, winner_by_dnf, "
            "human_count, real_human_count, team_id, season_id, "
            "club_snapshot_id, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                match_id,
                club_id,
                details.get("name"),
                1 if club_id in our_club_ids else 0,
                goals_for,
                goals_against,
                _outcome(goals_for, goals_against),
                club.get("result"),
                _to_int(club.get("winnerByDnf")) or 0,
                len(club_players),
                real_count,
                str(club.get("TEAM")) if club.get("TEAM") is not None else None,
                str(club.get("season_id")) if club.get("season_id") is not None else None,
                snapshot_ids.get(club_id),
                _json(club),
            ),
        )

    return True


def store_club_snapshot(conn: sqlite3.Connection, club_id: str,
                        stats: dict) -> int:
    cursor = conn.execute(
        "INSERT INTO club_snapshots (club_id, fetched_at, skill_rating, "
        "games_played, wins, losses, ties, goals, goals_against, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            club_id,
            int(time.time()),
            _to_int(stats.get("skillRating")),
            _to_int(stats.get("gamesPlayed")),
            _to_int(stats.get("wins")),
            _to_int(stats.get("losses")),
            _to_int(stats.get("ties")),
            _to_int(stats.get("goals")),
            _to_int(stats.get("goalsAgainst")),
            _json(stats),
        ),
    )
    return int(cursor.lastrowid)


# ---------------------------------------------------------------------------
# Roster snapshots (/members/stats). Review rules D2 and D9.
#
# This is the club's CURRENT roster and each member's CURRENT pro build.
# It is never per match. Rows are timestamped and must never be projected
# backwards onto matches played earlier.
# ---------------------------------------------------------------------------

_MEMBER_COLUMN_SOURCE = {
    "pro_name": "proName",
    "pro_pos": "proPos",
    "favorite_position": "favoritePosition",
    "pro_style": "proStyle",
    "pro_overall": "proOverall",
    "pro_height": "proHeight",
    "pro_nationality": "proNationality",
    "games_played": "gamesPlayed",
    "win_rate": "winRate",
    "goals": "goals",
    "assists": "assists",
    "rating_ave": "ratingAve",
    "passes_made": "passesMade",
    "pass_success_rate": "passSuccessRate",
    "tackles_made": "tacklesMade",
    "tackle_success_rate": "tackleSuccessRate",
    "shot_success_rate": "shotSuccessRate",
    "clean_sheets_def": "cleanSheetsDef",
    "clean_sheets_gk": "cleanSheetsGK",
    "man_of_the_match": "manOfTheMatch",
    "red_cards": "redCards",
}

_MEMBER_INT_COLUMNS = {
    "pro_overall", "pro_height", "games_played", "win_rate", "goals",
    "assists", "passes_made", "pass_success_rate", "tackles_made",
    "tackle_success_rate", "shot_success_rate", "clean_sheets_def",
    "clean_sheets_gk", "man_of_the_match", "red_cards",
}


def _resolve_player_id(conn: sqlite3.Connection, name: str) -> str | None:
    """Soft name lookup. /members/stats carries no numeric EA player id.

    Returns None when the name is unknown or ambiguous. A wrong link is worse
    than no link, so ties resolve to None.
    """
    rows = conn.execute(
        "SELECT player_id FROM players WHERE latest_name = ?", (name,)
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0][0])
    if rows:
        return None  # ambiguous, refuse to guess

    rows = conn.execute(
        "SELECT DISTINCT player_id FROM player_names WHERE name = ?", (name,)
    ).fetchall()
    return str(rows[0][0]) if len(rows) == 1 else None


def store_member_snapshot(conn: sqlite3.Connection, club_id: str, data: dict,
                          raw_response_id: int | None = None) -> int:
    """Stores one /members/stats response. Returns the snapshot id."""
    members = data.get("members") or []
    now = int(time.time())

    cursor = conn.execute(
        "INSERT INTO member_snapshots (club_id, fetched_at, member_count, "
        "position_count_json, raw_response_id, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            club_id,
            now,
            len(members),
            _json(data.get("positionCount")) if data.get("positionCount") else None,
            raw_response_id,
            _json(data),
        ),
    )
    snapshot_id = int(cursor.lastrowid)

    seen: set[str] = set()
    for member in members:
        name = str(member.get("name") or "").strip()
        if not name or name in seen:
            continue  # EA has been known to repeat a name; keep the first
        seen.add(name)

        values: dict[str, Any] = {}
        for column, source in _MEMBER_COLUMN_SOURCE.items():
            raw = member.get(source)
            if column in _MEMBER_INT_COLUMNS:
                values[column] = _to_int(raw)
            elif column == "rating_ave":
                values[column] = _to_float(raw)
            else:
                values[column] = None if raw is None else str(raw)

        known = set(_MEMBER_COLUMN_SOURCE.values()) | {"name"}
        extras = {k: v for k, v in member.items() if k not in known}

        columns = (["snapshot_id", "club_id", "name", "player_id"]
                   + list(_MEMBER_COLUMN_SOURCE)
                   + ["extras_json", "raw_json"])
        row = ([snapshot_id, club_id, name, _resolve_player_id(conn, name)]
               + [values[c] for c in _MEMBER_COLUMN_SOURCE]
               + [_json(extras), _json(member)])

        conn.execute(
            "INSERT INTO member_snapshot_rows (" + ", ".join(columns) + ") "
            "VALUES (" + ", ".join("?" for _ in columns) + ")",
            row,
        )

    return snapshot_id


def reclassify_appearances(conn: sqlite3.Connection) -> dict[str, int]:
    """Recomputes appearance_class for every stored row.

    Needed when the rule changes, as it did when the review raised the bar
    from half the longest appearance to 90 percent of it. The raw match JSON is
    kept verbatim, so this recomputes rather than guesses, and running it twice
    changes nothing the second time.
    """
    changed = 0
    checked = 0
    moved: dict[str, int] = {}

    rows = conn.execute(
        "SELECT match_id, raw_json FROM matches ORDER BY match_id").fetchall()

    for row in rows:
        match = json.loads(row["raw_json"])
        for club_key, club_players in (match.get("players") or {}).items():
            club_id = str(club_key)
            longest = max(
                (_to_int(p.get("secondsPlayed")) or 0
                 for p in club_players.values()),
                default=0,
            )
            for player_key, player in club_players.items():
                checked += 1
                seconds = _to_int(player.get("secondsPlayed"))
                appearance, is_real = classify_appearance(seconds, longest)

                current = conn.execute(
                    "SELECT appearance_class FROM player_match_stats "
                    "WHERE match_id = ? AND club_id = ? AND player_id = ?",
                    (row["match_id"], club_id, str(player_key))).fetchone()
                if current is None or current["appearance_class"] == appearance:
                    continue

                key = current["appearance_class"] + " -> " + appearance
                moved[key] = moved.get(key, 0) + 1
                changed += 1
                conn.execute(
                    "UPDATE player_match_stats "
                    "SET appearance_class = ?, is_real_appearance = ? "
                    "WHERE match_id = ? AND club_id = ? AND player_id = ?",
                    (appearance, 1 if is_real else 0,
                     row["match_id"], club_id, str(player_key)),
                )

    # real_human_count on match_clubs is derived, so it moves with them.
    conn.execute(
        "UPDATE match_clubs SET real_human_count = ("
        "  SELECT COUNT(*) FROM player_match_stats s "
        "  WHERE s.match_id = match_clubs.match_id "
        "    AND s.club_id = match_clubs.club_id "
        "    AND s.is_real_appearance = 1)")

    result = {"checked": checked, "changed": changed}
    result.update(moved)
    return result
