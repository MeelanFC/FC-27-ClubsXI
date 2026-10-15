"""Guards the two mistakes found in testing.

  1. Ranking by games played measures who turns up, and punishes anyone who
     rotates builds.
  2. Ranking by raw output measures which club the games were in, because the
     practice club plays much weaker opposition.

Everything here must be MEASURED from the data, never assumed, so the numbers
recompute as games arrive.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import db, ingest, strength  # noqa: E402

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


class RateTests(Base):
    def test_a_rate_not_a_total(self):
        """Two goals in half a game is not the same as two in a full one."""
        half = strength.Appearance("x", MAIN, "forward", "11", 2700,
                                   2, 0, 8.0)
        whole = strength.Appearance("y", MAIN, "forward", "11", 5400,
                                    2, 0, 8.0)
        self.assertAlmostEqual(half.contribution_rate, 4.0)
        self.assertAlmostEqual(whole.contribution_rate, 2.0)

    def test_zero_seconds_cannot_divide_by_zero(self):
        ghost = strength.Appearance("x", MAIN, "forward", "11", 0, 0, 0, None)
        self.assertEqual(ghost.contribution_rate, 0.0)

    def test_only_near_complete_clean_games_count(self):
        rows = strength.appearances(self.conn)
        self.assertTrue(rows)
        stored = self.conn.execute(
            "SELECT COUNT(*) FROM player_match_stats s "
            "JOIN matches m ON m.match_id = s.match_id "
            "JOIN match_clubs mc ON mc.match_id = s.match_id "
            "  AND mc.club_id = s.club_id AND mc.is_our_club = 1 "
            "WHERE s.is_real_appearance = 1 AND s.appearance_class = 'full' "
            "  AND m.validity = 'ok'").fetchone()[0]
        self.assertEqual(len(rows), stored)


class PoolingTests(Base):
    def test_builds_are_pooled_not_split(self):
        """The bug that dropped the best forward. His games were fragmented."""
        rows = strength.appearances(self.conn)
        multi = [a.player for a in rows if a.band == "forward"]
        self.assertTrue(multi)

        for score in strength.scores(self.conn, "forward"):
            counted = sum(1 for a in rows
                          if a.player == score.player and a.band == "forward")
            self.assertEqual(score.appearances, counted,
                             score.player + " lost games to build splitting")

    def test_a_player_rotating_builds_keeps_all_their_games(self):
        rows = strength.appearances(self.conn)
        by_player: dict[str, set[str]] = {}
        for a in rows:
            if a.band == "forward":
                by_player.setdefault(a.player, set()).add(a.archetype_id)
        rotators = [p for p, builds in by_player.items() if len(builds) > 1]
        self.assertTrue(rotators, "fixtures should contain a build rotator")

        scored = {s.player: s.appearances
                  for s in strength.scores(self.conn, "forward")}
        for player in rotators:
            if player in scored:
                self.assertGreaterEqual(scored[player], 2)


class ClubAdjustmentTests(Base):
    def test_the_premium_is_measured_within_player(self):
        """It must compare a player to himself, not club to club."""
        gaps = strength.practice_premium(self.conn, PRACTICE)
        for band, value in gaps.items():
            self.assertIsInstance(value, float)
            self.assertIn(band, set(strength.BANDS) | {"all"})

    def test_no_premium_is_claimed_without_games_on_both_sides(self):
        only_one_club = db.connect(Path(":memory:"))
        for match in load_fixture("matches_practice_league.json"):
            ingest.ingest_match(only_one_club, match,
                                match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        only_one_club.commit()
        self.assertEqual(
            strength.practice_premium(only_one_club, PRACTICE), {})
        only_one_club.close()

    def test_a_practice_only_player_is_adjusted_more_than_a_main_only_one(self):
        rows = strength.scores(self.conn, "forward", practice_club_id=PRACTICE)
        for s in rows:
            drop = s.raw - s.adjusted
            if s.practice_share == 0:
                self.assertAlmostEqual(drop, 0.0, places=6)
            self.assertGreaterEqual(s.practice_share, 0.0)
            self.assertLessEqual(s.practice_share, 1.0)

    def test_adjustment_is_proportional_to_practice_share(self):
        rows = strength.scores(self.conn, "forward", practice_club_id=PRACTICE)
        drops = [(s.practice_share, s.raw - s.adjusted) for s in rows]
        for share, drop in drops:
            if share == 0:
                self.assertAlmostEqual(drop, 0.0, places=6)
        heavier = [d for sh, d in drops if sh > 0.7]
        lighter = [d for sh, d in drops if 0 < sh < 0.3]
        if heavier and lighter:
            self.assertGreater(max(heavier), min(lighter))


class ShrinkageTests(Base):
    def test_a_small_sample_leans_on_the_league_average(self):
        rows = strength.scores(self.conn, "forward")
        for s in rows:
            self.assertGreaterEqual(s.prior_weight, 0.0)
            self.assertLessEqual(s.prior_weight, 1.0)

    def test_more_games_means_less_prior(self):
        rows = strength.scores(self.conn, "forward")
        if len(rows) >= 2:
            by_games = sorted(rows, key=lambda s: s.appearances)
            self.assertGreaterEqual(by_games[0].prior_weight,
                                    by_games[-1].prior_weight)

    def test_the_shrunk_score_sits_between_the_player_and_the_average(self):
        prior = strength.league_prior(self.conn).get("forward", 0.0)
        for s in strength.scores(self.conn, "forward"):
            low, high = sorted((s.adjusted, prior))
            self.assertGreaterEqual(s.shrunk, low - 1e-9)
            self.assertLessEqual(s.shrunk, high + 1e-9)

    def test_a_metric_that_cannot_separate_players_returns_infinity(self):
        """Not a sample size problem. The spread IS the noise."""
        flat = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json"):
            ingest.ingest_match(flat, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        flat.execute("UPDATE player_match_stats SET goals = 0, assists = 0")
        flat.commit()
        self.assertTrue(math.isinf(strength.shrinkage_k(flat, "forward")))
        flat.close()

    def test_shrinkage_is_measured_not_hardcoded(self):
        for band in ("forward", "midfielder"):
            k = strength.shrinkage_k(self.conn, band)
            self.assertTrue(k > 0)

    def test_a_thin_band_falls_back_to_a_cautious_default(self):
        tiny = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json")[:1]:
            ingest.ingest_match(tiny, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        tiny.commit()
        self.assertEqual(strength.shrinkage_k(tiny, "goalkeeper"),
                         strength.FALLBACK_K)
        tiny.close()


class RefusalTests(Base):
    def test_defenders_and_keepers_are_never_ranked_in_the_output(self):
        text = strength.scores_text(self.conn, practice_club_id=PRACTICE)
        for band in strength.UNRANKABLE:
            self.assertIn(band.upper() + ": not ranked", text)

    def test_a_player_below_the_floor_is_not_listed(self):
        rows = strength.scores(self.conn, "forward")
        for s in rows:
            self.assertGreaterEqual(s.appearances,
                                    strength.MIN_APPEARANCES)

    def test_the_output_says_how_much_is_prior(self):
        text = strength.scores_text(self.conn, practice_club_id=PRACTICE)
        self.assertIn("% prior", text)


class WastedTests(Base):
    def test_only_reports_a_real_mismatch(self):
        for f in strength.wasted(self.conn):
            self.assertNotEqual(f["played"], f["best"])
            self.assertGreater(f["gain"], 0)

    def test_both_roles_need_enough_games(self):
        for f in strength.wasted(self.conn, min_each=3):
            self.assertGreaterEqual(f["played_games"], 3)
            self.assertGreaterEqual(f["best_games"], 3)

    def test_a_player_with_one_role_is_never_flagged(self):
        findings = strength.wasted(self.conn)
        singles = strength.appearances(self.conn)
        roles: dict[str, set] = {}
        for a in singles:
            roles.setdefault(a.player, set()).add((a.band, a.archetype_id))
        for f in findings:
            self.assertGreater(len(roles[f["player"]]), 1)


class KeeperTests(Base):
    def test_the_keeper_effect_is_split_by_club(self):
        rows = strength.keeper_effect(self.conn)
        clubs = {r["club"] for r in rows}
        self.assertGreaterEqual(len(clubs), 1)
        for r in rows:
            self.assertIn("human_games", r)
            self.assertIn("ai_games", r)

    def test_the_text_explains_why_it_is_split(self):
        text = strength.keeper_text(self.conn)
        self.assertIn("which league the game was in", text)

    def test_no_difference_is_claimed_when_a_side_is_empty(self):
        for r in strength.keeper_effect(self.conn):
            if not r["human_games"]:
                self.assertIsNone(r["human_ga"])
            if not r["ai_games"]:
                self.assertIsNone(r["ai_ga"])


if __name__ == "__main__":
    unittest.main()
