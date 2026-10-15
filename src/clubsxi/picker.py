"""Tonight's picker: from whoever is online, who plays where, which spots go to AI, bench order.

Built from a design review (docs/07-player-score-and-testing.md). Everything is in
"team goal difference per game". Rebuilt from the database after every new match.

  gain(person, group) = value of a human over AI there + his fit there - cost of moving him there

Sizes from the walk-forward tests (docs/07-player-score-and-testing.md), agreed with
an outside reviewer: each game predicted from earlier games only, on one club's games and on ~90 other clubs.

* human value: a human keeper is worth +0.98 over AI, any outfield human +0.29 (1.2x the review's
        numbers; humans on each side were the only part that clearly predicted results).
* fit   ATK and MID: half of his own player score (goals added a game, no EA points) above our
        line average, pulled toward the average with 16 (ATK) or 8 (MID) games of "average".
        Only in his main line (most games), so the score never pulls people out of DEF or GK.
        DEF and GK: the score could not tell people apart once club strength was removed, so
        no score; 0.001 a game played in that line breaks ties (experience first).
* move cost: from the share of his own league games played in that group. Under 10% -0.6,
        10-25% -0.2, 25%+ 0; times 1.5 into GK and DEF, 1.0 MID, 0.5 ATK (half the review's, which
        was too big on our games). Under 3 games in all: 0 where his build fits the line, else
        0.2 times the same multiplier, at most 0.25. A build that does not fit a line cost about
        0.9 goals a player on other clubs. Into goal keeps the full review size (-1.8 / -0.6),
        so an outfielder never beats the AI keeper.
        An outfielder never goes in goal while a real keeper (25%+ of games in goal) is online.

The choice is exact over every placement. Anyone whose best spot is worth less than AI sits
out, so unfamiliar spots go to AI. Everyone else is bench or reserve at his best spot.
"""
from __future__ import annotations

import collections
import html
import json
import math
import statistics as st
import time
import urllib.parse

from . import config as _config

OURS = _config.season_club_ids()      # clubs whose games count this season (main, practice)
FC27_TS = _config.season_start()      # first game of the season (0 = all games)
LINK = _config.same_person()          # EA account -> person, one person on two accounts
SHOW: dict[str, str] = {}             # optional display names
GROUP = {'goalkeeper': 'GK', 'defender': 'DEF', 'midfielder': 'MID', 'forward': 'ATK'}
GROUPS = ('GK', 'DEF', 'MID', 'ATK')
SHAPE = {'GK': 1, 'DEF': 4, 'MID': 3, 'ATK': 3}
K_CAP = 15          # never pull with more than 15 games of "average"
WIN = 2.5           # one stat can move a person at most 2.5 real-spread units
MIN_LEAGUE = 4      # league people need 4+ games in a group to measure noise and spread
HUMAN = {'GK': 0.98, 'DEF': 0.29, 'MID': 0.29, 'ATK': 0.29}
MOVE_STEPS = ((0.10, 0.6), (0.25, 0.2))      # (share below, cost)
NEW_GAMES, NEW_COST, NEW_CAP = 3, 0.2, 0.25   # newcomers: under 3 games in all
SKILL_K = {'ATK': 16, 'MID': 8}              # games of "average" mixed in (club-centred, other clubs)
SKILL_SIZE = 0.5                              # player score counts at half its goal value
SECOND_LINE = 0.1                             # a known line that is not his main one, times MOVE_MULT
RECENT_DAYS, RECENT_WEIGHT = 30, 2               # recent games count double for where people play
EXPERIENCE = 0.001                            # goals per game played in that line (tie-break)
MOVE_MULT = {'GK': 1.5, 'DEF': 1.5, 'MID': 1.0, 'ATK': 0.5}
KEEPER_SHARE = 0.25
ACTIVE_DAYS = 7
# review round 3: fit predicts held-out results no better than none; a quarter weight
# keeps it as a tie-break so it cannot overrule human value or where people usually play
FIT_WEIGHT = 0.25


def ev(p):
    c = collections.Counter()
    for k in ('match_event_aggregate_0', 'match_event_aggregate_1',
              'match_event_aggregate_2', 'match_event_aggregate_3'):
        for part in str(p.get(k) or '').split(','):
            if ':' in part:
                a, b = part.split(':')
                c[int(a)] += int(b)
    return c


def f(p, k):
    try:
        return float(p.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def rows_of(m):
    players, clubs = m['players'], m['clubs']
    allp = [p for pl in players.values() for p in pl.values()]
    longest = max((int(p.get('secondsPlayed') or 0) for p in allp), default=0)
    if longest <= 0:
        return []
    heads = {c: len(pl) for c, pl in players.items()}
    out = []
    for club, pl in players.items():
        if club not in clubs:
            continue
        opp = [c for c in players if c != club]
        gf, ga = int(clubs[club].get('goals') or 0), int(clubs[club].get('goalsAgainst') or 0)
        for p in pl.values():
            if int(p.get('secondsPlayed') or 0) < 0.9 * longest or p.get('pos') not in GROUP:
                continue
            e = ev(p)
            ours = club in OURS
            name = LINK.get(p['playername'], p['playername']) if ours else club + ':' + p['playername']
            out.append(dict(match=m['matchId'], ts=int(m['timestamp']), club=club, ours=ours, name=name,
                            grp=GROUP[p['pos']], hid=bool(e), rating=f(p, 'rating'),
                            gpa=f(p, 'goals') + f(p, 'assists'), beats=e[38], fwon=e[4], box=e[13] + e[14],
                            pm=f(p, 'passesmade'),
                            tm=f(p, 'tacklesmade'), ta=f(p, 'tackleattempts'), dri=e[174], ftp=e[143],
                            pa=f(p, 'passattempts'), saves=f(p, 'saves'), conc=f(p, 'goalsconceded'),
                            gd=gf - ga, ga=ga, hd=heads[club] - (heads[opp[0]] if opp else 0)))
    return out


# per-game value of each stat (None = unknown in that game)
STAT = {
    'EA rating': lambda r: r['rating'],
    'goals+assists': lambda r: r['gpa'],
    'skill beats': lambda r: r['beats'] if r['hid'] else None,
    'tackle success': lambda r: r['tm'] / r['ta'] if r['ta'] else None,
    'team conceded': lambda r: r['gar'],
    'fewer dribbles': lambda r: r['dri'] if r['hid'] else None,
    'first-time pass share': lambda r: (r['ftp'] / r['pa']) if (r['hid'] and r['pa']) else None,
    'save share': lambda r: r['saves'] / (r['saves'] + r['conc']) if (r['saves'] + r['conc']) else None,
    'fouls won': lambda r: r['fwon'] if r['hid'] else None,
    'shots in the box': lambda r: r['box'] if r['hid'] else None,
    'pass accuracy': lambda r: r['pm'] / r['pa'] if r['pa'] else None,
}
SIGN = {'team conceded': -1, 'fewer dribbles': -1}
MODEL = {'GK': ['team conceded', 'save share'],
         'DEF': ['tackle success', 'team conceded', 'fewer dribbles', 'first-time pass share'],
         # no EA match rating: EA builds it partly from the result.
         # Picked by the other-games test on other clubs' league players with 6+ games in the group.
         'MID': ['shots in the box', 'skill beats', 'team conceded'],
         'ATK': ['goals+assists', 'skill beats']}


def vals(rs, s):
    return [v for v in (STAT[s](r) for r in rs) if v is not None]


def cov(x, y):
    mx, my = st.mean(x), st.mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)


def load(records):
    """records: (source, match_type, validity, raw match dict). Finished league games only."""
    own, lg, seen = [], [], set()
    for source, mtype, validity, m in records:
        j = dict(source=source, type=mtype, validity=validity)
        if m['matchId'] in seen or j.get('validity', 'ok') != 'ok' or j.get('type') != 'leagueMatch':
            continue
        seen.add(m['matchId'])
        rs = rows_of(m)
        if j['source'] == 'own':
            own += [r for r in rs if r['ours']]
        elif int(m['timestamp']) >= FC27_TS:
            lg += [r for r in rs if not r['ours']]
    # head-count adjustment (each extra human vs the opponent), fitted on every finished side
    sides = list({(r['match'], r['club']): (r['hd'], r['ga'], r['gd']) for r in own + lg}.values())
    mx = st.mean(v[0] for v in sides) if sides else 0.0
    sxx = sum((v[0] - mx) ** 2 for v in sides)
    b_ga = sum((v[0] - mx) * v[1] for v in sides) / sxx if sxx else 0.0
    b_gd = sum((v[0] - mx) * v[2] for v in sides) / sxx if sxx else 0.0
    mga = st.mean(v[1] for v in sides) if sides else 0.0
    for r in own + lg:
        r['gar'] = r['ga'] - (mga + b_ga * (r['hd'] - mx))   # conceded vs expected for the head count
        r['gda'] = r['gd'] - b_gd * r['hd']
    return own, lg


def build(own, lg):
    lp = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in lg:
        lp[r['grp']][r['name']].append(r)
    meta, table = {}, collections.defaultdict(dict)
    for g, stats in MODEL.items():
        people = {n: sorted(rs, key=lambda r: r['ts']) for n, rs in lp[g].items() if len(rs) >= MIN_LEAGUE}
        ks, taus, lmean = {}, {}, {}
        for s in stats:
            per = [v for v in (vals(rs, s) for rs in people.values()) if len(v) >= 2]
            if len(per) < 2:
                # a new database: too few other-club people to measure noise yet
                ks[s], taus[s] = float(K_CAP), 1.0
                lmean[s] = st.mean(x for v in per for x in v) if per else 0.0
                continue
            w = st.mean(st.variance(v) for v in per)
            tau2 = st.pvariance([st.mean(v) for v in per]) - w / st.mean(len(v) for v in per)
            tau2 = max(tau2, w / K_CAP)
            ks[s], taus[s] = w / tau2, math.sqrt(tau2)
            lmean[s] = st.mean(x for v in per for x in v)
        # beta = team goal difference per 1 unit of the composite, measured on OTHER games:
        # his composite in half A vs team GD in half B (and B vs A), divided by how much the
        # composite itself repeats (A vs B), so noise in the composite does not shrink it.
        ca, cb, ya, yb = [], [], [], []
        for rs in people.values():
            halves = (rs[0::2], rs[1::2])
            zs = []
            for h in halves:
                z = 0.0
                for s in stats:
                    v = vals(h, s)
                    z += SIGN.get(s, 1) * ((st.mean(v) - lmean[s]) / taus[s] if v else 0.0) / len(stats)
                zs.append(z)
            ca.append(zs[0]); cb.append(zs[1])
            ya.append(st.mean(r['gda'] for r in halves[0])); yb.append(st.mean(r['gda'] for r in halves[1]))
        enough = len(ca) >= 3
        c_true = cov(ca, cb) if enough else 0.0
        c_pred = (cov(ca, yb) + cov(cb, ya)) / 2 if enough else 0.0
        beta = max(c_pred / c_true, 0.0) if c_true > 0 else 0.0
        how = 'learned on other clubs (other-half games)'
        if g == 'GK':
            # too few league keepers to learn a slope; the conceded part is already in goals
            beta = taus['team conceded'] * len(stats)
            how = 'goals conceded directly (too few league keepers to learn)'
        mine = collections.defaultdict(list)
        for r in own:
            if r['grp'] == g:
                mine[r['name']].append(r)
        mus = {s: st.mean([v for rs in mine.values() for v in vals(rs, s)] or [0.0]) for s in stats}
        meta[g] = dict(stats=stats, goals_per_unit=round(beta, 3), slope_from=how,
                       league_people=len(people),
                       repeat_cov=round(c_true, 3), predict_cov=round(c_pred, 3),
                       k_games_of_average={s: round(ks[s], 1) for s in stats},
                       our_average={s: round(mus[s], 3) for s in stats})
        for n, rs in mine.items():
            z = var = sure = 0.0
            for s in stats:
                v = vals(rs, s)
                k = ks[s]
                m = (sum(v) + k * mus[s]) / (len(v) + k)
                z += max(-WIN, min(WIN, SIGN.get(s, 1) * (m - mus[s]) / taus[s])) / len(stats)
                var += math.sqrt(k / (len(v) + k)) / len(stats)   # stats may move together: add SDs, not variances
                sure += (len(v) / (len(v) + k)) / len(stats)
            score, sd = z * beta * FIT_WEIGHT, var * beta * FIT_WEIGHT
            p = 0.5 * (1 + math.erf(score / (sd * math.sqrt(2)))) if sd > 0 else 0.5
            table[n][g] = dict(score=round(score, 3), games=len(rs), sure=round(sure, 2),
                               p_above=round(p, 2), last=max(r['ts'] for r in rs))
    for n in table:
        for g in MODEL:
            table[n].setdefault(g, dict(score=0.0, games=0, sure=0.0, p_above=0.5, last=None))
    return dict(meta=dict(groups=meta,
                          our_games=len({r['match'] for r in own if r['ts'] >= FC27_TS}),
                          league_games=len({r['match'] for r in lg}),
                          zero_games_rule='score 0 (our average there), sure 0, p_above 0.5',
                          score_units='goal difference per game vs our average player in that group'),
                people={n: table[n] for n in sorted(table)})




# ---------------------------------------------------------------- where people usually play
def familiarity(records):
    """person -> {group: games}, last played, from our FC27 league games (finished or not).
    Games in the last RECENT_DAYS (before our latest game) count RECENT_WEIGHT times, so the page
    follows where people play now."""
    games = collections.defaultdict(collections.Counter)
    last = {}
    records = list(records)
    newest = max((int(m.get('timestamp') or 0) for s_, t_, v_, m in records
                  if s_ == 'own' and t_ == 'leagueMatch'), default=0)
    for source, mtype, validity, m in records:
        if source != 'own' or mtype != 'leagueMatch':
            continue
        players = m.get('players') or {}
        allp = [p for pl in players.values() for p in pl.values()]
        longest = max((int(p.get('secondsPlayed') or 0) for p in allp), default=0)
        for club, pl in players.items():
            if club not in OURS:
                continue
            for p in pl.values():
                if p.get('pos') not in GROUP or int(p.get('secondsPlayed') or 0) < 0.5 * longest:
                    continue
                n = LINK.get(p['playername'], p['playername'])
                recent = newest - int(m['timestamp']) <= RECENT_DAYS * 86400
                games[n][GROUP[p['pos']]] += RECENT_WEIGHT if recent else 1
                last[n] = max(last.get(n, 0), int(m['timestamp']))
    return games, last


BUILD_LINE = {'Shot Stopper': 'GK', 'Sweeper Keeper': 'GK', 'Progressor': 'DEF', 'Boss': 'DEF',
              'Marauder': 'DEF', 'Disruptor': 'MID', 'Recycler': 'MID', 'Maestro': 'MID', 'Creator': 'MID',
              'Spark': 'ATK', 'Magician': 'ATK', 'Finisher': 'ATK', 'Target': 'ATK'}


def move_cost(counts, builds=None):
    """counts: {group: games}. builds: {group: his build there} (used only for newcomers)."""
    total = sum(counts.values())
    out = {}
    for g in GROUPS:
        if total < NEW_GAMES:
            fits = BUILD_LINE.get((builds or {}).get(g)) == g
            out[g] = 0.0 if fits else round(min(NEW_CAP, NEW_COST * MOVE_MULT[g]), 2)
            continue
        share = counts.get(g, 0) / total
        cost = next((c for lim, c in MOVE_STEPS if share < lim), 0.0)
        # into goal keeps the review's full size: halved, an outfielder would beat the AI keeper
        out[g] = round(cost * MOVE_MULT[g] * (2 if g == 'GK' else 1), 2)
    return out


# ---------------------------------------------------------------- the pick
def pick(online, fit, cost, keepers):
    """Exact best placement. online: names. fit/cost: {name: {group: x}}. keepers: names allowed in goal
    while any of them is online."""
    people = list(dict.fromkeys(online))
    keeper_on = any(n in keepers for n in people)

    def gain(n, g):
        if g == 'GK' and keeper_on and n not in keepers:
            return None
        return HUMAN[g] + fit.get(n, {}).get(g, 0.0) - cost.get(n, {}).get(g, 0.0)

    cap = tuple(SHAPE[g] for g in GROUPS)
    best = {(0, 0, 0, 0): (0.0, ())}
    for n in people:
        nxt = {}
        for state, (score, plan) in best.items():
            opts = [('OUT', 0.0)]
            for i, g in enumerate(GROUPS):
                v = gain(n, g)
                if state[i] < cap[i] and v is not None:
                    opts.append((g, v))
            for g, add in opts:
                ns = list(state)
                if g != 'OUT':
                    ns[GROUPS.index(g)] += 1
                ns = tuple(ns)
                cand = (score + add, plan + (g,))
                if ns not in nxt or cand[0] > nxt[ns][0] + 1e-9:
                    nxt[ns] = cand
        best = nxt
    state, (score, plan) = max(best.items(), key=lambda kv: kv[1][0])
    lineup = {g: [] for g in GROUPS}
    out = []
    for n, g in zip(people, plan):
        (out if g == 'OUT' else lineup[g]).append(n)
    for g in GROUPS:
        lineup[g].sort(key=lambda n: -fit.get(n, {}).get(g, 0.0))

    def best_spot(n):
        opts = [(gain(n, g), g) for g in GROUPS if gain(n, g) is not None]
        return max(opts) if opts else (0.0, 'MID')
    out.sort(key=lambda n: -best_spot(n)[0])
    return dict(lineup=lineup, ai={g: SHAPE[g] - len(lineup[g]) for g in GROUPS},
                out=[(n, best_spot(n)[1], best_spot(n)[0]) for n in out], score=round(score, 2))


# ---------------------------------------------------------------- one call for the web page
def build_all(records):
    records = list(records)
    own, lg = load(records)
    own = [r for r in own if r['club'] in OURS]
    table = build(own, lg)
    counts, last = familiarity(records)
    people = sorted(counts, key=lambda n: -last.get(n, 0))
    keepers = {n for n in people if counts[n]['GK'] / max(1, sum(counts[n].values())) >= KEEPER_SHARE}
    rating, build_of = ratings(records)
    lean = build_of.pop('_lean', {})
    skill = build_of.pop('_skill', {})
    rating_b = build_of.pop('_recent', {})
    cost = {n: move_cost(counts[n], build_of.get(n)) for n in people}
    # a second line he knows (25%+ of his games) is not quite home: small cost, so weak evidence
    # does not shuffle people out of their main line
    for n in people:
        if sum(counts[n].values()) >= NEW_GAMES:
            home = max(GROUPS, key=lambda g: counts[n][g])
            for g in GROUPS:
                if g != home and cost[n][g] == 0.0:
                    cost[n][g] = round(SECOND_LINE * MOVE_MULT[g], 2)
    # fit: half his player score above our line average, only in his main line (ATK, MID; the score
    # cannot rank DEF or GK, and counting it elsewhere would pull good players out of defence and goal),
    # plus a little for experience there
    main = {n: max(GROUPS, key=lambda g: counts[n][g]) for n in people}
    fit = {n: {g: round(SKILL_SIZE * skill.get(n, {}).get(g, 0.0) * (g == main[n]) + EXPERIENCE * counts[n][g], 4)
               for g in GROUPS} for n in people}
    return dict(table=table, counts=counts, last=last, people=people, fit=fit, cost=cost, keepers=keepers,
                rating=rating, build=build_of, lean=lean, rating_b=rating_b)


ARCH = {'1': 'Shot Stopper', '2': 'Sweeper Keeper', '3': 'Progressor', '4': 'Boss', '5': 'Disruptor',
        '6': 'Marauder', '7': 'Recycler', '8': 'Maestro', '9': 'Creator', '10': 'Spark',
        '11': 'Magician', '12': 'Finisher', '13': 'Target'}
RATING_K = {'ATK': 16, 'MID': 8, 'DEF': 20, 'GK': 20}   # games of "our line average" mixed in, for the card
RATING_MID = 6.5      # our average in a line


def ratings(records):
    """Our own rating per person per line, from player_score (no EA points), on a 10-point scale:
    6.5 = our average in that line, one point = one spread of our players' averages there.
    Few games are pulled toward 6.5. Also each person's most-used build per line."""
    from . import player_score as ps
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    arch = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    role = collections.defaultdict(list)     # attackers: (box shots, assists + through balls + passes/10)
    timed = collections.defaultdict(lambda: collections.defaultdict(list))
    for source, mtype, validity, m in records:
        if source != 'own' or mtype not in ('leagueMatch', 'playoffMatch') or validity != 'ok':
            continue
        if int(m.get('timestamp') or 0) < FC27_TS:
            continue
        for club, pl in (m.get('players') or {}).items():
            if club not in OURS:
                continue
            for p in pl.values():
                g = GROUP.get(p.get('pos'))
                if not g:
                    continue
                n = LINK.get(p['playername'], p['playername'])
                total, _, reduced = ps.score(p)
                if not reduced:
                    per[n][g].append(total)
                    timed[n][g].append((int(m['timestamp']), total))
                    if g == 'ATK':
                        e = ps._ev(p)
                        role[n].append((e[13] + e[14], ps._f(p, 'assists') + e[152] + ps._f(p, 'passesmade') / 10))
                arch[n][g][str(p.get('archetypeid') or '')] += 1
    out = collections.defaultdict(dict)
    recent = collections.defaultdict(dict)   # same rating, last RECENT_DAYS counted double (version B)
    skill = collections.defaultdict(dict)    # raw goals a game above our line average, pulled in (ATK, MID)
    for g in GROUPS:
        allv = [v for d in per.values() for v in d.get(g, [])]
        if not allv:
            continue
        mu = st.mean(allv)
        shr = {n: (sum(d[g]) + RATING_K[g] * mu) / (len(d[g]) + RATING_K[g]) for n, d in per.items() if d.get(g)}
        if g in SKILL_K:
            for n, d in per.items():
                if d.get(g):
                    skill[n][g] = (sum(d[g]) + SKILL_K[g] * mu) / (len(d[g]) + SKILL_K[g]) - mu
        # spread of the regulars' plain averages (5+ games), so pulled-in averages are not over-stretched
        big = [st.mean(d[g]) for d in per.values() if len(d.get(g, [])) >= 5]
        sd = st.pstdev(big) if len(big) >= 3 else 0.3
        sd = sd or 0.3
        for n, v in shr.items():
            out[n][g] = round(max(1.0, min(9.9, RATING_MID + (v - mu) / sd)), 1)
        newest = max(t for d in timed.values() for x in d.values() for t, _ in x)
        for n, d in timed.items():
            if d.get(g):
                w = [(RECENT_WEIGHT if newest - t <= RECENT_DAYS * 86400 else 1, x) for t, x in d[g]]
                v = (sum(a * x for a, x in w) + RATING_K[g] * mu) / (sum(a for a, _ in w) + RATING_K[g])
                recent[n][g] = round(max(1.0, min(9.9, RATING_MID + (v - mu) / sd)), 1)
    builds = {}
    for n, d in arch.items():
        allc = sum(d.values(), collections.Counter())
        builds[n] = {g: ARCH.get((d[g] or allc).most_common(1)[0][0], '') for g in GROUPS if (d[g] or allc)}
    # striker lean: box shots a game against making chances a game, each against our attackers' spread;
    # above 0 shoots more than he creates (ST), below 0 creates more (wing). Pulled to 0 with few games.
    lean = {}
    big = {n: v for n, v in role.items() if len(v) >= 3}
    if len(big) >= 3:
        sh = [st.mean(x for x, _ in v) for v in big.values()]
        cr = [st.mean(y for _, y in v) for v in big.values()]
        ms, ss = st.mean(sh), st.pstdev(sh) or 1
        mc, sc = st.mean(cr), st.pstdev(cr) or 1
        for n, v in role.items():
            k = len(v) / (len(v) + RATING_K['ATK'])
            z = (st.mean(x for x, _ in v) - ms) / ss - (st.mean(y for _, y in v) - mc) / sc
            lean[n] = round(z * k, 2)
    builds['_lean'] = lean
    builds['_skill'] = dict(skill)
    builds['_recent'] = dict(recent)
    return dict(out), builds


def records_from_db(conn):
    for source, mtype, validity, raw in conn.execute(
            "SELECT source, match_type, validity, raw_json FROM matches"):
        try:
            m = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if int(m.get('timestamp') or 0) >= FC27_TS - 400 * 86400:
            yield source, mtype, validity, m


# ---------------------------------------------------------------- page
CSS = """
.pk .pitch{display:grid;gap:10px;margin-top:12px}
.pk .row{display:flex;justify-content:center;gap:8px}
.pk .card{flex:0 0 calc((100% - 24px) / 4);max-width:200px;min-width:0;background:var(--panel);
 border:1px solid var(--line);border-radius:10px;padding:6px;display:flex;flex-direction:column;gap:4px}
.pk .pos{text-align:center;font-size:11px;font-weight:700;letter-spacing:.12em;color:var(--dim)}
.pk .p{border-radius:7px;padding:3px 4px;text-align:center;color:#1b1b1b;display:flex;flex-direction:column;
 justify-content:center;height:54px;line-height:1.25;overflow:hidden}
.pk .p.gold,.pk .card>.p.ai{height:74px}
.pk .p i{font-style:normal;font-size:clamp(8px,1.6vw,10px);font-weight:700;letter-spacing:.08em;opacity:.75;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .p b{font-size:clamp(10px,2.4vw,15px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pk .p em{font-style:normal;font-weight:700;font-size:clamp(11px,2.6vw,16px)}
.pk .p.gold{background:linear-gradient(160deg,#f6e27a,#c9a227)}.pk .p.gold em{font-size:clamp(13px,3.2vw,20px)}
.pk .p.silver{background:linear-gradient(160deg,#eef0f3,#a9afb8)}
.pk .p.bronze{background:linear-gradient(160deg,#e9b98a,#a8652e)}
.pk .p.none{background:transparent;border:1px dashed var(--line)}
.pk .p.ai{background:transparent;color:var(--dim);border:1px dashed var(--line)}
"""


AB_CSS = """
.pk input[name=ab]{display:none}
.pk .abbar{display:flex;gap:8px;margin:10px 0}
.pk .abbar label{border:1px solid var(--line);border-radius:16px;padding:5px 14px;cursor:pointer;font-size:13px}
.pk #ab-a:checked~.abbar label[for=ab-a],.pk #ab-b:checked~.abbar label[for=ab-b]{background:var(--accent);color:#000;
 border-color:var(--accent);font-weight:700}
.pk .aba,.pk .abb{display:none}.pk #ab-a:checked~.aba,.pk #ab-b:checked~.abb{display:block}
.pk .abnote{display:none}
.pk .top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px}
.pk .top h1{margin:0}.pk .top .abbar{margin:0}
.pk details{color:var(--dim);font-size:13px;margin:0 0 4px}.pk details summary{cursor:pointer}
.pk{--blue:#2F5BB7;--gold:#f2c94c;--silver:#c9d1dc;--bronze:#d08a4a}
.pk .pitch{gap:clamp(6px,1.4vh,14px);margin-top:6px;padding:clamp(8px,1.6vh,16px) 8px;border-radius:14px;
 background:repeating-linear-gradient(180deg,#0f2a1c 0 12.5%,#11301f 12.5% 25%);border:1px solid #1f4a33}
.pk .row{flex-wrap:nowrap;gap:clamp(6px,1vw,12px);margin:0}
.pk .xc{flex:none;width:min(230px,calc((100vw - 80px) / 4));height:calc((100dvh - 190px) / 4);min-height:96px;
 max-height:150px;display:flex;flex-direction:column;background:#141a26;border:1px solid #2a3550;border-radius:12px;
 overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.pk .xc .xh{display:flex;justify-content:space-between;align-items:center;background:var(--blue);color:#fff;
 padding:2px 10px;font-size:clamp(11px,1.5vh,14px);font-weight:800;letter-spacing:.06em}
.pk .xc .xh .rt{background:var(--gold);color:#1a1300;border-radius:6px;padding:0 6px;font-size:clamp(12px,1.7vh,16px)}
.pk .xc .gold{flex:1;display:flex;flex-direction:column;justify-content:center;padding:2px 10px;
 border-left:4px solid var(--gold);min-height:0}
.pk .xc .gn{color:#fff;font-weight:800;font-size:clamp(13px,2.1vh,19px);line-height:1.15;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis}
.pk .xc .gb{color:#aab6cc;font-size:clamp(10px,1.4vh,13px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .xc .sv{display:flex;gap:6px;align-items:center;padding:3px 10px;background:#1b2333;border-top:1px solid #2a3550;
 border-left:4px solid var(--silver);color:#dfe5ee;font-size:clamp(11px,1.6vh,14px);min-width:0}
.pk .xc .sv b{flex:0 1 auto;min-width:55%;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pk .xc .sv em{flex:1 1 0;min-width:0;text-align:right;font-style:normal;color:#aab6cc;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.pk .xc .sv.bz{border-left-color:var(--bronze)}
.pk .xc.ai .gn{color:#8d98ad}
"""


def _show(n):
    return SHOW.get(n, n)


def _word(r):
    if r is None:
        return 'no rated games there'
    if r >= 7.5:
        return 'strong here'
    if r >= 6.9:
        return 'leans good'
    if r > 6.1:
        return 'about average'
    return 'below our average'


BENCH = {'GK': 1, 'DEF': 2, 'MID': 2, 'ATK': 2}


def depth(data, now=None):
    """Best XI from people seen lately, then each other person's best spot: bench (next in) or reserve."""
    now = now or time.time()
    people, last, fit, cost = data['people'], data['last'], data['fit'], data['cost']
    active = [n for n in people if now - last.get(n, 0) <= ACTIVE_DAYS * 86400]
    res = pick(active, fit, cost, data['keepers'])
    starters = {n for v in res['lineup'].values() for n in v}

    def gain(n, g):
        return HUMAN[g] + fit.get(n, {}).get(g, 0.0) - cost.get(n, {}).get(g, 0.0)
    rest = collections.defaultdict(list)
    for n in people:
        if n in starters:
            continue
        g = max(GROUPS, key=lambda g: gain(n, g) if (g != 'GK' or n in data['keepers']) else -9)
        rest[g].append(n)
    bench, reserve = {}, {}
    for g in GROUPS:
        seen = sorted((n for n in rest[g] if n in active), key=lambda n: -gain(n, g))
        bench[g] = seen[:BENCH[g]]
        reserve[g] = seen[BENCH[g]:] + sorted((n for n in rest[g] if n not in active),
                                              key=lambda n: -last.get(n, 0))
    return dict(lineup=res['lineup'], ai=res['ai'], bench=bench, reserve=reserve, active=active)


ST_BUILDS = {'Finisher', 'Target'}
CB_BUILDS = {'Progressor', 'Boss'}
SPOTS = {'ATK': ['LW', 'ST', 'RW'], 'DEF': ['LB', 'CB', 'CB', 'RB']}


def load_positions(path=None):
    """name = LW|ST|RW|W|CB|LB|RB|FB from config/positions.txt (or CLUBSXI_POSITIONS)."""
    import os
    from pathlib import Path
    paths = [path, os.environ.get('CLUBSXI_POSITIONS'), '/config/positions.txt',
             str(Path(__file__).resolve().parents[2] / 'config' / 'positions.txt')]
    for p in paths:
        if p and os.path.exists(p):
            out = {}
            for line in open(p, encoding='utf-8'):
                line = line.split('#', 1)[0].strip()
                if '=' in line:
                    n, v = (x.strip() for x in line.split('=', 1))
                    if v.upper() in ('LW', 'ST', 'RW', 'W', 'CB', 'LB', 'RB', 'FB'):
                        out[LINK.get(n, n)] = v.upper()
            return out
    return {}


def role(n, g, build, pins):
    """The kind of spot a person plays in a line: ST or W up front, CB or FB at the back."""
    pin = pins.get(n)
    if g == 'ATK':
        if pin in ('LW', 'RW', 'W'):
            return 'W'
        if pin == 'ST':
            return 'ST'
        return 'ST' if build in ST_BUILDS else 'W'
    if g == 'DEF':
        if pin in ('LB', 'RB', 'FB'):
            return 'FB'
        if pin == 'CB':
            return 'CB'
        return 'CB' if build in CB_BUILDS else 'FB'
    return g


def place(starters, g, build, pins, lean=None):
    """Put a line's starters into named spots (LW ST RW / LB CB CB RB): own side pins first, then by role.
    Up front, the most striker-like (box shots against making chances) is placed first, so with two
    striker builds he takes ST. Stats cannot tell full backs from centre backs (no better than chance
    on other clubs), so the back four goes by build. LW / RW and LB / RB are not in the data."""
    labels = SPOTS.get(g)
    if not labels:
        return starters, [g] * len(starters)
    slots = [None] * len(labels)
    want = {'LW': 'W', 'RW': 'W', 'ST': 'ST', 'LB': 'FB', 'RB': 'FB', 'CB': 'CB'}
    people = [n for n in starters if n]
    for n in list(people):                       # exact pins (LW, RW, ST, LB, RB, CB)
        p = pins.get(n)
        if p in labels:
            for i, lab in enumerate(labels):
                if lab == p and slots[i] is None:
                    slots[i] = n
                    people.remove(n)
                    break
    if g == 'ATK' and lean:
        people.sort(key=lambda n: -lean.get(n, 0.0))
    for n in list(people):                       # then by role
        r = role(n, g, build(n, g), pins)
        for i, lab in enumerate(labels):
            if slots[i] is None and want[lab] == r:
                slots[i] = n
                people.remove(n)
                break
    for n in people:                             # anyone left takes a free spot
        i = slots.index(None)
        slots[i] = n
    return slots, labels


# ---------------------------------------------------------------- version B: the captain's rules
# Rules a captain set in plain words, all in rating points (6.5 = our average in that line):
#  1. Full-back spots go to full-back builds, centre-back spots to Boss / Progressor.
#  2. Close ratings are a tie: recent form first (last 30 days count double), then experience.
#  3. A versatile player (a quarter of his games outside defence) can shift from CB to full back for free.
#  4. Pick for the whole team: the exact search puts each person where the team loses least.
#  5. Off his natural spot only when clearly better: another line he knows costs 0.5 points,
#     a line he has under 3 games in costs 2 points.
#  6. Where the captain does not know, the data decides.
SLOTS_B = (('GK', 'GK', 1), ('CB', 'DEF', 2), ('FB', 'DEF', 2), ('MID', 'MID', 3), ('ST', 'ATK', 1), ('W', 'ATK', 2))
HUMAN_B = {'GK': 10.0, 'DEF': 3.0, 'MID': 3.0, 'ATK': 3.0}     # any human first (worth far more than any rating gap)
FIT_B = {'GK': {'Shot Stopper', 'Sweeper Keeper'}, 'CB': {'Boss', 'Progressor'}, 'FB': {'Marauder'},
         'ST': {'Finisher', 'Target'}, 'W': {'Spark', 'Magician', 'Creator'}}
OTHER_LINE_B, NEW_LINE_B, UNKNOWN_B = 0.5, 2.0, 6.0


def gain_b(n, slot, data, keeper_on):
    line = dict((s_, l) for s_, l, _ in SLOTS_B)[slot]
    if line == 'GK' and keeper_on and n not in data['keepers']:
        return None
    counts = data['counts'][n]
    r = data['rating_b'].get(n, {}).get(line)
    v = HUMAN_B[line] + ((r if r is not None else UNKNOWN_B) - RATING_MID)
    home = max(GROUPS, key=lambda g: counts[g]) if sum(counts.values()) else None
    b = data['build'].get(n, {}).get(line, '')
    natural = BUILD_LINE.get(b) == line and counts[line] >= 0.25 * sum(counts.values())   # e.g. a full back who also plays MID
    if line != home and not natural:
        v -= OTHER_LINE_B if counts[line] >= 3 else NEW_LINE_B * MOVE_MULT[line]   # a stranger costs more at the back
    if line == 'GK' and n not in data['keepers']:
        v -= 5.0
    b = data['build'].get(n, {}).get(line, '')
    if slot in FIT_B and b not in FIT_B[slot]:
        if slot == 'FB' and b in FIT_B['CB']:
            v -= 1.0                               # rule 1: a Boss plays full back only when no full back is free
        elif slot == 'CB' and b in FIT_B['FB']:
            v -= 0.5
        elif slot in ('ST', 'W') and b in FIT_B['ST'] | FIT_B['W']:
            v -= 0.2
        else:
            v -= 1.0
    return v + 0.01 * counts[line]


def pick_b(data, now=None):
    now = now or time.time()
    active = [n for n in data['people'] if now - data['last'].get(n, 0) <= ACTIVE_DAYS * 86400]
    keeper_on = any(n in data['keepers'] for n in active)
    caps = tuple(c for _, _, c in SLOTS_B)
    names = [s_ for s_, _, _ in SLOTS_B]
    best = {tuple(0 for _ in caps): (0.0, ())}
    for n in active:
        nxt = {}
        for state, (score, plan) in best.items():
            opts = [('OUT', 0.0)]
            for i, s_ in enumerate(names):
                v = gain_b(n, s_, data, keeper_on)
                if state[i] < caps[i] and v is not None and v > 0:
                    opts.append((s_, v))
            for s_, add in opts:
                ns = list(state)
                if s_ != 'OUT':
                    ns[names.index(s_)] += 1
                ns = tuple(ns)
                cand = (score + add, plan + (s_,))
                if ns not in nxt or cand[0] > nxt[ns][0] + 1e-9:
                    nxt[ns] = cand
        best = nxt
    _, (score, plan) = max(best.items(), key=lambda kv: kv[1][0])
    lineup = {s_: [] for s_ in names}
    for n, s_ in zip(active, plan):
        if s_ != 'OUT':
            lineup[s_].append(n)
    for s_ in names:
        lineup[s_].sort(key=lambda n: -gain_b(n, s_, data, keeper_on))
    starters = {n for v in lineup.values() for n in v}
    # backups: each other active person at his best slot, best first
    pool = collections.defaultdict(list)
    for n in active:
        if n in starters:
            continue
        opts = [(gain_b(n, s_, data, keeper_on), s_) for s_ in names if gain_b(n, s_, data, keeper_on) is not None]
        if opts:
            v, s_ = max(opts)
            pool[s_].append((v, n))
    for s_ in names:
        pool[s_] = [n for v, n in sorted(pool[s_], reverse=True)]
    return dict(lineup=lineup, pool=pool, active=active, keeper_on=keeper_on)


def render_b(data, now=None):
    e = html.escape
    d = pick_b(data, now)
    build = lambda n, g: data['build'].get(n, {}).get(g, '')
    rate = lambda n, g: data['rating_b'].get(n, {}).get(g)

    def person(n, g, tier, cover=False):
        if not n:
            return '<div class="p none"></div>'
        r = rate(n, g)
        tag = ('COVER · ' if cover else '') + (build(n, g).upper() or '-')
        return ('<div class="p %s"><i>%s</i><b title="%s">%s</b><em>%s</em></div>'
                % (tier, e(tag), e(_show(n)), e(_show(n)), '%.1f' % r if r is not None else '-'))
    layout = {'ATK': [('LW', 'W', 0), ('ST', 'ST', 0), ('RW', 'W', 1)], 'MID': [('MID', 'MID', i) for i in range(3)],
              'DEF': [('LB', 'FB', 0), ('CB', 'CB', 0), ('CB', 'CB', 1), ('RB', 'FB', 1)], 'GK': [('GK', 'GK', 0)]}
    # one person, one place: starters in their spot; everyone else once, at the
    # spot where he adds most that still has room, silver on every card before any bronze
    everyone_on = {n for v in d['lineup'].values() for n in v}
    room = {s_: 2 * c for s_, _, c in SLOTS_B}
    room['GK'] = 2
    placed = collections.defaultdict(list)
    left = [n for n in d['active'] if n not in everyone_on]
    names = [s_ for s_, _, _ in SLOTS_B]

    def ok(n, s_):
        return gain_b(n, s_, data, d['keeper_on']) is not None and (s_ == 'GK') == (n in data['keepers'])
    for depth_ in (1, 2):                  # silver on every card first, then bronze; best total for the team
        caps = tuple(room[s_] // 2 for s_ in names)
        best = {tuple(0 for _ in caps): (0.0, ())}
        for n in left:
            nxt = {}
            for state, (score, plan) in best.items():
                for k, s_ in [(-1, 'OUT')] + list(enumerate(names)):
                    if k >= 0 and (state[k] >= caps[k] or not ok(n, s_)):
                        continue
                    ns = tuple(c + (i == k) for i, c in enumerate(state))
                    cand = (score + (0 if k < 0 else 10 + gain_b(n, s_, data, d['keeper_on'])), plan + (s_,))
                    if ns not in nxt or cand[0] > nxt[ns][0] + 1e-9:
                        nxt[ns] = cand
            best = nxt
        plan = max(best.values(), key=lambda x: x[0])[1]
        got = [(n, s_) for n, s_ in zip(left, plan) if s_ != 'OUT']
        for n, s_ in sorted(got, key=lambda x: -gain_b(x[0], x[1], data, d['keeper_on'])):
            placed[s_].append(n)
        left = [n for n in left if n not in {m for m, _ in got}]
    done = {n for v in placed.values() for n in v}
    home = lambda n: max(GROUPS, key=lambda g: data['counts'][n][g]) if sum(data['counts'][n].values()) else None
    covered = {n for n in done if home(n) != dict((s_, l) for s_, l, _ in SLOTS_B)[next(s_ for s_ in placed if n in placed[s_])]}
    rows = []
    for g in ('ATK', 'MID', 'DEF', 'GK'):
        cards = []
        under = {}
        for s_ in {s_ for _, s_, _ in layout[g]}:
            idx = [i for _, t, i in layout[g] if t == s_]
            for k, n in enumerate(placed[s_]):
                under.setdefault((s_, idx[k % len(idx)]), []).append(n)
        for lab, s_, i in layout[g]:
            st_ = d['lineup'][s_][i] if i < len(d['lineup'][s_]) else None
            cards.append(hero(lab, g, st_, under.get((s_, i), []), covered, data['build'], rate))
        rows.append('<div class=row>%s</div>' % ''.join(cards))
    return '<div class=pitch>' + ''.join(rows) + '</div>'


def hero(lab, g, gold, subs, covered, builds, rate):
    """One flat card: position and rating on the blue bar, the starter big, backups in thin rows below."""
    e = html.escape
    build = lambda n: builds.get(n, {}).get(g, '')
    r = rate(gold, g) if gold else None
    out = ('<div class="xc%s"><div class=xh><span>%s</span>%s</div>'
           % ('' if gold else ' ai', lab, '<span class=rt>%.1f</span>' % r if r is not None else ''))
    out += ('<div class=gold><div class=gn title="%s">%s</div><div class=gb>%s</div></div>'
            % ((e(_show(gold)), e(_show(gold)), e(build(gold) or '-')) if gold else ('AI', 'AI', 'no one free')))
    for k, n in enumerate(list(subs)[:2]):
        if not n:
            continue
        rr = rate(n, g)
        tag = build(n) or '-'
        out += ('<div class="sv%s" title="%s"><b>%s</b><em>%s%s</em></div>'
                % (' bz' if k else '', e(tag), e(_show(n)), e(tag), ' · %.1f' % rr if rr is not None else ''))
    return out + '</div>'


def render(data, now=None):
    now = now or time.time()
    e = html.escape
    d = depth(data, now)
    build = lambda n, g: data['build'].get(n, {}).get(g, '')

    def person(n, g, tier, cover=False):
        if not n:
            return '<div class="p none"></div>'
        r = data['rating'].get(n, {}).get(g)
        tag = ('COVER · ' if cover else '') + (build(n, g).upper() or '-')
        return ('<div class="p %s"><i>%s</i><b title="%s">%s</b><em>%s</em></div>'
                % (tier, e(tag), e(_show(n)), e(_show(n)), '%.1f' % r if r is not None else '-'))

    pins = load_positions()
    want = {'LW': 'W', 'RW': 'W', 'ST': 'ST', 'LB': 'FB', 'RB': 'FB', 'CB': 'CB'}

    def fits(n, g, label, starter):
        if label in want:
            return role(n, g, build(n, g), pins) == want[label]
        return bool(starter) and build(starter, g) == build(n, g)

    rows = []
    for g in ('ATK', 'MID', 'DEF', 'GK'):
        starters, labels = place(list(d['lineup'][g]) + [None] * d['ai'][g], g, build, pins, data.get('lean'))
        under = [[] for _ in starters]
        rest = list(d['bench'][g] + d['reserve'][g])
        for depth_ in (1, 2):      # silver round, then bronze round
            take, rest = rest[:len(starters)], rest[len(starters):]
            for n in take:
                open_ = [i for i in range(len(starters)) if len(under[i]) < depth_]
                same = [i for i in open_ if fits(n, g, labels[i], starters[i])]
                under[(same or open_)[0]].append(n)
        # empty slots: cover from people whose best line is elsewhere but who play here at least a quarter
        # of their games (moving them there cost almost nothing in the data); marked as cover
        shown = set(n for n in starters if n) | set(n for u in under for n in u)
        everyone_on = set(n for v in d['lineup'].values() for n in v)
        cover = sorted((n for n in d['active'] if n not in shown and n not in everyone_on
                        and data['counts'][n][g] >= 3 and data['cost'][n][g] <= round(SECOND_LINE * MOVE_MULT[g], 2)
                        and (g != 'GK' or n in data['keepers'])),
                       key=lambda n: -(data['fit'].get(n, {}).get(g, 0.0) - data['cost'][n][g]))
        covered = set()
        for depth_ in (1, 2):
            for i in range(len(starters)):
                if len(under[i]) < depth_ and cover:
                    pool = [n for n in cover if fits(n, g, labels[i], starters[i])] or cover
                    n = pool[0]
                    cover.remove(n)
                    under[i].append(n)
                    covered.add(n)
        # starters from other lines can cover here too: into an empty slot, or in place
        # of a backup with a lower rating here; same rules as cover (a quarter of his games here, keepers only
        # in goal); marked as cover
        rate = lambda n: data['rating'].get(n, {}).get(g)
        extra = sorted((n for n in everyone_on if n not in d['lineup'][g] and rate(n) is not None
                        and data['counts'][n][g] >= 3 and data['cost'][n][g] <= round(SECOND_LINE * MOVE_MULT[g], 2)
                        and (g != 'GK' or n in data['keepers'])), key=lambda n: -rate(n))
        for n in extra:
            empty = [i for i in range(len(starters)) if len(under[i]) < 2]
            if empty:
                i = ([i for i in empty if fits(n, g, labels[i], starters[i])] or empty)[0]
                under[i].append(n)
            else:
                i, j = min(((i, j) for i in range(len(starters)) for j in range(len(under[i]))),
                           key=lambda ij: rate(under[ij[0]][ij[1]]) or 0)
                if (rate(under[i][j]) or 0) >= rate(n):
                    continue
                under[i][j] = n
            under[i].sort(key=lambda m: -(rate(m) or 0))
            covered.add(n)
        cards = []
        for lab, st_, subs in zip(labels, starters, under):
            cards.append(hero(lab, g, st_, subs, covered, data['build'],
                              lambda n, g: data['rating'].get(n, {}).get(g)))
        rows.append('<div class=row>%s</div>' % ''.join(cards))
    head = ('<p>Gold starts, silver is next in, bronze after that. '
            'The number is our own average rating in that line (6.5 = our average), no EA points. '
            'League and playoff games only, no scrims. COVER = usually plays another line but plays here a '
            'quarter of his games or more.</p>')
    a = '<div class=pitch>' + ''.join(rows) + '</div>'
    b = render_b(data, now)
    tabs = ('<input type=radio name=ab id=ab-b checked><input type=radio name=ab id=ab-a>'
            '<div class=top><h1>Best XI</h1><div class=abbar><label for=ab-b>B: captain\'s rules</label>'
            '<label for=ab-a>A: by the numbers</label></div></div><details><summary>How this works</summary>'
            + head + '</details>'
            '<div class=abb><p class=abnote>B: full backs and centre backs by build; a player moves off his natural '
            'spot only when clearly better (more than 0.5) elsewhere; close calls go to recent form, then '
            'experience; a versatile CB can shift to full back; the whole team is picked together. '
            'Ratings here count the last 30 days double.</p>' + b + '</div>'
            '<div class=aba><p class=abnote>A: the tested formula (humans first, stay near your usual line, '
            'the rating only breaks ties in attack and midfield).</p>' + a + '</div>')
    return '<div class=pk><style>' + CSS + AB_CSS + '</style>' + tabs + '</div>'
