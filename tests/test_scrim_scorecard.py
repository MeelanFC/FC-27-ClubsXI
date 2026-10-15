import testenv  # noqa: F401  (test settings, must come first)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from clubsxi import scrims as sc  # noqa: E402


def player(name, **kw):
    base = dict(playername=name, pos="midfielder", secondsPlayed="5400", goals="0", assists="0",
                shots="0", passesmade="10", passattempts="10", tacklesmade="1", tackleattempts="2",
                rating="7.0")
    base.update({k: str(v) for k, v in kw.items()})
    return base


def match(a_players, b_players, a_goals, b_goals, ts=1700000000, clubs=("100001", "100002")):
    a, b = clubs
    return {
        "matchId": "m1", "timestamp": ts,
        "clubs": {a: {"goals": str(a_goals), "details": {"name": "A"}},
                  b: {"goals": str(b_goals), "details": {"name": "B"}}},
        "players": {a: {str(i): p for i, p in enumerate(a_players)},
                    b: {str(i): p for i, p in enumerate(b_players)}},
    }


class ScrimScorecardTests(unittest.TestCase):
    def test_only_our_two_clubs_count_as_a_scrim(self):
        self.assertTrue(sc.is_scrim(match([], [], 0, 0)))
        self.assertFalse(sc.is_scrim(match([], [], 0, 0, clubs=("100001", "999"))))

    def test_seven_points_are_always_handed_out(self):
        s = sc.score(match([player("x", goals=1, shots=3)], [player("y", shots=1)], 1, 0))
        self.assertEqual(sum(s["points"].values()), 7)

    def test_the_loser_can_win_the_scorecard_on_habits(self):
        # A wins 2-1 on solo goals from lots of shots; B passes, tackles and sets up its goal
        a = [player("a", goals=2, shots=20, passesmade=5, passattempts=20, tacklesmade=0, tackleattempts=5)]
        b = [player("b", goals=1, assists=1, shots=25, passesmade=18, passattempts=20,
                    tacklesmade=4, tackleattempts=5)]
        s = sc.score(match(a, b, 2, 1))
        self.assertEqual(s["points"]["100001"], 3)       # result 2, finishing 1
        self.assertEqual(s["points"]["100002"], 4)      # passing, tackling, defence, team goals

    def test_assisted_goals_beat_solo_goals(self):
        a = [player("a", goals=2, assists=2, shots=4)]
        b = [player("b", goals=2, shots=4)]
        s = sc.score(match(a, b, 2, 2))
        self.assertEqual(s["winners"]["teamgoals"], "100001")

    def test_late_games_stay_on_the_same_night(self):
        # 23:30 and 00:30 on the same evening (tests run in UTC)
        self.assertEqual(sc.night_of(1700004600), sc.night_of(1700008200))

    def test_awards_need_enough_passes(self):
        s = sc.score(match([player("few", passesmade=5, passattempts=5)],
                           [player("many", passesmade=20, passattempts=25)], 0, 0))
        best = dict((t, n) for t, n, _ in sc.awards([s]))
        self.assertEqual(best["Best passer"], "many")


if __name__ == "__main__":
    unittest.main()
