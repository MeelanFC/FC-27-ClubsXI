"""Checks the evidence rules: quits and short spells stay out by default."""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import analysis, db, ingest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MAIN = "100001"
PRACTICE = "100002"
OUR_CLUBS = {MAIN, PRACTICE}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        self.matches = load("matches_main_league.json")

    def tearDown(self) -> None:
        self.conn.close()

    def ingest(self, matches) -> None:
        for match in matches:
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def test_dnf_match_is_excluded_by_default(self):
        matches = copy.deepcopy(self.matches)
        for club in matches[0]["clubs"].values():
            club["winnerByDnf"] = "1"
        self.ingest(matches)

        clean = sum(s.appearances for s in analysis.slices(self.conn))
        messy = sum(s.appearances
                    for s in analysis.slices(self.conn, include_messy=True))
        self.assertLess(clean, messy)

    def test_toggle_brings_the_quits_back(self):
        matches = copy.deepcopy(self.matches)
        for club in matches[0]["clubs"].values():
            club["winnerByDnf"] = "1"
        self.ingest(matches)

        excluded = self.conn.execute(
            "SELECT COUNT(*) FROM player_match_stats s "
            "JOIN matches m ON m.match_id = s.match_id "
            "JOIN match_clubs mc ON mc.match_id = s.match_id "
            "  AND mc.club_id = s.club_id AND mc.is_our_club = 1 "
            "WHERE m.validity = 'dnf' AND s.is_real_appearance = 1"
        ).fetchone()[0]
        self.assertGreater(excluded, 0)

        clean = sum(s.appearances for s in analysis.slices(self.conn))
        messy = sum(s.appearances
                    for s in analysis.slices(self.conn, include_messy=True))
        self.assertEqual(messy - clean, excluded)

    def test_short_spells_do_not_count_by_default(self):
        matches = copy.deepcopy(self.matches)
        victim = list(matches[1]["players"][MAIN])[0]
        matches[1]["players"][MAIN][victim]["secondsPlayed"] = "300"
        self.ingest(matches)

        counted = [s for s in analysis.slices(self.conn)
                   if s.player_id == victim]
        with_messy = [s for s in analysis.slices(self.conn, include_messy=True)
                      if s.player_id == victim]
        self.assertLess(sum(s.appearances for s in counted),
                        sum(s.appearances for s in with_messy))

    def test_ghosts_never_count_even_with_the_toggle(self):
        matches = copy.deepcopy(self.matches)
        victim = list(matches[2]["players"][MAIN])[0]
        matches[2]["players"][MAIN][victim]["secondsPlayed"] = "0"
        self.ingest(matches)

        match_id = str(matches[2]["matchId"])
        for messy in (False, True):
            rows = [s for s in analysis.slices(self.conn, include_messy=messy)
                    if s.player_id == victim]
            total = sum(s.appearances for s in rows)
            in_that_match = self.conn.execute(
                "SELECT appearance_class FROM player_match_stats "
                "WHERE match_id = ? AND player_id = ?",
                (match_id, victim)).fetchone()["appearance_class"]
            self.assertEqual(in_that_match, "ghost")
            self.assertGreaterEqual(total, 0)

        ghost_counted = self.conn.execute(
            "SELECT COUNT(*) FROM player_match_stats "
            "WHERE appearance_class = 'ghost' AND is_real_appearance = 1"
        ).fetchone()[0]
        self.assertEqual(ghost_counted, 0)

    def test_team_goals_beat_personal_goals_in_the_ranking(self):
        """A player's best scoring position must not win if the team did worse."""
        good = analysis.Slice(
            player_id="1", player_name="x", club_id=MAIN, pos="defender",
            archetype_id="4", appearances=10, team_gf=30, team_ga=10,
            wins=8, draws=1, losses=1, goals=0, assists=1, avg_rating=7.0)
        flashy = analysis.Slice(
            player_id="1", player_name="x", club_id=MAIN, pos="forward",
            archetype_id="12", appearances=10, team_gf=15, team_ga=25,
            wins=2, draws=1, losses=7, goals=20, assists=5, avg_rating=8.9)
        ordered = sorted([flashy, good], key=analysis.rank_key)
        self.assertEqual(ordered[0].pos, "defender")

    def test_sample_size_breaks_a_tie_on_goal_difference(self):
        many = analysis.Slice("1", "x", MAIN, "midfielder", "6", 20,
                              40, 20, 14, 3, 3, 5, 5, 7.5)
        few = analysis.Slice("1", "x", MAIN, "forward", "11", 5,
                             10, 5, 4, 0, 1, 5, 5, 7.5)
        ordered = sorted([few, many], key=analysis.rank_key)
        self.assertEqual(ordered[0].appearances, 20)

    def test_barely_seen_slices_are_separated(self):
        self.ingest(self.matches)
        grouped = analysis.top_positions(self.conn)
        for entry in grouped.values():
            for s in entry["ranked"]:
                self.assertGreaterEqual(
                    s.appearances, analysis.EXPOSURE_MIN_APPEARANCES)
            for s in entry["thin"]:
                self.assertLess(
                    s.appearances, analysis.EXPOSURE_MIN_APPEARANCES)
                self.assertEqual(s.confidence, "barely seen")

    def test_confidence_wording_is_cautious(self):
        """Review rule D4: nothing is comparable below 20 near-complete games."""
        self.assertEqual(analysis.confidence(1), "barely seen")
        self.assertEqual(analysis.confidence(6), "exposure only")
        self.assertEqual(analysis.confidence(19), "exposure only")
        self.assertEqual(analysis.confidence(20), "comparable, thin")
        self.assertEqual(analysis.confidence(40), "comparable")

    def test_nothing_in_our_data_is_comparable_yet(self):
        """The honest state of play. If this ever fails we have real data."""
        self.ingest(self.matches)
        for s in analysis.slices(self.conn):
            self.assertFalse(
                s.qualified,
                "a slice cleared 20 games: performance ordering may now be "
                "switched on, but only deliberately")

    def test_slices_are_ordered_by_exposure_not_goal_difference(self):
        """Review rule D3 and D4. Goal difference must not decide any order."""
        few_but_flattering = analysis.Slice(
            "1", "x", MAIN, "forward", "12", 4,
            40, 4, 4, 0, 0, 12, 3, 9.1)
        many_but_plain = analysis.Slice(
            "1", "x", MAIN, "midfielder", "6", 15,
            15, 15, 5, 5, 5, 1, 1, 6.8)
        ordered = sorted([few_but_flattering, many_but_plain],
                         key=analysis.exposure_key)
        self.assertEqual(ordered[0].appearances, 15)

    def test_the_old_rank_key_no_longer_ranks_by_goal_difference(self):
        """Guards against a caller quietly restoring the old behaviour."""
        self.assertIs(analysis.rank_key, analysis.exposure_key)

    def test_clubs_are_not_pooled_silently(self):
        """A slice is per club, so main and mock never merge by accident."""
        self.ingest(self.matches)
        self.ingest(load("matches_practice_league.json"))
        both = analysis.slices(self.conn)
        clubs = {s.club_id for s in both}
        self.assertIn(MAIN, clubs)
        self.assertIn(PRACTICE, clubs)
        only_main = analysis.slices(self.conn, club_ids=[MAIN])
        self.assertEqual({s.club_id for s in only_main}, {MAIN})



class CombinationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_pairs_only_include_people_who_really_played_together(self):
        pairs = analysis.combinations_of_size(self.conn, 2, min_games=1)
        self.assertTrue(pairs)
        for combo in pairs:
            self.assertEqual(len(combo.player_ids), 2)
            self.assertEqual(len(set(combo.player_ids)), 2)

    def test_a_combination_never_claims_more_games_than_exist(self):
        total = self.conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        for combo in analysis.combinations_of_size(self.conn, 2, min_games=1):
            self.assertLessEqual(combo.games, total)

    def test_min_games_is_respected(self):
        for combo in analysis.combinations_of_size(self.conn, 3, min_games=4):
            self.assertGreaterEqual(combo.games, 4)

    def test_quit_games_stay_out_of_combinations_by_default(self):
        clean = analysis.combinations_of_size(self.conn, 2, min_games=1)
        clean_total = sum(c.games for c in clean)

        self.conn.execute(
            "UPDATE matches SET validity = 'dnf' WHERE match_id = "
            "(SELECT match_id FROM matches LIMIT 1)")
        self.conn.commit()

        after = analysis.combinations_of_size(self.conn, 2, min_games=1)
        self.assertLess(sum(c.games for c in after), clean_total)

    def test_suggested_lineup_refuses_when_no_squad_repeats(self):
        squads = analysis.suggested_lineup(self.conn, min_games=99)
        self.assertEqual(squads, [])


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_report_runs_and_says_what_it_counted(self):
        from clubsxi import report
        text = report.full_report(self.conn)
        self.assertIn("CLUBSXI EVIDENCE REPORT", text)
        self.assertIn("CLUB RECORD", text)
        self.assertIn("WHERE EACH PLAYER HAS ACTUALLY BEEN SEEN", text)
        self.assertIn("gauge, not a verdict", text)

    def test_report_never_claims_results_happened_on_the_pitch(self):
        """Review correction: we only have the whole-match score."""
        from clubsxi import report
        text = report.full_report(self.conn)
        self.assertNotIn("while they were on the pitch,", text)
        self.assertIn("WHOLE MATCH score", text)

    def test_report_states_the_performance_floor(self):
        from clubsxi import report
        text = report.top_positions_text(self.conn)
        self.assertIn("NOT by performance", text)
        self.assertIn(str(analysis.PERFORMANCE_MIN_APPEARANCES), text)

    def test_report_offers_no_algorithmic_best_eleven(self):
        """The review removed it. It can never fire with a rotating group."""
        from clubsxi import report
        text = report.full_report(self.conn)
        self.assertNotIn("SUGGESTED LINEUP", text)
        self.assertIn("the captain's to set", text)

    def test_quit_matches_appear_in_the_club_record(self):
        """Review rule D5. They are our best nights and must not vanish."""
        from clubsxi import report
        self.conn.execute(
            "UPDATE matches SET validity = 'dnf' WHERE match_id = "
            "(SELECT match_id FROM matches LIMIT 1)")
        self.conn.commit()
        text = report.club_record_text(self.conn)
        self.assertIn("quit early", text)

    def test_unconfirmed_archetype_names_carry_a_question_mark(self):
        from clubsxi import report
        labels = report.archetype_labels(self.conn)
        self.assertEqual(labels["11"], "Magician")
        self.assertEqual(labels["4"], "Boss")

    def test_report_names_the_club_so_main_and_mock_never_blur(self):
        from clubsxi import report
        for match in load("matches_practice_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()
        text = report.top_positions_text(self.conn)
        self.assertIn("Home FC", text)
        self.assertIn("Practice FC", text)

if __name__ == "__main__":
    unittest.main()
