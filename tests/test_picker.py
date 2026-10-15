import testenv  # noqa: F401  (test settings, must come first)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from clubsxi import picker as pk  # noqa: E402


def costs(**usual):
    """name -> group he always plays, so every other group is a never-played move."""
    return {n: pk.move_cost({g: 10}) for n, g in usual.items()}


class PickerTests(unittest.TestCase):
    def test_people_stay_in_their_usual_group_and_ai_covers_the_rest(self):
        cost = costs(A="ATK", B="ATK", C="ATK", D="ATK", M="MID")
        r = pk.pick(list(cost), {}, cost, set())
        self.assertEqual(len(r["lineup"]["ATK"]), 3)
        self.assertEqual(r["lineup"]["MID"], ["M"])
        self.assertEqual(r["lineup"]["DEF"], [])           # no forward dropped into defence
        self.assertEqual(r["ai"]["DEF"], 4)
        self.assertEqual(len(r["out"]), 1)                   # fourth forward waits on the bench
        self.assertEqual(r["out"][0][1], "ATK")

    def test_outfielder_never_in_goal_while_a_keeper_is_online(self):
        cost = costs(K="GK", X="MID")
        fit = {"X": {"GK": 5.0}}
        r = pk.pick(["K", "X"], fit, cost, {"K"})
        self.assertEqual(r["lineup"]["GK"], ["K"])

    def test_better_fit_wins_the_last_spot(self):
        cost = costs(A="MID", B="MID", C="MID", D="MID")
        fit = {"D": {"MID": 0.5}, "A": {"MID": -0.3}}
        r = pk.pick(["A", "B", "C", "D"], fit, cost, set())
        self.assertNotIn("A", r["lineup"]["MID"])

    def test_move_cost_steps(self):
        self.assertEqual(pk.move_cost({"MID": 10})["DEF"], 0.9)
        self.assertEqual(pk.move_cost({"MID": 8, "DEF": 2})["DEF"], 0.3)
        self.assertEqual(pk.move_cost({"MID": 7, "ATK": 3})["ATK"], 0.0)

    def test_newcomer_cost_follows_his_build(self):
        c = pk.move_cost({"MID": 1}, {"DEF": "Progressor", "MID": "Progressor"})
        self.assertEqual(c["DEF"], 0.0)       # build fits defence
        self.assertEqual(c["MID"], 0.2)       # build does not fit midfield
        self.assertEqual(c["GK"], 0.25)       # capped


if __name__ == "__main__":
    unittest.main()
