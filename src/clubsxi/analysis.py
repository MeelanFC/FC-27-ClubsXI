"""Reads the collected evidence back out. No verdicts, no invented numbers.

Rules set in a design review. See docs/05-collector.md.

What counts as a near-complete appearance (D6):
  - EA reported them actually playing (not a ghost), and
  - they reached 90 percent of the longest appearance in that match, and
  - the match itself is clean (no DNF, nothing suspicious).

DNF matches (D5) are kept, flagged, and reported separately. They are excluded
from completed-match performance averages only, because a shortened game is not
an equivalent observation. They are NOT deleted, because opponents quit when
they are losing and dropping them would delete our best nights.

Nothing here orders players by team goal difference (D3, D4). At this sample
size that ranks circumstances. Team results are shown as a labelled fact beside
each row and never decide an order.

Careful with wording: team goals for and against are the WHOLE MATCH score in
matches featuring that player. There is no event timing in the payload, so
"while they were on the pitch" would be a different and unmeasurable quantity.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Review rule D4. Before this many near-complete appearances in the role
# being compared, NOTHING may be ordered by performance. Nobody is close to it
# and that is the point: the honest answer today is "we do not know yet".
PERFORMANCE_MIN_APPEARANCES = 20

# The floor below which a slice is not even worth listing as exposure.
EXPOSURE_MIN_APPEARANCES = 3

# Old name kept so nothing breaks. Points at the exposure floor, not the
# performance floor, because that is what it was used for.
DEFAULT_MIN_APPEARANCES = EXPOSURE_MIN_APPEARANCES

_CLEAN = ("s.is_real_appearance = 1 "
          "AND s.appearance_class = 'full' "
          "AND m.validity = 'ok'")
_MESSY = "s.is_real_appearance = 1"


def evidence_filter(include_messy: bool) -> str:
    return _MESSY if include_messy else _CLEAN


def confidence(appearances: int,
               floor: int = PERFORMANCE_MIN_APPEARANCES) -> str:
    """Plain words, deliberately cautious. Nothing here is a strong claim.

    Nothing reads better than "exposure only" until it clears the review's
    floor of 20 near-complete appearances in that role.
    """
    if appearances < EXPOSURE_MIN_APPEARANCES:
        return "barely seen"
    if appearances < floor:
        return "exposure only"
    if appearances < 40:
        return "comparable, thin"
    return "comparable"


@dataclass
class Slice:
    player_id: str
    player_name: str
    club_id: str
    pos: str
    archetype_id: str
    appearances: int
    team_gf: int
    team_ga: int
    wins: int
    draws: int
    losses: int
    goals: int
    assists: int
    avg_rating: float | None

    @property
    def diff(self) -> int:
        return self.team_gf - self.team_ga

    @property
    def diff_per_game(self) -> float:
        return self.diff / self.appearances if self.appearances else 0.0

    @property
    def gf_per_game(self) -> float:
        return self.team_gf / self.appearances if self.appearances else 0.0

    @property
    def ga_per_game(self) -> float:
        return self.team_ga / self.appearances if self.appearances else 0.0

    @property
    def output_per_game(self) -> float:
        if not self.appearances:
            return 0.0
        return (self.goals + self.assists) / self.appearances

    @property
    def qualified(self) -> bool:
        """True only when performance may influence ordering at all."""
        return self.appearances >= PERFORMANCE_MIN_APPEARANCES

    @property
    def confidence(self) -> str:
        return confidence(self.appearances)


def slices(conn: sqlite3.Connection, *, club_ids: list[str] | None = None,
           include_messy: bool = False) -> list[Slice]:
    """One row per player, club, broad position and archetype."""
    where = [evidence_filter(include_messy), "mc.is_our_club = 1"]
    args: list[str] = []
    if club_ids:
        where.append("s.club_id IN (" + ",".join("?" for _ in club_ids) + ")")
        args.extend(club_ids)

    rows = conn.execute(
        "SELECT s.player_id, "
        "  COALESCE(p.latest_name, s.player_id) AS player_name, "
        "  s.club_id, s.pos, s.archetype_id, "
        "  COUNT(*) AS appearances, "
        "  SUM(mc.goals_for) AS team_gf, SUM(mc.goals_against) AS team_ga, "
        "  SUM(mc.outcome = 'win') AS wins, "
        "  SUM(mc.outcome = 'draw') AS draws, "
        "  SUM(mc.outcome = 'loss') AS losses, "
        "  SUM(s.goals) AS goals, SUM(s.assists) AS assists, "
        "  AVG(NULLIF(s.rating, 0)) AS avg_rating "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE " + " AND ".join(where) +
        " GROUP BY s.player_id, s.club_id, s.pos, s.archetype_id",
        tuple(args)).fetchall()

    return [Slice(
        player_id=r["player_id"],
        player_name=r["player_name"],
        club_id=r["club_id"],
        pos=r["pos"] or "unknown",
        archetype_id=r["archetype_id"] or "?",
        appearances=r["appearances"],
        team_gf=r["team_gf"] or 0,
        team_ga=r["team_ga"] or 0,
        wins=r["wins"] or 0,
        draws=r["draws"] or 0,
        losses=r["losses"] or 0,
        goals=r["goals"] or 0,
        assists=r["assists"] or 0,
        avg_rating=r["avg_rating"],
    ) for r in rows]


def exposure_key(item: Slice) -> tuple:
    """How a player's own slices are ordered today.

    By how much we have actually seen them there, nothing else. Review
    decision D3 and D4: team goal difference at this sample size ranks
    circumstances, not players, so it does not order anything. It is shown
    beside the row as a labelled fact.
    """
    return (-item.appearances, item.pos, item.archetype_id)


def performance_key(item: Slice) -> tuple:
    """Reserved for when a slice clears the 20-appearance floor.

    Not used by the report yet. Kept so the intended order is written down:
    team results first, then sample size, then the player's own output.
    """
    return (
        -item.diff_per_game,
        -item.appearances,
        -item.output_per_game,
        item.avg_rating is None,
        -(item.avg_rating or 0.0),
    )


# Old name kept pointing at the honest ordering, so no caller silently keeps
# ranking by goal difference.
rank_key = exposure_key


def top_positions(conn: sqlite3.Connection, *,
                  club_ids: list[str] | None = None,
                  include_messy: bool = False,
                  min_appearances: int = EXPOSURE_MIN_APPEARANCES,
                  ) -> dict[str, dict]:
    """Per player: where they have actually been seen, most seen first.

    This is NOT a performance ranking. Ordering is by exposure only. Returns
    {player_id: {"name": str, "ranked": [Slice], "thin": [Slice]}} where
    "ranked" means listed and "thin" means barely seen.
    """
    grouped: dict[str, dict] = {}
    for item in slices(conn, club_ids=club_ids, include_messy=include_messy):
        entry = grouped.setdefault(item.player_id, {
            "name": item.player_name, "ranked": [], "thin": []})
        bucket = "ranked" if item.appearances >= min_appearances else "thin"
        entry[bucket].append(item)

    for entry in grouped.values():
        entry["ranked"].sort(key=exposure_key)
        entry["thin"].sort(key=lambda s: -s.appearances)
        entry["total"] = (sum(s.appearances for s in entry["ranked"])
                          + sum(s.appearances for s in entry["thin"]))

    return dict(sorted(grouped.items(),
                       key=lambda kv: -kv[1]["total"]))


def evidence_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How much of what we collected actually counts, and what got excluded."""
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "matches": one("SELECT COUNT(*) FROM matches"),
        "clean_matches": one(
            "SELECT COUNT(*) FROM matches WHERE validity = 'ok'"),
        "dnf_matches": one(
            "SELECT COUNT(*) FROM matches WHERE validity = 'dnf'"),
        "other_flagged": one(
            "SELECT COUNT(*) FROM matches WHERE validity NOT IN ('ok','dnf')"),
        "counting_appearances": one(
            "SELECT COUNT(*) FROM player_match_stats s "
            "JOIN matches m ON m.match_id = s.match_id WHERE " + _CLEAN),
        "excluded_appearances": one(
            "SELECT COUNT(*) FROM player_match_stats s "
            "JOIN matches m ON m.match_id = s.match_id "
            "WHERE NOT (" + _CLEAN + ")"),
        "ghosts": one("SELECT COUNT(*) FROM player_match_stats "
                      "WHERE appearance_class = 'ghost'"),
        "shorts": one("SELECT COUNT(*) FROM player_match_stats "
                      "WHERE appearance_class = 'short'"),
    }


# ---------------------------------------------------------------------------
# Combinations. Who was on the pitch together, and what the team did.
# ---------------------------------------------------------------------------

@dataclass
class Combo:
    player_ids: tuple[str, ...]
    names: tuple[str, ...]
    club_id: str
    games: int
    team_gf: int
    team_ga: int
    wins: int
    draws: int
    losses: int

    @property
    def diff(self) -> int:
        return self.team_gf - self.team_ga

    @property
    def diff_per_game(self) -> float:
        return self.diff / self.games if self.games else 0.0

    @property
    def confidence(self) -> str:
        return confidence(self.games)


def _counting_lineups(conn: sqlite3.Connection, *,
                      club_ids: list[str] | None = None,
                      include_messy: bool = False,
                      ) -> dict[tuple[str, str], dict]:
    """One entry per (match, our club): who counted, and how the game went."""
    where = [evidence_filter(include_messy), "mc.is_our_club = 1"]
    args: list[str] = []
    if club_ids:
        where.append("s.club_id IN (" + ",".join("?" for _ in club_ids) + ")")
        args.extend(club_ids)

    rows = conn.execute(
        "SELECT s.match_id, s.club_id, s.player_id, "
        "  COALESCE(p.latest_name, s.player_id) AS player_name, "
        "  mc.goals_for, mc.goals_against, mc.outcome "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE " + " AND ".join(where), tuple(args)).fetchall()

    games: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["match_id"], r["club_id"])
        game = games.setdefault(key, {
            "club_id": r["club_id"],
            "gf": r["goals_for"] or 0,
            "ga": r["goals_against"] or 0,
            "outcome": r["outcome"],
            "players": {},
        })
        game["players"][r["player_id"]] = r["player_name"]
    return games


def combinations_of_size(conn: sqlite3.Connection, size: int, *,
                         club_ids: list[str] | None = None,
                         include_messy: bool = False,
                         min_games: int = 3) -> list[Combo]:
    """Every group of `size` players that actually played together.

    `size=0` means the whole counting lineup exactly as it happened.
    """
    import itertools

    games = _counting_lineups(conn, club_ids=club_ids,
                              include_messy=include_messy)
    tally: dict[tuple[str, tuple[str, ...]], dict] = {}

    for game in games.values():
        ids = sorted(game["players"])
        groups = ([tuple(ids)] if size == 0
                  else list(itertools.combinations(ids, size)))
        for group in groups:
            key = (game["club_id"], group)
            entry = tally.setdefault(key, {
                "games": 0, "gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0,
                "names": tuple(game["players"][pid] for pid in group),
            })
            entry["games"] += 1
            entry["gf"] += game["gf"]
            entry["ga"] += game["ga"]
            entry["w"] += game["outcome"] == "win"
            entry["d"] += game["outcome"] == "draw"
            entry["l"] += game["outcome"] == "loss"

    combos = [Combo(
        player_ids=group, names=entry["names"], club_id=club_id,
        games=entry["games"], team_gf=entry["gf"], team_ga=entry["ga"],
        wins=entry["w"], draws=entry["d"], losses=entry["l"],
    ) for (club_id, group), entry in tally.items()
        if entry["games"] >= min_games]

    combos.sort(key=lambda c: (-c.diff_per_game, -c.games))
    return combos


def suggested_lineup(conn: sqlite3.Connection, *,
                     club_ids: list[str] | None = None,
                     include_messy: bool = False,
                     min_games: int = 3, limit: int = 5) -> list[Combo]:
    """Whole squads that actually took the pitch together, best first.

    This is not "the best eleven players". It is "these exact groups played,
    and here is what happened". A group that always appears because those
    people are always online is confounded, and the caller must say so.
    """
    return combinations_of_size(
        conn, 0, club_ids=club_ids, include_messy=include_messy,
        min_games=min_games)[:limit]
