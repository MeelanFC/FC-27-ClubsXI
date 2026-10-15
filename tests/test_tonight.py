"""Who plays where tonight, given who is online.

The rules under test:
  - Goalkeeper is settled first when anyone online can do it.
  - The captain's own starters are honoured when they are online.
  - Nobody is placed in two slots.
  - Nobody is placed somewhere they are not eligible.
  - Slots nobody can cover become AI, loudly, never quietly.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import chart, db, ingest, tonight  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MAIN = "100001"
PRACTICE = "100002"
OUR_CLUBS = {MAIN, PRACTICE}

FORMATION = "\n".join([
    "FORMATION: 4-3-3 (2)",
    "GK  = KeeperOne, ,",
    "LB  = , ,",
    "LCB = BackOne, ,",
    "RCB = , ,",
    "RB  = , ,",
    "CDM = HolderOne, ,",
    "LCM = WideOne, ,",
    "RCM = Captain, ,",
    "LW  = Player10, ,",
    "ST  = Player08, ,",
    "RW  = Player09, ,",
])


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        for name in ("matches_main_league.json",
                     "matches_practice_league.json"):
            for match in load_fixture(name):
                ingest.ingest_match(self.conn, match,
                                    match_type="leagueMatch",
                                    our_club_ids=OUR_CLUBS)
        self.conn.commit()
        self.chart = chart.parse(FORMATION)

    def tearDown(self) -> None:
        self.conn.close()

    def plan(self, online, **kwargs):
        return tonight.plan(self.chart, self.conn, online, **kwargs)

    def test_everyone_online_gets_at_most_one_slot(self):
        online = ["WideOne", "Captain", "BackOne", "HolderOne",
                  "Player10", "Player08", "Player09"]
        p = self.plan(online)
        placed = [a.player for a in p.assignments]
        self.assertEqual(len(placed), len(set(placed)))

    def test_no_slot_is_used_twice(self):
        p = self.plan(["WideOne", "Captain", "BackOne"])
        slots = [a.slot for a in p.assignments]
        self.assertEqual(len(slots), len(set(slots)))

    def test_uncovered_slots_become_ai_and_are_listed(self):
        p = self.plan(["WideOne"])
        self.assertGreater(len(p.ai_slots), 0)
        self.assertEqual(len(p.assignments) + len(p.ai_slots),
                         len(self.chart.slots))

    def test_no_human_keeper_is_warned_about_loudly(self):
        p = self.plan(["WideOne", "Captain", "BackOne"])
        self.assertTrue(any("NO HUMAN KEEPER" in w for w in p.warnings))

    def test_a_keeper_online_is_placed_in_goal(self):
        p = self.plan(["KeeperOne", "WideOne", "Captain"])
        keeper = [a for a in p.assignments if a.slot == "GK"]
        self.assertEqual(len(keeper), 1)
        self.assertEqual(keeper[0].player, "KeeperOne")
        self.assertFalse(any("NO HUMAN KEEPER" in w for w in p.warnings))

    def test_the_keeper_is_taken_before_the_easy_slots(self):
        """A keeper who also plays outfield must not be used up elsewhere."""
        p = self.plan(["KeeperOne"])
        self.assertEqual(len(p.assignments), 1)
        self.assertEqual(p.assignments[0].slot, "GK")

    def test_nobody_is_placed_somewhere_they_cannot_play(self):
        online = ["WideOne", "Captain", "BackOne", "HolderOne",
                  "Player10", "Player08", "Player09"]
        p = self.plan(online)
        seen = chart.broad_appearances(self.conn)
        for a in p.assignments:
            self.assertGreater(seen.get((a.player, a.band), 0), 0)

    def test_a_refusal_is_respected(self):
        p = self.plan(["KeeperOne", "WideOne"],
                      wont={"KeeperOne": {"goalkeeper"}})
        self.assertNotIn("KeeperOne",
                         [a.player for a in p.assignments if a.slot == "GK"])

    def test_willingness_lets_someone_keep_goal_untried(self):
        p = self.plan(["MidOne"], can={"MidOne": {"goalkeeper"}})
        self.assertEqual([a.slot for a in p.assignments], ["GK"])

    def test_an_unmatched_name_is_reported_not_ignored(self):
        p = self.plan(["NotAPlayer", "WideOne"])
        self.assertIn("NotAPlayer", p.unknown_names)

    def test_a_partial_name_still_matches(self):
        p = self.plan(["capt"])
        self.assertEqual(p.unknown_names, [])
        self.assertEqual(p.assignments[0].player, "Captain")

    def test_more_players_than_slots_leaves_people_unused(self):
        everyone = sorted(chart.known_names(self.conn))
        p = self.plan(everyone)
        self.assertLessEqual(len(p.assignments), len(self.chart.slots))
        self.assertEqual(
            len(p.assignments) + len(p.unused),
            len([n for n in everyone if n not in p.unknown_names]))

    def test_slots_print_in_formation_order(self):
        p = self.plan(["WideOne", "KeeperOne"])
        text = tonight.render(p, self.conn)
        rows = [line.split()[0] for line in text.splitlines()
                if line.startswith("  ") and len(line.split()) > 1]
        order = [s for s in p.slot_order if s in rows]
        self.assertEqual([r for r in rows if r in p.slot_order], order)

    def test_the_output_refuses_to_claim_quality(self):
        p = self.plan(["WideOne", "Captain"])
        text = tonight.render(p, self.conn)
        self.assertIn("COVERAGE, not who is better", text)

    def test_alternatives_are_a_players_real_bands(self):
        options = tonight.alternatives(self.conn, "WideOne")
        self.assertTrue(options)
        counts = [n for _band, n in options]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_alternatives_drop_a_refused_band(self):
        options = tonight.alternatives(
            self.conn, "WideOne", wont={"WideOne": {"forward"}})
        self.assertNotIn("forward", [band for band, _ in options])

    def test_nobody_online_means_a_full_ai_team(self):
        p = self.plan([])
        self.assertEqual(p.assignments, [])
        self.assertEqual(len(p.ai_slots), len(self.chart.slots))


if __name__ == "__main__":
    unittest.main()
