import testenv  # noqa: F401  (test settings, must come first)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from clubsxi import slot_ranking as sr  # noqa: E402


def row(name, pos="midfielder", arch="8", match="m1", club="100001", **kw):
    base = dict(match=match, club=club, ours=True, validity="ok", name=name, pos=pos, arch=arch,
                rating=7.0, edge=0.0, goals=0, assists=0, sot=0, dri=0, inter=0, clr=0, fwd=0,
                pm=10, pa=12, tm=1, ta=2, saves=0, conceded=0, won=3, lost=3,
                won_a=1, lost_a=1, won_d=1, lost_d=1, ga=1, heads=8, oheads=8, gar=0.0)
    base.update(kw)
    return base


class SlotRoutingTests(unittest.TestCase):
    def ctx(self, rows):
        return sr.Ctx(rows)

    def test_back_line_split_by_build(self):
        c = self.ctx([row("A")])
        for arch in ("3", "4"):                           # Progressor, Boss
            self.assertTrue(c.in_slot(row("A", pos="defender", arch=arch), "CB"))
            self.assertFalse(c.in_slot(row("A", pos="defender", arch=arch), "FB"))
        for arch in ("5", "6", "7", "11"):                # Disruptor, Marauder, Recycler, Magician
            self.assertTrue(c.in_slot(row("A", pos="defender", arch=arch), "FB"))
            self.assertFalse(c.in_slot(row("A", pos="defender", arch=arch), "CB"))

    def test_without_fullbacks_every_defender_game_is_centre_back(self):
        c = self.ctx([row("A")])
        sr.FULLBACK_PLAYED = False
        try:
            for arch in ("4", "5", "9"):
                self.assertTrue(c.in_slot(row("A", pos="defender", arch=arch), "CB"))
                self.assertFalse(c.in_slot(row("A", pos="defender", arch=arch), "FB"))
        finally:
            sr.FULLBACK_PLAYED = True

    def test_games_without_hidden_counters_do_not_count_as_zero(self):
        league = row("A", hid=True, dri=10)
        friendly = row("A", hid=False, dri=0)       # EA sends no counters for friendlies
        self.assertEqual(sr.values([league, friendly], "dribbles"), [10])
        self.assertEqual(sr.values([league, friendly], "goals + assists"), [0, 0])   # labelled: always known

    def test_only_this_seasons_games_count_for_the_order(self):
        old = [row("Vet", pos="forward", arch="12", club="100003", match=f"o{i}") for i in range(8)]
        new = [row("Vet", pos="forward", arch="12", club="100001", match=f"n{i}") for i in range(2)]
        res = sr.rank_slot(sr.Ctx(old + new), "ST", 1, {}, reps=5)
        self.assertEqual(res["people"], [])               # 2 current games: not considered yet
        new += [row("Vet", pos="forward", arch="12", club="100001", match="n9")]
        res = sr.rank_slot(sr.Ctx(old + new), "ST", 1, {}, reps=5)
        self.assertEqual(res["people"][0]["n"], 3)        # last year's 8 are history only
        self.assertEqual(res["people"][0]["history"], 8)

    def test_forward_builds_route_to_st_and_wing(self):
        c = self.ctx([row("A")])
        self.assertTrue(c.in_slot(row("A", pos="forward", arch="13"), "ST"))
        self.assertFalse(c.in_slot(row("A", pos="forward", arch="13"), "WING"))
        self.assertTrue(c.in_slot(row("A", pos="forward", arch="10"), "WING"))

    def test_deepest_usual_midfielder_is_cdm_in_that_match(self):
        deep = dict(won_a=0, lost_a=0, won_d=4, lost_d=4)       # usual depth strongly negative
        high = dict(won_a=4, lost_a=4, won_d=0, lost_d=0)
        rows = []
        for i in range(3):                                       # other games set the usual depth
            rows += [row("Holder", match=f"o{i}", **deep), row("Winger", match=f"o{i}", **high)]
        rows += [row("Holder", match="x", **deep), row("Winger", match="x", **high)]
        cdm = sr.cdm_games([r for r in rows if r["ours"]])
        self.assertIn(("x", "Holder"), cdm)
        self.assertNotIn(("x", "Winger"), cdm)


class RankingRuleTests(unittest.TestCase):
    def test_a_new_player_with_three_great_games_can_be_gold(self):
        people = [dict(name="New", n=3, score=0.9), dict(name="Solid", n=6, score=0.5),
                  dict(name="Two", n=2, score=0.95)]
        t = sr.tiers({"cards": 1, "people": people})
        self.assertEqual(t["gold"][0]["name"], "New")
        self.assertEqual(t["silver"][0]["name"], "Solid")    # 2 games is not enough to be considered

    def test_typical_is_the_regulars_average_so_few_games_are_pulled_to_it(self):
        regs = [row(n, pos="forward", arch="12", club="100001", match=f"{n}{i}", goals=1)
                for n in "ABC" for i in range(5)]
        new = [row("New", pos="forward", arch="12", club="100001", match=f"z{i}", goals=0) for i in range(3)]
        res = sr.rank_slot(sr.Ctx(regs + new), "ST", 1, {}, reps=5)
        self.assertEqual(res["typical"]["goals + assists"], 1.0)   # the new player's 0s are not in it

    def test_two_cards_take_consecutive_ranks(self):
        people = [dict(name=c, n=6, score=1 - i / 10) for i, c in enumerate("ABCDEF")]
        t = sr.tiers({"cards": 2, "people": people})
        self.assertEqual([r["name"] for r in t["gold"]], ["A", "B"])
        self.assertEqual([r["name"] for r in t["silver"]], ["C", "D"])
        self.assertEqual([r["name"] for r in t["bronze"]], ["E", "F"])

    def test_how_sure_words(self):
        self.assertEqual(sr.how_sure(80), "very sure")
        self.assertEqual(sr.how_sure(79), "likely")
        self.assertEqual(sr.how_sure(54), "close call")

    def test_few_games_are_pulled_toward_typical(self):
        # one game of 10 against a typical of 2, with 4 games of typical added
        self.assertAlmostEqual(sr.shrunk([10.0], "dribbles", 2.0, 4.0, None), (10 + 8) / 5)

    def test_head_to_head_orders_by_wins(self):
        games = {"Good": [row("Good", goals=2, sot=3, edge=0.5)] * 5,
                 "Mid": [row("Mid", goals=1, sot=1, edge=0.0)] * 5,
                 "Low": [row("Low", edge=-0.5)] * 5}
        pri = {m: sr.typical([r for g in games.values() for r in g], m) for m in sr.SETS["ST"]}
        ks = {m: 2.0 for m in sr.SETS["ST"]}
        s = sr.score_people(games, "ST", pri, ks)
        self.assertGreater(s["Good"]["score"], s["Mid"]["score"])
        self.assertGreater(s["Mid"]["score"], s["Low"]["score"])


def person(name, n, score):
    return dict(name=name, n=n, score=score, history=0)


def fake_results(**slots):
    return {s: dict(slot=s, cards=cards, people=people) for s, (cards, people) in slots.items()}


class PrimarySlotTests(unittest.TestCase):
    def test_one_person_starts_in_one_slot_only(self):
        res = fake_results(
            MID=(1, [person("Alpha", 6, .9), person("Bravo", 9, .5)]),
            DEF=(1, [person("Alpha", 10, .8), person("Charlie", 5, .4), person("Third", 6, .3)]))
        t, moves = sr.assign(res)
        golds = [r["name"] for s in t.values() for r in s["gold"] if r]
        self.assertEqual(len(golds), len(set(golds)))
        self.assertEqual(t["MID"]["gold"][0]["name"], "Alpha")       # CDM has fewer rivals (1 vs 2)
        self.assertEqual(t["DEF"]["gold"][0]["name"], "Charlie")      # next person promoted
        self.assertIn("Alpha", [r["name"] for r in t["DEF"]["silver"] if r])   # secondary, not dropped
        self.assertTrue(moves)

    def test_captains_pin_wins(self):
        res = fake_results(
            MID=(1, [person("Alpha", 6, .9), person("Bravo", 9, .5)]),
            DEF=(1, [person("Alpha", 10, .8), person("Charlie", 5, .4)]))
        t, _ = sr.assign(res, {"Alpha": "DEF"})
        self.assertEqual(t["DEF"]["gold"][0]["name"], "Alpha")
        self.assertEqual(t["MID"]["gold"][0]["name"], "Bravo")

    def test_promotion_can_cascade_without_looping_forever(self):
        res = fake_results(
            MID=(1, [person("X", 6, .9), person("Y", 6, .5)]),
            ATK=(1, [person("X", 6, .8), person("Y", 6, .6), person("Z", 6, .1)]))
        t, _ = sr.assign(res)
        golds = [r["name"] for s in t.values() for r in s["gold"] if r]
        self.assertEqual(len(golds), len(set(golds)))

    def test_pins_file_is_read_and_two_accounts_are_one_person(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# comment\nWideOne = cdm\nPlayer07 = WING\nnobody = XX\n")
        pins = sr.load_primary(f.name)
        os.unlink(f.name)
        self.assertEqual(pins, {"WideOne": "MID", "Player09": "ATK"})


if __name__ == "__main__":
    unittest.main()
