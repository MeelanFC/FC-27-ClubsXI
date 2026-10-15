"""What each build does, and who is running a weak one.

The point of this module is that "Player X is our worst forward" is a judgement
about a person and probably wrong, while "Spark forwards score less than
Magicians across the whole league" is a fact about a build. These tests guard
the things that would turn the second back into the first.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clubsxi import builds, db, ingest  # noqa: E402

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


class ProfileTests(Base):
    def test_the_opposition_is_included(self):
        """The whole point. Our own rota is not a fact about the game."""
        found = builds.profiles(self.conn)
        self.assertTrue(found)
        self.assertTrue(any(p.opponent_appearances > 0 for p in found),
                        "opponent players must be in the build profiles")

    def test_a_profile_is_a_rate_not_a_total(self):
        for p in builds.profiles(self.conn):
            self.assertGreaterEqual(p.goals_90, 0)
            self.assertLess(p.goals_90, 20, p.label + " rate looks like a total")

    def test_thin_profiles_are_marked_not_hidden(self):
        found = builds.profiles(self.conn)
        thin = [p for p in found if not p.trusted]
        self.assertTrue(thin, "fixtures should contain some thin profiles")
        text = builds.profiles_text(self.conn)
        self.assertIn("thin", text)

    def test_a_thin_profile_never_drives_a_suggestion(self):
        trusted = {(p.band, p.archetype_id)
                   for p in builds.profiles(self.conn) if p.trusted}
        for s in builds.suggestions(self.conn):
            self.assertIn((s["band"], s["current"].archetype_id), trusted)
            self.assertIn((s["band"], s["best"].archetype_id), trusted)

    def test_conversion_is_none_rather_than_zero_without_shots(self):
        for p in builds.profiles(self.conn):
            if p.shots_90 == 0:
                self.assertIsNone(p.conversion)

    def test_unconfirmed_names_keep_a_question_mark(self):
        self.conn.execute("UPDATE archetype_map SET verified = 0 WHERE archetype_id = '4'")   # all 13 confirmed now
        labels = [p.label for p in builds.profiles(self.conn)]
        self.assertTrue(any(label.endswith("?") for label in labels))
        self.assertTrue(any(not label.endswith("?") for label in labels))


class SuggestionTests(Base):
    def test_a_suggestion_always_names_a_better_build(self):
        for s in builds.suggestions(self.conn):
            self.assertGreater(s["best"].output_90, s["current"].output_90)
            self.assertNotEqual(s["best"].archetype_id,
                                s["current"].archetype_id)

    def test_a_small_gap_is_not_worth_mentioning(self):
        for s in builds.suggestions(self.conn):
            self.assertGreaterEqual(s["gap"], builds.WORTH_MENTIONING)

    def test_a_player_with_few_games_is_left_alone(self):
        for s in builds.suggestions(self.conn):
            self.assertGreaterEqual(s["games_on_current"],
                                    builds.MIN_PLAYER_GAMES)

    def test_it_knows_when_a_player_already_owns_the_build(self):
        """Telling somebody to make a build they already run is embarrassing."""
        everything = builds.player_builds(self.conn)
        owned: dict[str, set] = {}
        for (player, _band), entry in everything.items():
            owned.setdefault(player, set()).update(entry["builds"])
        for s in builds.suggestions(self.conn):
            expected = s["best"].archetype_id in owned.get(s["player"], set())
            self.assertEqual(s["owns_it"], expected)

    def test_it_notices_when_somebody_beats_their_own_build(self):
        for s in builds.suggestions(self.conn):
            self.assertEqual(
                s["beating_their_build"],
                s["their_output"] > s["current"].output_90)

    def test_the_text_says_this_is_a_fix_not_a_benching(self):
        text = builds.suggestions_text(self.conn)
        self.assertIn("not a benching", text)
        self.assertIn("not between people", text)

    def test_no_suggestions_is_stated_plainly(self):
        empty = db.connect(Path(":memory:"))
        self.assertIn("Nobody is clearly on the wrong build",
                      builds.suggestions_text(empty))
        empty.close()

    def test_a_band_with_one_build_produces_no_suggestion(self):
        one = db.connect(Path(":memory:"))
        for match in load_fixture("matches_main_league.json"):
            ingest.ingest_match(one, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        one.execute("UPDATE player_match_stats SET archetype_id = '11'")
        one.commit()
        self.assertEqual(builds.suggestions(one), [])
        one.close()

    def test_ordered_by_how_much_it_would_matter(self):
        found = builds.suggestions(self.conn)
        weight = [s["gap"] * s["games_on_current"] for s in found]
        self.assertEqual(weight, sorted(weight, reverse=True))


if __name__ == "__main__":
    unittest.main()
