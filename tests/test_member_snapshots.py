"""Guards the roster snapshot rules agreed by the review (D2 and D9).

The rules under test:
  - /members/stats is stored whole, timestamped, every poll.
  - It is NEVER projected backwards onto matches played earlier.
  - positionCount is a club-wide broad counter, not per member. Nothing to diff.
  - There is no numeric EA player id in this payload, so any link to a player
    is a soft name match that must refuse to guess when ambiguous.
"""
from __future__ import annotations

import testenv  # noqa: F401  (test settings, must come first)
import copy
import json
import sys
import time
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


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))
        self.roster = load("members_main.json")

    def tearDown(self) -> None:
        self.conn.close()

    def test_stores_every_member(self):
        snapshot_id = ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM member_snapshot_rows WHERE snapshot_id = ?",
            (snapshot_id,)).fetchone()[0]
        self.assertEqual(rows, len(self.roster["members"]))

    def test_snapshot_is_timestamped(self):
        before = int(time.time())
        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        row = self.conn.execute(
            "SELECT fetched_at, club_id FROM member_snapshots").fetchone()
        self.assertGreaterEqual(row["fetched_at"], before)
        self.assertEqual(row["club_id"], MAIN)

    def test_two_polls_make_two_snapshots_not_an_overwrite(self):
        """History of the roster matters. Later polls never replace earlier ones."""
        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        changed = copy.deepcopy(self.roster)
        changed["members"][0]["proPos"] = "25"
        ingest.store_member_snapshot(self.conn, MAIN, changed)

        snapshots = self.conn.execute(
            "SELECT COUNT(*) FROM member_snapshots").fetchone()[0]
        self.assertEqual(snapshots, 2)

        positions = [r[0] for r in self.conn.execute(
            "SELECT pro_pos FROM member_snapshot_rows WHERE name = ? "
            "ORDER BY snapshot_id", (self.roster["members"][0]["name"],))]
        self.assertEqual(len(positions), 2)
        self.assertNotEqual(positions[0], positions[1])

    def test_position_count_is_club_wide_and_broad_only(self):
        """Confirmed live. This kills the per-match diffing idea."""
        counts = self.roster["positionCount"]
        self.assertEqual(set(counts),
                         {"goalkeeper", "defender", "midfielder", "forward"})
        for member in self.roster["members"]:
            self.assertNotIn("positionCount", member)

        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        stored = json.loads(self.conn.execute(
            "SELECT position_count_json FROM member_snapshots").fetchone()[0])
        self.assertEqual(stored, counts)

    def test_pro_pos_is_stored_raw_and_never_named(self):
        """Review rule: raw codes only until a human confirms the map in game."""
        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        codes = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT pro_pos FROM member_snapshot_rows")}
        self.assertTrue(codes)
        for code in codes:
            self.assertTrue(code.isdigit(), "pro_pos must stay a raw code")

        named = self.conn.execute(
            "SELECT COUNT(*) FROM pro_pos_map WHERE verified = 1").fetchone()[0]
        self.assertEqual(named, 0, "no pro_pos name may be treated as verified")

    def test_unknown_member_fields_survive(self):
        roster = copy.deepcopy(self.roster)
        roster["members"][0]["brandNewEaField"] = "77"
        ingest.store_member_snapshot(self.conn, MAIN, roster)
        extras = json.loads(self.conn.execute(
            "SELECT extras_json FROM member_snapshot_rows WHERE name = ?",
            (roster["members"][0]["name"],)).fetchone()[0])
        self.assertEqual(extras["brandNewEaField"], "77")

    def test_player_link_is_soft_and_refuses_to_guess(self):
        """No numeric id in this payload. An unknown name links to nothing."""
        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        linked = self.conn.execute(
            "SELECT COUNT(*) FROM member_snapshot_rows "
            "WHERE player_id IS NOT NULL").fetchone()[0]
        self.assertEqual(linked, 0, "no players ingested yet, so no links")

        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        row = self.conn.execute(
            "SELECT player_id FROM member_snapshot_rows "
            "WHERE name = 'Captain' ORDER BY snapshot_id DESC "
            "LIMIT 1").fetchone()
        self.assertEqual(row["player_id"], "3000000013")

    def test_snapshots_never_touch_match_rows(self):
        """The no-back-projection rule, enforced."""
        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

        before = self.conn.execute(
            "SELECT match_id, club_id, player_id, pos, archetype_id "
            "FROM player_match_stats ORDER BY 1, 2, 3").fetchall()

        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        ingest.store_member_snapshot(self.conn, PRACTICE,
                                     load("members_practice.json"))
        self.conn.commit()

        after = self.conn.execute(
            "SELECT match_id, club_id, player_id, pos, archetype_id "
            "FROM player_match_stats ORDER BY 1, 2, 3").fetchall()
        self.assertEqual([tuple(r) for r in before], [tuple(r) for r in after])

    def test_clubs_keep_separate_rosters(self):
        ingest.store_member_snapshot(self.conn, MAIN, self.roster)
        ingest.store_member_snapshot(self.conn, PRACTICE,
                                     load("members_practice.json"))
        clubs = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT club_id FROM member_snapshot_rows")}
        self.assertEqual(clubs, {MAIN, PRACTICE})

    def test_a_repeated_name_does_not_crash_the_snapshot(self):
        roster = copy.deepcopy(self.roster)
        roster["members"].append(copy.deepcopy(roster["members"][0]))
        snapshot_id = ingest.store_member_snapshot(self.conn, MAIN, roster)
        rows = self.conn.execute(
            "SELECT COUNT(*) FROM member_snapshot_rows WHERE snapshot_id = ?",
            (snapshot_id,)).fetchone()[0]
        self.assertEqual(rows, len(self.roster["members"]))

    def test_empty_roster_is_stored_not_skipped(self):
        snapshot_id = ingest.store_member_snapshot(
            self.conn, MAIN, {"members": [], "positionCount": {}})
        row = self.conn.execute(
            "SELECT member_count FROM member_snapshots WHERE id = ?",
            (snapshot_id,)).fetchone()
        self.assertEqual(row["member_count"], 0)


if __name__ == "__main__":
    unittest.main()


class AppearanceRuleTests(unittest.TestCase):
    """Review rule D6: 90 percent of the longest appearance, and a rebuild that
    can re-apply the rule to data already stored."""

    def setUp(self) -> None:
        self.conn = db.connect(Path(":memory:"))

    def tearDown(self) -> None:
        self.conn.close()

    def test_ninety_percent_is_the_bar(self):
        from clubsxi.ingest import classify_appearance
        self.assertEqual(classify_appearance(5500, 5500), ("full", True))
        self.assertEqual(classify_appearance(5000, 5500), ("full", True))
        self.assertEqual(classify_appearance(4900, 5500), ("short", True))
        self.assertEqual(classify_appearance(3000, 5500), ("short", True))
        self.assertEqual(classify_appearance(0, 5500), ("ghost", False))

    def test_a_row_just_under_the_bar_is_not_near_complete(self):
        from clubsxi import ingest
        self.assertEqual(ingest.NEAR_COMPLETE_RATIO, 0.9)
        just_under = int(5500 * 0.9) - 1
        self.assertEqual(
            ingest.classify_appearance(just_under, 5500)[0], "short")

    def test_rebuild_reapplies_the_rule_to_stored_data(self):
        from clubsxi import ingest
        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()

        # Pretend an older, looser rule had marked everything full.
        self.conn.execute(
            "UPDATE player_match_stats SET appearance_class = 'full', "
            "is_real_appearance = 1")
        self.conn.commit()

        result = ingest.reclassify_appearances(self.conn)
        self.conn.commit()
        self.assertGreater(result["changed"], 0)

        again = ingest.reclassify_appearances(self.conn)
        self.assertEqual(again["changed"], 0, "rebuild must be idempotent")

    def test_rebuild_keeps_real_human_count_in_step(self):
        from clubsxi import ingest
        for match in load("matches_main_league.json"):
            ingest.ingest_match(self.conn, match, match_type="leagueMatch",
                                our_club_ids=OUR_CLUBS)
        self.conn.commit()
        ingest.reclassify_appearances(self.conn)
        self.conn.commit()

        mismatched = self.conn.execute(
            "SELECT COUNT(*) FROM match_clubs mc WHERE mc.real_human_count != ("
            "  SELECT COUNT(*) FROM player_match_stats s "
            "  WHERE s.match_id = mc.match_id AND s.club_id = mc.club_id "
            "    AND s.is_real_appearance = 1)").fetchone()[0]
        self.assertEqual(mismatched, 0)
