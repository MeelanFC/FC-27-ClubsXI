"""Our own player score: goals each person added in a game, from what they did. No EA points.

Each action is worth what it was worth in real results (fit on about a thousand other clubs' FC27
league sides, same game, head counts held fixed):

  shooting   a shot in the box 0.42 goals, from outside 0.17 (goals per shot)
  creating   through ball 0.056, line break 0.044, skill-move beat 0.13, foul won 0.07,
             completed pass 0.007 (how much each adds to the team's shot value)
  defending  interception 0.10, ball won 0.07 (fewer goals let in)
  mistakes   ball lost -0.028, failed pass -0.035, penalty given away -0.66
  keeping    save 0.30 (rough: about one in three saved shots would have gone in; not fitted)

Checked on the author's own club league games, which were not used to set the values: the difference in team
scores follows the real goal difference at r = 0.62 (EA's rating sums: 0.51). A person's score in
their odd games matches their even games at r = 0.78. Forwards score higher by the nature of the job,
so people are compared with our average in the same line.

Friendlies have no hidden counters, so they get a reduced score from the labelled numbers only
(shots at 0.33, passes, tackles won as ball won, saves) and are marked as reduced.
"""
from __future__ import annotations

import collections
import html
import json
import statistics as st
from datetime import datetime, timezone

from . import config as _config

OURS = _config.season_club_ids()          # clubs whose games count this season
FC27_TS = _config.season_start()          # first game of the season (0 = all games)
LINK = _config.same_person()              # EA account -> person, one person on two accounts
SHOW: dict[str, str] = {}                 # optional display names
LINE = {'goalkeeper': 'GK', 'defender': 'DEF', 'midfielder': 'MID', 'forward': 'ATK'}


def _ev(p):
    c = collections.Counter()
    for k in ('match_event_aggregate_0', 'match_event_aggregate_1',
              'match_event_aggregate_2', 'match_event_aggregate_3'):
        for part in str(p.get(k) or '').split(','):
            if ':' in part:
                a, b = part.split(':')
                c[int(a)] += int(b)
    return c


def _f(p, k):
    try:
        return float(p.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


# (label, goals per action, count from hidden counters e and the player row p)
FULL = [
    ('shots in the box', 0.42, lambda e, p: e[13] + e[14]),
    ('shots from outside', 0.17, lambda e, p: e[18] + e[19]),
    ('through balls', 0.056, lambda e, p: e[152]),
    ('line breaks', 0.044, lambda e, p: e[8] + e[184] + e[10]),
    ('skill-move beats', 0.13, lambda e, p: e[38]),
    ('fouls won', 0.07, lambda e, p: e[4]),
    ('passes completed', 0.007, lambda e, p: _f(p, 'passesmade')),
    ('interceptions', 0.10, lambda e, p: e[6]),
    ('ball won', 0.07, lambda e, p: e[108] + e[109] + e[110]),
    ('ball lost', -0.028, lambda e, p: e[105] + e[106] + e[107]),
    ('passes failed', -0.035, lambda e, p: _f(p, 'passattempts') - _f(p, 'passesmade')),
    ('penalties given away', -0.66, lambda e, p: e[94]),
    ('saves', 0.30, lambda e, p: _f(p, 'saves')),
]
REDUCED = [
    ('shots', 0.33, lambda e, p: _f(p, 'shots')),
    ('passes completed', 0.007, lambda e, p: _f(p, 'passesmade')),
    ('passes failed', -0.035, lambda e, p: _f(p, 'passattempts') - _f(p, 'passesmade')),
    ('tackles won', 0.07, lambda e, p: _f(p, 'tacklesmade')),
    ('saves', 0.30, lambda e, p: _f(p, 'saves')),
]


def score(p):
    """-> (total, [(label, count, value)], reduced?) for one player row of an EA match."""
    e = _ev(p)
    parts = FULL if e else REDUCED
    items = []
    for label, w, fn in parts:
        n = fn(e, p)
        if n:
            items.append((label, n, w * n))
    return round(sum(v for _, _, v in items), 2), items, not e


def our_games(conn, limit=None):
    """Our FC27 games (league, playoff, friendly), newest first, each player scored."""
    out = []
    for mtype, validity, raw in conn.execute(
            "SELECT match_type, validity, raw_json FROM matches WHERE source='own' "
            "ORDER BY match_timestamp DESC"):
        m = json.loads(raw)
        if int(m.get('timestamp') or 0) < FC27_TS:
            continue
        sides = {}
        for club, pl in (m.get('players') or {}).items():
            rows = []
            for p in pl.values():
                total, items, reduced = score(p)
                rows.append(dict(name=LINK.get(p['playername'], p['playername']) if club in OURS else p['playername'],
                                 line=LINE.get(p.get('pos'), '?'), score=total, items=items, reduced=reduced,
                                 goals=int(_f(p, 'goals')), assists=int(_f(p, 'assists'))))
            sides[club] = sorted(rows, key=lambda r: -r['score'])
        out.append(dict(m=m, type=mtype, validity=validity, sides=sides))
        if limit and len(out) >= limit:
            break
    return out


def season(games):
    """person -> line -> [scores], league and playoff games only (full score)."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for g in games:
        if g['type'] == 'friendlyMatch' or g['validity'] != 'ok':
            continue
        for club, rows in g['sides'].items():
            if club in OURS:
                for r in rows:
                    per[r['name']][r['line']].append(r['score'])
    return per


# ---------------------------------------------------------------- page
CSS = """
.ps .game{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}
.ps .game h3{margin:0 0 6px;font-size:15px}.ps .game small{color:var(--dim)}
.ps table{width:100%}.ps td.why{color:var(--dim);font-size:12px;white-space:normal}
.ps .up{color:var(--good)}.ps .down{color:var(--bad)}
"""


def _show(n):
    return SHOW.get(n, n)


def _why(items, k=3):
    top = sorted(items, key=lambda t: -abs(t[2]))[:k]
    return ', '.join('%s %g (%+.2f)' % (lbl, n, v) for lbl, n, v in top)


def render(conn, n_games=8):
    e = html.escape
    games = our_games(conn)
    per = season(games)
    # season table: average per line against our average in that line
    line_avg = {}
    for ln in ('ATK', 'MID', 'DEF', 'GK'):
        allv = [s for d in per.values() for s in d.get(ln, [])]
        line_avg[ln] = st.mean(allv) if allv else 0.0
    rows = []
    for name, d in per.items():
        for ln, v in d.items():
            if len(v) >= 3 and ln in line_avg:
                rows.append((ln, name, len(v), st.mean(v), st.mean(v) - line_avg[ln]))
    order = {'ATK': 0, 'MID': 1, 'DEF': 2, 'GK': 3}
    rows.sort(key=lambda r: (order[r[0]], -r[4]))
    trs = ''.join('<tr><td>%s</td><td><b>%s</b></td><td class=num>%d</td><td class=num>%+.2f</td>'
                  '<td class="num %s">%+.2f</td></tr>'
                  % (ln, e(_show(n)), k, a, 'up' if d > 0.1 else ('down' if d < -0.1 else ''), d)
                  for ln, n, k, a, d in rows)
    table = ('<div class=wrap><table><thead><tr><th>Line</th><th>Player</th><th class=num>Games</th>'
             '<th class=num>Avg score</th><th class=num>vs our line avg</th></tr></thead><tbody>'
             + trs + '</tbody></table></div>')
    cards = []
    for g in games[:n_games]:
        m = g['m']
        ours = [c for c in g['sides'] if c in OURS]
        if not ours:
            continue
        c = ours[0]
        clubs = m.get('clubs', {})
        opp = [k for k in clubs if k != c]
        name = lambda k: e(((clubs.get(k) or {}).get('details') or {}).get('name') or k)
        gf = (clubs.get(c) or {}).get('goals', '?')
        ga = (clubs.get(c) or {}).get('goalsAgainst', '?')
        when = datetime.fromtimestamp(int(m['timestamp']), timezone.utc).strftime('%Y-%m-%d %H:%M')
        kind = {'leagueMatch': 'league', 'playoffMatch': 'playoff', 'friendlyMatch': 'scrim'}.get(g['type'], g['type'])
        flag = '' if g['validity'] == 'ok' else ' (%s)' % e(g['validity'])
        reduced = any(r['reduced'] for r in g['sides'][c])
        body = ''.join('<tr><td><b>%s</b> <small>%s</small></td><td class=num>%+.2f</td><td class=num>%d / %d</td>'
                       '<td class=why>%s</td></tr>'
                       % (e(_show(r['name'])), r['line'], r['score'], r['goals'], r['assists'], e(_why(r['items'])))
                       for r in g['sides'][c])
        team = sum(r['score'] for r in g['sides'][c])
        oteam = sum(r['score'] for r in g['sides'][opp[0]]) if opp else 0.0
        cards.append('<div class=game><h3>%s %s - %s %s <small>%s, %s%s. Team score %+.1f vs %+.1f%s</small></h3>'
                     '<div class=wrap><table><thead><tr><th>Player</th><th class=num>Score</th>'
                     '<th class=num>G / A</th><th>Biggest parts</th></tr></thead><tbody>%s</tbody></table></div></div>'
                     % (name(c), e(gf), e(ga), name(opp[0]) if opp else '?', when, kind, flag, team, oteam,
                        ' (reduced: scrims have no hidden stats)' if reduced else '', body))
    note = ('<div class=note><b>What the score is.</b> Goals each person added in the game, from what he did, '
            'with no EA points. Every action is worth what it was worth in about 1,100 other clubs\' games: a shot '
            'in the box 0.42 goals, from outside 0.17; through ball 0.06, line break 0.04, skill-move beat 0.13, '
            'foul won 0.07; interception 0.10, ball won 0.07; ball lost -0.03, failed pass -0.04, penalty given '
            'away -0.66; save 0.30 (rough). On our games the team scores follow the real result better than EA\'s '
            'ratings do. Forwards score higher by the nature of the job, so the season table compares each person '
            'with our average in the same line. Goals and assists are shown but not counted: finishing swings a '
            'lot from game to game. Scrims have no hidden stats, so they get a reduced score.</div>')
    return ('<div class=ps><style>' + CSS + '</style><h1>Player scores</h1>'
            '<h2>Latest games</h2>' + ''.join(cards)
            + '<h2>Season, by line</h2><p>League and playoff games, 3 or more in that line.</p>' + table
            + note + '</div>')
