"""Tests run against synthetic EA payloads with the same shape as real ones.

Run with:  python -m unittest discover -s tests
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import db, ingest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MAIN = "100001"
PRACTICE = "100002"
OUR_CLUBS = {MAIN, PRACTICE}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class IngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        self.main = load("matches_main_league.json")
        self.practice = load("matches_practice_league.json")

    def tearDown(self) -> None:
        self.conn.close()

    def ingest_all(self, matches) -> int:
        new = 0
        for match in matches:
            if ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                   our_club_ids=OUR_CLUBS):
                new += 1
        self.conn.commit()
        return new

    def test_fixtures_look_like_real_matches(self):
        self.assertEqual(len(self.main), 10)
        self.assertEqual(len(self.practice), 10)
        self.assertIn("matchId", self.main[0])
        self.assertIn("players", self.main[0])

    def test_first_ingest_inserts_every_match(self):
        self.assertEqual(self.ingest_all(self.main), 10)
        self.assertEqual(db.counts(self.conn)["matches"], 10)

    def test_second_ingest_inserts_nothing(self):
        self.ingest_all(self.main)
        before = db.counts(self.conn)
        self.assertEqual(self.ingest_all(self.main), 0)
        self.assertEqual(db.counts(self.conn), before)

    def test_both_clubs_share_one_row_per_match(self):
        """The same match seen from two of our clubs must not duplicate."""
        shared = copy.deepcopy(self.main[0])
        self.ingest_all([shared])
        self.assertEqual(self.ingest_all([copy.deepcopy(shared)]), 0)
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE match_id = ?",
            (str(shared["matchId"]),)).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_ingest_is_deterministic(self):
        self.ingest_all(self.main)
        first = self.conn.execute(
            "SELECT match_id, club_id, player_id, appearance_class, extras_json "
            "FROM player_match_stats ORDER BY match_id, club_id, player_id"
        ).fetchall()

        other = db.connect(Path(":memory:"))
        for match in self.main:
            ingest.ingest_match(other, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        other.commit()
        second = other.execute(
            "SELECT match_id, club_id, player_id, appearance_class, extras_json "
            "FROM player_match_stats ORDER BY match_id, club_id, player_id"
        ).fetchall()
        other.close()

        self.assertEqual([tuple(r) for r in first], [tuple(r) for r in second])

    def test_ghost_appearance_is_flagged_and_not_counted(self):
        match = copy.deepcopy(self.main[0])
        club_players = match["players"][MAIN]
        victim = list(club_players)[0]
        club_players[victim]["secondsPlayed"] = "0"
        club_players[victim]["gameTime"] = "0"

        self.ingest_all([match])
        row = self.conn.execute(
            "SELECT appearance_class, is_real_appearance FROM player_match_stats "
            "WHERE match_id = ? AND player_id = ?",
            (str(match["matchId"]), victim)).fetchone()
        self.assertEqual(row["appearance_class"], "ghost")
        self.assertEqual(row["is_real_appearance"], 0)

        club = self.conn.execute(
            "SELECT human_count, real_human_count FROM match_clubs "
            "WHERE match_id = ? AND club_id = ?",
            (str(match["matchId"]), MAIN)).fetchone()
        self.assertEqual(club["real_human_count"], club["human_count"] - 1)

    def test_real_fixtures_contain_ghosts(self):
        """Proof the flag matters: EA really does send zero-second players."""
        self.ingest_all(self.main)
        self.ingest_all(self.practice)
        ghosts = self.conn.execute(
            "SELECT COUNT(*) FROM player_match_stats "
            "WHERE appearance_class = 'ghost'").fetchone()[0]
        self.assertGreater(ghosts, 0)

    def test_dnf_is_flagged_not_dropped(self):
        match = copy.deepcopy(self.main[0])
        for club in match["clubs"].values():
            club["winnerByDnf"] = "1"
        self.ingest_all([match])
        row = self.conn.execute(
            "SELECT validity, winner_by_dnf FROM matches WHERE match_id = ?",
            (str(match["matchId"]),)).fetchone()
        self.assertEqual(row["validity"], "dnf")
        self.assertEqual(row["winner_by_dnf"], 1)

    def test_incomplete_match_is_flagged_not_dropped(self):
        match = copy.deepcopy(self.main[1])
        match["clubs"].pop(list(match["clubs"])[0])
        self.ingest_all([match])
        row = self.conn.execute(
            "SELECT validity FROM matches WHERE match_id = ?",
            (str(match["matchId"]),)).fetchone()
        self.assertEqual(row["validity"], "incomplete")

    def test_hack_flag_marks_suspicious(self):
        match = copy.deepcopy(self.main[2])
        first = list(match["players"][MAIN])[0]
        match["players"][MAIN][first]["vprohackreason"] = "3"
        self.ingest_all([match])
        row = self.conn.execute(
            "SELECT validity FROM matches WHERE match_id = ?",
            (str(match["matchId"]),)).fetchone()
        self.assertEqual(row["validity"], "suspicious")

    def test_unknown_fields_survive(self):
        match = copy.deepcopy(self.main[0])
        first = list(match["players"][MAIN])[0]
        match["players"][MAIN][first]["brandNewEaField"] = "42"
        self.ingest_all([match])
        row = self.conn.execute(
            "SELECT extras_json FROM player_match_stats "
            "WHERE match_id = ? AND player_id = ?",
            (str(match["matchId"]), first)).fetchone()
        self.assertEqual(json.loads(row["extras_json"])["brandNewEaField"], "42")

    def test_event_aggregate_is_kept_raw(self):
        self.ingest_all(self.main)
        row = self.conn.execute(
            "SELECT event_aggregate_0 FROM player_match_stats "
            "WHERE event_aggregate_0 IS NOT NULL AND event_aggregate_0 != '' "
            "LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertIn(":", row["event_aggregate_0"])

    def test_outcome_matches_goals(self):
        self.ingest_all(self.main)
        rows = self.conn.execute(
            "SELECT goals_for, goals_against, outcome FROM match_clubs").fetchall()
        self.assertTrue(rows)
        for row in rows:
            if row["goals_for"] > row["goals_against"]:
                self.assertEqual(row["outcome"], "win")
            elif row["goals_for"] < row["goals_against"]:
                self.assertEqual(row["outcome"], "loss")
            else:
                self.assertEqual(row["outcome"], "draw")

    def test_our_club_is_marked(self):
        self.ingest_all(self.main)
        ours = self.conn.execute(
            "SELECT DISTINCT club_id FROM match_clubs WHERE is_our_club = 1"
        ).fetchall()
        self.assertEqual([r["club_id"] for r in ours], [MAIN])

    def test_positions_are_broad_only(self):
        self.ingest_all(self.main)
        self.ingest_all(self.practice)
        found = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT pos FROM player_match_stats")}
        self.assertTrue(
            found <= {"goalkeeper", "defender", "midfielder", "forward"},
            "EA sent an unexpected position, investigate: " + str(found))

    def test_validation_player_is_present(self):
        self.ingest_all(self.main)
        self.ingest_all(self.practice)
        row = self.conn.execute(
            "SELECT latest_name FROM players WHERE player_id = '3000000013'"
        ).fetchone()
        self.assertIsNotNone(row, "Captain's numeric id not found in fixtures")

    def test_lineups_view_reconstructs_a_squad(self):
        self.ingest_all(self.main)
        match_id = str(self.main[0]["matchId"])
        rows = self.conn.execute(
            "SELECT player_id, pos, archetype_id, is_real_appearance "
            "FROM lineups WHERE match_id = ? AND club_id = ?",
            (match_id, MAIN)).fetchall()
        self.assertGreater(len(rows), 0)
        self.assertEqual(
            len(rows), len(self.main[0]["players"][MAIN]))


class ClassifierTests(unittest.TestCase):
    def test_short_appearance_is_relative_to_the_match(self):
        self.assertEqual(ingest.classify_appearance(5500, 5500), ("full", True))
        self.assertEqual(ingest.classify_appearance(1000, 5500), ("short", True))
        self.assertEqual(ingest.classify_appearance(0, 5500), ("ghost", False))
        self.assertEqual(ingest.classify_appearance(None, 5500), ("ghost", False))


if __name__ == "__main__":
    unittest.main()
