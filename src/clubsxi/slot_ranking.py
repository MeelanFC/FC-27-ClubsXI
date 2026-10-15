"""Gold / silver / bronze per slot from the decoded numbers. A PREVIEW engine.

    python tools/slot_ranking.py ARCHIVE.jsonl [LEAGUE.json]

The live viewer reads the same thing straight from the database (from_db).

Method (docs/08-squad-picker.md):
1. Our near-complete appearances (90 percent of the longest minutes in that
   MATCH), both clubs pooled, no club penalty. Two accounts of one person are one
   person (config/same_person.txt).
2. A game belongs to a slot by EA's band, the build and the captain's usual ranges.
   Only this season's games decide the order; last season's
   games are shown as history (early season, builds still changing). Midfield games are split CDM / CM match
   by match: the human midfielder who usually plays deepest is that match's CDM.
3. Each slot has 3 or 4 numbers that passed two tests on other clubs' games
   (steady from game to game, and linked to the team doing better).
4. Small samples are pulled toward our typical player in that slot, by a number
   of "games of typical" measured from how noisy one game is against how much
   people really differ (measured on the league sample, capped at 15).
5. Per number, each person is compared head to head with the other candidates;
   the order is the average share of comparisons won, every number counting the
   same. The combined score is never shown on a card.
6. Anyone with 3 games in the slot is considered (captain's rule: a new
   player who is great for 3 games should count). Few games are pulled hard
   toward "typical", and typical is the game-weighted average of the regulars
   (5+ games there), so 3 great games rank high only if they are well above
   what the regulars do. "How sure" is how often the
   person is gold when each person's games are resampled 100 times.

Left versus right is not used anywhere.
"""
from __future__ import annotations

import collections
import json
import math
import random
import statistics as st
import sys

from . import config as _config

OURS = _config.our_club_ids()          # every club id in CLUBSXI_CLUB_IDS
LINK = _config.same_person()           # EA account -> person (one person, two EA accounts)
ARCH = {"1": "Shot Stopper", "2": "Sweeper Keeper", "3": "Progressor", "4": "Boss",
        "5": "Disruptor", "6": "Marauder", "7": "Recycler", "8": "Maestro", "9": "Creator",
        "10": "Spark", "11": "Magician", "12": "Finisher", "13": "Target"}
CB_ARCH = {"3", "4"}
WING_ARCH = {"9", "10", "11", "12"}
ST_ARCH = {"11", "12", "13"}
FC27_CLUBS = _config.season_club_ids()  # games played this season; older games are history
FULLBACK_PLAYED = True                # set False if your club never plays LB or RB
SLOTS = ["GK", "DEF", "MID", "ATK"]   # EA's four groups, each ranked as one list. Builds do not show
                                     # position (people play with different builds), so
                                     # no slot is guessed from a build; left/right/centre is sorted in game.
GOLD_MIN, LIST_MIN = 3, 3
REGULAR = 5                           # "typical" comes from people with this many games in the slot
K_CAP, TEAM_K = 15, 8
REPS = 100

# ---------------------------------------------------------------- loading


def events(p: dict) -> collections.Counter:
    out: collections.Counter = collections.Counter()
    for key in ("match_event_aggregate_0", "match_event_aggregate_1",
                "match_event_aggregate_2", "match_event_aggregate_3"):
        for part in str(p.get(key) or "").split(","):
            if ":" in part:
                a, b = part.split(":")
                out[int(a)] += int(b)
    return out


def num(p: dict, key: str) -> float:
    try:
        return float(p.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def rows_from(match: dict, validity: str) -> list[dict]:
    players, clubs = match["players"], match["clubs"]
    everyone = [p for pl in players.values() for p in pl.values()]
    longest = max((int(p.get("secondsPlayed") or 0) for p in everyone), default=0)
    if longest <= 0:
        return []
    heads = {c: len(pl) for c, pl in players.items()}
    out = []
    for club, pl in players.items():
        if club not in clubs:
            continue
        ours = club in OURS
        opp = [c for c in players if c != club]
        gf, ga = int(clubs[club].get("goals") or 0), int(clubs[club].get("goalsAgainst") or 0)
        full = [p for p in pl.values() if int(p.get("secondsPlayed") or 0) >= 0.9 * longest]
        for p in full:
            ev = events(p)
            mates = [num(o, "rating") for o in full if o is not p and o["pos"] != "goalkeeper"]
            name = LINK.get(p["playername"], p["playername"]) if ours else club + ":" + p["playername"]
            out.append(dict(
                match=match["matchId"], club=club, ours=ours, validity=validity, name=name,
                pos=p["pos"], arch=str(p["archetypeid"]), rating=num(p, "rating"),
                edge=(num(p, "rating") - sum(mates) / len(mates))
                if len(mates) >= 3 and p["pos"] != "goalkeeper" else None,
                goals=num(p, "goals"), assists=num(p, "assists"), sot=ev[217], dri=ev[174],
                inter=ev[6], clr=ev[9], fwd=ev[30],
                pm=num(p, "passesmade"), pa=num(p, "passattempts"),
                tm=num(p, "tacklesmade"), ta=num(p, "tackleattempts"),
                saves=num(p, "saves"), conceded=num(p, "goalsconceded"),
                won=ev[108] + ev[109] + ev[110], lost=ev[105] + ev[106] + ev[107],
                won_a=ev[110], lost_a=ev[107], won_d=ev[108], lost_d=ev[105],
                # EA leaves the hidden counters out of friendlies: no counters means
                # unknown, not zero (docs/04-hidden-counters.md)
                hid=bool(ev), beats=ev[38], ftp=ev[143], pens=ev[94],
                # proven against the in-game Match Facts screen (docs/04-hidden-counters.md)
                lb=ev[8] + ev[184] + ev[10], tb=ev[152], box=ev[13] + ev[14], crs=ev[37],
                ga=ga, heads=heads.get(club, 0), oheads=heads.get(opp[0], 0) if opp else 0))
    return out


def load(archive: str, league_json: str | None = None) -> list[dict]:
    own = ((j["raw"], j.get("validity", "ok"))
           for j in map(json.loads, open(archive, encoding="utf-8")))
    league = json.load(open(league_json, encoding="utf-8")) if league_json else []
    return load_matches(own, league)


def from_db(conn) -> list[dict]:
    """Same rows, read from the collector's database: our matches, plus other
    clubs' matches from this season to measure how noisy each number is."""
    own = [(json.loads(raw), validity) for raw, validity in conn.execute(
        "SELECT raw_json, validity FROM matches WHERE source = 'own'")]
    starts = [int(m["timestamp"]) for m, _ in own if set(m.get("clubs", {})) & FC27_CLUBS]
    league = [json.loads(raw) for (raw,) in conn.execute(
        "SELECT raw_json FROM matches WHERE source != 'own' AND match_timestamp >= ?",
        (min(starts) if starts else 0,))]
    return load_matches(own, league)


def fc27_matches(rows: list[dict]) -> int:
    return len({r["match"] for r in rows if r["ours"] and r["club"] in FC27_CLUBS})


def load_matches(own, league) -> list[dict]:
    """own: (match, validity) pairs of our games; league: other clubs' matches."""
    rows, seen = [], set()
    for m, validity in own:
        if m["matchId"] in seen:
            continue
        seen.add(m["matchId"])
        rows += rows_from(m, validity)
    for m in league:
        if m["matchId"] not in seen:
            seen.add(m["matchId"])
            rows += rows_from(m, "ok")
    if not rows:
        return rows
    # goals conceded, adjusted for how many humans each side had
    sides = {(r["match"], r["club"]): (r["ga"], r["heads"] - r["oheads"])
             for r in rows if r["validity"] == "ok"}
    xs = [v[1] for v in sides.values()]
    ys = [v[0] for v in sides.values()]
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    a = my - b * mx
    for r in rows:
        r["gar"] = (r["ga"] - (a + b * (r["heads"] - r["oheads"]))) if r["validity"] == "ok" else None
    return rows


# ---------------------------------------------------------------- slots


def depth_pool(rows: list[dict]) -> dict[str, list[int]]:
    pooled: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r["pos"] == "midfielder":
            p = pooled[r["name"]]
            p[0] += r["won_a"] + r["lost_a"]
            p[1] += r["won_d"] + r["lost_d"]
            p[2] += r["won"] + r["lost"]
    return pooled


def person_labels(rows: list[dict]) -> dict[str, str]:
    out = {}
    for n, (a, d, t) in depth_pool(rows).items():
        dep = (a - d) / t if t >= 15 else 0.0
        out[n] = "deep" if dep <= -0.3 else "high" if dep >= 0.1 else "central"
    return out


def cdm_games(ours: list[dict]) -> set[tuple[str, str]]:
    """Per match: the human midfielder who usually plays deepest is that match's CDM."""
    pool = depth_pool(ours)

    def usual(r):  # his depth over his OTHER midfield games
        a, d, t = pool[r["name"]]
        a -= r["won_a"] + r["lost_a"]
        d -= r["won_d"] + r["lost_d"]
        t -= r["won"] + r["lost"]
        return (a - d) / t if t >= 8 else 0.0

    def here(r):
        t = r["won"] + r["lost"]
        return ((r["won_a"] + r["lost_a"]) - (r["won_d"] + r["lost_d"])) / t if t else 0.0

    by: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for r in ours:
        if r["pos"] == "midfielder":
            by[(r["match"], r["club"])].append(r)
    out: set[tuple[str, str]] = set()
    for mids in by.values():
        if len(mids) == 1:
            if usual(mids[0]) <= -0.3:
                out.add((mids[0]["match"], mids[0]["name"]))
            continue
        # Tested version: deepest by usual depth, this match's depth only breaks exact ties.
        # (A tolerance band of 0.15 was suggested but not tested.)
        best = min(mids, key=lambda r: (usual(r), here(r)))
        out.add((best["match"], best["name"]))
    return out


class Ctx:
    def __init__(self, rows: list[dict]):
        self.ours = [r for r in rows if r["ours"]]
        self.league = [r for r in rows if not r["ours"]]
        self.cdm = cdm_games(self.ours)
        self.lg_labels = person_labels(self.league)

    def in_slot(self, r: dict, slot: str) -> bool:
        pos, arch = r["pos"], r["arch"]
        if slot == "GK":
            return pos == "goalkeeper"
        # EA only says "defender". Boss and Progressor builds are centre backs; any
        # other build in the back line (Disruptor, Marauder, Recycler, Magician...) is a fullback.
        if slot == "DEF":
            return pos == "defender"
        if slot == "MID":
            return pos == "midfielder"
        if slot == "ATK":
            return pos == "forward"
        if slot == "CB":
            return pos == "defender" and (arch in CB_ARCH or not FULLBACK_PLAYED)
        if slot == "FB":
            return FULLBACK_PLAYED and pos == "defender" and arch not in CB_ARCH
        if slot == "WING":
            return pos == "forward" and arch in WING_ARCH
        if slot == "ST":
            return pos == "forward" and arch in ST_ARCH
        if pos != "midfielder":
            return False
        if r["ours"]:
            return ((r["match"], r["name"]) in self.cdm) == (slot == "CDM")
        return slot == "CM" or self.lg_labels.get(r["name"], "central") in ("deep", "central")


# ---------------------------------------------------------------- numbers
# kind: "game" = mean of a per-game value, "ratio" = total made over total tried
def hidden(fn):
    """A number built from hidden counters is unknown in games without them."""
    return lambda r: fn(r) if r.get("hid", True) else None


MET = {
    "rating vs teammates": ("game", lambda r: r["edge"], 1),
    "EA rating": ("game", lambda r: r["rating"], 1),
    "goals + assists": ("game", lambda r: r["goals"] + r["assists"], 1),
    "shots on target": ("game", hidden(lambda r: r["sot"]), 1),
    "dribbles": ("game", hidden(lambda r: r["dri"]), 1),
    "interceptions": ("game", hidden(lambda r: r["inter"]), 1),
    "forward passes": ("game", hidden(lambda r: r["fwd"]), 1),
    "won minus lost": ("game", hidden(lambda r: r["won"] - r["lost"]), 1),
    # added after the steady + goes-with-winning test on other clubs' league games
    "skill-move beats": ("game", hidden(lambda r: r["beats"]), 1),
    "dribbles (fewer is better)": ("game", hidden(lambda r: r["dri"]), -1),
    "penalties given away": ("game", hidden(lambda r: r["pens"]), -1),
    "first-time pass share": ("ratio", hidden(lambda r: (r["ftp"], r["pa"])), 1),
    # added after the Match Facts proof (docs/04-hidden-counters.md) and the same test
    "line breaks": ("game", hidden(lambda r: r["lb"]), 1),
    "through balls": ("game", hidden(lambda r: r["tb"]), 1),
    "shots in the box": ("game", hidden(lambda r: r["box"]), 1),
    "crosses": ("game", hidden(lambda r: r["crs"]), 1),
    "team conceded": ("game", lambda r: r["gar"], -1),
    "tackle success": ("ratio", lambda r: (r["tm"], r["ta"]), 1),
    "pass accuracy": ("ratio", lambda r: (r["pm"], r["pa"]), 1),
    "save share": ("ratio", lambda r: (r["saves"], r["saves"] + r["conceded"]), 1),
}
SETS = {
    "GK": ["team conceded", "save share", "EA rating"],
    "DEF": ["team conceded", "rating vs teammates", "tackle success", "first-time pass share",
            "dribbles (fewer is better)", "penalties given away"],
    "MID": ["goals + assists", "forward passes", "pass accuracy", "tackle success", "won minus lost",
            "rating vs teammates", "shots in the box", "crosses"],
    "ATK": ["goals + assists", "shots on target", "dribbles", "skill-move beats", "rating vs teammates",
            "line breaks", "through balls"],
    "CB": ["team conceded", "rating vs teammates", "tackle success"],
    "FB": ["rating vs teammates", "tackle success", "forward passes", "interceptions"],
    "CDM": ["tackle success", "won minus lost", "pass accuracy", "rating vs teammates"],
    "CM": ["goals + assists", "won minus lost", "forward passes", "rating vs teammates"],
    "WING": ["goals + assists", "shots on target", "dribbles", "rating vs teammates"],
    "ST": ["goals + assists", "shots on target", "rating vs teammates"],
}


def values(rs: list[dict], metric: str) -> list:
    kind, fn, _ = MET[metric]
    out = []
    for r in rs:
        v = fn(r)
        if v is not None:
            out.append(v)
    return out


def shrink_k(by_person: dict[str, list[float]], minn: int = 3) -> float:
    """Games of 'typical' to add: noise inside a person over real spread between people."""
    pp = {k: v for k, v in by_person.items() if len(v) >= minn}
    if len(pp) < 6:
        return float("nan")
    w = [st.pvariance(v) * len(v) / (len(v) - 1) for v in pp.values()]
    sw = st.mean(w)
    tau2 = st.pvariance([st.mean(v) for v in pp.values()]) - sw / st.mean([len(v) for v in pp.values()])
    return sw / tau2 if tau2 > 0 else float("inf")


def k_for(ctx: Ctx, slot: str, metric: str, cache: dict) -> float:
    if metric == "team conceded":
        return TEAM_K
    key = (slot, metric)
    if key not in cache:
        kind, fn, _ = MET[metric]
        byp: dict[str, list[float]] = collections.defaultdict(list)
        for r in ctx.league:
            if ctx.in_slot(r, slot):
                v = fn(r)
                if v is None:
                    continue
                if kind == "ratio":
                    if not v[1]:
                        continue
                    v = v[0] / v[1]
                byp[r["name"]].append(v)
        k = shrink_k(byp)
        cache[key] = K_CAP if (not math.isfinite(k)) else min(k, K_CAP)
    return cache[key]


def typical(rs: list[dict], metric: str):
    kind, fn, _ = MET[metric]
    vals = values(rs, metric)
    if kind == "game":
        return st.mean(vals), None
    n = sum(a for a, b in vals)
    d = sum(b for a, b in vals)
    return n / d, d / len(vals)


def shrunk(vals: list, metric: str, mu: float, k: float, per_game_den) -> float:
    kind = MET[metric][0]
    if kind == "game":
        return (sum(vals) + k * mu) / (len(vals) + k)
    n = sum(a for a, b in vals)
    d = sum(b for a, b in vals)
    return (n + k * per_game_den * mu) / (d + k * per_game_den)


def raw_value(vals: list, metric: str) -> float:
    if MET[metric][0] == "game":
        return st.mean(vals)
    d = sum(b for a, b in vals)
    return sum(a for a, b in vals) / d if d else float("nan")


# ---------------------------------------------------------------- ranking


def score_people(games: dict[str, list[dict]], slot: str, pri: dict, ks: dict) -> dict[str, dict]:
    """Head-to-head share per number, then the average. games: person -> his rows in slot."""
    mets = SETS[slot]
    v: dict[str, dict[str, float]] = {n: {} for n in games}
    for n, rs in games.items():
        for m in mets:
            vals = values(rs, m)
            if vals:
                mu, pgd = pri[m]
                v[n][m] = shrunk(vals, m, mu, ks[m], pgd) * MET[m][2]
    out = {}
    for n in games:
        ps = {}
        for m in mets:
            if m not in v[n]:
                continue
            others = [v[o][m] for o in games if o != n and m in v[o]]
            if others:
                ps[m] = (sum(1 for o in others if o < v[n][m]) + 0.5 * sum(1 for o in others if o == v[n][m])) / len(others)
        out[n] = {"p": ps, "v": v[n], "score": st.mean(ps.values()) if ps else 0.5}
    return out


def rank_slot(ctx: Ctx, slot: str, cards: int, cache: dict, reps: int = REPS) -> dict:
    mets = SETS[slot]
    everything = [r for r in ctx.ours if ctx.in_slot(r, slot)]
    pool = [r for r in everything if r["club"] in FC27_CLUBS]
    history = collections.Counter(r["name"] for r in everything if r["club"] not in FC27_CLUBS)
    games: dict[str, list[dict]] = collections.defaultdict(list)
    for r in pool:
        games[r["name"]].append(r)
    # "typical" = the regulars' games pooled, so more games weigh more; with fewer
    # than 10 such games it falls back to everyone this season, then to all our games
    regulars = [r for g in games.values() if len(g) >= REGULAR for r in g]
    typical_all = len(pool) < 10
    base_rows = everything if typical_all else regulars if len(regulars) >= 10 else pool
    games = {n: g for n, g in games.items() if len(g) >= LIST_MIN}
    pri, ks = {}, {}
    for m in mets:
        if not values(base_rows, m):
            continue
        pri[m] = typical(base_rows, m)
        ks[m] = k_for(ctx, slot, m, cache)
    mets = [m for m in mets if m in pri]
    if not games or not mets:
        return {"slot": slot, "cards": cards, "people": [], "typical": {}, "metrics": mets}
    base = score_people(games, slot, pri, ks)
    people = []
    for n, g in games.items():
        raw = {m: raw_value(values(g, m), m) for m in mets if values(g, m)}
        above = sum(1 for m in mets if m in base[n]["v"] and base[n]["v"][m] > pri[m][0] * MET[m][2])
        builds = collections.Counter(ARCH.get(r["arch"], r["arch"]) for r in g)
        job = st.mean(r["inter"] + r["clr"] for r in g) if slot in ("DEF", "CB", "FB", "CDM") else None
        people.append(dict(name=n, n=len(g), history=history[n], score=base[n]["score"], p=base[n]["p"], raw=raw, job_actions=job,
                           above=above, checks=len(base[n]["v"]), builds=builds.most_common(3),
                           clubs=collections.Counter(r["club"] for r in g)))
    people.sort(key=lambda r: (-r["score"], -r["n"]))
    # how sure: resample each person's games, recount who is gold
    rng = random.Random(5)
    gold = collections.Counter()
    for _ in range(reps):
        boot = {n: [rng.choice(g) for _ in g] for n, g in games.items()}
        s = score_people(boot, slot, pri, ks)
        order = sorted(s, key=lambda n: (-s[n]["score"], -len(games[n])))
        for n in [n for n in order if len(games[n]) >= GOLD_MIN][:cards]:
            gold[n] += 1
    for r in people:
        r["gold_share"] = 100 * gold[r["name"]] / reps
    return {"slot": slot, "cards": cards, "people": people, "metrics": mets,
            "typical": {m: pri[m][0] for m in mets}, "typical_all": typical_all}


def how_sure(share: float) -> str:
    return "very sure" if share >= 80 else "likely" if share >= 55 else "close call"


def tiers(result: dict) -> dict[str, list]:
    cards = result["cards"]
    people = result["people"]
    gold = [r for r in people if r["n"] >= GOLD_MIN][:cards]
    rest = [r for r in people if r not in gold]
    pad = lambda rows: [rows[i] if i < len(rows) else None for i in range(cards)]
    return {"gold": pad(gold), "silver": pad(rest[:cards]), "bronze": pad(rest[cards:2 * cards])}


def load_primary(path: str | None) -> dict[str, str]:
    """The captain's pins: 'Name = SLOT' per line (GK, DEF, MID, ATK; CB, CDM, ST and so on also work). Optional."""
    pins: dict[str, str] = {}
    if not path:
        return pins
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return pins
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        name, slot = (x.strip() for x in line.split("=", 1))
        slot = {"CB": "DEF", "FB": "DEF", "LB": "DEF", "RB": "DEF", "CDM": "MID", "CM": "MID", "CAM": "MID",
                "WING": "ATK", "LW": "ATK", "RW": "ATK", "ST": "ATK"}.get(slot.upper(), slot.upper())
        if slot in SLOTS:
            pins[LINK.get(name, name)] = slot
    return pins


def assign(results: dict[str, dict], pins: dict[str, str] | None = None):
    """Gold per slot with ONE primary slot per person.

    Everyone starts (gold) in at most one slot; elsewhere he can only be silver or
    bronze. A person who would be gold in several slots keeps the slot where he is
    needed most: the one with the fewest other people holding 5 games, then the
    higher head-to-head score. The captain's pins win. Moving someone promotes the next
    person, which can create a new clash, so it repeats until none are left.
    Returns (tiers per slot, list of moves for the page).
    """
    pins = pins or {}
    eligible = {s: [r for r in res["people"] if r["n"] >= GOLD_MIN] for s, res in results.items()}
    removed: dict[str, set[str]] = {s: set() for s in results}
    forced: dict[str, list[dict]] = {s: [] for s in results}
    for name, slot in pins.items():
        res = results.get(slot)
        mine = [r for r in (res["people"] if res else []) if r["name"] == name]
        if mine:
            forced[slot].append(mine[0])
            for other in results:
                if other != slot:
                    removed[other].add(name)
    moves: list[dict] = []

    def current(slot: str) -> list[dict]:
        cards = results[slot]["cards"]
        rows = forced[slot] + [r for r in eligible[slot] if r["name"] not in removed[slot]
                               and all(r["name"] != f["name"] for f in forced[slot])]
        return rows[:cards]

    for _ in range(50):
        where: dict[str, list[str]] = collections.defaultdict(list)
        for slot in results:
            for r in current(slot):
                where[r["name"]].append(slot)
        clashes = {n: sl for n, sl in where.items() if len(sl) > 1}
        if not clashes:
            break
        for name, slots in clashes.items():
            def need(slot: str):
                rivals = sum(1 for r in eligible[slot] if r["name"] != name and r["name"] not in removed[slot])
                mine = next(r for r in eligible[slot] if r["name"] == name)
                return (rivals, -mine["score"], SLOTS.index(slot))
            keep = min(slots, key=need)
            for slot in slots:
                if slot != keep:
                    removed[slot].add(name)
                    moves.append({"name": name, "keeps": keep, "demoted": slot})
    out = {}
    for slot, res in results.items():
        cards = res["cards"]
        gold = current(slot)
        rest = [r for r in res["people"] if all(r["name"] != g["name"] for g in gold)]
        pad = lambda rows: [rows[i] if i < len(rows) else None for i in range(cards)]
        out[slot] = {"gold": pad(gold), "silver": pad(rest[:cards]), "bronze": pad(rest[cards:2 * cards])}
    return out, moves


CARDS = {"GK": 1, "DEF": 4, "MID": 3, "ATK": 3, "CB": 2, "FB": 2, "CDM": 1, "CM": 2, "WING": 2, "ST": 1}


def played(ctx: Ctx) -> dict[str, dict[str, list[int]]]:
    """person -> slot -> [FC27 games, FC26 games], every game counted, no minimum."""
    out: dict[str, dict[str, list[int]]] = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in ctx.ours:
        for s in SLOTS:
            if ctx.in_slot(r, s):
                out[r["name"]][s][0 if r["club"] in FC27_CLUBS else 1] += 1
    return out


def run_all(rows: list[dict], reps: int = REPS) -> dict[str, dict]:
    ctx = Ctx(rows)
    cache: dict = {}
    return {s: rank_slot(ctx, s, CARDS[s], cache, reps) for s in SLOTS}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    rows = load(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(len(rows), "appearances,", sum(r["ours"] for r in rows), "ours")
    for slot, res in run_all(rows).items():
        print(f"\n== {slot}  numbers: {', '.join(res['metrics'])}")
        for i, r in enumerate(res["people"][:6]):
            tag = "" if r["n"] >= REGULAR else " (new here)"
            print(f"  {i + 1}. {r['name']:18} {r['n']:3d} games  beats {100 * r['score']:3.0f}%  "
                  f"gold in {r['gold_share']:3.0f}/100  ahead on {r['above']}/{r['checks']}{tag}")


if __name__ == "__main__":
    main()
