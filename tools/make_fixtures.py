"""Make the synthetic EA test data in tests/fixtures/.

Every match, player, score, time and stat here comes from a random number
generator with a fixed seed. Nothing comes from a real match. The files have
the same shape as real EA responses, so the tests exercise the real code paths.

Run from the project folder:  python tools/make_fixtures.py
"""
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
rng = random.Random(20271)

MAIN, PRACTICE = "100001", "100002"
CAPTAIN_ID = "3000000013"
POS = ("goalkeeper", "defender", "midfielder", "forward")

# Hidden counter codes: any number EA might send. Rows pick a random subset.
CODES = list(range(0, 270))

# Builds that fit each line (archetype ids, docs/00-words-used.md).
BUILDS = {"goalkeeper": ["1", "2"], "defender": ["3", "4", "5", "6", "8", "9"],
          "midfielder": ["6", "7", "8", "9", "10", "11", "12"],
          "forward": ["9", "10", "11", "12", "13"]}

# Made-up squad: name, chance to play a main-club match, chance to play a
# practice-club match, lines with weights, builds per line. Round numbers,
# picked by hand so that every test has something to check.
SQUAD = [
    ("KeeperOne", .8, .8, {"goalkeeper": 1}, {"goalkeeper": ["1", "2"]}),
    ("Captain", .8, .5, {"defender": 1, "midfielder": 1}, {"defender": ["3", "4"], "midfielder": ["7", "8"]}),
    ("BackOne", .8, .5, {"defender": 1}, {"defender": ["4", "5"]}),
    ("HolderOne", .8, .5, {"midfielder": 1}, {"midfielder": ["6", "7"]}),
    ("MidOne", .5, .5, {"midfielder": 1, "forward": 1}, {"midfielder": ["8", "10"], "forward": ["10"]}),
    ("WideOne", .5, .8, {"forward": 1, "midfielder": 1}, {"forward": ["10", "13"], "midfielder": ["12"]}),
    ("Player01", .5, .5, {"forward": 1}, {"forward": ["11", "13"]}),
    ("Player02", .8, .5, {"defender": 1, "midfielder": 1}, {"defender": ["8"], "midfielder": ["11"]}),
    ("Player03", .5, .5, {"forward": 1}, {"forward": ["9", "12"]}),
    ("Player04", .5, 0, {"defender": 1}, {"defender": ["3"]}),
    ("Player05", .5, .5, {"midfielder": 1}, {"midfielder": ["9", "6"]}),
    ("Player06", .5, .5, {"forward": 1}, {"forward": ["13"]}),
    ("Player07", .2, 0, {"defender": 1}, {"defender": ["6"]}),
    ("Player08", .2, .2, {"forward": 1}, {"forward": ["12"]}),
    ("Player09", .2, 0, {"forward": 1}, {"forward": ["11"]}),
    ("Player10", .2, .2, {"forward": 1}, {"forward": ["9"]}),
    ("Player11", 0, .5, {"midfielder": 1}, {"midfielder": ["10"]}),
]
SAME_PERSON = ("Player07", "Player09")   # tests/fixtures/same_person.txt

ROW_KEYS = ['archetypeid', 'assists', 'ballDiveSaves', 'cleansheetsany', 'cleansheetsdef',
            'cleansheetsgk', 'crossSaves', 'gameTime', 'goals', 'goalsconceded',
            'goodDirectionSaves', 'losses', 'match_event_aggregate_0', 'match_event_aggregate_1',
            'match_event_aggregate_2', 'match_event_aggregate_3', 'mom', 'namespace', 'parrySaves',
            'passattempts', 'passesmade', 'pos', 'punchSaves', 'rating', 'realtimegame',
            'realtimeidle', 'redcards', 'reflexSaves', 'saves', 'SCORE', 'secondsPlayed', 'shots',
            'tackleattempts', 'tacklesmade', 'userResult', 'vproattr', 'vprohackreason', 'wins',
            'playername']
KIT = ["kitId", "seasonalTeamId", "seasonalKitId", "selectedKitType", "customKitId",
       "customAwayKitId", "customThirdKitId", "customKeeperKitId", "kitColor1", "kitColor2",
       "kitColor3", "kitColor4", "kitAColor1", "kitAColor2", "kitAColor3", "kitAColor4",
       "kitThrdColor1", "kitThrdColor2", "kitThrdColor3", "kitThrdColor4", "dCustomKit",
       "crestColor", "crestAssetId"]

ids = {"Captain": CAPTAIN_ID}
used_ids = {CAPTAIN_ID}
rival_no = [0]
club_no = [0]


def pid(name):
    if name not in ids:
        while True:
            n = str(rng.randint(3000000100, 3999999999))
            if n not in used_ids:
                break
        ids[name] = n
        used_ids.add(n)
    return ids[name]


def club_name(cid):
    return {MAIN: "Home FC", PRACTICE: "Practice FC"}.get(cid, "Rival Club %02d" % (int(cid) - 900000))


def details(cid):
    kit = {"stadName": "Club Stadium"}
    kit.update({k: "1000" for k in KIT})
    return {"name": club_name(cid), "clubId": int(cid), "regionId": 1000, "teamId": 100,
            "customKit": kit}


def counters(pos):
    if rng.random() < 0.03:
        return ""
    picks = sorted(rng.sample(CODES, rng.randint(22, 45)))
    top = {"goalkeeper": 4, "defender": 8, "midfielder": 12, "forward": 8}[pos]
    return ",".join("%d:%d" % (c, rng.randint(1, top)) for c in picks)


def row(name, pos, build, length, seconds):
    passes = rng.randint(6, 40) if seconds else 0
    tackles = rng.randint(0, 10) if seconds and pos != "goalkeeper" else 0
    shots = {"forward": rng.randint(0, 6), "midfielder": rng.randint(0, 3),
             "defender": rng.randint(0, 1), "goalkeeper": 0}[pos] if seconds else 0
    saves = rng.randint(0, 7) if pos == "goalkeeper" and seconds else 0
    r = {k: "0" for k in ROW_KEYS}
    r.update({
        "archetypeid": build, "pos": pos, "playername": name, "namespace": "2",
        "vproattr": "NH", "secondsPlayed": str(seconds), "gameTime": str(seconds),
        "passattempts": str(passes), "passesmade": str(int(passes * rng.uniform(.6, .95))),
        "tackleattempts": str(tackles), "tacklesmade": str(rng.randint(0, tackles)),
        "shots": str(shots), "saves": str(saves),
        "realtimegame": str(seconds // 6 + rng.randint(5, 60)) if seconds else "0",
        "realtimeidle": str(rng.randint(5, 80)) if seconds else "0",
        "match_event_aggregate_0": counters(pos) if seconds else "",
        "match_event_aggregate_1": "", "match_event_aggregate_2": "",
        "match_event_aggregate_3": "", "rating": "0.00",
    })
    if saves:
        for k in ("ballDiveSaves", "reflexSaves", "parrySaves"):
            r[k] = str(rng.randint(0, saves))
    return r


def spread_goals(players, n):
    live = [p for p in players.values() if int(p["secondsPlayed"]) > 0]
    if not live:
        return
    weight = {"forward": 6, "midfielder": 3, "defender": 1, "goalkeeper": 0.01}
    for _ in range(n):
        s = rng.choices(live, [weight[p["pos"]] for p in live])[0]
        s["goals"] = str(int(s["goals"]) + 1)
        s["shots"] = str(max(int(s["shots"]), int(s["goals"])))
        if len(live) > 1 and rng.random() < 0.6:
            a = rng.choice([p for p in live if p is not s])
            a["assists"] = str(int(a["assists"]) + 1)


def our_side(slot):
    side = []
    for name, p_main, p_prac, lines, builds in SQUAD:
        if rng.random() < (p_main if slot == MAIN else p_prac):
            side.append((name, lines, builds))
    names = [s[0] for s in side]
    if all(n in names for n in SAME_PERSON):
        side = [s for s in side if s[0] != SAME_PERSON[1]]
    return side[:9]


def make_match(our_cid, rival_cid, ts, forced=()):
    length = rng.randint(5380, 5720)
    side = our_side(our_cid)
    have = {s[0] for s in side}
    for name in forced:
        if name not in have:
            entry = next(s for s in SQUAD if s[0] == name)
            side.append((entry[0], entry[3], entry[4]))
    # the practice club scores more here, so the practice-gap code has a gap to remove
    ours = [4, 10, 18, 20, 18, 16, 14] if our_cid == PRACTICE else [14, 22, 22, 18, 12, 7, 5]
    goals = {our_cid: rng.choices(range(7), ours)[0],
             rival_cid: rng.choices(range(7), [14, 22, 22, 18, 12, 7, 5])[0]}
    players = {our_cid: {}, rival_cid: {}}
    for name, lines, builds in side:
        pos = rng.choices(list(lines), list(lines.values()))[0]
        build = rng.choice(builds[pos])
        roll = rng.random()
        short = our_cid == PRACTICE and roll < 0.14
        secs = 0 if roll < 0.04 else rng.randint(int(length * .3), int(length * .85)) if short else length
        players[our_cid][pid(name)] = row(name, pos, build, length, secs)
    for _ in range(rng.randint(2, 7)):
        rival_no[0] += 1
        name = "Rival%03d" % rival_no[0]
        pos = rng.choices(POS, [1, 3, 3, 3])[0]
        roll = rng.random()
        secs = 0 if roll < 0.03 else rng.randint(int(length * .3), int(length * .85)) if roll < 0.12 else length
        players[rival_cid][pid(name)] = row(name, pos, rng.choice(BUILDS[pos]), length, secs)
    clubs = {}
    for cid in (rival_cid, our_cid):
        other = rival_cid if cid == our_cid else our_cid
        gf, ga = goals[cid], goals[other]
        res = "1" if gf > ga else "2" if gf < ga else "4"
        clubs[cid] = {"date": str(ts), "gameNumber": "0", "goals": str(gf), "goalsAgainst": str(ga),
                      "losses": "1" if res == "2" else "0", "matchType": "1", "result": res,
                      "score": str(gf), "season_id": "0", "TEAM": "100",
                      "ties": "1" if res == "4" else "0", "winnerByDnf": "0",
                      "wins": "1" if res == "1" else "0", "details": details(cid)}
        pl = players[cid]
        spread_goals(pl, gf)
        for p in pl.values():
            p["SCORE"] = str(gf)
            p["goalsconceded"] = str(ga)
            p["wins"] = clubs[cid]["wins"]
            p["losses"] = clubs[cid]["losses"]
            if ga == 0:
                p["cleansheetsany"] = "1"
                p["cleansheetsdef"] = "1" if p["pos"] == "defender" else "0"
                p["cleansheetsgk"] = "1" if p["pos"] == "goalkeeper" else "0"
            if int(p["secondsPlayed"]) > 0:
                lost = int(p["passattempts"]) - int(p["passesmade"])
                r = (6.6 + 0.6 * int(p["goals"]) + 0.3 * int(p["assists"]) - 0.08 * lost
                     + (0.6 if p["pos"] == "defender" else 0.0) + rng.uniform(-0.6, 0.6))
                p["rating"] = "%.2f" % max(4.0, min(10.0, r))
    best = max(goals, key=goals.get)
    live = [p for p in players[best].values() if int(p["secondsPlayed"]) > 0]
    if live:
        rng.choice(live)["mom"] = "1"
    aggregate = {}
    for cid, pl in players.items():
        tot = {}
        for k in ROW_KEYS:
            if k == "playername":
                continue
            v = 0.0
            for p in pl.values():
                try:
                    v += float(p[k])
                except ValueError:
                    pass
            tot[k] = round(v, 1) if k == "rating" else int(v)
        aggregate[cid] = tot
    return {"matchId": str(rng.randint(10 ** 11, 10 ** 12 - 1)), "timestamp": ts,
            "timeAgo": {"number": rng.randint(1, 20), "unit": rng.choice(["days", "weeks"])},
            "clubs": clubs, "players": players, "aggregate": aggregate}


def times(n):
    """n made-up kickoff times, spread over a year and over the whole clock."""
    start = 1700000000
    return sorted((start + rng.randint(0, 365 * 86400) for _ in range(n)), reverse=True)


def season(our_cid, need):
    matches = []
    for i, ts in enumerate(times(10)):
        club_no[0] += 1
        forced = need[i::10]
        matches.append(make_match(our_cid, str(900000 + club_no[0]), ts, forced))
    # the newest match has no ghost on our side (tests change one row on purpose)
    for i, m in enumerate(matches):
        if all(int(p["secondsPlayed"]) > 0 for p in m["players"][our_cid].values()):
            matches[0]["timestamp"], m["timestamp"] = m["timestamp"], matches[0]["timestamp"]
            for x in (matches[0], m):
                for c in x["clubs"].values():
                    c["date"] = str(x["timestamp"])
            break
    return sorted(matches, key=lambda m: m["timestamp"], reverse=True)


def members(matches, cid, extra):
    seen = []
    for m in matches:
        for p in m["players"][cid].values():
            if p["playername"] not in seen:
                seen.append(p["playername"])
    names = seen + extra
    rng.shuffle(names)
    out = []
    for name in names:
        gp = rng.randint(1, 60)
        fav = rng.choice(POS)
        mem = {"name": name, "gamesPlayed": str(gp), "winRate": str(rng.randint(20, 80)),
               "goals": str(rng.randint(0, gp)), "assists": str(rng.randint(0, gp)),
               "cleanSheetsDef": str(rng.randint(0, gp // 4)),
               "cleanSheetsGK": str(rng.randint(0, gp // 4) if fav == "goalkeeper" else 0),
               "shotSuccessRate": str(rng.randint(0, 70)), "passesMade": str(gp * rng.randint(8, 25)),
               "passSuccessRate": str(rng.randint(60, 90)), "ratingAve": "%.1f" % rng.uniform(6, 8),
               "tacklesMade": str(gp * rng.randint(0, 6)), "tackleSuccessRate": str(rng.randint(10, 50)),
               "proName": "Pro", "proPos": str(rng.choice((0, 3, 5, 7, 10, 12, 14, 18))),
               "proStyle": "0", "proHeight": str(rng.randint(165, 195)), "proNationality": "1",
               "proOverall": str(rng.randint(70, 95)), "manOfTheMatch": str(rng.randint(0, gp // 5)),
               "redCards": str(rng.randint(0, 2))}
        mem["proOverallStr"] = mem["proOverall"]
        mem["prevGoals"] = str(rng.randint(0, 3))
        for i in range(1, 11):
            mem["prevGoals%d" % i] = str(rng.randint(0, 3))
        mem["favoritePosition"] = fav
        out.append(mem)
    return {"members": out, "positionCount": {p: rng.randint(0, 9) for p in POS}}


def record(matches):
    w, d, l = rng.randint(20, 60), rng.randint(3, 15), rng.randint(10, 40)
    gp = w + d + l
    r = {"clubId": MAIN, "bestDivision": None, "bestFinishGroup": None}
    for i in range(1, 7):
        r["finishesInDivision%dGroup1" % i] = "0"
    r.update({"gamesPlayed": str(gp), "gamesPlayedPlayoff": "0", "goals": str(rng.randint(gp, gp * 3)),
              "goalsAgainst": str(rng.randint(gp // 2, gp * 2)), "promotions": str(rng.randint(0, 5)),
              "relegations": str(rng.randint(0, 3)), "losses": str(l), "ties": str(d), "wins": str(w)})
    for i in range(10):
        r["lastMatch%d" % i] = str(rng.choice((1, 2, 4))) if i < 6 else "-1"
    rivals = [c for m in matches for c in m["clubs"] if c != MAIN]
    for i in range(10):
        r["lastOpponent%d" % i] = rivals[i] if i < len(rivals) else "-1"
    r.update({"wstreak": "0", "unbeatenstreak": "0", "skillRating": "1500", "reputationtier": "1",
              "leagueAppearances": str(gp)})
    return [r]


def write(name, data):
    (OUT / name).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


main = season(MAIN, [s[0] for s in SQUAD if s[1] > 0])
practice = season(PRACTICE, [s[0] for s in SQUAD if s[2] > 0])
write("matches_main_league.json", main)
write("matches_practice_league.json", practice)
write("members_main.json", members(main, MAIN, ["Player12", "Player13"]))
write("members_practice.json", members(practice, PRACTICE, ["Player14"]))
write("overallstats_main.json", record(main))
print("fixtures written to", OUT)
