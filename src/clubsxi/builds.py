"""What each build actually does, measured across everyone we have ever seen.

The point of this module is one sentence: "Player X is our worst forward" is a
judgement about a person, and it is probably wrong. "Spark forwards score
0.35 per 90 across the whole league while Magicians score 0.94" is a fact
about a build, and it turns a benching into a fix that costs nothing but
in-game build time.

This is the one analysis where the opposition's players matter most. Our own
twenty rotate through builds by habit and availability, so a profile built
only from us is really a profile of our rota. The opponents did not choose
their builds to suit our squad, so including them is what makes a build
profile a fact about the game rather than a fact about us.

Nothing here ranks a person. It ranks builds, and then says which of your
people are running a weak one for the job they do.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

MATCH_SECONDS = 5400.0

# A build profile needs this much behind it before it is printed as evidence.
MIN_APPEARANCES = 8
MIN_PLAYERS = 4

# A player needs this many games on a build before we comment on their choice.
MIN_PLAYER_GAMES = 4

# Below this gap in goals plus assists per 90, changing build is not worth
# anybody's time.
WORTH_MENTIONING = 0.25


@dataclass
class Profile:
    band: str
    archetype_id: str
    name: str
    verified: bool
    appearances: int
    players: int
    opponent_appearances: int
    goals_90: float
    assists_90: float
    shots_90: float
    conversion: float | None
    passes_90: float
    pass_pct: float | None
    tackles_90: float
    rating: float | None

    @property
    def label(self) -> str:
        return self.archetype_id + " " + self.name + ("" if self.verified else "?")

    @property
    def output_90(self) -> float:
        return self.goals_90 + self.assists_90

    @property
    def trusted(self) -> bool:
        return (self.appearances >= MIN_APPEARANCES
                and self.players >= MIN_PLAYERS)


def profiles(conn: sqlite3.Connection) -> list[Profile]:
    """One row per position and build, across our players and the opposition."""
    rows = conn.execute(
        "SELECT s.pos AS band, s.archetype_id, "
        "  COALESCE(a.name, 'unknown') AS arch_name, "
        "  COALESCE(a.verified, 0) AS verified, "
        "  COUNT(*) AS appearances, "
        "  COUNT(DISTINCT s.player_id) AS players, "
        "  SUM(CASE WHEN mc.is_our_club = 0 THEN 1 ELSE 0 END) AS opponents, "
        "  SUM(s.seconds_played) AS seconds, "
        "  SUM(s.goals) AS goals, SUM(s.assists) AS assists, "
        "  SUM(s.shots) AS shots, SUM(s.passes_made) AS passes, "
        "  SUM(s.pass_attempts) AS pass_attempts, "
        "  SUM(s.tackles_made) AS tackles, "
        "  AVG(NULLIF(s.rating, 0)) AS rating "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN archetype_map a ON a.archetype_id = s.archetype_id "
        "WHERE s.is_real_appearance = 1 AND s.appearance_class = 'full' "
        "  AND m.validity = 'ok' "
        "GROUP BY s.pos, s.archetype_id").fetchall()

    out: list[Profile] = []
    for r in rows:
        n90 = max(r["seconds"] or 0, 1) / MATCH_SECONDS
        shots = r["shots"] or 0
        attempts = r["pass_attempts"] or 0
        out.append(Profile(
            band=r["band"] or "unknown",
            archetype_id=str(r["archetype_id"]),
            name=r["arch_name"], verified=bool(r["verified"]),
            appearances=r["appearances"], players=r["players"],
            opponent_appearances=r["opponents"] or 0,
            goals_90=(r["goals"] or 0) / n90,
            assists_90=(r["assists"] or 0) / n90,
            shots_90=shots / n90,
            conversion=((r["goals"] or 0) / shots * 100) if shots else None,
            passes_90=(r["passes"] or 0) / n90,
            pass_pct=((r["passes"] or 0) / attempts * 100) if attempts else None,
            tackles_90=(r["tackles"] or 0) / n90,
            rating=r["rating"],
        ))

    out.sort(key=lambda p: (p.band, -p.output_90))
    return out


def player_builds(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """Which build each of our players runs in each position, and how often."""
    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS player, "
        "  s.pos AS band, s.archetype_id, COUNT(*) AS games, "
        "  SUM(s.seconds_played) AS seconds, "
        "  SUM(s.goals) AS goals, SUM(s.assists) AS assists "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1 AND s.is_real_appearance = 1 "
        "  AND s.appearance_class = 'full' AND m.validity = 'ok' "
        "GROUP BY player, s.pos, s.archetype_id").fetchall()

    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["player"], r["band"] or "unknown")
        entry = out.setdefault(key, {"total": 0, "builds": {}})
        entry["total"] += r["games"]
        n90 = max(r["seconds"] or 0, 1) / MATCH_SECONDS
        entry["builds"][str(r["archetype_id"])] = {
            "games": r["games"],
            "output_90": ((r["goals"] or 0) + (r["assists"] or 0)) / n90,
        }
    return out


def suggestions(conn: sqlite3.Connection) -> list[dict]:
    """Our players who mainly run a build the league says is weak for that job.

    Only fires when the league profile is trustworthy, the player has enough
    games on it, and the gap is big enough to be worth the build time.
    """
    by_band: dict[str, list[Profile]] = {}
    for p in profiles(conn):
        if p.trusted:
            by_band.setdefault(p.band, []).append(p)

    everything = player_builds(conn)

    # A build is a build. Somebody who runs Magician up front already owns it
    # and can bring it to midfield, so do not tell them to make one.
    owned: dict[str, set[str]] = {}
    for (player, _band), entry in everything.items():
        owned.setdefault(player, set()).update(entry["builds"])

    out: list[dict] = []
    for (player, band), entry in everything.items():
        options = by_band.get(band, [])
        if len(options) < 2:
            continue

        main_id, main_use = max(entry["builds"].items(),
                                key=lambda kv: kv[1]["games"])
        if main_use["games"] < MIN_PLAYER_GAMES:
            continue

        current = next((p for p in options if p.archetype_id == main_id), None)
        best = max(options, key=lambda p: p.output_90)
        if current is None or best.archetype_id == main_id:
            continue

        gap = best.output_90 - current.output_90
        if gap < WORTH_MENTIONING:
            continue

        out.append({
            "player": player, "band": band,
            "current": current, "best": best, "gap": gap,
            "games_on_current": main_use["games"],
            "their_output": main_use["output_90"],
            "has_it_here": best.archetype_id in entry["builds"],
            "owns_it": best.archetype_id in owned.get(player, set()),
            "beating_their_build": main_use["output_90"] > current.output_90,
        })

    out.sort(key=lambda d: -d["gap"] * d["games_on_current"])
    return out


def _fmt(value: float | None, places: int = 2) -> str:
    return format(value, "." + str(places) + "f") if value is not None else " - "


def profiles_text(conn: sqlite3.Connection) -> str:
    out = ["  What each build does, across EVERY player we have seen,",
           "  ours and the opposition's. Opponents matter here: they did not",
           "  pick their builds to suit our squad, so including them makes",
           "  this a fact about the game rather than a fact about our rota.",
           "",
           "  OPP counts appearances for any club outside ours, including history.",
           "  A ? means the archetype name is unconfirmed.",
           "  thin means fewer than " + str(MIN_APPEARANCES) + " games or "
           + str(MIN_PLAYERS) + " different players behind it.", ""]

    current_band = None
    for p in profiles(conn):
        if p.band != current_band:
            current_band = p.band
            out.append("")
            out.append("  " + p.band.upper())
            out.append("      " + "BUILD".ljust(18) + "GMS  OPP   G/90  A/90"
                       + "   SH/90  CONV   PASS/90  PASS%  RATING")
        out.append("      " + p.label.ljust(18)
                   + str(p.appearances).rjust(3) + str(p.opponent_appearances).rjust(5)
                   + _fmt(p.goals_90).rjust(7) + _fmt(p.assists_90).rjust(6)
                   + _fmt(p.shots_90).rjust(8)
                   + (_fmt(p.conversion, 0) + "%").rjust(7)
                   + _fmt(p.passes_90, 1).rjust(10)
                   + (_fmt(p.pass_pct, 0) + "%").rjust(7)
                   + _fmt(p.rating).rjust(8)
                   + ("" if p.trusted else "   thin"))
    out.append("")
    out.append("  GMS is total appearances. OPP is how many of those were the")
    out.append("  opposition's players rather than ours.")
    return "\n".join(out)


def suggestions_text(conn: sqlite3.Connection) -> str:
    found = suggestions(conn)
    out = ["  Our players mainly running a build the league says is weak for",
           "  the job they do. This is a fix, not a benching.", ""]

    footer = [
        "  The gap is between BUILDS, not between people. Somebody on",
        "  a weak build is not a weak player.",
    ]

    if not found:
        out.append("  Nobody is clearly on the wrong build for their position.")
        out.append("")
        out.extend(footer)
        return "\n".join(out)

    for f in found:
        current, best = f["current"], f["best"]
        out.append("  " + f["player"] + " at " + f["band"])
        out.append("      runs " + current.label + " in "
                   + str(f["games_on_current"]) + " games, producing "
                   + _fmt(f["their_output"]) + " per 90")
        out.append("      league says " + current.label + " gives "
                   + _fmt(current.output_90) + " per 90 over "
                   + str(current.appearances) + " games")
        out.append("      league says " + best.label + " gives "
                   + _fmt(best.output_90) + " per 90 over "
                   + str(best.appearances) + " games")
        if f["has_it_here"]:
            out.append("      He already uses that build here. Just more of it.")
        elif f["owns_it"]:
            out.append("      HE ALREADY OWNS THAT BUILD, he uses it in another")
            out.append("      position. Nothing to make, just bring it.")
        else:
            out.append("      He would need to build it. Costs time, not money.")
        if f["beating_their_build"]:
            out.append("      Note: he is ALREADY beating what his build")
            out.append("      normally gives. This is about the build's ceiling,")
            out.append("      not about him underperforming.")
        out.append("")

    out.extend(footer)
    return "\n".join(out)
