"""Who is quietly good.

This exists because some good players score almost no goals, and any
output-based chart benches them. The tests below guard the
things that would make this measure dishonest.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import db, ingest, unseen  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MAIN = "100001"
PRACTICE = "100002"
OUR_CLUBS = {MAIN, PRACTICE}


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for name in ("matches_main_league.json",
                     "matches_practice_league.json"):
            for match in load_fixture(name):
                ingest.ingest_match(self.conn, match,
                                    match_type="leagueMatch",
                                    our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()


class InputTests(Base):
    def test_keepers_are_excluded(self):
        """A keeper rating is a different scale and would poison the fit."""
        keepers = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT COALESCE(p.latest_name, s.player_id) "
            "FROM player_match_stats s "
            "LEFT JOIN players p ON p.player_id = s.player_id "
            "WHERE s.pos = 'goalkeeper'")}
        outfield_rows = {name for name, _f, _r in unseen.rows(self.conn)}
        pure_keepers = keepers - {
            r[0] for r in self.conn.execute(
                "SELECT DISTINCT COALESCE(p.latest_name, s.player_id) "
                "FROM player_match_stats s "
                "LEFT JOIN players p ON p.player_id = s.player_id "
                "WHERE s.pos != 'goalkeeper'")}
        self.assertFalse(pure_keepers & outfield_rows)

    def test_rows_without_a_rating_are_skipped(self):
        for _name, _features, rating in unseen.rows(self.conn):
            self.assertGreater(rating, 0)

    def test_lost_passes_are_never_negative(self):
        """A stray payload must not produce a negative count."""
        self.conn.execute(
            "UPDATE player_match_stats SET pass_attempts = 0, passes_made = 9")
        self.conn.commit()
        for _name, features, _rating in unseen.rows(self.conn):
            self.assertGreaterEqual(features[4], 0.0)
            self.assertGreaterEqual(features[6], 0.0)


class FitTests(Base):
    def test_it_refuses_to_fit_on_too_little_data(self):
        self.assertIsNone(unseen.fit([]))
        tiny = unseen.rows(self.conn)[:5]
        self.assertIsNone(unseen.fit(tiny))

    def test_a_fit_explains_some_of_the_rating(self):
        result = unseen.fit(unseen.rows(self.conn))
        self.assertIsNotNone(result)
        _coeffs, r2 = result
        self.assertGreater(r2, 0.1)
        self.assertLessEqual(r2, 1.0)

    def test_goals_and_assists_help_a_rating(self):
        """A sanity check. If scoring hurt your rating, the fit is broken."""
        _players, _r2, coeffs = unseen.above_expected(self.conn)
        self.assertGreater(coeffs["goals"], 0)
        self.assertGreater(coeffs["assists"], 0)

    def test_losing_the_ball_hurts(self):
        _players, _r2, coeffs = unseen.above_expected(self.conn)
        self.assertLess(coeffs["passes_lost"], 0)

    def test_the_fit_is_deterministic(self):
        first = unseen.above_expected(self.conn)[2]
        second = unseen.above_expected(self.conn)[2]
        self.assertEqual(first, second)


class OutputTests(Base):
    def test_residuals_are_centred_near_zero(self):
        """If everyone beat expectation, the model would be useless."""
        players, _r2, _c = unseen.above_expected(self.conn)
        self.assertTrue(players)
        above = [p["above"] for p in players]
        self.assertTrue(any(a > 0 for a in above))
        self.assertTrue(any(a < 0 for a in above))

    def test_ordered_best_first(self):
        players, _r2, _c = unseen.above_expected(self.conn)
        values = [p["above"] for p in players]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_a_player_below_the_floor_is_not_listed(self):
        players, _r2, _c = unseen.above_expected(self.conn, min_games=5)
        for p in players:
            self.assertGreaterEqual(p["games"], 5)

    def test_above_is_really_rating_minus_expected(self):
        players, _r2, _c = unseen.above_expected(self.conn)
        for p in players:
            self.assertAlmostEqual(p["above"], p["rating"] - p["expected"],
                                   places=9)

    def test_the_text_says_how_much_is_unexplained(self):
        text = unseen.text(self.conn)
        self.assertIn("percent of EA's rating", text)
        self.assertIn("Do not bench them off a goals chart", text)

    def test_the_text_admits_when_it_cannot_fit(self):
        empty = db.connect(Path(":memory:"))
        self.assertIn("Not enough games", unseen.text(empty))
        empty.close()

    def test_a_goalless_player_can_still_rank_top(self):
        """The whole point. Someone with no goals must be able to lead."""
        players, _r2, _c = unseen.above_expected(self.conn)
        goals = {r[0]: r[1] for r in self.conn.execute(
            "SELECT COALESCE(p.latest_name, s.player_id), SUM(s.goals) "
            "FROM player_match_stats s "
            "JOIN match_clubs mc ON mc.match_id = s.match_id "
            "  AND mc.club_id = s.club_id AND mc.is_our_club = 1 "
            "LEFT JOIN players p ON p.player_id = s.player_id "
            "GROUP BY 1")}
        top_half = players[:max(len(players) // 2, 1)]
        self.assertTrue(
            any(goals.get(p["player"], 0) == 0 for p in top_half),
            "a player with no goals should be able to reach the top half")


if __name__ == "__main__":
    unittest.main()
