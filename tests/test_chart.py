"""Guards the captain's chart rules (review rule D1, D3, D8).

The rules under test:
  - The chart is the captain's. Nothing derives it from match data.
  - Exact slot names are printed, but evidence stays broad.
  - Blanks are real information and are never filled in automatically.
  - Someone booked as first choice in two slots is flagged.
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

SAMPLE = """
# a comment
FORMATION: 4-3-3 (2)

GK  = KeeperOne, ,
LCB = BackOne, Captain,
CDM = HolderOne, ,
ST  = Player08, ,
"""


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ParseTests(unittest.TestCase):
    def test_reads_formation_and_slots(self):
        c = chart.parse(SAMPLE)
        self.assertEqual(c.formation, "4-3-3 (2)")
        self.assertEqual([s.name for s in c.slots],
                         ["GK", "LCB", "CDM", "ST"])

    def test_blank_picks_stay_blank(self):
        c = chart.parse(SAMPLE)
        gk = c.slots[0]
        self.assertEqual(gk.pick(0), "KeeperOne")
        self.assertEqual(gk.pick(1), "")
        self.assertEqual(gk.pick(2), "")

    def test_every_slot_maps_to_a_broad_position(self):
        c = chart.parse(SAMPLE)
        self.assertEqual(c.slots[0].broad, "goalkeeper")
        self.assertEqual(c.slots[1].broad, "defender")
        self.assertEqual(c.slots[2].broad, "midfielder")
        self.assertEqual(c.slots[3].broad, "forward")

    def test_comments_and_blank_lines_are_ignored(self):
        c = chart.parse("# nothing\n\n\nFORMATION: 4-4-2\nGK = someone, ,\n")
        self.assertEqual(len(c.slots), 1)

    def test_an_unreadable_line_is_reported_not_swallowed(self):
        c = chart.parse("FORMATION: 4-3-3\nthis is not a slot line\n")
        self.assertTrue(any("could not read" in n for n in c.notes))

    def test_the_real_shipped_chart_parses(self):
        path = ROOT / "config" / "depth_chart.txt"
        self.assertTrue(path.exists(), "the captain's chart file is missing")
        c = chart.load(path)
        self.assertEqual(len(c.slots), 11, "a formation has eleven slots")
        self.assertEqual(c.notes, [])


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_evidence_is_broad_never_the_exact_slot(self):
        """Review rule D8: the row may say LCB, the evidence may not."""
        seen = chart.broad_appearances(self.conn)
        for (_name, pos) in seen:
            self.assertIn(pos, {"goalkeeper", "defender",
                                "midfielder", "forward"})

    def test_a_slot_with_only_one_body_is_reported(self):
        """A blank slot is filled by the tool, so warn about cover, not blanks."""
        c = chart.parse("FORMATION: x\nGK = KeeperOne, ,\n")
        issues = chart.problems(c, self.conn)
        self.assertTrue(
            any(i.startswith("GK: only ") for i in issues),
            "expected a no-cover warning, got: " + str(issues))

    def test_double_booking_a_starter_is_flagged(self):
        c = chart.parse(
            "FORMATION: x\nLCM = Captain, ,\nRCM = Captain, ,\n")
        issues = chart.problems(c, self.conn)
        self.assertTrue(
            any("first choice in more than one slot" in i for i in issues))

    def test_someone_can_back_up_two_slots_without_a_warning(self):
        """Only first choice clashes matter. Backups are meant to be shared."""
        c = chart.parse(
            "FORMATION: x\n"
            "LCM = HolderOne, Captain,\n"
            "RCM = MidOne, Captain,\n")
        issues = chart.problems(c, self.conn)
        self.assertFalse(
            any("first choice in more than one slot" in i for i in issues))

    def test_an_unknown_name_is_flagged(self):
        c = chart.parse("FORMATION: x\nGK = NotARealPlayer, ,\n")
        issues = chart.problems(c, self.conn)
        self.assertTrue(any("never appeared" in i for i in issues))

    def test_a_player_with_no_games_in_that_band_is_flagged(self):
        """Listing a keeper at striker should say so out loud."""
        c = chart.parse("FORMATION: x\nST = KeeperOne, ,\n")
        issues = chart.problems(c, self.conn)
        self.assertTrue(
            any("no near-complete forward games" in i for i in issues))

    def test_render_prints_exact_slot_names(self):
        c = chart.parse(SAMPLE)
        text = chart.render(c, self.conn)
        self.assertIn("LCB", text)
        self.assertIn("CDM", text)

    def test_render_says_the_numbers_are_broad(self):
        c = chart.parse(SAMPLE)
        text = chart.render(c, self.conn)
        self.assertIn("BROAD", text)

    def test_rendering_is_deterministic(self):
        """Same chart, same database, same output. No random tie-breaking."""
        text = chart.render(chart.parse("FORMATION: x\nRB = , ,\n"), self.conn)
        again = chart.render(chart.parse("FORMATION: x\nRB = , ,\n"), self.conn)
        self.assertEqual(text, again)

    def test_a_suggestion_is_always_marked_as_one(self):
        """A suggested name must never look like the captain set it."""
        text = chart.render(chart.parse("FORMATION: x\nRB = , ,\n"), self.conn)
        for line in text.splitlines():
            if line.strip().startswith("RB "):
                self.assertIn("*", line)



class SuggestionTests(unittest.TestCase):
    """The captain could not fill bench and reserve, so the tool suggests them.

    Rules: habit not skill, no double-booked starters, captain entries win.
    """

    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        for match in load_fixture("matches_practice_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def full_chart(self):
        return chart.load(ROOT / "config" / "depth_chart.txt")

    def test_blank_backups_get_filled(self):
        c = self.full_chart()
        ideas = chart.suggest(c, self.conn)
        filled = sum(1 for picks in ideas.values() for p in picks if p)
        self.assertGreater(filled, 0)

    def test_a_captain_entry_is_never_overwritten(self):
        c = chart.parse("FORMATION: x\nGK = KeeperOne, ,\n")
        ideas = chart.suggest(c, self.conn)
        self.assertEqual(ideas["GK"][0], "",
                         "the captain set the starter, so nothing is suggested")

    def test_nobody_is_suggested_as_starter_twice(self):
        c = chart.parse(
            "FORMATION: x\nLB = , ,\nLCB = , ,\nRCB = , ,\nRB = , ,\n")
        ideas = chart.suggest(c, self.conn)
        starters = [picks[0] for picks in ideas.values() if picks[0]]
        self.assertEqual(len(starters), len(set(starters)))

    def test_cover_may_be_shared_between_slots(self):
        """Only one slot will need them on the night, so this is honest."""
        c = chart.parse(
            "FORMATION: x\n"
            "LW = Player10, ,\nST = Player08, ,\n"
            "RW = Player09, ,\n")
        ideas = chart.suggest(c, self.conn)
        benches = [picks[1] for picks in ideas.values() if picks[1]]
        self.assertGreater(len(benches), len(set(benches)),
                           "the same backup should be able to cover two slots")

    def test_a_suggestion_has_really_played_that_band(self):
        c = self.full_chart()
        ideas = chart.suggest(c, self.conn)
        seen = chart.broad_appearances(self.conn)
        for slot in c.slots:
            for who in ideas.get(slot.name, []):
                if who:
                    self.assertGreater(seen.get((who, slot.broad), 0), 0)

    def test_an_empty_band_suggests_nobody(self):
        c = chart.parse("FORMATION: x\nCF = , ,\n")
        self.conn.execute("DELETE FROM player_match_stats WHERE pos = 'forward'")
        self.conn.commit()
        ideas = chart.suggest(c, self.conn)
        self.assertEqual(ideas["CF"], ["", "", ""])

    def test_a_slot_nobody_can_cover_is_called_a_hole(self):
        self.conn.execute(
            "DELETE FROM player_match_stats WHERE pos = 'goalkeeper'")
        self.conn.commit()
        c = chart.parse("FORMATION: x\nGK = , ,\n")
        issues = chart.problems(c, self.conn)
        self.assertTrue(any("AI plays here" in i for i in issues))

    def test_suggestions_are_marked_in_the_output(self):
        c = self.full_chart()
        text = chart.render(c, self.conn)
        self.assertIn("*", text)
        self.assertIn("NOT skill", text)

    def test_suggestions_can_be_turned_off(self):
        c = self.full_chart()
        text = chart.render(c, self.conn, with_suggestions=False)
        self.assertNotIn("(13)*", text)

    def test_suggestion_order_follows_games_played(self):
        c = chart.parse("FORMATION: x\nCM = , ,\n")
        ideas = chart.suggest(c, self.conn)["CM"]
        seen = chart.broad_appearances(self.conn)
        counts = [seen[(who, "midfielder")] for who in ideas if who]
        self.assertEqual(counts, sorted(counts, reverse=True))


if __name__ == "__main__":
    unittest.main()


class BandDepthTests(unittest.TestCase):
    """Top three for each position, whoever is online. Review rule D3 and D4."""

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

    def test_every_band_gets_an_order(self):
        depth = chart.band_depth(self.conn)
        self.assertEqual(set(depth), set(chart.BANDS))

    def test_order_is_by_games_played(self):
        for band, rows in chart.band_depth(self.conn).items():
            counts = [n for _name, n in rows]
            self.assertEqual(counts, sorted(counts, reverse=True), band)

    def test_nobody_appears_twice_in_one_band(self):
        for band, rows in chart.band_depth(self.conn).items():
            names = [n for n, _ in rows]
            self.assertEqual(len(names), len(set(names)), band)

    def test_a_player_may_rank_in_several_bands(self):
        """People rotate. The whole point is that they show up in more than one."""
        depth = chart.band_depth(self.conn)
        appears = {}
        for band, rows in depth.items():
            for name, _ in rows:
                appears.setdefault(name, set()).add(band)
        self.assertTrue(any(len(bands) > 1 for bands in appears.values()))

    def test_a_refusal_removes_them_from_that_band(self):
        depth = chart.band_depth(self.conn, wont={"WideOne": {"forward"}})
        self.assertNotIn("WideOne", [n for n, _ in depth["forward"]])

    def test_willingness_adds_them_with_zero_games(self):
        depth = chart.band_depth(self.conn, can={"MidOne": {"goalkeeper"}})
        self.assertIn("MidOne", [n for n, _ in depth["goalkeeper"]])

    def test_the_text_names_all_four_bands(self):
        text = chart.band_depth_text(self.conn)
        for band in chart.BANDS:
            self.assertIn(band.upper(), text)

    def test_the_text_refuses_to_claim_skill(self):
        text = chart.band_depth_text(self.conn)
        self.assertIn("habit, not skill", text)

    def test_an_empty_band_says_so(self):
        self.conn.execute(
            "DELETE FROM player_match_stats WHERE pos = 'goalkeeper'")
        self.conn.commit()
        text = chart.band_depth_text(self.conn)
        self.assertIn("nobody has ever played here", text)
