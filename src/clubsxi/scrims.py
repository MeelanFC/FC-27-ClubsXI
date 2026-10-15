"""Scrim scorecard: score our club-vs-club scrims on habits, not just the result.

A scrim is a match where both sides are our clubs (main club vs practice club).
Everything comes from EA's own match stats, so nobody has to count anything.

Each scrim hands out 7 points:
- Result: 2 for a win, 1 each for a draw. Goals still matter, just not alone.
- Five habits, 1 point each to the side that did better (half each on a tie):
  passing (share of passes completed), tackling (share of tackles won),
  defence (fewest shots let in), finishing (goals per shot),
  team goals (share of goals that had an assist).
EA leaves the hidden ball won / ball lost counters out of friendlies, so
giveaways cannot be scored.

Players get night awards from all of that night's scrims pooled. A night runs
from noon to noon in CLUBSXI_TIMEZONE, so games after midnight stay on the same night.
"""
from __future__ import annotations

import collections
import datetime
import html
from zoneinfo import ZoneInfo

from . import config as _config

OURS = _config.our_club_ids()     # every club id in CLUBSXI_CLUB_IDS
LINK = _config.same_person()      # EA account -> person (one person, two EA accounts)


def num(p: dict, key: str) -> float:
    try:
        return float(p.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


TZ = ZoneInfo(_config.timezone_name())   # CLUBSXI_TIMEZONE, default UTC
HABITS = [  # key, label, what it means
    ("passing", "Passing", "share of passes completed"),
    ("tackling", "Tackling", "share of tackles won"),
    ("defence", "Defence", "fewest shots let in"),
    ("finishing", "Finishing", "goals per shot"),
    ("teamgoals", "Team goals", "share of goals that had an assist"),
]
MIN_PASSES, MIN_TACKLES = 20, 5   # night totals needed for the passer / tackler awards


STYLE = """
.scr h1{font-size:20px;margin:0 0 4px}.scr h2{font-size:16px;margin:28px 0 6px;color:var(--text);text-transform:none;letter-spacing:0}
.scr .sub,.scr .aw span,.scr .when,.scr .who{color:var(--dim)}.scr .night{font-size:16px;margin:4px 0}
.scr .aw{padding-left:18px;margin:6px 0 10px}
.scr .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.scr .sc{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.scr table{width:100%;border-collapse:collapse;font-size:13px}
.scr th,.scr td{padding:3px 4px;text-align:right;border:0;white-space:nowrap;text-transform:none;letter-spacing:0}
.scr th:first-child,.scr td:first-child{text-align:left;color:var(--dim)}
.scr td.w{color:var(--good);font-weight:700}.scr tr.tot td{border-top:1px solid var(--line);font-weight:700;color:var(--text)}
.scr .who{font-size:12px;margin-top:8px}.scr .when{font-size:12px}
.scr .paste{width:100%;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.4 ui-monospace,Consolas,monospace}
"""


def ratio(a: float, b: float) -> float:
    return a / b if b else 0.0


def is_scrim(match: dict) -> bool:
    clubs = set(match.get("clubs", {}))
    return len(clubs) == 2 and clubs <= OURS


def side(match: dict, club: str) -> dict:
    c = match["clubs"][club]
    players = []
    for p in match["players"].get(club, {}).values():
        if int(p.get("secondsPlayed") or 0) <= 0:
            continue
        players.append(dict(
            name=LINK.get(p["playername"], p["playername"]), pos=p.get("pos", ""),
            goals=num(p, "goals"), assists=num(p, "assists"), shots=num(p, "shots"),
            pm=num(p, "passesmade"), pa=num(p, "passattempts"),
            tm=num(p, "tacklesmade"), ta=num(p, "tackleattempts"),
            rating=num(p, "rating")))
    t = {k: sum(p[k] for p in players) for k in ("shots", "pm", "pa", "tm", "ta", "assists")}
    goals = int(c.get("goals") or 0)
    return dict(
        club=club, name=c.get("details", {}).get("name") or club, goals=goals, players=players,
        habits=dict(passing=ratio(t["pm"], t["pa"]), tackling=ratio(t["tm"], t["ta"]),
                    finishing=ratio(goals, t["shots"]),
                    teamgoals=ratio(min(t["assists"], goals), goals)),
        totals=t)


def score(match: dict) -> dict:
    a, b = (side(match, c) for c in sorted(match["clubs"]))
    a["habits"]["defence"], b["habits"]["defence"] = -b["totals"]["shots"], -a["totals"]["shots"]
    pts = {a["club"]: 0.0, b["club"]: 0.0}
    if a["goals"] > b["goals"]:
        pts[a["club"]] += 2
    elif b["goals"] > a["goals"]:
        pts[b["club"]] += 2
    else:
        pts[a["club"]] += 1
        pts[b["club"]] += 1
    winners = {}
    for key, _, _ in HABITS:
        va, vb = a["habits"][key], b["habits"][key]
        if abs(va - vb) < 1e-9:
            pts[a["club"]] += 0.5
            pts[b["club"]] += 0.5
            winners[key] = None
        else:
            w = a if va > vb else b
            pts[w["club"]] += 1
            winners[key] = w["club"]
    return dict(id=match["matchId"], ts=int(match["timestamp"]), sides=[a, b], points=pts, winners=winners)


def night_of(ts: int) -> datetime.date:
    return (datetime.datetime.fromtimestamp(ts, TZ) - datetime.timedelta(hours=12)).date()


def awards(scrims: list[dict]) -> list[tuple[str, str, str]]:
    tot: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for s in scrims:
        for sd in s["sides"]:
            for p in sd["players"]:
                for k in ("goals", "assists", "pm", "pa", "tm", "ta", "rating"):
                    tot[p["name"]][k] += p[k]
                tot[p["name"]]["games"] += 1
    out = []
    passers = [(ratio(t["pm"], t["pa"]), n) for n, t in tot.items() if t["pa"] >= MIN_PASSES]
    if passers:
        v, n = max(passers)
        out.append(("Best passer", n, f"{v:.0%} of {int(tot[n]['pa'])} passes"))
    tacklers = [(ratio(t["tm"], t["ta"]), n) for n, t in tot.items() if t["ta"] >= MIN_TACKLES]
    if tacklers:
        v, n = max(tacklers)
        out.append(("Best tackler", n, f"won {int(tot[n]['tm'])} of {int(tot[n]['ta'])} tackles"))
    if tot:
        v, n = max((ratio(t["rating"], t["games"]), n) for n, t in tot.items())
        out.append(("Top rated", n, f"EA match rating {v:.1f} on average"))
        v, n = max((t["assists"], n) for n, t in tot.items())
        if v:
            out.append(("Most assists", n, f"{int(v)} assists"))
    return out


def scored(matches) -> list[dict]:
    """Score every scrim among these raw EA match objects, oldest first."""
    seen, out = set(), []
    for m in matches:
        if m["matchId"] in seen or not is_scrim(m):
            continue
        seen.add(m["matchId"])
        out.append(score(m))
    return sorted(out, key=lambda s: s["ts"])


def by_night(scrims: list[dict]) -> dict:
    nights: dict = collections.defaultdict(list)
    for s in scrims:
        nights[night_of(s["ts"])].append(s)
    return dict(sorted(nights.items(), reverse=True))


def night_points(scrims: list[dict]) -> dict[str, float]:
    pts: collections.Counter = collections.Counter()
    for s in scrims:
        pts.update(s["points"])
    return pts


def fmt_habit(key: str, v: float) -> str:
    if key == "defence":
        return f"{-v:.0f} shots"
    if key == "finishing":
        return f"{v:.2f}"
    return f"{v:.0%}"


def pts(v: float) -> str:
    return f"{v:g}"


def discord(night: datetime.date, scrims: list[dict]) -> str:
    names = {sd["club"]: sd["name"] for s in scrims for sd in s["sides"]}
    tally = night_points(scrims)
    goals = collections.Counter()
    for s in scrims:
        for sd in s["sides"]:
            goals[sd["club"]] += sd["goals"]
    lines = [f"**Scrim scorecard, {night:%a %b %d}** ({len(scrims)} scrims)"]
    for c in sorted(tally, key=lambda c: -tally[c]):
        lines.append(f"{names[c]}: **{pts(tally[c])} pts** ({goals[c]} goal{'' if goals[c] == 1 else 's'})")
    for key, label, _ in HABITS:
        w = collections.Counter(s["winners"][key] for s in scrims if s["winners"][key])
        if w:
            c, n = w.most_common(1)[0]
            lines.append(f"- {label}: {names[c]} won it {n} of {len(scrims)}")
    lines.append("")
    for title, n, why in awards(scrims):
        lines.append(f"{title}: {n} ({why})")
    return "\n".join(lines)


def body(scrims: list[dict]) -> str:
    e = html.escape
    parts = []
    for night, ss in by_night(scrims).items():
        tally = night_points(ss)
        names = {sd["club"]: sd["name"] for s in ss for sd in s["sides"]}
        head = " &nbsp;vs&nbsp; ".join(f"{e(names[c])} <b>{pts(tally[c])}</b>" for c in sorted(tally))
        cards = []
        for s in ss:
            a, b = s["sides"]
            rows = [f"<tr><td>Result</td><td>{a['goals']}</td><td>{b['goals']}</td></tr>"]
            for key, label, _ in HABITS:
                w = s["winners"][key]
                ca = " class=w" if w == a["club"] else ""
                cb = " class=w" if w == b["club"] else ""
                rows.append(f"<tr><td>{label}</td><td{ca}>{fmt_habit(key, a['habits'][key])}</td>"
                            f"<td{cb}>{fmt_habit(key, b['habits'][key])}</td></tr>")
            rows.append(f"<tr class=tot><td>Points</td><td>{pts(s['points'][a['club']])}</td>"
                        f"<td>{pts(s['points'][b['club']])}</td></tr>")
            who = "".join(f"<div><b>{e(sd['name'])}:</b> {e(', '.join(p['name'] for p in sd['players']))}</div>"
                          for sd in (a, b))
            when = datetime.datetime.fromtimestamp(s["ts"], TZ).strftime("%I:%M %p").lstrip("0")
            cards.append(f"<div class=sc><div class=when>{when}</div><table><tr><th></th>"
                         f"<th>{e(a['name'])}</th><th>{e(b['name'])}</th></tr>{''.join(rows)}</table>"
                         f"<div class=who>{who}</div></div>")
        aw = "".join(f"<li><b>{e(t)}:</b> {e(n)} <span>({e(why)})</span></li>" for t, n, why in awards(ss))
        parts.append(f"<section><h2>{night:%A %b %d} &middot; {len(ss)} scrims</h2>"
                     f"<div class=night>{head}</div><ul class=aw>{aw}</ul>"
                     f"<div class=grid>{''.join(cards)}</div></section>")
    legend = "".join(f"<li><b>{label}</b>: {why}</li>" for _, label, why in HABITS)
    nights = by_night(scrims)
    paste = ""
    if nights:
        night, ss = next(iter(nights.items()))
        paste = ("<h2>Paste in Discord</h2><textarea class=paste readonly rows=12 onclick=this.select()>"
                 + e(discord(night, ss)) + "</textarea>")
    return (f"<div class=scr><style>{STYLE}</style><h1>Scrim scorecard</h1>"
            "<p class=sub>Every scrim hands out 7 points: 2 for winning the game, 1 each for these five "
            "habits (green = won it). All numbers come from EA, nobody counts anything.</p>"
            f"<ul class=sub>{legend}</ul>{paste}"
            f"{''.join(parts) or '<p>No scrims saved yet.</p>'}</div>")


def render(scrims: list[dict]) -> str:
    """A standalone page, for looking at it without the viewer."""
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1"><title>Scrim Scorecard</title>'
            "<style>:root{color-scheme:dark;--bg:#12141a;--panel:#1a1d25;--line:#2b303b;--text:#e6e8ee;"
            "--dim:#9aa1b1;--good:#57d38c}*{box-sizing:border-box}body{margin:0;background:var(--bg);"
            "color:var(--text);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}"
            "main{max-width:1100px;margin:0 auto;padding:16px}</style></head><body><main>"
            + body(scrims) + "</main></body></html>")
