"""The captain's depth chart.

Review rules D1, D3 and D8. This does NOT come from the data:

  - Exact positions do not exist anywhere in EA's payload.
  - The roster fields describe a player's build, not where they line up.
  - Confirmed in testing: one archetype was played at LW, ST and LCM in the
    same match, and Marauder appeared on a forward. Build and slot are
    independent.

So the captain writes the chart. This module holds it, checks it against what
actually happened, and prints the two things that make it useful on a match
night: who backs up whom, and where the squad has no cover at all.

The evidence line under a name always reads in broad terms, "defender games",
never "LB games", because that is all the API can honestly support.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# Broad position each slot belongs to. Used only to look up honest evidence,
# never to claim someone played that exact slot.
SLOT_BROAD = {
    "GK": "goalkeeper",
    "LB": "defender", "LCB": "defender", "CB": "defender",
    "RCB": "defender", "RB": "defender", "LWB": "defender", "RWB": "defender",
    "CDM": "midfielder", "LDM": "midfielder", "RDM": "midfielder",
    "LCM": "midfielder", "CM": "midfielder", "RCM": "midfielder",
    "LM": "midfielder", "RM": "midfielder", "CAM": "midfielder",
    "LW": "forward", "RW": "forward", "ST": "forward", "LS": "forward",
    "RS": "forward", "CF": "forward", "LF": "forward", "RF": "forward",
}

DEPTHS = ("starter", "bench", "reserve")

BANDS = ("goalkeeper", "defender", "midfielder", "forward")


def parse_can_play(text: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Reads the willingness file.

    Returns (can, wont). The data can only see where somebody HAS been put.
    Only a human knows who is willing to play somewhere they have not been
    tried, or who refuses a band the data has seen them in once.
    """
    can: dict[str, set[str]] = {}
    wont: dict[str, set[str]] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        name = match.group(1)
        for token in match.group(2).split(","):
            token = token.strip().lower()
            if not token:
                continue
            if token.startswith("-"):
                band = token[1:].strip()
                if band in BANDS:
                    wont.setdefault(name, set()).add(band)
            elif token in BANDS:
                can.setdefault(name, set()).add(token)

    return can, wont


def load_can_play(path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    if path is None or not Path(path).exists():
        return {}, {}
    return parse_can_play(Path(path).read_text(encoding="utf-8"))


@dataclass
class Slot:
    name: str
    picks: list[str] = field(default_factory=list)  # up to 3, "" means empty

    @property
    def broad(self) -> str | None:
        return SLOT_BROAD.get(self.name.upper())

    def pick(self, depth: int) -> str:
        return self.picks[depth] if depth < len(self.picks) else ""


@dataclass
class Chart:
    formation: str
    slots: list[Slot]
    notes: list[str] = field(default_factory=list)


_LINE = re.compile(r"^\s*([A-Za-z0-9_ .\-]+?)\s*=\s*(.*)$")


def parse(text: str) -> Chart:
    """Reads the captain's file. Blank picks are allowed and meaningful."""
    formation = ""
    slots: list[Slot] = []
    notes: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("FORMATION:"):
            formation = line.split(":", 1)[1].strip()
            continue
        match = _LINE.match(line)
        if not match:
            notes.append("could not read this line: " + line)
            continue
        name = match.group(1).upper()
        picks = [p.strip() for p in match.group(2).split(",")]
        picks = (picks + ["", "", ""])[:3]
        slots.append(Slot(name, picks))

    return Chart(formation or "not set", slots, notes)


def load(path: Path) -> Chart | None:
    if not path.exists():
        return None
    return parse(path.read_text(encoding="utf-8"))


def broad_appearances(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    """(player name, broad position) -> near-complete appearances for our clubs."""
    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS name, s.pos, "
        "  COUNT(*) AS games "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1 AND s.is_real_appearance = 1 "
        "  AND s.appearance_class = 'full' AND m.validity = 'ok' "
        "GROUP BY name, s.pos").fetchall()
    return {(r["name"], r["pos"]): r["games"] for r in rows}


def known_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT COALESCE(p.latest_name, s.player_id) "
        "FROM player_match_stats s "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1")}


def _last_seen(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS name, s.pos, "
        "  MAX(m.match_timestamp) AS last "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1 AND s.is_real_appearance = 1 "
        "  AND s.appearance_class = 'full' AND m.validity = 'ok' "
        "GROUP BY name, s.pos").fetchall()
    return {(r["name"], r["pos"]): (r["last"] or 0) for r in rows}


def suggest(chart: Chart, conn: sqlite3.Connection, *,
            can: dict[str, set[str]] | None = None,
            wont: dict[str, set[str]] | None = None,
            ) -> dict[str, list[str]]:
    """Fills blank bench and reserve spots with a suggestion.

    NOT a quality ranking. Nobody has the 20 games in a role that the review
    set as the floor for judging performance, so this cannot and does not say
    who is better. It says who actually does that job.

    The order is exactly the review's fallback: eligibility first, meaning
    they have really played in that broad band, then habit, meaning how often,
    then how recently.

    Anyone the captain has made first choice somewhere else is skipped. They
    are already committed, so naming them as cover elsewhere would be a lie
    about availability.
    """
    games = broad_appearances(conn)
    last = _last_seen(conn)
    can = can or {}
    wont = wont or {}

    # Someone the captain says can play a band counts as eligible there even
    # with zero recorded games. They sort last within the band, because habit
    # still beats a standing offer.
    for name, bands in can.items():
        for band in bands:
            games.setdefault((name, band), 0)

    # Nobody can start in two places at once. This grows as we suggest, so a
    # blank starter slot never gets a name already promised to another slot.
    starters = {slot.pick(0) for slot in chart.slots if slot.pick(0)}

    def ranked(band: str, exclude: set[str]) -> list[str]:
        pool = [(name, count) for (name, pos), count in games.items()
                if pos == band and name not in exclude
                and band not in wont.get(name, set())]
        pool.sort(key=lambda item: (-item[1],
                                    -last.get((item[0], band), 0),
                                    item[0]))
        return [name for name, _ in pool]

    out: dict[str, list[str]] = {slot.name: ["", "", ""]
                                 for slot in chart.slots}

    # Pass one: starters only, so the scarce people are allocated first.
    for slot in chart.slots:
        if slot.pick(0) or not slot.broad:
            continue
        named = {who for who in slot.picks if who}
        candidates = ranked(slot.broad, named | starters)
        if candidates:
            out[slot.name][0] = candidates[0]
            starters.add(candidates[0])

    # Pass two: cover. Backups may be shared between slots, because only one
    # of them will actually be needed on any given night.
    for slot in chart.slots:
        if not slot.broad:
            continue
        named = {who for who in slot.picks if who}
        named |= {who for who in out[slot.name] if who}
        candidates = ranked(slot.broad, named | starters)
        for depth in (1, 2):
            if slot.pick(depth):
                continue
            if candidates:
                out[slot.name][depth] = candidates.pop(0)

    return out


def problems(chart: Chart, conn: sqlite3.Connection, *,
             can: dict[str, set[str]] | None = None,
             wont: dict[str, set[str]] | None = None) -> list[str]:
    """What is wrong or missing. This is the most useful output early on."""
    found: list[str] = list(chart.notes)
    names = known_names(conn)
    seen = broad_appearances(conn)

    booked: dict[str, list[str]] = {}
    for slot in chart.slots:
        if not slot.broad:
            found.append(slot.name + " is not a slot name I recognise")
        for depth, who in enumerate(slot.picks):
            if not who:
                continue
            booked.setdefault(who, []).append(
                slot.name + " " + DEPTHS[depth])
            if who not in names:
                found.append(who + " (" + slot.name
                             + ") has never appeared in a match we hold")
            elif (slot.broad
                  and not seen.get((who, slot.broad))
                  and slot.broad not in (can or {}).get(who, set())):
                found.append(who + " is listed at " + slot.name
                             + " but has no near-complete "
                             + slot.broad + " games")

    for who, places in sorted(booked.items()):
        starters = [p for p in places if p.endswith("starter")]
        if len(starters) > 1:
            found.append(who + " is first choice in more than one slot: "
                         + ", ".join(starters))

    ideas = suggest(chart, conn, can=can, wont=wont)
    for slot in chart.slots:
        depth = [slot.pick(i) or ideas.get(slot.name, ["", "", ""])[i]
                 for i in range(3)]
        depth = [who for who in depth if who]
        if not depth:
            found.append(slot.name + ": nobody at all, set or worked out. "
                         "AI plays here.")
        elif len(depth) == 1:
            found.append(slot.name + ": only " + depth[0]
                         + ". No cover if they are not on.")

    return found


def band_depth(conn: sqlite3.Connection, *,
               can: dict[str, set[str]] | None = None,
               wont: dict[str, set[str]] | None = None,
               limit: int = 0) -> dict[str, list[tuple[str, int]]]:
    """Everyone who can play each band, in order, deepest first.

    This is the honest resolution. The API cannot tell LB from RCB, so a
    separate pecking order for those two would be invented. One order per
    band, and the slot chart below spreads it across the actual positions.
    """
    can = can or {}
    wont = wont or {}
    games = broad_appearances(conn)
    last = _last_seen(conn)

    for name, bands in can.items():
        for band in bands:
            games.setdefault((name, band), 0)

    out: dict[str, list[tuple[str, int]]] = {}
    for band in BANDS:
        rows = [(name, count) for (name, pos), count in games.items()
                if pos == band and band not in wont.get(name, set())]
        rows.sort(key=lambda item: (-item[1],
                                    -last.get((item[0], band), 0),
                                    item[0]))
        out[band] = rows[:limit] if limit else rows
    return out


def band_depth_text(conn: sqlite3.Connection, *,
                    can: dict[str, set[str]] | None = None,
                    wont: dict[str, set[str]] | None = None,
                    limit: int = 3) -> str:
    """Top N per band. The answer to "top three for each position"."""
    depth = band_depth(conn, can=can, wont=wont)
    out = ["  Top " + str(limit) + " for each position, whoever is online.",
           "  Ordered by near-complete games in that role, then how recent.",
           "  That is habit, not skill. Nobody has the 20 games needed to",
           "  judge skill yet.", ""]

    for band in BANDS:
        rows = depth.get(band, [])
        out.append("  " + band.upper())
        if not rows:
            out.append("      nobody has ever played here")
        for i, (name, count) in enumerate(rows[:limit], start=1):
            out.append("      " + str(i) + ". " + name.ljust(20)
                       + str(count) + " games")
        rest = rows[limit:]
        if rest:
            out.append("      then: " + ", ".join(
                n + " (" + str(c) + ")" for n, c in rest))
        out.append("")
    return "\n".join(out)


def render(chart: Chart, conn: sqlite3.Connection, *,
           with_suggestions: bool = True,
           can: dict[str, set[str]] | None = None,
           wont: dict[str, set[str]] | None = None) -> str:
    seen = broad_appearances(conn)
    ideas = (suggest(chart, conn, can=can, wont=wont)
             if with_suggestions else {})
    width = max([len(s.name) for s in chart.slots] + [4]) + 2
    cell_width = 26

    out = ["Formation: " + chart.formation + "   (set by the captain)", ""]
    out.append("  " + "SLOT".ljust(width)
               + "STARTER".ljust(cell_width)
               + "BENCH".ljust(cell_width) + "RESERVE")

    for slot in chart.slots:
        suggested = ideas.get(slot.name, ["", "", ""])
        cells = []
        for depth in range(3):
            who = slot.pick(depth)
            if who:
                games = seen.get((who, slot.broad or ""), 0)
                cells.append(who + " (" + str(games) + ")")
                continue
            idea = suggested[depth] if depth < len(suggested) else ""
            if idea:
                games = seen.get((idea, slot.broad or ""), 0)
                cells.append(idea + " (" + str(games) + ")*")
            else:
                cells.append("- nobody")
        out.append("  " + slot.name.ljust(width)
                   + cells[0].ljust(cell_width)
                   + cells[1].ljust(cell_width) + cells[2])

    out.append("")
    out.append("  * = suggested by the tool, not set by the captain.")
    out.append("    Suggestions are ordered by who has actually played that")
    out.append("    broad role, how often, and how recently. That is habit,")
    out.append("    NOT skill. Nobody has enough games to judge skill yet.")
    out.append("    Nobody is suggested as first choice in two slots. Cover")
    out.append("    IS shared, because only one slot will need them on the")
    out.append("    night, so the same name can appear on several benches.")
    out.append("")
    out.append("  Numbers in brackets are near-complete games in that BROAD")
    out.append("  role, not in that exact slot. The API cannot tell LB from")
    out.append("  RCB. A zero means we have never seen them in that band.")

    issues = problems(chart, conn, can=can, wont=wont)
    out.append("")
    if issues:
        out.append("  Gaps and warnings:")
        for issue in issues:
            out.append("    - " + issue)
    else:
        out.append("  No gaps. Every slot has a starter and a backup.")

    return "\n".join(out)
