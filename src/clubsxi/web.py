"""A small read-only web page for looking at what the collector saved.

It shows evidence, sample size and flags. It ranks a player's own positions
against each other by what the team did, but it never scores players against
each other and never picks an XI. Standard library only, no internet needed to
load the page.
"""
from __future__ import annotations

import html
import json
import logging
import os
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analysis, formation, picker, player_score, scrims, slot_ranking

log = logging.getLogger("clubsxi.web")

CSS = """
:root { color-scheme: dark; --bg:#12141a; --panel:#1a1d25; --line:#2b303b;
  --text:#e6e8ee; --dim:#9aa1b1; --accent:#6ea8ff; --good:#57d38c;
  --bad:#ff7b7b; --warn:#ffcc66; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header { background:var(--panel); border-bottom:1px solid var(--line);
  padding:12px 20px; display:flex; gap:18px; align-items:baseline;
  flex-wrap:wrap; position:sticky; top:0; z-index:5; }
header .brand { font-weight:700; letter-spacing:.5px; }
header nav a { margin-right:14px; color:var(--dim); }
header nav a.on { color:var(--text); border-bottom:2px solid var(--accent); }
main { padding:20px; max-width:1200px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:15px; margin:26px 0 8px; color:var(--dim);
  text-transform:uppercase; letter-spacing:.08em; }
.sub { color:var(--dim); margin:0 0 18px; }
.cards { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:12px 16px; min-width:130px; }
.card .n { font-size:22px; font-weight:700; }
.card .k { color:var(--dim); font-size:12px; }
.wrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px;
  background:var(--panel); }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--line);
  white-space:nowrap; }
th { color:var(--dim); font-weight:600; font-size:12px;
  text-transform:uppercase; letter-spacing:.05em; }
tbody tr:hover { background:#20242e; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px;
  border:1px solid var(--line); color:var(--dim); }
.win { color:var(--good); } .loss { color:var(--bad); } .draw { color:var(--warn); }
.ghost { color:var(--bad); } .short { color:var(--warn); }
.ok { color:var(--dim); }
.rank1 td { background:#1d2633; }
.thin { color:var(--dim); font-style:italic; }
.pill { display:inline-block; padding:2px 10px; border-radius:12px;
  font-size:12px; border:1px solid var(--line); margin-right:6px; }
.pill.on { border-color:var(--accent); color:var(--accent); }
.player-block { margin:0 0 26px; }
.player-block h3 { margin:0 0 6px; font-size:15px; }
form.filters { margin:0 0 14px; display:flex; gap:8px; flex-wrap:wrap; }
select, input, button { background:var(--panel); color:var(--text);
  border:1px solid var(--line); border-radius:6px; padding:6px 9px;
  font-size:13px; }
button { cursor:pointer; }
pre { background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:14px; overflow:auto; font-size:12px; max-height:70vh; }
.note { background:#1b2030; border-left:3px solid var(--accent);
  padding:10px 14px; border-radius:0 6px 6px 0; color:var(--dim);
  margin:16px 0; font-size:13px; }
.empty { color:var(--dim); padding:18px; }
.row { display:flex; gap:10px; flex-wrap:wrap; justify-content:center; margin:6px 0 26px; }
.fut { position:relative; width:250px; height:350px; color:#fff;
  background:url(/static/card.png) center/contain no-repeat, linear-gradient(160deg,#2a2f4a,#11141f);
  border-radius:14px; }
.fut .ovr { position:absolute; left:15%; top:22%; font-size:34px; font-weight:900;
  line-height:1; text-shadow:0 2px 6px rgba(0,0,0,.7); }
.fut .band { position:absolute; left:15%; top:32%; font-size:13px; font-weight:800;
  letter-spacing:.08em; text-shadow:0 2px 6px rgba(0,0,0,.7); }
.fut .badge { position:absolute; right:13%; top:24%; background:#7a3fd1;
  border:1.5px solid #ffd27a; font-size:10px; font-weight:800; padding:2px 7px;
  border-radius:6px; letter-spacing:.05em; max-width:80px; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.fut .tiers { position:absolute; left:14%; right:14%; top:39%; }
.fut .tier { display:flex; align-items:center; gap:6px; padding:3px 6px;
  border-radius:6px; margin-bottom:4px; background:rgba(8,4,20,.62);
  border:1px solid rgba(255,210,140,.28); }
.fut .tier .star { font-size:14px; line-height:1; width:16px; text-align:center; }
.fut .tier.gold .star { color:#ffd54a; text-shadow:0 0 6px #ffb300; }
.fut .tier.silver .star { color:#d9dee8; }
.fut .tier.bronze .star { color:#d08a4a; }
.fut .tier .who { min-width:0; }
.fut .tier .nm { font-weight:800; font-size:11.5px; line-height:1.15; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.fut .tier .bd { font-size:9.5px; color:#e6d6ff; opacity:.9; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.fut .tier.none { color:#b9aed6; font-style:italic; font-size:10.5px; }
.fut .name { position:absolute; left:14%; right:14%; top:76%; text-align:center;
  font-size:13px; font-weight:900; letter-spacing:.03em; text-transform:uppercase;
  text-shadow:0 2px 6px rgba(0,0,0,.8); white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis; }
.fut .foot { position:absolute; left:14%; right:14%; top:83%; text-align:center;
  font-size:8.5px; color:#cbbde8; }
.fut a { color:inherit; text-decoration:none; }
h2.sec { margin-top:18px; }
"""

NAV = [("/", "Overview"), ("/squad", "Squad"), ("/scores", "Scores"), ("/scrims", "Scrims"), ("/matches", "Matches"),
       ("/players", "Players"), ("/positions", "Positions"), ("/polls", "Poll log")]


_XI_CACHE: dict = {}   # one ranking run per new match, not per page view
_PICK_CACHE: dict = {}  # picker inputs, rebuilt when a new match lands


def e(value) -> str:
    return html.escape("" if value is None else str(value))


def when(unix) -> str:
    if not unix:
        return "-"
    return datetime.fromtimestamp(int(unix), timezone.utc).strftime(
        "%Y-%m-%d %H:%M")


def mmss(seconds) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    return str(seconds // 60) + "m"


def page(title: str, path: str, body: str) -> bytes:
    nav = "".join(
        '<a class="' + ("on" if href == path else "") + '" href="' + href
        + '">' + label + "</a>"
        for href, label in NAV)
    doc = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<title>" + e(title) + " - ClubsXI</title><style>" + CSS + "</style>"
        "</head><body><header><span class=brand>ClubsXI</span><nav>" + nav
        + "</nav></header><main>" + body + "</main></body></html>")
    return doc.encode("utf-8")


def table(headers: list[str], rows: list[list[str]],
          numeric: set[int] | None = None) -> str:
    if not rows:
        return '<div class="wrap"><div class=empty>Nothing here yet.</div></div>'
    numeric = numeric or set()
    head = "".join(
        '<th class="' + ("num" if i in numeric else "") + '">' + h + "</th>"
        for i, h in enumerate(headers))
    body = ""
    for row in rows:
        cells = "".join(
            '<td class="' + ("num" if i in numeric else "") + '">' + str(c)
            + "</td>" for i, c in enumerate(row))
        body += "<tr>" + cells + "</tr>"
    return ('<div class="wrap"><table><thead><tr>' + head
            + "</tr></thead><tbody>" + body + "</tbody></table></div>")


class Views:
    def __init__(self, conn: sqlite3.Connection, our_clubs: dict[str, str]):
        self.conn = conn
        self.our_clubs = our_clubs

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    def club_label(self, club_id: str) -> str:
        return self.our_clubs.get(str(club_id), str(club_id))

    # Overview ------------------------------------------------------------

    def overview(self) -> str:
        stats = [
            ("matches", "SELECT COUNT(*) FROM matches"),
            ("player rows", "SELECT COUNT(*) FROM player_match_stats"),
            ("people", "SELECT COUNT(*) FROM players"),
            ("real appearances",
             "SELECT COUNT(*) FROM player_match_stats WHERE is_real_appearance=1"),
            ("ghosts",
             "SELECT COUNT(*) FROM player_match_stats WHERE appearance_class='ghost'"),
            ("api calls stored", "SELECT COUNT(*) FROM raw_responses"),
        ]
        cards = "".join(
            '<div class=card><div class=n>' + str(self.q(sql)[0][0])
            + '</div><div class=k>' + label + "</div></div>"
            for label, sql in stats)

        by_club = self.q(
            "SELECT mc.club_id, mc.club_name, COUNT(*) AS games, "
            "  SUM(mc.goals_for) AS gf, SUM(mc.goals_against) AS ga, "
            "  SUM(mc.outcome='win') AS w, SUM(mc.outcome='draw') AS d, "
            "  SUM(mc.outcome='loss') AS l "
            "FROM match_clubs mc WHERE mc.is_our_club=1 "
            "GROUP BY mc.club_id ORDER BY games DESC")
        club_rows = [[
            '<a href="/matches?club=' + e(r["club_id"]) + '">'
            + e(self.club_label(r["club_id"])) + "</a>",
            r["games"], r["w"], r["d"], r["l"], r["gf"], r["ga"],
            (r["gf"] or 0) - (r["ga"] or 0),
        ] for r in by_club]

        flags = self.q(
            "SELECT validity, COUNT(*) AS n FROM matches "
            "GROUP BY validity ORDER BY n DESC")
        flag_rows = [[e(r["validity"]), r["n"]] for r in flags]

        recent = self.q(
            "SELECT m.match_id, m.match_timestamp, m.match_type, m.validity, "
            "  mc.club_id, mc.club_name, mc.goals_for, mc.goals_against, "
            "  mc.outcome, mc.real_human_count, "
            "  (SELECT club_name FROM match_clubs o WHERE o.match_id=m.match_id "
            "     AND o.club_id != mc.club_id) AS opponent "
            "FROM matches m JOIN match_clubs mc ON mc.match_id=m.match_id "
            "WHERE mc.is_our_club=1 ORDER BY m.match_timestamp DESC LIMIT 15")

        return (
            "<h1>Overview</h1><p class=sub>Everything the collector has saved so "
            "far. This page only shows evidence. It does not rank anyone.</p>"
            '<div class=cards>' + cards + "</div>"
            "<h2>Our clubs</h2>"
            + table(["Club", "Games", "W", "D", "L", "GF", "GA", "Diff"],
                    club_rows, {1, 2, 3, 4, 5, 6, 7})
            + "<h2>Match flags</h2>"
            + table(["Flag", "Matches"], flag_rows, {1})
            + "<h2>Latest matches</h2>" + self._match_table(recent))

    # Matches -------------------------------------------------------------

    def _match_table(self, rows) -> str:
        out = []
        for r in rows:
            score = str(r["goals_for"]) + " - " + str(r["goals_against"])
            out.append([
                when(r["match_timestamp"]),
                e(self.club_label(r["club_id"])),
                '<span class="' + e(r["outcome"]) + '">' + score + "</span>",
                e(r["opponent"] or "?"),
                '<span class=tag>' + e(r["match_type"].replace("Match", ""))
                + "</span>",
                r["real_human_count"],
                ('<span class=ok>ok</span>' if r["validity"] == "ok"
                 else '<span class=ghost>' + e(r["validity"]) + "</span>"),
                '<a href="/match/' + e(r["match_id"]) + '">open</a>',
            ])
        return table(["Played", "Our club", "Score", "Opponent", "Type",
                      "Humans", "Flag", ""], out, {5})

    def matches(self, params: dict) -> str:
        where, args = ["mc.is_our_club=1"], []
        if params.get("club"):
            where.append("mc.club_id = ?")
            args.append(params["club"])
        if params.get("type"):
            where.append("m.match_type = ?")
            args.append(params["type"])
        if params.get("validity"):
            where.append("m.validity = ?")
            args.append(params["validity"])

        rows = self.q(
            "SELECT m.match_id, m.match_timestamp, m.match_type, m.validity, "
            "  mc.club_id, mc.goals_for, mc.goals_against, mc.outcome, "
            "  mc.real_human_count, "
            "  (SELECT club_name FROM match_clubs o WHERE o.match_id=m.match_id "
            "     AND o.club_id != mc.club_id) AS opponent "
            "FROM matches m JOIN match_clubs mc ON mc.match_id=m.match_id "
            "WHERE " + " AND ".join(where)
            + " ORDER BY m.match_timestamp DESC LIMIT 500", tuple(args))

        def picker(name: str, label: str, options: list[str]) -> str:
            chosen = params.get(name, "")
            opts = '<option value="">' + label + "</option>"
            for o in options:
                sel = " selected" if o == chosen else ""
                text = self.club_label(o) if name == "club" else o
                opts += ('<option value="' + e(o) + '"' + sel + ">"
                         + e(text) + "</option>")
            return "<select name=" + name + ">" + opts + "</select>"

        clubs = [r[0] for r in self.q(
            "SELECT DISTINCT club_id FROM match_clubs WHERE is_our_club=1")]
        types = [r[0] for r in self.q(
            "SELECT DISTINCT match_type FROM matches")]
        flags = [r[0] for r in self.q("SELECT DISTINCT validity FROM matches")]

        return (
            "<h1>Matches</h1><p class=sub>" + str(len(rows))
            + " shown. Newest first.</p>"
            '<form class=filters method=get>'
            + picker("club", "All clubs", clubs)
            + picker("type", "All types", types)
            + picker("validity", "All flags", flags)
            + "<button>Filter</button></form>"
            + self._match_table(rows))

    def match_detail(self, match_id: str) -> str:
        match = self.q("SELECT * FROM matches WHERE match_id=?", (match_id,))
        if not match:
            return "<h1>Not found</h1><p class=sub>No match with that id.</p>"
        m = match[0]
        sides = self.q(
            "SELECT * FROM match_clubs WHERE match_id=? ORDER BY is_our_club DESC",
            (match_id,))

        header = ""
        if len(sides) == 2:
            a, b = sides[0], sides[1]
            header = (e(a["club_name"] or a["club_id"]) + "  "
                      + str(a["goals_for"]) + " - " + str(a["goals_against"])
                      + "  " + e(b["club_name"] or b["club_id"]))

        blocks = ""
        for side in sides:
            snap = self.q(
                "SELECT * FROM club_snapshots WHERE id=?",
                (side["club_snapshot_id"],)) if side["club_snapshot_id"] else []
            rating = ("skill rating " + str(snap[0]["skill_rating"])
                      + " when saved") if snap and snap[0]["skill_rating"] else ""

            players = self.q(
                "SELECT * FROM player_match_stats WHERE match_id=? AND club_id=? "
                "ORDER BY CASE pos WHEN 'goalkeeper' THEN 0 WHEN 'defender' "
                "THEN 1 WHEN 'midfielder' THEN 2 ELSE 3 END, rating DESC",
                (match_id, side["club_id"]))
            rows = []
            for p in players:
                cls = p["appearance_class"]
                rows.append([
                    '<a href="/player/' + e(p["player_id"]) + '">'
                    + e(p["player_name"] or p["player_id"]) + "</a>",
                    e(p["pos"]),
                    '<span class=tag>' + e(p["archetype_id"]) + "</span>",
                    mmss(p["seconds_played"]),
                    '<span class="' + (cls if cls != "full" else "ok") + '">'
                    + cls + "</span>",
                    p["rating"] if p["rating"] is not None else "-",
                    p["goals"], p["assists"], p["shots"],
                    str(p["passes_made"]) + "/" + str(p["pass_attempts"]),
                    str(p["tackles_made"]) + "/" + str(p["tackle_attempts"]),
                    p["saves"], p["goals_conceded"],
                    "yes" if p["mom"] else "",
                ])
            blocks += (
                "<h2>" + e(side["club_name"] or side["club_id"]) + " - "
                + str(side["goals_for"]) + " goals, "
                + str(side["real_human_count"]) + " of "
                + str(side["human_count"]) + " humans really played"
                + ((" - " + rating) if rating else "") + "</h2>"
                + table(["Player", "Position", "Arch", "Time", "Appearance",
                         "Rating", "G", "A", "Sh", "Pass", "Tack", "Sv",
                         "Conc", "MOM"],
                        rows, {5, 6, 7, 8, 11, 12}))

        notes = ('<div class=note>Flag: <b>' + e(m["validity"]) + "</b>. "
                 + e(m["validity_notes"] or "no notes") + "</div>")

        return (
            "<h1>" + header + "</h1>"
            "<p class=sub>" + when(m["match_timestamp"]) + " UTC &middot; "
            + e(m["match_type"]) + " &middot; match id " + e(m["match_id"])
            + ' &middot; <a href="/raw/' + e(m["match_id"])
            + '">raw JSON</a></p>' + notes + blocks)

    # Players -------------------------------------------------------------

    def players(self) -> str:
        rows = self.q(
            "SELECT p.player_id, p.latest_name, "
            "  COUNT(*) AS rows_seen, "
            "  SUM(s.is_real_appearance) AS apps, "
            "  SUM(s.appearance_class='ghost') AS ghosts, "
            "  SUM(s.goals) AS goals, SUM(s.assists) AS assists, "
            "  ROUND(AVG(NULLIF(s.rating,0)),2) AS avg_rating, "
            "  MAX(m.match_timestamp) AS last_seen "
            "FROM player_match_stats s "
            "JOIN players p ON p.player_id=s.player_id "
            "JOIN matches m ON m.match_id=s.match_id "
            "JOIN match_clubs mc ON mc.match_id=s.match_id "
            "  AND mc.club_id=s.club_id AND mc.is_our_club=1 "
            "WHERE s.club_id IN (?, ?) "          # this year's clubs, same as EA's totals beside them
            "GROUP BY p.player_id ORDER BY apps DESC", tuple(sorted(picker.OURS)))
        # EA's own club totals: the newest member snapshot of each club, added up over both clubs.
        # They include games from before the collector started and games it missed between polls.
        ea: dict = {}
        for m in self.q(
                "SELECT r.name, r.player_id, r.games_played, r.goals, r.assists FROM member_snapshot_rows r "
                "WHERE r.snapshot_id IN (SELECT MAX(id) FROM member_snapshots WHERE club_id IN (?, ?) GROUP BY club_id)",
                tuple(sorted(picker.OURS))):   # this season's clubs only, not last year's ids
            for key in {m["player_id"], m["name"]} - {None, ""}:
                t = ea.setdefault(key, [0, 0, 0])
                t[0] += m["games_played"] or 0
                t[1] += m["goals"] or 0
                t[2] += m["assists"] or 0

        def ea_for(r):
            return ea.get(r["player_id"]) or ea.get(r["latest_name"]) or None
        out = []
        for r in rows:
            t = ea_for(r)
            out.append([
                '<a href="/player/' + e(r["player_id"]) + '">'
                + e(r["latest_name"] or r["player_id"]) + "</a>",
                r["apps"] or 0, r["goals"] or 0, r["assists"] or 0,
                t[0] if t else "-", t[1] if t else "-", t[2] if t else "-",
                r["ghosts"] or 0, r["avg_rating"] if r["avg_rating"] else "-",
                when(r["last_seen"]),
            ])
        return (
            "<h1>Players</h1><p class=sub>Everyone who has played for one of our "
            "clubs. Identity is the EA numeric id, not the name.</p>"
            '<div class=note>Games, goals and assists are the FC27 games our collector saved (league, playoff and '
            "scrims), which the ratings use. EA games, EA goals and EA assists are EA's own club totals for both clubs: "
            "they also count games from before the collector started and games EA dropped "
            "before we could save them, so they are usually higher. Ghost rows are appearances EA reported "
            "with zero seconds played; they are kept but never counted as playing.</div>"
            + table(["Player", "Games", "Goals", "Assists", "EA games", "EA goals", "EA assists",
                     "Ghosts", "Avg rating", "Last seen"], out, {1, 2, 3, 4, 5, 6, 7, 8}))

    def player_detail(self, player_id: str) -> str:
        person = self.q("SELECT * FROM players WHERE player_id=?", (player_id,))
        if not person:
            return "<h1>Not found</h1><p class=sub>No player with that id.</p>"
        p = person[0]

        names = self.q(
            "SELECT name FROM player_names WHERE player_id=? ORDER BY last_seen DESC",
            (player_id,))
        alias = ", ".join(e(n["name"]) for n in names)

        slices = self.q(
            "SELECT s.club_id, s.pos, s.archetype_id, "
            "  COUNT(*) AS apps, "
            "  SUM(mc.goals_for) AS team_gf, SUM(mc.goals_against) AS team_ga, "
            "  SUM(mc.outcome='win') AS w, SUM(mc.outcome='draw') AS d, "
            "  SUM(mc.outcome='loss') AS l, "
            "  SUM(s.goals) AS goals, SUM(s.assists) AS assists, "
            "  ROUND(AVG(NULLIF(s.rating,0)),2) AS avg_rating "
            "FROM player_match_stats s "
            "JOIN match_clubs mc ON mc.match_id=s.match_id AND mc.club_id=s.club_id "
            "WHERE s.player_id=? AND s.is_real_appearance=1 AND mc.is_our_club=1 "
            "GROUP BY s.club_id, s.pos, s.archetype_id "
            "ORDER BY apps DESC", (player_id,))
        slice_rows = [[
            e(self.club_label(r["club_id"])),
            e(r["pos"]),
            '<span class=tag>' + e(r["archetype_id"]) + "</span>",
            r["apps"],
            r["team_gf"], r["team_ga"], (r["team_gf"] or 0) - (r["team_ga"] or 0),
            str(r["w"]) + "/" + str(r["d"]) + "/" + str(r["l"]),
            r["goals"], r["assists"],
            r["avg_rating"] if r["avg_rating"] else "-",
        ] for r in slices]

        appearances = self.q(
            "SELECT m.match_id, m.match_timestamp, m.match_type, m.validity, "
            "  s.pos, s.archetype_id, s.seconds_played, s.appearance_class, "
            "  s.rating, s.goals, s.assists, mc.club_id, "
            "  mc.goals_for, mc.goals_against, mc.outcome, "
            "  (SELECT club_name FROM match_clubs o WHERE o.match_id=m.match_id "
            "     AND o.club_id != s.club_id) AS opponent "
            "FROM player_match_stats s "
            "JOIN matches m ON m.match_id=s.match_id "
            "JOIN match_clubs mc ON mc.match_id=s.match_id AND mc.club_id=s.club_id "
            "WHERE s.player_id=? ORDER BY m.match_timestamp DESC LIMIT 300",
            (player_id,))
        app_rows = [[
            when(r["match_timestamp"]),
            e(self.club_label(r["club_id"])),
            '<span class="' + e(r["outcome"] or "") + '">'
            + str(r["goals_for"]) + " - " + str(r["goals_against"]) + "</span>",
            e(r["opponent"] or "?"),
            e(r["pos"]),
            '<span class=tag>' + e(r["archetype_id"]) + "</span>",
            mmss(r["seconds_played"]),
            '<span class="' + (r["appearance_class"]
                               if r["appearance_class"] != "full" else "ok")
            + '">' + e(r["appearance_class"]) + "</span>",
            r["rating"] if r["rating"] is not None else "-",
            r["goals"], r["assists"],
            '<a href="/match/' + e(r["match_id"]) + '">open</a>',
        ] for r in appearances]

        teammates = self.q(
            "SELECT o.player_id, o.player_name, COUNT(*) AS together, "
            "  SUM(mc.goals_for) AS gf, SUM(mc.goals_against) AS ga, "
            "  SUM(mc.outcome='win') AS w "
            "FROM player_match_stats s "
            "JOIN player_match_stats o ON o.match_id=s.match_id "
            "  AND o.club_id=s.club_id AND o.player_id != s.player_id "
            "JOIN match_clubs mc ON mc.match_id=s.match_id AND mc.club_id=s.club_id "
            "WHERE s.player_id=? AND s.is_real_appearance=1 "
            "  AND o.is_real_appearance=1 AND mc.is_our_club=1 "
            "GROUP BY o.player_id ORDER BY together DESC LIMIT 25", (player_id,))
        mate_rows = [[
            '<a href="/player/' + e(r["player_id"]) + '">'
            + e(r["player_name"] or r["player_id"]) + "</a>",
            r["together"], r["gf"], r["ga"], (r["gf"] or 0) - (r["ga"] or 0),
            r["w"],
        ] for r in teammates]

        return (
            "<h1>" + e(p["latest_name"] or player_id) + "</h1>"
            "<p class=sub>EA id " + e(player_id)
            + " &middot; seen as: " + alias
            + " &middot; first seen " + when(p["first_seen"]) + "</p>"
            '<div class=note>Team goals for and against are the whole team while '
            "this player was really on the pitch. They are not this player's "
            "doing. Small numbers of appearances mean very little.</div>"
            "<h2>Slices: club, broad position, archetype</h2>"
            + table(["Club", "Position", "Arch", "Apps", "Team GF", "Team GA",
                     "Diff", "W/D/L", "Goals", "Assists", "Avg rating"],
                    slice_rows, {3, 4, 5, 6, 8, 9, 10})
            + "<h2>Played alongside</h2>"
            + table(["Teammate", "Games together", "Team GF", "Team GA",
                     "Diff", "Wins"], mate_rows, {1, 2, 3, 4, 5})
            + "<h2>Every appearance</h2>"
            + table(["Played", "Club", "Score", "Opponent", "Position", "Arch",
                     "Time", "Appearance", "Rating", "G", "A", ""],
                    app_rows, {8, 9, 10}))

    # Positions -----------------------------------------------------------

    def positions(self, params: dict) -> str:
        include_messy = params.get("include") == "all"
        club = params.get("club") or ""
        club_ids = [club] if club else None

        counts = analysis.evidence_counts(self.conn)
        grouped = analysis.top_positions(
            self.conn, club_ids=club_ids, include_messy=include_messy)

        def pill(label: str, href: str, on: bool) -> str:
            return ('<a class="pill' + (" on" if on else "") + '" href="'
                    + href + '">' + label + "</a>")

        club_bit = ("&club=" + urllib.parse.quote(club)) if club else ""
        toggle = (
            pill("Clean games only", "/positions?include=clean" + club_bit,
                 not include_messy)
            + pill("Include quits and short games",
                   "/positions?include=all" + club_bit, include_messy))

        clubs = [r[0] for r in self.q(
            "SELECT DISTINCT club_id FROM match_clubs WHERE is_our_club=1")]
        include_bit = "&include=" + ("all" if include_messy else "clean")
        club_pills = pill("All clubs", "/positions?x=1" + include_bit, not club)
        for c in clubs:
            club_pills += pill(self.club_label(c),
                               "/positions?club=" + urllib.parse.quote(c)
                               + include_bit, club == c)

        if include_messy:
            rule = ("Counting <b>every</b> appearance, including quits, "
                    "DNF games and very short spells. Use this to look, not "
                    "to decide.")
        else:
            rule = ("Counting only full appearances in clean games. "
                    + str(counts["dnf_matches"]) + " DNF match(es), "
                    + str(counts["ghosts"]) + " ghost row(s) and "
                    + str(counts["shorts"]) + " short spell(s) are left out.")

        blocks = ""
        shown = 0
        for player_id, entry in grouped.items():
            if not entry["ranked"] and not entry["thin"]:
                continue
            shown += 1
            rows = []
            for i, s in enumerate(entry["ranked"]):
                rows.append([
                    str(i + 1),
                    e(s.pos),
                    '<span class=tag>' + e(s.archetype_id) + "</span>",
                    e(self.club_label(s.club_id)),
                    s.appearances,
                    ("+" if s.diff > 0 else "") + str(s.diff),
                    format(s.diff_per_game, ".2f"),
                    format(s.gf_per_game, ".2f"),
                    format(s.ga_per_game, ".2f"),
                    str(s.wins) + "/" + str(s.draws) + "/" + str(s.losses),
                    format(s.output_per_game, ".2f"),
                    format(s.avg_rating, ".2f") if s.avg_rating else "-",
                    s.confidence,
                ])
            for s in entry["thin"]:
                rows.append([
                    '<span class=thin>-</span>',
                    '<span class=thin>' + e(s.pos) + "</span>",
                    '<span class=tag>' + e(s.archetype_id) + "</span>",
                    e(self.club_label(s.club_id)),
                    s.appearances,
                    "", "", "", "", "", "", "",
                    '<span class=thin>not enough evidence</span>',
                ])
            blocks += (
                '<div class=player-block><h3><a href="/player/' + e(player_id)
                + '">' + e(entry["name"]) + "</a> <span class=tag>"
                + str(entry["total"]) + " appearances counted</span></h3>"
                + table(["#", "Position", "Arch", "Club", "Apps", "Diff",
                         "Diff/game", "GF/game", "GA/game", "W/D/L",
                         "G+A/game", "Rating", "Confidence"],
                        rows, {4, 5, 6, 7, 8, 10, 11}) + "</div>")

        if not shown:
            blocks = ('<div class="wrap"><div class=empty>No appearances count '
                      "yet under this filter.</div></div>")

        return (
            "<h1>Top positions</h1>"
            "<p class=sub>Ordered by what the team did while the player was on "
            "the pitch, then by how many games back it up. Their own goals and "
            "assists only break ties.</p>"
            "<div>" + toggle + "</div><div style=margin-top:8px>" + club_pills
            + "</div>"
            '<div class=note>' + rule + "<br><br>"
            "A slice needs at least " + str(analysis.DEFAULT_MIN_APPEARANCES)
            + " counting appearances before it is ranked. "
            "Right now " + str(counts["counting_appearances"]) + " of "
            + str(counts["counting_appearances"] + counts["excluded_appearances"])
            + " appearances count. This is a gauge, not a verdict. "
            "Position names are EA's broad ones and the archetype is EA's raw "
            "number. Nothing here says a player caused anything."
            "</div>" + blocks)

    # Other ---------------------------------------------------------------

    def squad(self) -> str:
        """Best XI, then bench and reserve per line, redrawn when a new match lands."""
        stamp = tuple(self.q("SELECT COUNT(*), MAX(first_seen_at) FROM matches")[0])
        if _PICK_CACHE.get("stamp") != stamp:
            _PICK_CACHE.update(stamp=stamp, data=picker.build_all(picker.records_from_db(self.conn)))
        return picker.render(_PICK_CACHE["data"])

    def cards(self) -> str:
        """The 4-3-3 cards from slot_ranking, redrawn when a new match lands."""
        stamp = tuple(self.q("SELECT COUNT(*), MAX(first_seen_at) FROM matches")[0])
        if _XI_CACHE.get("stamp") != stamp:
            rows = slot_ranking.from_db(self.conn)
            pins = Path(os.environ.get("CLUBSXI_PRIMARY_SLOTS", "/config/primary_slots.txt"))
            if not pins.exists():
                pins = Path(__file__).resolve().parents[2] / "config" / "primary_slots.txt"
            _XI_CACHE.update(stamp=stamp, body=formation.render(
                slot_ranking.run_all(rows), slot_ranking.played(slot_ranking.Ctx(rows)),
                slot_ranking.load_primary(str(pins)), matches=slot_ranking.fc27_matches(rows),
                art_url="/static/card.png", standalone=False))
        return _XI_CACHE["body"]

    def old_squad(self) -> str:
        from . import config as config_mod
        from . import report as report_mod
        from . import squad as squad_mod

        practice = config_mod.Config().practice_club_id
        names = report_mod.archetype_labels(self.conn)
        chosen, info = squad_mod.pick(self.conn, practice_club_id=practice)
        ids = {r["latest_name"]: r["player_id"] for r in
               self.q("SELECT player_id, latest_name FROM players")}

        def build_of(p) -> str:
            b = p.best_build
            return names.get(b.archetype, b.archetype) if b else "?"

        def card(band: str, label: str, i: int) -> str:
            tiers = chosen[band]
            starter = tiers["starter"][i] if i < len(tiers["starter"]) else None
            badge = e(build_of(starter)) if starter else "open"
            rows = ""
            for tier, klass, star in (("starter", "gold", "&#9733;"),
                                      ("bench", "silver", "&#9733;"),
                                      ("reserve", "bronze", "&#9733;")):
                p = tiers[tier][i] if i < len(tiers[tier]) else None
                if p is None:
                    rows += ('<div class="tier ' + klass + ' none"><span class=star>'
                             + star + "</span><span>nobody with 3 games</span></div>")
                    continue
                link = ids.get(p.player)
                nm = ('<a href="/player/' + e(link) + '">' + e(p.player) + "</a>"
                      if link else e(p.player))
                rows += ('<div class="tier ' + klass + '"><span class=star>' + star
                         + '</span><div class=who><div class=nm>' + nm
                         + "</div><div class=bd>" + e(build_of(p)) + " · "
                         + str(p.games) + " games</div></div></div>")
            name = e(starter.player) if starter else "open slot"
            return ('<div class="fut"><div class=band>'
                    + label + "</div><div class=badge>" + badge + "</div>"
                    '<div class=tiers>' + rows + "</div><div class=name>" + name
                    + "</div><div class=foot>gold starts · silver bench · bronze reserve"
                    "</div></div>")

        out = ["<h1>The eleven</h1>",
               "<p class=sub>Eleven cards: three attack, three midfield, four "
               "defence, one keeper. Gold star starts, silver is bench, bronze is "
               "reserve, each with the build to run. Redrawn "
               "from the database every time you open this page.</p>"]
        for band, label, title in (("forward", "ATK", "Attack"),
                                   ("midfielder", "MID", "Midfield"),
                                   ("defender", "DEF", "Defence"),
                                   ("goalkeeper", "GK", "Goal")):
            slots = dict(squad_mod.FORMATION)[band]
            out.append('<h2 class=sec>' + title + "</h2>")
            out.append('<div class=row>' + "".join(
                card(band, label, i) for i in range(slots)) + "</div>")
        eligible = ", ".join(b + " " + str(n) for b, n in info["eligible"].items())
        out.append('<div class="note">Attack and midfield ranked on goals plus '
                   "assists per 90, practice club taken out, thin samples pulled "
                   "toward the average. Defence ranked on EA rating above what the "
                   "player's own numbers predict, weaker evidence. Keeper listed by "
                   "games, not ranked. One person per tier; two accounts of one person "
                   "count as one. Needs 3 full games in the position. People with "
                   "that: " + e(eligible) + ".</div>")
        return "".join(out)

    def scrims(self) -> str:
        rows = self.q("SELECT raw_json FROM matches WHERE match_type='friendlyMatch' "
                      "AND source='own' ORDER BY match_timestamp")
        return scrims.body(scrims.scored(json.loads(r["raw_json"]) for r in rows))

    def polls(self) -> str:
        rows = self.q(
            "SELECT * FROM poll_log ORDER BY id DESC LIMIT 100")
        out = [[
            when(r["started_at"]),
            (str(int(r["finished_at"]) - int(r["started_at"])) + "s"
             if r["finished_at"] else "running"),
            r["calls_made"], r["calls_failed"], r["matches_seen"],
            r["matches_new"], r["matches_duplicate"],
            ('<span class=ghost>' + e(r["errors"])[:120] + "</span>"
             if r["errors"] else ""),
        ] for r in rows]
        return ("<h1>Poll log</h1><p class=sub>One row per cycle. New matches "
                "only appear after games are played.</p>"
                + table(["Started", "Took", "Calls", "Failed", "Seen", "New",
                         "Duplicate", "Errors"], out, {2, 3, 4, 5, 6}))

    def raw(self, match_id: str) -> str:
        rows = self.q("SELECT raw_json FROM matches WHERE match_id=?",
                      (match_id,))
        if not rows:
            return "<h1>Not found</h1>"
        pretty = json.dumps(json.loads(rows[0]["raw_json"]), indent=2)
        return ("<h1>Raw match " + e(match_id) + "</h1>"
                '<p class=sub>Exactly what EA sent, nothing removed. '
                '<a href="/match/' + e(match_id) + '">back to the match</a></p>'
                "<pre>" + e(pretty) + "</pre>")


def build_handler(db_path: Path, our_clubs: dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ClubsXI"

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            params = {k: v[0] for k, v in
                      urllib.parse.parse_qs(parsed.query).items()}

            # Read-only connection. The collector is the only writer.
            conn = sqlite3.connect(
                "file:" + str(db_path) + "?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            views = Views(conn, our_clubs)

            try:
                if path == "/":
                    body, title = views.overview(), "Overview"
                elif path == "/matches":
                    body, title = views.matches(params), "Matches"
                elif path == "/players":
                    body, title = views.players(), "Players"
                elif path == "/positions":
                    body, title = views.positions(params), "Positions"
                elif path == "/squad":
                    body, title = views.squad(), "Squad"
                elif path == "/cards":
                    body, title = views.cards(), "Squad"
                    path = "/squad"
                elif path == "/scrims":
                    body, title = views.scrims(), "Scrims"
                elif path == "/scores":
                    body, title = player_score.render(conn), "Scores"
                elif path == "/polls":
                    body, title = views.polls(), "Poll log"
                elif path.startswith("/match/"):
                    body, title = views.match_detail(path[7:]), "Match"
                    path = "/matches"
                elif path.startswith("/player/"):
                    body, title = views.player_detail(path[8:]), "Player"
                    path = "/players"
                elif path.startswith("/raw/"):
                    body, title = views.raw(path[5:]), "Raw"
                    path = "/matches"
                elif path == "/static/card.png":
                    # Optional card art. The cards still work without it.
                    art = Path(__file__).with_name("assets") / "card.png"
                    if art.exists():
                        self._send(art.read_bytes(), "image/png")
                    else:
                        self._send(b"", "image/png", 404)
                    return
                elif path == "/healthz":
                    self._send(b"ok", "text/plain", 200)
                    return
                else:
                    self._send(page("Not found", path,
                                    "<h1>Not found</h1>"), status=404)
                    return
                self._send(page(title, path, body))
            except Exception as exc:
                log.exception("page failed")
                self._send(page("Error", path,
                                "<h1>Something went wrong</h1><pre>"
                                + e(str(exc)) + "</pre>"), status=500)
            finally:
                conn.close()

        def _send(self, payload: bytes, content_type: str = "text/html; charset=utf-8",
                  status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def serve(db_path: Path, host: str, port: int,
          our_clubs: dict[str, str]) -> None:
    server = ThreadingHTTPServer((host, port), build_handler(db_path, our_clubs))
    log.info("inspect UI on http://%s:%d (reading %s read-only)",
             host, port, db_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        server.server_close()
