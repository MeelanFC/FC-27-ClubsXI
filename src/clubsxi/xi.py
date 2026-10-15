"""The two questions, answered as player plus archetype.

  1. A player's top three positions.
  2. A starting eleven: who, and running what.

Why archetype and not an exact position: exact position is not in EA's data
and never will be. The archetype IS, and eight of the thirteen names are now
confirmed against human reports. A captain's own point is the key one:

    "progressor and boss are always cb"

The group reads the position off the archetype themselves. So the useful unit
is the pair (player, archetype), and a slot is really "broad position plus
archetype". That is exactly what the report already slices on.

Some people deliberately try different builds. They will move around
this chart and that is correct behaviour, not a bug.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# A 4-3-3 needs this many humans per band. Taken from the formation, not
# guessed: the default formation is 4-3-3 with no LM or RM.
DEFAULT_SHAPE = {"goalkeeper": 1, "defender": 4, "midfielder": 3, "forward": 3}

BAND_ORDER = ("goalkeeper", "defender", "midfielder", "forward")


@dataclass
class Role:
    """One (player, broad position, archetype) that really happened."""
    player: str
    band: str
    archetype_id: str
    archetype_name: str
    verified: bool
    games: int
    last: int
    rating: float | None

    @property
    def label(self) -> str:
        name = self.archetype_name + ("" if self.verified else "?")
        return self.archetype_id + " " + name


def roles(conn: sqlite3.Connection, *,
          club_ids: list[str] | None = None) -> list[Role]:
    """Every (player, band, archetype) with near-complete games behind it."""
    where = ["mc.is_our_club = 1", "s.is_real_appearance = 1",
             "s.appearance_class = 'full'", "m.validity = 'ok'"]
    args: list[str] = []
    if club_ids:
        where.append("s.club_id IN (" + ",".join("?" for _ in club_ids) + ")")
        args.extend(club_ids)

    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS player, "
        "  s.pos AS band, s.archetype_id, "
        "  COALESCE(a.name, 'unknown') AS arch_name, "
        "  COALESCE(a.verified, 0) AS verified, "
        "  COUNT(*) AS games, MAX(m.match_timestamp) AS last, "
        "  AVG(NULLIF(s.rating, 0)) AS rating "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "LEFT JOIN archetype_map a ON a.archetype_id = s.archetype_id "
        "WHERE " + " AND ".join(where) +
        " GROUP BY player, s.pos, s.archetype_id", tuple(args)).fetchall()

    return [Role(
        player=r["player"], band=r["band"] or "unknown",
        archetype_id=str(r["archetype_id"]),
        archetype_name=r["arch_name"], verified=bool(r["verified"]),
        games=r["games"], last=r["last"] or 0, rating=r["rating"],
    ) for r in rows]


def _order(role: Role) -> tuple:
    """Most played, then most recent. Habit, not skill."""
    return (-role.games, -role.last, role.player, role.archetype_id)


def top_roles(conn: sqlite3.Connection, *, limit: int = 3,
              club_ids: list[str] | None = None) -> dict[str, list[Role]]:
    """Each player's top few (position, archetype) pairs. Question one."""
    grouped: dict[str, list[Role]] = {}
    for role in roles(conn, club_ids=club_ids):
        grouped.setdefault(role.player, []).append(role)
    for player, items in grouped.items():
        items.sort(key=_order)
        grouped[player] = items[:limit] if limit else items
    return dict(sorted(grouped.items(),
                       key=lambda kv: -sum(r.games for r in kv[1])))


def starting_eleven(conn: sqlite3.Connection, *,
                    shape: dict[str, int] | None = None,
                    club_ids: list[str] | None = None) -> tuple[list[Role], list[str]]:
    """Eleven (player, archetype) picks. Question two.

    One appearance per person. Bands are filled scarcest first, so the hard
    jobs are allocated before the crowded ones. Within a band, whoever has
    played that exact (band, archetype) most goes in.

    Returns (picks, gaps) where gaps names bands we could not fill.
    """
    shape = shape or DEFAULT_SHAPE
    pool = sorted(roles(conn, club_ids=club_ids), key=_order)

    by_band: dict[str, list[Role]] = {}
    for role in pool:
        by_band.setdefault(role.band, []).append(role)

    # Scarcest band first. Filling forwards before keepers is how you end up
    # with no keeper.
    bands = sorted(shape, key=lambda b: (
        len({r.player for r in by_band.get(b, [])}), BAND_ORDER.index(b)))

    picks: list[Role] = []
    used: set[str] = set()
    gaps: list[str] = []

    for band in bands:
        wanted = shape[band]
        taken = 0
        for role in by_band.get(band, []):
            if taken >= wanted:
                break
            if role.player in used:
                continue
            picks.append(role)
            used.add(role.player)
            taken += 1
        if taken < wanted:
            gaps.append(band + ": " + str(wanted - taken)
                        + " of " + str(wanted) + " left to AI")

    picks.sort(key=lambda r: (BAND_ORDER.index(r.band), -r.games))
    return picks, gaps


def top_roles_text(conn: sqlite3.Connection, *, limit: int = 3,
                   club_ids: list[str] | None = None) -> str:
    grouped = top_roles(conn, limit=limit, club_ids=club_ids)
    out = ["  Each player's top " + str(limit) + " builds, most played first.",
           "  Position is EA's broad one. The archetype is exact and mostly",
           "  confirmed, so you can read the real position off it yourselves.",
           "  A ? means the archetype name is unconfirmed.", ""]

    for player, items in grouped.items():
        out.append("  " + player)
        for i, r in enumerate(items, start=1):
            out.append("      " + str(i) + ". " + r.band.ljust(11)
                       + r.label.ljust(17)
                       + str(r.games).rjust(3) + " games   EA rating "
                       + (format(r.rating, ".2f") if r.rating else " -  "))
        out.append("")
    if not grouped:
        out.append("  Nothing counts yet.")
    return "\n".join(out)


def starting_eleven_text(conn: sqlite3.Connection, *,
                         shape: dict[str, int] | None = None,
                         club_ids: list[str] | None = None) -> str:
    picks, gaps = starting_eleven(conn, shape=shape, club_ids=club_ids)
    shape = shape or DEFAULT_SHAPE
    counts = " ".join(str(shape[b]) + " " + b for b in BAND_ORDER if shape.get(b))

    out = ["  Shape: " + counts, "",
           "  " + "POSITION".ljust(12) + "PLAYER".ljust(20)
           + "ARCHETYPE".ljust(17) + "GAMES  RATING"]

    for r in picks:
        out.append("  " + r.band.ljust(12) + r.player.ljust(20)
                   + r.label.ljust(17) + str(r.games).rjust(4) + "   "
                   + (format(r.rating, ".2f") if r.rating else " -  "))

    if gaps:
        out.append("")
        for gap in gaps:
            out.append("  ! " + gap)

    out.append("")
    out.append("  Picked by who has played that build most, not by who is")
    out.append("  better. Nobody has the 20 games in a role needed to judge")
    out.append("  that. One slot each. Scarce jobs filled first.")
    return "\n".join(out)
