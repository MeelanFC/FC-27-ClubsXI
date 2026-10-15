import testenv  # noqa: F401  (test settings, must come first)
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clubsxi import builds, collector, db, ingest, strength
from clubsxi.config import Config
from clubsxi.ea_client import ApiResult

FIXTURE = Path(__file__).parent / "fixtures" / "opponent_history.json"


def match(mid, left, right):
    data = copy.deepcopy(json.loads(FIXTURE.read_text())[0])
    data["matchId"] = mid
    for key in ("clubs", "players"):
        data[key] = dict(zip((left, right), data[key].values()))
    return data


def response(data, status=200):
    return ApiResult("https://fixture.invalid", status, json.dumps(data), data,
                     None if status == 200 else f"HTTP {status}")


class Client:
    def __init__(self, history=None, own=None):
        self.history = history if history is not None else response(json.loads(FIXTURE.read_text()))
        self.own = own if own is not None else [match("meeting", "ours", "opponent")]
        self.calls = []

    def members_stats(self, platform, club):
        self.calls.append(("roster", club))
        return response({"members": []})

    def club_overall_stats(self, platform, club):
        self.calls.append(("standing", club))
        return response([{"skillRating": "1000"}])

    def club_matches(self, platform, club, kind, count):
        self.calls.append(("matches", club, kind, count))
        if club in {"ours", "also-ours"}:
            return response(self.own if kind == "leagueMatch" else [])
        return self.history


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "_write_report", lambda *args: None)
    cfg = Config(club_ids=["ours", "also-ours"], call_spacing_seconds=0,
                 db_path=tmp_path / "test.sqlite3")
    conn = db.connect(cfg.db_path)
    yield conn, cfg
    conn.close()


def history_calls(client):
    return [c for c in client.calls if c[0] == "matches" and c[1] not in {"ours", "also-ours"}]


def test_first_meeting_restart_no_recursion_and_provenance(setup):
    conn, cfg = setup
    client = Client()
    result = collector.poll_once(conn, cfg, client)
    assert len(history_calls(client)) == 3
    assert {c[1] for c in history_calls(client)} == {"opponent"}
    assert all(c[3] == 10 for c in history_calls(client))
    assert result.matches_new == 2
    assert tuple(conn.execute("SELECT source, seed_club_id FROM matches WHERE match_id='history-1'").fetchone()) == ("opponent_history", "opponent")
    assert conn.execute("SELECT SUM(is_our_club) FROM match_clubs WHERE match_id='history-1'").fetchone()[0] == 0
    assert conn.execute("SELECT source FROM matches WHERE match_id='meeting'").fetchone()[0] == "own"
    assert conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0] == len(client.calls)
    assert len([c for c in client.calls if c == ("standing", "opponent")]) == 1
    assert tuple(conn.execute("SELECT calls_made, calls_failed, matches_seen, matches_new FROM opponent_history_fetches").fetchone()) == (3, 0, 3, 1)
    reopened = db.connect(cfg.db_path)
    try:
        second = Client()
        collector.poll_once(reopened, cfg, second)
        assert history_calls(second) == []
    finally:
        reopened.close()


@pytest.mark.parametrize("bad", [response(None, 403), response(None, 404),
                                 response(None, 503),
                                 ApiResult("fixture", 200, "not JSON", None, "response was not JSON"),
                                 response({"unexpected": True})])
def test_failures_are_recorded_and_never_retried(setup, bad):
    conn, cfg = setup
    client = Client(history=bad)
    collector.poll_once(conn, cfg, client)
    assert tuple(conn.execute("SELECT calls_made, calls_failed FROM opponent_history_fetches").fetchone()) == (3, 3)
    collector.poll_once(conn, cfg, client)
    assert len(history_calls(client)) == 3
    assert conn.execute("SELECT COUNT(*) FROM raw_responses WHERE body=?", (bad.body_text,)).fetchone()[0] == 3


def test_existing_opponents_cap_and_own_club_exclusion(setup):
    from dataclasses import replace
    conn, cfg = setup
    for i, other in enumerate(("one", "two", "three", "also-ours")):
        ingest.ingest_match(conn, match(str(i), "ours", other),
                            match_type="leagueMatch", our_club_ids=set(cfg.club_ids))
    conn.commit()
    cfg = replace(cfg, opponent_history_clubs_per_poll=2)
    client = Client(history=response([]), own=[])
    collector.poll_once(conn, cfg, client)
    assert len(history_calls(client)) == 6
    collector.poll_once(conn, cfg, client)
    assert len(history_calls(client)) == 9
    assert conn.execute("SELECT COUNT(*) FROM opponent_history_fetches").fetchone()[0] == 3
    assert conn.execute("SELECT SUM(calls_failed) FROM opponent_history_fetches").fetchone()[0] == 0


def test_bad_match_keeps_raw_response_and_continues(setup):
    conn, cfg = setup
    malformed = match("broken", "opponent", "third")
    malformed["players"]["opponent"]["p1"] = "bad player"
    client = Client(history=response([None, malformed, json.loads(FIXTURE.read_text())[0]]))
    result = collector.poll_once(conn, cfg, client)
    assert result.matches_new == 2
    assert conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0] == len(client.calls)
    assert conn.execute("SELECT COUNT(*) FROM matches WHERE match_id='broken'").fetchone()[0] == 0


def test_analysis_population_keeps_practice_premium_local(setup):
    conn, cfg = setup
    for mid, club in (("main", "ours"), ("practice", "also-ours")):
        ingest.ingest_match(conn, match(mid, club, "opponent"),
                            match_type="leagueMatch", our_club_ids=set(cfg.club_ids))
    conn.commit()
    before = strength.practice_premium(conn, "also-ours", min_each_side=1)
    count = len(strength.appearances(conn, ours_only=False))
    prior = strength.league_prior(conn)
    history = match("extra", "opponent", "third")
    history["players"]["opponent"]["p1"]["goals"] = "20"
    ingest.ingest_match(conn, history, match_type="leagueMatch", our_club_ids=set(cfg.club_ids))
    assert len(strength.appearances(conn, ours_only=False)) == count + 2
    assert strength.league_prior(conn) != prior
    assert strength.practice_premium(conn, "also-ours", min_each_side=1) == before
    assert sum(p.opponent_appearances for p in builds.profiles(conn)) == 4


def test_existing_database_migration_is_idempotent(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    schema = db.SCHEMA_PATH.read_text()
    schema = schema.replace("    source            TEXT NOT NULL DEFAULT 'own',\n", "")
    schema = schema.replace("    seed_club_id      TEXT,\n", "")
    old.executescript(schema)
    old.execute("INSERT INTO matches (match_id, match_type, club_count, validity, first_seen_at, raw_json) VALUES ('old', 'leagueMatch', 2, 'ok', 0, '{}')")
    old.commit()
    old.close()
    for _ in range(2):
        upgraded = db.connect(path)
        assert tuple(upgraded.execute("SELECT source, seed_club_id FROM matches").fetchone()) == ("own", None)
        upgraded.close()


def test_default_cap_and_spacing(setup, monkeypatch):
    conn, cfg = setup
    from dataclasses import replace
    cfg = replace(cfg, call_spacing_seconds=2)
    events = []
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: events.append(seconds))
    for i in range(21):
        ingest.ingest_match(conn, match(str(i), "ours", f"opponent-{i:02}"),
                            match_type="leagueMatch", our_club_ids=set(cfg.club_ids))
    conn.commit()
    client = Client(history=response([]), own=[])
    collector.poll_once(conn, cfg, client)
    assert len(history_calls(client)) == 60
    assert len(events) == len(client.calls) - 1
    assert set(events) == {2}


def test_interrupted_claim_is_not_retried(setup):
    conn, cfg = setup

    class Interrupted(Client):
        def club_matches(self, platform, club, kind, count):
            if club == "opponent":
                raise KeyboardInterrupt
            return super().club_matches(platform, club, kind, count)

    with pytest.raises(KeyboardInterrupt):
        collector.poll_once(conn, cfg, Interrupted())
    assert conn.execute("SELECT calls_made FROM opponent_history_fetches").fetchone()[0] == 0
    client = Client()
    collector.poll_once(conn, cfg, client)
    assert history_calls(client) == []


def test_default_history_client_has_no_http_retries(setup, monkeypatch):
    conn, cfg = setup
    clients = []

    def factory(timeout, retries):
        client = Client(history=response([]))
        clients.append((retries, client))
        return client

    monkeypatch.setattr(collector, "EaClient", factory)
    collector.poll_once(conn, cfg)
    assert clients[0][0] == 1
    assert len(history_calls(clients[0][1])) == 3
    assert clients[1][0] == cfg.max_retries
    assert history_calls(clients[1][1]) == []
