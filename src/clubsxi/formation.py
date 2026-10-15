"""The 4-3-3 as FUT-style cards, gold / silver / bronze per slot. A PREVIEW.

    python tools/formation_preview.py ARCHIVE.jsonl LEAGUE.json OUT.html [PINS.txt]

Everyone is gold on ONE card only (config/primary_slots.txt can pin it); elsewhere
he can be silver or bronze and the card says where he starts.

Picks come from tools/slot_ranking.py (read its docstring): per slot, a few
numbers that passed tests, compared head to head, 3 games to be considered, and a
"how sure" label from 100 resamples. No combined score is shown on any card.

Cards of the same slot type (LW and RW, LCB and RCB, LB and RB, LCM and RCM)
take consecutive ranks: gold goes to the best N people, silver to the next N,
bronze to the next N. EA cannot tell left from right and the captain said it does
not matter. The same person can be gold in more than one slot; the page lists
those so the captain can settle them. Not an approved result.
"""
from __future__ import annotations

import base64
import collections
import html
import os
import sys

from . import slot_ranking as sr

LAYOUT = [  # rows top to bottom: (card label, slot, card index)
    [("ATK", "ATK", 0), ("ATK", "ATK", 1), ("ATK", "ATK", 2)],
    [("MID", "MID", 0), ("MID", "MID", 1), ("MID", "MID", 2)],
    [("DEF", "DEF", 0), ("DEF", "DEF", 1), ("DEF", "DEF", 2), ("DEF", "DEF", 3)],
    [("GK", "GK", 0)],
]
SLOT_WORD = {"GK": "keeper", "DEF": "defender", "MID": "midfielder", "ATK": "attacker", "CB": "centre back", "FB": "fullback", "CDM": "CDM",
             "CM": "CM", "WING": "winger", "ST": "striker"}
CARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "card.png")


def e(x) -> str:
    return html.escape(str(x))


def phrase(metric: str, raw: float, typ: float, slot: str) -> str:
    w = SLOT_WORD[slot]
    if metric == "tackle success":
        return f"Wins {raw * 100:.0f}% of his tackles (our {w}s: {typ * 100:.0f}%)."
    if metric == "pass accuracy":
        return f"{raw * 100:.0f}% of his passes reach a teammate (our {w}s: {typ * 100:.0f}%)."
    if metric == "won minus lost":
        return f"Wins the ball back {raw:+.1f} more times than he loses it a game (our {w}s: {typ:+.1f})."
    if metric == "rating vs teammates":
        note = " Holders and defenders usually rate a little below attackers." if slot in ("DEF", "CB", "FB", "CDM") else ""
        return f"EA rates him {raw:+.2f} against his teammates in the same game (our {w}s: {typ:+.2f}).{note}"
    if metric == "EA rating":
        return f"EA match rating {raw:.2f} (our {w}s: {typ:.2f})."
    if metric == "goals + assists":
        return f"{raw:.1f} goals plus assists a game (our {w}s: {typ:.1f})."
    if metric == "shots on target":
        return f"{raw:.1f} shots on target a game (our {w}s: {typ:.1f})."
    if metric == "dribbles":
        return f"{raw:.1f} dribbles a game (our {w}s: {typ:.1f})."
    if metric == "forward passes":
        return f"{raw:.0f} forward passes completed a game (our {w}s: {typ:.0f})."
    if metric == "interceptions":
        return f"{raw:.1f} interceptions a game (our {w}s: {typ:.1f})."
    if metric == "team conceded":
        return (f"Team let in {raw:+.2f} goals a game against what the head count predicts with him here "
                f"(our {w}s: {typ:+.2f}; lower is better). Shared with whoever played alongside him.")
    if metric == "skill-move beats":
        return f"Beats {raw:.2f} players a game with a skill move (our {w}s: {typ:.2f})."
    if metric == "dribbles (fewer is better)":
        return f"{raw:.1f} dribbles a game (our {w}s: {typ:.1f}; fewer is better back here)."
    if metric == "penalties given away":
        return f"Gives away {raw:.2f} penalties a game (our {w}s: {typ:.2f}; fewer is better)."
    if metric == "first-time pass share":
        return f"{raw * 100:.0f}% of his passes are first time (our {w}s: {typ * 100:.0f}%)."
    if metric == "line breaks":
        return f"Breaks the other team's back line {raw:.1f} times a game, around, through or over (our {w}s: {typ:.1f})."
    if metric == "through balls":
        return f"{raw:.1f} through balls a game (our {w}s: {typ:.1f})."
    if metric == "shots in the box":
        return f"{raw:.1f} shots from inside the box a game (our {w}s: {typ:.1f})."
    if metric == "crosses":
        return f"{raw:.1f} crosses a game (our {w}s: {typ:.1f})."
    if metric == "save share":
        return f"Saves {raw * 100:.0f}% of the shots that reach him (our {w}s: {typ * 100:.0f}%)."
    return f"{metric}: {raw:.2f} (ours {typ:.2f})."


def explain(res: dict, r: dict, label: str | None, starts: list[str] | None = None) -> str:
    slot = res["slot"]
    lines = []
    for m in res["metrics"]:
        if m in r["raw"]:
            lines.append(phrase(m, r["raw"][m], res["typical"][m], slot))
    lines.append(f"Ahead of our typical {SLOT_WORD[slot]} on {r['above']} of {r['checks']} numbers. "
                 f"{r['n']} games in this slot, all builds together: "
                 + ", ".join(f"{b} {c}" for b, c in r["builds"]) + ".")
    if starts:
        lines.append(f"He starts at {', '.join(starts)}, so here he is secondary.")
    if r.get("history"):
        lines.append(f"Last year (FC26) he also played {r['history']} games in this slot. They are not counted.")
    if res.get("typical_all"):
        lines.append("Our typical here is built from last year's games too, because this season has under 10 so far.")
    if r["job_actions"] is not None:
        lines.append(f"Describes the job, not used to pick: {r['job_actions']:.1f} clearances plus interceptions a game.")
    if r["n"] < sr.GOLD_MIN:
        lines.append(f"Only {r['n']} games here, so he cannot be gold yet.")
    if label:
        lines.append(f"How sure: {label}.")
    return "\n".join(lines)


def card(label: str, slot: str, idx: int, results: dict, tiers: dict, starts: dict) -> str:
    res = results[slot]
    rows = ""
    for tier in ("gold", "silver", "bronze"):
        r = tiers[slot][tier][idx]
        if r is None:
            if not res["people"]:
                msg = "nobody has played here yet" if tier == "gold" else "-"
            else:
                msg = "nobody with " + str(sr.GOLD_MIN) + " games"
            rows += (f'<div class="tier {tier} none"><span class=star>&#9733;</span><span>{msg}</span></div>')
            continue
        top, k = r["builds"][0] if r["builds"] else ("?", 0)
        sure = sr.how_sure(r["gold_share"]) if tier == "gold" else None
        thin = " · thin" if r["n"] < sr.GOLD_MIN else ""
        elsewhere = [x for x in starts.get(r["name"], []) if x != label] if tier != "gold" else []
        sub = (f"{r['n']} games · starts {', '.join(elsewhere)}" if elsewhere
               else f"{r['n']} games · {e(top)} {k}{thin}")
        rows += (f'<div class="tier {tier}" title="{e(explain(res, r, sure, elsewhere))}"><span class=star>&#9733;</span>'
                 f"<div class=who><div class=nm>{e(r['name'])}</div>"
                 f"<div class=bd>{sub}</div></div></div>")
    gold = tiers[slot]["gold"][idx]
    badge = e(gold["builds"][0][0]) if gold and gold["builds"] else "open"
    name = e(gold["name"]) if gold else "open slot"
    if gold:
        sure = sr.how_sure(gold["gold_share"])
        solid = sum(1 for r in res["people"] if r["n"] >= sr.GOLD_MIN)
        only = solid <= res["cards"]          # everyone eligible is gold: nobody to beat
        foot = "no rivals yet" if only else f"gold: {sure}"
        cls = "only" if only else sure.replace(" ", "")
    else:
        foot, cls = ("not played yet" if not res["people"] else "no gold yet"), "closecall"
    return (f'<div class=fut><div class=band>{label}</div><div class=badge>{badge}</div>'
            f"<div class=tiers>{rows}</div><div class=name>{name}</div>"
            f'<div class="foot {cls}">{e(foot)}</div></div>')


def top_slots(results: dict) -> dict[str, list]:
    out: dict[str, list] = collections.defaultdict(list)
    for slot, res in results.items():
        if slot == "GK":
            continue
        ranked = res["people"]
        for i, r in enumerate(ranked):
            out[r["name"]].append((slot, r["n"], i + 1, len(ranked), r["score"], r["gold_share"]))
    return out


def render(results: dict, played: dict, pins: dict | None = None, *, matches: int = 0,
           art_url: str | None = None, standalone: bool = True) -> str:
    """The whole page; standalone=False gives a block for the live viewer."""
    tiers, moves = sr.assign(results, pins)
    starts: dict[str, list[str]] = collections.defaultdict(list)
    for line in LAYOUT:
        for label, slot, i in line:
            g = tiers[slot]["gold"][i]
            if g:
                starts[g["name"]].append(label)
    # Card art is optional. Put your own image at src/clubsxi/assets/card.png.
    if not art_url and os.path.exists(CARD):
        art_url = "data:image/png;base64," + base64.b64encode(open(CARD, "rb").read()).decode()
    art = art_url or ""
    css = f"""
:root{{color-scheme:dark;--bg:#12141a;--panel:#1a1d25;--line:#2b303b;--text:#e6e8ee;--dim:#9aa1b1;--accent:#6ea8ff}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
main{{max-width:1200px;margin:0 auto;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:15px;margin:22px 0 8px;color:var(--dim)}}
.sub{{color:var(--dim);margin:0 0 12px}}
.note{{background:#1b2030;border-left:3px solid var(--accent);padding:10px 14px;border-radius:0 6px 6px 0;color:var(--dim);margin:14px 0;font-size:13px}}
.pitch{{border-radius:14px;padding:14px 6px;border:1px solid #1f5a33;
 background:repeating-linear-gradient(0deg,#1d6b3a 0,#1d6b3a 70px,#1a6235 70px,#1a6235 140px)}}
.line{{display:flex;gap:6px;flex-wrap:nowrap;justify-content:center;margin:2px 0 6px}}
.fut{{--w:clamp(60px,calc((min(100vw,1200px) - 80px) / 4),255px);position:relative;width:var(--w);height:calc(var(--w)*1.4);
 font-size:calc(var(--w)*.064);color:#fff;
 background:url({art}) center/contain no-repeat}}
.fut .band{{position:absolute;left:15%;top:25%;font-size:1.06em;font-weight:900;letter-spacing:.08em;text-shadow:0 .12em .4em rgba(0,0,0,.7)}}
.fut .badge{{position:absolute;right:13%;top:24%;background:#7a3fd1;border:.1em solid #ffd27a;font-size:.62em;font-weight:800;padding:.2em .7em;border-radius:.6em;letter-spacing:.05em;max-width:9em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fut .tiers{{position:absolute;left:14%;right:14%;top:39%}}
.fut .tier{{display:flex;align-items:center;gap:.4em;padding:.2em .4em;border-radius:.4em;margin-bottom:.25em;background:rgba(8,4,20,.62);border:1px solid rgba(255,210,140,.28)}}
.fut .tier .star{{font-size:.88em;line-height:1;width:1em;text-align:center}}
.fut .tier.gold .star{{color:#ffd54a;text-shadow:0 0 .4em #ffb300}}
.fut .tier.silver .star{{color:#d9dee8}}
.fut .tier.bronze .star{{color:#d08a4a}}
.fut .tier .who{{min-width:0}}
.fut .tier .nm{{font-weight:800;font-size:.74em;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fut .tier .bd{{font-size:.6em;color:#e6d6ff;opacity:.9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fut .tier.none{{color:#b9aed6;font-style:italic;font-size:.66em}}
.fut .name{{position:absolute;left:14%;right:14%;top:76%;text-align:center;font-size:.82em;font-weight:900;letter-spacing:.03em;text-transform:uppercase;text-shadow:0 .12em .4em rgba(0,0,0,.8);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fut .foot{{position:absolute;left:14%;right:14%;top:83%;text-align:center;font-size:.66em;font-weight:700;color:#cbbde8}}
.fut .foot.verysure{{color:#7dffb0}}.fut .foot.likely{{color:#ffe08a}}.fut .foot.closecall{{color:#ffab8a}}.fut .foot.only{{color:#cbbde8}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;white-space:normal;text-transform:none;letter-spacing:0}}
th{{color:var(--dim);font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}}
.pc{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px}}
.pc h3{{margin:0 0 4px;font-size:14px}}.pc div{{font-size:12.5px;color:var(--dim)}}
"""
    if not standalone:   # the viewer has its own page shell
        css = "\n".join(line for line in css.splitlines()
                        if not line.startswith((":root", "*{", "body{", "main{")))
    out = [(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>The eleven, formation preview</title><style>{css}</style><main>") if standalone
           else f"<style>{css}</style><div class=xi>",
           "<h1>The eleven: 4-3-3 preview</h1>",
           "<p class=sub>Gold starts, silver is bench, bronze is reserve. Hover or tap a name for the numbers "
           "behind it. The line under each card says how sure the gold is. Only this season's games (FC27) decide the "
           "order; last year's are shown as history. Early season, builds still changing, so treat this as a draft.</p>"
           "<div class=pitch>"]
    for line in LAYOUT:
        out.append("<div class=line>" + "".join(card(l, s, i, results, tiers, starts) for l, s, i in line) + "</div>")
    out.append("</div>")

    why, seen = [], set()
    for m in moves:
        if m["name"] in (pins or {}) or (m["name"], m["demoted"]) in seen:
            continue
        seen.add((m["name"], m["demoted"]))
        why.append(f"{e(m['name'])} starts at {SLOT_WORD[m['keeps']]} (fewest rivals there) and is secondary at "
                   f"{SLOT_WORD[m['demoted']]}")
    for name, slot in (pins or {}).items():
        if name in starts:
            why.append(f"{e(name)} starts at {SLOT_WORD[slot]} (your pick)")
    out.append("<div class=note><b>One start per person.</b> Everyone is gold on one card only; anywhere else he "
               "can be silver or bronze, and the card says where he starts. "
               + ("; ".join(why) + "." if why else "No one clashed, so nothing was moved.")
               + " To choose someone's primary slot yourself, edit config/primary_slots.txt.</div>")

    out.append("<h2>Why each gold</h2><table><tr><th>Card</th><th>Gold</th><th>How sure</th>"
               "<th>The numbers</th><th>Next in line</th></tr>")
    for line in LAYOUT:
        for label, slot, i in line:
            res, t = results[slot], tiers[slot]
            g = t["gold"][i]
            if not g:
                out.append(f"<tr><td>{label}</td><td colspan=4>" + ("nobody has played here yet this season" if not res["people"] else "no gold yet: nobody has " + str(sr.GOLD_MIN) + " games here this season") + "</td></tr>")
                continue
            solid = sum(1 for r in res["people"] if r["n"] >= sr.GOLD_MIN)
            sure = "no rivals yet" if solid <= res["cards"] else sr.how_sure(g["gold_share"])
            nxt = ", ".join(e(x["name"]) for x in (t["silver"][i], t["bronze"][i]) if x) or "none"
            nums = " ".join(phrase(m, g["raw"][m], res["typical"][m], slot) for m in res["metrics"] if m in g["raw"])
            out.append(f"<tr><td>{label}</td><td><b>{e(g['name'])}</b><div style='color:var(--dim)'>"
                       f"{g['n']} games this season" + (f", {g['history']} last year" if g.get('history') else "") + f"</div></td><td>{sure}</td><td>{e(nums)} Ahead of our typical on "
                       f"{g['above']} of {g['checks']}.</td><td>{nxt}</td></tr>")
    out.append("</table>")

    out.append("<h2>Who has played where</h2><div class=note>Everyone is rotating and still building, so this "
               "shows every slot each person has tried, with no minimum. FC27 games first; FC26 games in brackets "
               "are last year and are not counted in the picks.</div><div class=grid>")
    order = ["ATK", "MID", "DEF", "GK"]
    for name in sorted(played, key=lambda n: -sum(v[0] for v in played[n].values())):
        mine = played[name]
        if not any(v[0] for v in mine.values()):
            continue
        out.append(f"<div class=pc><h3>{e(name)}</h3>")
        for slot in sorted((s for s in mine if mine[s][0] or mine[s][1]), key=lambda s: (-mine[s][0], -mine[s][1], order.index(s))):
            a, b = mine[slot]
            note = ("" if a >= sr.GOLD_MIN else " (trying it)" if 0 < a < sr.LIST_MIN else
                    " (last year only)" if a == 0 else "")
            last = f" ({b} last year)" if b and a else ""
            games = f"{a} game" + ("" if a == 1 else "s") if a else f"{b} games last year"
            out.append(f"<div><b>{SLOT_WORD[slot]}</b>: {games}{last}{note}</div>")
        out.append("</div>")
    out.append("</div>")

    out.append("<div class=note><b>How the order works.</b> Each slot uses 3 or 4 numbers that were tested on "
               "other clubs' games: steady from game to game, and linked to the team doing better. Each person is "
               "compared head to head with the other candidates on every number, and the order is how many of "
               "those comparisons he wins. Every number counts the same. Few games are pulled toward the regulars' average (people with " + str(sr.REGULAR) + "+ games there), so a new "
               "player with a few great games can still rank, but only if he is clearly above them. Every name on a card needs " + str(sr.LIST_MIN) + " games in the slot. 'How sure' is how often he is gold when "
               "his games are reshuffled 100 times. Both clubs are pooled with no club penalty. Only FC27 games count. "
               "No combined score is shown anywhere.</div>")
    out.append("<div class=note><b>Numbers used.</b> "
               + " | ".join(f"<b>{SLOT_WORD[s]}</b>: {', '.join(sr.SETS[s])}" for s in sr.SLOTS)
               + ". Raw clearances, blocks and interceptions are not used to pick centre backs and holders: other "
               "clubs' games show they go with the other team shooting more, so they describe how much defending "
               "was needed, not how well it was done.</div>")
    out.append("<div class=note><b>Limits.</b> Only " + str(matches) + " matches this season so far, so one or two games can flip a gold. "
               "EA only says keeper, defender, midfielder or forward, and builds do not show where someone "
               "plays, so each group is ranked as one list: three attackers, three midfielders, four "
               "defenders, one keeper. Who plays left, right, holding or up top is sorted in game. "
               "People who always play together, like a centre back and a holder, cannot be "
               "separated, so team numbers are shared between them.</div>")
    out.append("</main>" if standalone else "</div>")
    return "".join(out)


def main() -> None:
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    rows = sr.load(sys.argv[1], sys.argv[2])
    results = sr.run_all(rows)
    pins_path = sys.argv[4] if len(sys.argv) == 5 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "primary_slots.txt")
    open(sys.argv[3], "w", encoding="utf-8").write(
        render(results, sr.played(sr.Ctx(rows)), sr.load_primary(pins_path),
               matches=sr.fc27_matches(rows)))
    print(f"{len(rows)} appearances -> {sys.argv[3]}")


if __name__ == "__main__":
    main()
