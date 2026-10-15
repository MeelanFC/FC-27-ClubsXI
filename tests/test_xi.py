"""The two questions, answered as player plus archetype.

  1. A player's top three builds.
  2. A starting eleven of eleven different people.

Archetype is the unit because exact position is not in EA's data and never
will be, while the archetype is exact and mostly human-confirmed. The group
reads the position off the archetype themselves.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import db, ingest, xi  # noqa: E402

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


class TopRolesTests(Base):
    def test_every_role_really_happened(self):
        for role in xi.roles(self.conn):
            self.assertGreater(role.games, 0)
            self.assertIn(role.band, {"goalkeeper", "defender",
                                      "midfielder", "forward"})

    def test_a_player_gets_at_most_three(self):
        for player, items in xi.top_roles(self.conn, limit=3).items():
            self.assertLessEqual(len(items), 3, player)

    def test_ordered_by_games_played(self):
        for player, items in xi.top_roles(self.conn, limit=0).items():
            counts = [r.games for r in items]
            self.assertEqual(counts, sorted(counts, reverse=True), player)

    def test_a_player_with_one_build_gets_one_row_not_three(self):
        """No padding to three. Fewer is the honest answer."""
        grouped = xi.top_roles(self.conn, limit=3)
        self.assertTrue(any(len(items) == 1 for items in grouped.values()))

    def test_the_same_archetype_can_appear_in_two_bands(self):
        """Confirmed in real play: Magician at forward and at midfield."""
        seen: dict[str, set[str]] = {}
        for role in xi.roles(self.conn):
            seen.setdefault(role.archetype_id, set()).add(role.band)
        self.assertTrue(any(len(bands) > 1 for bands in seen.values()))

    def test_unconfirmed_archetype_names_carry_a_question_mark(self):
        self.conn.execute("UPDATE archetype_map SET verified = 0 WHERE archetype_id = '4'")   # all 13 confirmed now
        labels = {r.archetype_id: r.label for r in xi.roles(self.conn)}
        self.assertTrue(any(label.endswith("?") for label in labels.values()))
        self.assertTrue(any(not label.endswith("?")
                            for label in labels.values()))

    def test_the_text_explains_the_archetype_reading(self):
        text = xi.top_roles_text(self.conn)
        self.assertIn("read the real position off it", text)


class StartingElevenTests(Base):
    def test_nobody_appears_twice(self):
        picks, _gaps = xi.starting_eleven(self.conn)
        names = [p.player for p in picks]
        self.assertEqual(len(names), len(set(names)))

    def test_never_more_than_the_shape_asks_for(self):
        picks, _gaps = xi.starting_eleven(self.conn)
        counts: dict[str, int] = {}
        for p in picks:
            counts[p.band] = counts.get(p.band, 0) + 1
        for band, wanted in xi.DEFAULT_SHAPE.items():
            self.assertLessEqual(counts.get(band, 0), wanted, band)

    def test_a_keeper_is_picked_when_one_exists(self):
        picks, _gaps = xi.starting_eleven(self.conn)
        self.assertIn("goalkeeper", [p.band for p in picks])

    def test_a_missing_band_is_reported_as_a_gap(self):
        self.conn.execute(
            "DELETE FROM player_match_stats WHERE pos = 'goalkeeper'")
        self.conn.commit()
        picks, gaps = xi.starting_eleven(self.conn)
        self.assertNotIn("goalkeeper", [p.band for p in picks])
        self.assertTrue(any("goalkeeper" in g for g in gaps))

    def test_the_scarce_band_is_filled_before_the_crowded_one(self):
        """Fill forwards first and you strand the keeper."""
        picks, gaps = xi.starting_eleven(
            self.conn, shape={"goalkeeper": 1, "forward": 3})
        self.assertIn("goalkeeper", [p.band for p in picks])
        self.assertEqual(gaps, [])

    def test_every_pick_carries_a_real_archetype(self):
        picks, _gaps = xi.starting_eleven(self.conn)
        for p in picks:
            self.assertTrue(p.archetype_id)
            self.assertGreater(p.games, 0)

    def test_a_custom_shape_is_honoured(self):
        picks, _gaps = xi.starting_eleven(
            self.conn, shape={"goalkeeper": 1, "defender": 3,
                              "midfielder": 4, "forward": 3})
        counts: dict[str, int] = {}
        for p in picks:
            counts[p.band] = counts.get(p.band, 0) + 1
        self.assertLessEqual(counts.get("defender", 0), 3)
        self.assertLessEqual(counts.get("midfielder", 0), 4)

    def test_the_text_refuses_to_claim_quality(self):
        text = xi.starting_eleven_text(self.conn)
        self.assertIn("not by who is", text)

    def test_one_club_only_can_be_asked_for(self):
        picks, _gaps = xi.starting_eleven(self.conn, club_ids=[MAIN])
        self.assertTrue(picks)

    def test_an_empty_database_gives_no_eleven_and_says_so(self):
        empty = db.connect(Path(":memory:"))
        picks, gaps = xi.starting_eleven(empty)
        empty.close()
        self.assertEqual(picks, [])
        self.assertEqual(len(gaps), len(xi.DEFAULT_SHAPE))


if __name__ == "__main__":
    unittest.main()
