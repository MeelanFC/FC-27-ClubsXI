"""Who is willing to play where.

The match data only knows where somebody HAS been put. It cannot know who is
willing and able to play somewhere untried, and it cannot know who refuses.
That is the one thing only a human can supply, so it gets its own file and its
own tests.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import chart, db, ingest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MAIN = "100001"
PRACTICE = "100002"
OUR_CLUBS = {MAIN, PRACTICE}


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ParseTests(unittest.TestCase):
    def test_parses_bands_and_refusals(self):
        text = "\n".join([
            "# a note",
            "Captain = defender, midfielder",
            "KeeperOne = goalkeeper, -forward",
        ])
        can, wont = chart.parse_can_play(text)
        self.assertEqual(can["Captain"], {"defender", "midfielder"})
        self.assertEqual(can["KeeperOne"], {"goalkeeper"})
        self.assertEqual(wont["KeeperOne"], {"forward"})

    def test_a_name_with_spaces_or_digits_still_parses(self):
        can, _ = chart.parse_can_play("Player03 = defender")
        self.assertIn("Player03", can)

    def test_an_unknown_band_is_ignored_not_stored(self):
        can, _ = chart.parse_can_play("Someone = defender, striker, nonsense")
        self.assertEqual(can["Someone"], {"defender"})

    def test_the_shipped_file_parses(self):
        can, wont = chart.load_can_play(ROOT / "config" / "can_play.txt")
        self.assertIsInstance(can, dict)
        for bands in list(can.values()) + list(wont.values()):
            for band in bands:
                self.assertIn(band, chart.BANDS)

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(
            chart.load_can_play(Path("does-not-exist.txt")), ({}, {}))


class EffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()
        self.gk_slot = chart.parse("FORMATION: x\nGK = , ,\n")

    def tearDown(self) -> None:
        self.conn.close()

    def test_willingness_makes_someone_eligible_with_zero_games(self):
        before = chart.suggest(self.gk_slot, self.conn)["GK"]
        after = chart.suggest(self.gk_slot, self.conn,
                              can={"MidOne": {"goalkeeper"}})["GK"]
        self.assertNotIn("MidOne", before)
        self.assertIn("MidOne", after)

    def test_habit_still_outranks_a_standing_offer(self):
        """Someone who has actually done the job is suggested first."""
        picks = chart.suggest(self.gk_slot, self.conn,
                              can={"MidOne": {"goalkeeper"}})["GK"]
        seen = chart.broad_appearances(self.conn)
        self.assertGreater(seen.get((picks[0], "goalkeeper"), 0), 0)

    def test_a_refusal_removes_someone_the_data_has_seen(self):
        with_them = chart.suggest(self.gk_slot, self.conn)["GK"]
        self.assertTrue(with_them[0])
        without = chart.suggest(
            self.gk_slot, self.conn,
            wont={with_them[0]: {"goalkeeper"}})["GK"]
        self.assertNotIn(with_them[0], without)

    def test_willingness_silences_the_never_played_there_warning(self):
        c = chart.parse("FORMATION: x\nST = KeeperOne, ,\n")
        noisy = chart.problems(c, self.conn)
        self.assertTrue(any("no near-complete forward" in i for i in noisy))
        quiet = chart.problems(c, self.conn,
                               can={"KeeperOne": {"forward"}})
        self.assertFalse(any("no near-complete forward" in i for i in quiet))

    def test_a_refusal_can_create_a_real_hole(self):
        """Saying nobody will keep goal must show as a hole, not be hidden."""
        everyone = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT COALESCE(p.latest_name, s.player_id) "
            "FROM player_match_stats s "
            "LEFT JOIN players p ON p.player_id = s.player_id")}
        wont = {name: {"goalkeeper"} for name in everyone}
        issues = chart.problems(self.gk_slot, self.conn, wont=wont)
        self.assertTrue(any("AI plays here" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
