"""The poll cycle. Ask EA for recent matches, store anything new, log it.

One cycle is, per club: one roster snapshot, then one call per match type.
Two clubs is eight calls, plus one standings call per opponent we have not
seen this cycle. EA does not accept a comma separated club list, so the
per-club calls cannot be reduced.
"""
from __future__ import annotations

import logging
import signal
import sqlite3
import time
from dataclasses import dataclass, field

from . import db, ingest, report
from .config import Config
from .ea_client import ApiResult, EaClient

log = logging.getLogger("clubsxi")


@dataclass
class PollResult:
    calls_made: int = 0
    calls_failed: int = 0
    matches_seen: int = 0
    matches_new: int = 0
    matches_duplicate: int = 0
    roster_snapshots: int = 0
    errors: list[str] = field(default_factory=list)


def _record(conn: sqlite3.Connection, cfg: Config, endpoint: str,
            params: dict, result: ApiResult) -> int:
    return db.store_raw_response(
        conn,
        endpoint=endpoint,
        params=params,
        url=result.url,
        http_status=result.status,
        body=result.body_text,
        error=result.error,
        raw_dump_dir=cfg.raw_dump_dir,
    )


def _snapshot_club(conn: sqlite3.Connection, cfg: Config, client: EaClient,
                   club_id: str, cache: dict[str, int | None],
                   outcome: PollResult) -> int | None:
    """Fetches a club's current standing once per poll cycle and caches it."""
    if club_id in cache:
        return cache[club_id]

    if outcome.calls_made:
        time.sleep(cfg.call_spacing_seconds)
    result = client.club_overall_stats(cfg.platform, club_id)
    outcome.calls_made += 1
    _record(conn, cfg, "/clubs/overallStats",
            {"platform": cfg.platform, "clubIds": club_id}, result)

    snapshot_id: int | None = None
    if result.ok and isinstance(result.data, list):
        # An empty list is normal. Brand new clubs have no all-time record yet.
        if result.data and isinstance(result.data[0], dict):
            snapshot_id = ingest.store_club_snapshot(conn, club_id, result.data[0])
        elif result.data:
            outcome.calls_failed += 1
            outcome.errors.append("overallStats " + club_id + ": unexpected shape")
    else:
        outcome.calls_failed += 1
        outcome.errors.append(
            "overallStats " + club_id + ": " + (result.error or "unexpected shape"))

    cache[club_id] = snapshot_id
    return snapshot_id


def _snapshot_roster(conn: sqlite3.Connection, cfg: Config, client: EaClient,
                     club_id: str, outcome: PollResult) -> None:
    """Saves the club's current roster and pro builds.

    Review rule D9: this is the one thing that is lost forever if we do
    not capture it. /members/stats describes the CURRENT roster only. The row
    is timestamped and must never be projected backwards onto older matches.
    """
    result = client.members_stats(cfg.platform, club_id)
    outcome.calls_made += 1
    raw_id = _record(conn, cfg, "/members/stats",
                     {"platform": cfg.platform, "clubId": club_id}, result)

    if not result.ok or not isinstance(result.data, dict):
        outcome.calls_failed += 1
        message = ("members/stats " + club_id + ": "
                   + (result.error or "unexpected shape"))
        outcome.errors.append(message)
        log.warning("roster snapshot failed: %s", message)
        return

    try:
        ingest.store_member_snapshot(conn, club_id, result.data, raw_id)
        conn.commit()
        outcome.roster_snapshots += 1
        log.info("%s roster snapshot: %d members",
                 club_id, len(result.data.get("members") or []))
    except Exception as exc:
        conn.rollback()
        outcome.errors.append("roster snapshot " + club_id + ": " + str(exc))
        log.exception("roster snapshot failed for %s", club_id)


def _backfill_opponents(conn: sqlite3.Connection, cfg: Config, client: EaClient,
                        cache: dict[str, int | None], outcome: PollResult) -> None:
    # Materialize before ingestion: third parties cannot grow this cycle's queue.
    candidates = conn.execute(
        "SELECT DISTINCT opponent.club_id FROM match_clubs opponent "
        "JOIN match_clubs ours ON ours.match_id = opponent.match_id "
        "WHERE opponent.is_our_club = 0 AND ours.is_our_club = 1 "
        "AND NOT EXISTS (SELECT 1 FROM opponent_history_fetches f "
        "WHERE f.club_id = opponent.club_id) ORDER BY opponent.club_id"
    ).fetchall()
    candidates = [r[0] for r in candidates if r[0] not in cfg.club_ids]
    for club_id in candidates[:max(0, cfg.opponent_history_clubs_per_poll)]:
        # Commit the claim BEFORE any network call. Even interrupted runs never
        # retry this club. INSERT OR IGNORE also protects overlapping collectors.
        claimed = conn.execute(
            "INSERT OR IGNORE INTO opponent_history_fetches (club_id, fetched_at) "
            "VALUES (?, ?)", (club_id, int(time.time()))).rowcount
        conn.commit()
        if not claimed:
            continue
        for match_type in ("leagueMatch", "friendlyMatch", "playoffMatch"):
            time.sleep(cfg.call_spacing_seconds)
            result = client.club_matches(cfg.platform, club_id, match_type, 10)
            outcome.calls_made += 1
            raw_id = _record(conn, cfg, "/clubs/matches", {
                "platform": cfg.platform, "clubIds": club_id,
                "matchType": match_type, "maxResultCount": 10}, result)
            failed = not result.ok or not isinstance(result.data, list)
            matches = [] if failed else result.data
            outcome.calls_failed += int(failed)
            outcome.matches_seen += len(matches)
            conn.execute(
                "UPDATE opponent_history_fetches SET calls_made = calls_made + 1, "
                "calls_failed = calls_failed + ?, matches_seen = matches_seen + ? "
                "WHERE club_id = ?", (int(failed), len(matches), club_id))
            conn.commit()  # raw responses survive a malformed match rollback
            if failed:
                outcome.errors.append("opponent history " + club_id + " "
                                      + match_type + ": "
                                      + (result.error or "unexpected shape"))
            for match in matches:
                try:
                    match_id = str(match.get("matchId") or "").strip()
                    if not match_id:
                        raise ValueError("match object has no matchId")
                    if db.known_match_ids(conn, [match_id]):
                        outcome.matches_duplicate += 1
                        continue
                    snapshots = {}
                    for side in (match.get("clubs") or {}):
                        sid = _snapshot_club(conn, cfg, client, str(side), cache, outcome)
                        conn.commit()  # keep raw responses and cached snapshots
                        if sid is not None:
                            snapshots[str(side)] = sid
                    inserted = ingest.ingest_match(
                        conn, match, match_type=match_type,
                        our_club_ids=set(cfg.club_ids), raw_response_id=raw_id,
                        snapshot_ids=snapshots, source="opponent_history",
                        seed_club_id=club_id)
                    if inserted:
                        conn.execute(
                            "UPDATE opponent_history_fetches "
                            "SET matches_new = matches_new + 1 WHERE club_id = ?",
                            (club_id,))
                    conn.commit()
                    outcome.matches_new += int(inserted)
                    outcome.matches_duplicate += int(not inserted)
                except Exception as exc:
                    conn.rollback()
                    outcome.errors.append("opponent history ingest " + club_id + ": " + str(exc))
                    log.exception("opponent history ingest failed for %s", club_id)


def poll_once(conn: sqlite3.Connection, cfg: Config,
              client: EaClient | None = None) -> PollResult:
    # History has no HTTP retries: every attempt has one stored raw response.
    history_client = client if client is not None else EaClient(cfg.request_timeout, 1)
    client = client or EaClient(cfg.request_timeout, cfg.max_retries)
    our_club_ids = set(cfg.club_ids)
    outcome = PollResult()
    snapshot_cache: dict[str, int | None] = {}
    poll_id = db.start_poll(conn)

    for club_id in cfg.club_ids:
        if outcome.calls_made:
            time.sleep(cfg.call_spacing_seconds)
        _snapshot_roster(conn, cfg, client, club_id, outcome)

        # Our own clubs get a standings snapshot EVERY cycle, not only when a
        # new match arrives. Otherwise a club that has not played since the
        # collector started keeps one frozen rating forever, and every
        # opponent-strength comparison built on it is wrong.
        _snapshot_club(conn, cfg, client, club_id, snapshot_cache, outcome)
        conn.commit()

        for match_type in cfg.match_types:
            if outcome.calls_made:
                time.sleep(cfg.call_spacing_seconds)

            result = client.club_matches(
                cfg.platform, club_id, match_type, cfg.max_result_count)
            outcome.calls_made += 1
            params = {
                "platform": cfg.platform,
                "clubIds": club_id,
                "matchType": match_type,
                "maxResultCount": cfg.max_result_count,
            }
            raw_id = _record(conn, cfg, "/clubs/matches", params, result)

            if not result.ok or not isinstance(result.data, list):
                outcome.calls_failed += 1
                message = (club_id + " " + match_type + ": "
                           + (result.error or "unexpected shape"))
                outcome.errors.append(message)
                log.warning("poll call failed: %s", message)
                continue

            matches = result.data
            outcome.matches_seen += len(matches)
            ids = [str(m.get("matchId")) for m in matches if m.get("matchId")]
            known = db.known_match_ids(conn, ids)
            log.info("%s %s: %d returned, %d already stored",
                     club_id, match_type, len(matches), len(known))

            for match in matches:
                match_id = str(match.get("matchId") or "")
                if not match_id:
                    outcome.errors.append("match with no matchId skipped")
                    continue
                if match_id in known:
                    outcome.matches_duplicate += 1
                    continue

                snapshot_ids: dict[str, int] = {}
                for side_id in (match.get("clubs") or {}):
                    snapshot_id = _snapshot_club(
                        conn, cfg, client, str(side_id), snapshot_cache, outcome)
                    if snapshot_id is not None:
                        snapshot_ids[str(side_id)] = snapshot_id

                try:
                    inserted = ingest.ingest_match(
                        conn, match,
                        match_type=match_type,
                        our_club_ids=our_club_ids,
                        raw_response_id=raw_id,
                        snapshot_ids=snapshot_ids,
                    )
                except Exception as exc:  # one bad match must not kill the poll
                    conn.rollback()
                    message = "ingest failed for " + match_id + ": " + str(exc)
                    outcome.errors.append(message)
                    log.exception(message)
                    continue

                conn.commit()
                if inserted:
                    outcome.matches_new += 1
                    known.add(match_id)
                else:
                    outcome.matches_duplicate += 1

    _backfill_opponents(conn, cfg, history_client, snapshot_cache, outcome)

    db.finish_poll(
        conn, poll_id,
        calls_made=outcome.calls_made,
        calls_failed=outcome.calls_failed,
        matches_seen=outcome.matches_seen,
        matches_new=outcome.matches_new,
        matches_duplicate=outcome.matches_duplicate,
        errors=outcome.errors,
    )
    log.info("poll done: %d new, %d duplicate, %d rosters, %d calls, %d failed",
             outcome.matches_new, outcome.matches_duplicate,
             outcome.roster_snapshots, outcome.calls_made,
             outcome.calls_failed)
    _write_report(conn, cfg)
    return outcome


def _write_report(conn: sqlite3.Connection, cfg: Config) -> None:
    """Keep a fresh copy of the report on disk after every cycle.

    Cheap to build, so there is no schedule to drift and nothing to remember.
    Whatever reads it next - a person, or the Discord bot later - gets the
    current picture.
    """
    try:
        text = report.full_report(conn)
        cfg.report_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.report_path.write_text(text, encoding="utf-8")
        log.info("report written to %s", cfg.report_path)
    except Exception:
        # A broken report must never stop the collector. Collecting wins.
        log.exception("could not write the report")


class _StopSignal:
    """Lets Docker stop the container cleanly instead of killing it."""

    def __init__(self) -> None:
        self.stop = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle)
            except (ValueError, OSError):
                pass  # not the main thread, or platform does not support it

    def _handle(self, *_args: object) -> None:
        log.info("stop requested, finishing after this cycle")
        self.stop = True


def run_forever(conn: sqlite3.Connection, cfg: Config) -> None:
    stopper = _StopSignal()
    consecutive_failures = 0

    while not stopper.stop:
        try:
            outcome = poll_once(conn, cfg)
            if outcome.calls_failed == outcome.calls_made and outcome.calls_made:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            log.exception("poll cycle crashed, continuing")

        if consecutive_failures >= 3:
            log.error("ALERT: %d poll cycles in a row failed completely. "
                      "EA may be down, or the headers may need updating.",
                      consecutive_failures)

        deadline = time.time() + cfg.poll_minutes * 60
        while not stopper.stop and time.time() < deadline:
            time.sleep(min(5, max(0.1, deadline - time.time())))
