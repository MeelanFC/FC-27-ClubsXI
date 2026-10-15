"""Comparing players honestly: adjust for the club, then shrink small samples.

Two mistakes this module exists to avoid, both found in testing.

MISTAKE ONE, frequency. Ranking by games played measures who turns up, and it
punishes anyone who rotates builds. It dropped the best forward in the squad
because his games were split across three archetypes.

MISTAKE TWO, raw output. The fix for the first mistake is worse if applied
naively. When many matches are at a practice club against much weaker
opposition, and the SAME player produces measurably more there. Ranking on raw
per-90 output just swaps one confound for another.

So: pool a player's games across builds, convert to a rate, subtract the
measured practice-club premium, then pull the result toward the league average
by an amount that depends on how noisy the metric actually is.

Every number here is MEASURED from the database, not assumed. The premium, the
league averages and the shrinkage strength all recompute as games arrive.

What this module refuses to do:
  - Rank goalkeepers or defenders. Measured between-player variance on every
    defensive metric we hold is zero. They are not close calls, they are
    genuinely indistinguishable with this data.
  - Use shot volume for forwards. Measured as pure noise.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

# EA match length in seconds. Used only to turn totals into a rate.
MATCH_SECONDS = 5400.0

BANDS = ("goalkeeper", "defender", "midfielder", "forward")

# Bands we will not put in order. Not a sample size problem: the measured
# spread between our defenders is entirely game-to-game noise.
UNRANKABLE = ("defender", "goalkeeper")

# Used when there is not enough data to measure the shrinkage strength.
# Deliberately heavy: when we do not know how noisy a metric is, assume noisy.
FALLBACK_K = 10.0

# A player needs this many near-complete games in a band before any number is
# printed for them at all.
MIN_APPEARANCES = 3


@dataclass
class Appearance:
    player: str
    club_id: str
    band: str
    archetype_id: str
    seconds: int
    goals: int
    assists: int
    rating: float | None

    @property
    def n90(self) -> float:
        return max(self.seconds, 1) / MATCH_SECONDS

    @property
    def contribution_rate(self) -> float:
        """Goals plus assists per 90."""
        return (self.goals + self.assists) / self.n90


@dataclass
class Score:
    player: str
    band: str
    appearances: int
    raw: float
    adjusted: float
    shrunk: float
    prior_weight: float
    rating: float | None
    practice_share: float
    builds: dict[str, int]

    @property
    def confidence(self) -> str:
        """How much of the number is really the player, and how much is prior."""
        if self.prior_weight >= 0.6:
            return "mostly average, " + str(round(self.prior_weight * 100)) + "% prior"
        if self.prior_weight >= 0.35:
            return "thin, " + str(round(self.prior_weight * 100)) + "% prior"
        return "comparable, " + str(round(self.prior_weight * 100)) + "% prior"

    @property
    def top_build(self) -> str:
        if not self.builds:
            return ""
        return max(self.builds.items(), key=lambda kv: kv[1])[0]


def appearances(conn: sqlite3.Connection, *, ours_only: bool = True
                ) -> list[Appearance]:
    """Every near-complete appearance in a completed match.

    ours_only=False includes opponents and both sides of their backfilled
    matches, broadening the league average beyond our own rota.
    """
    where = ["s.is_real_appearance = 1", "s.appearance_class = 'full'",
             "m.validity = 'ok'"]
    if ours_only:
        where.append("mc.is_our_club = 1")

    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS player, "
        "  s.club_id, s.pos AS band, s.archetype_id, s.seconds_played, "
        "  s.goals, s.assists, s.rating, mc.is_our_club "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE " + " AND ".join(where)).fetchall()

    return [Appearance(
        player=r["player"], club_id=str(r["club_id"]),
        band=r["band"] or "unknown", archetype_id=str(r["archetype_id"]),
        seconds=r["seconds_played"] or 0, goals=r["goals"] or 0,
        assists=r["assists"] or 0, rating=r["rating"],
    ) for r in rows]


def league_prior(conn: sqlite3.Connection) -> dict[str, float]:
    """Average goals plus assists per 90 by band, across everyone we have seen.

    Includes the opposition. Their players are not chosen by our rota, so they
    make a fairer baseline than our own twenty.
    """
    totals: dict[str, list[float]] = {}
    for a in appearances(conn, ours_only=False):
        totals.setdefault(a.band, []).append(a.contribution_rate)
    return {band: (sum(v) / len(v)) for band, v in totals.items() if v}


def is_practice(club_id: str, practice_club_id: str | None) -> bool:
    """True when club_id is one of the practice clubs.

    The setting may hold several ids, comma separated, because the practice
    club can change id between game years (EA gave new ids for FC27).
    """
    if not practice_club_id:
        return False
    return club_id in {part.strip() for part in practice_club_id.split(",")}


def practice_premium(conn: sqlite3.Connection, practice_club_id: str,
                     *, min_each_side: int = 3) -> dict[str, float]:
    """How much more the SAME player produces at the practice club.

    Measured within player, so it cannot be explained away by the practice club
    simply having better players in it. Returns per band, plus an "all" key.
    Returns an empty dict when nobody has enough games on both sides, which is
    the honest answer early on.
    """
    by_player: dict[tuple[str, str], dict[str, list[float]]] = {}
    for a in appearances(conn):
        side = "practice" if is_practice(a.club_id, practice_club_id) else "main"
        by_player.setdefault((a.player, a.band), {}).setdefault(
            side, []).append(a.contribution_rate)

    gaps: dict[str, list[float]] = {}
    for (_player, band), sides in by_player.items():
        practice = sides.get("practice", [])
        main = sides.get("main", [])
        if len(practice) < min_each_side or len(main) < min_each_side:
            continue
        gap = sum(practice) / len(practice) - sum(main) / len(main)
        gaps.setdefault(band, []).append(gap)
        gaps.setdefault("all", []).append(gap)

    return {band: sum(v) / len(v) for band, v in gaps.items() if v}


def shrinkage_k(conn: sqlite3.Connection, band: str,
                *, min_players: int = 4) -> float:
    """How many games of evidence before we believe half of what we see.

    Splits the spread in per-90 output into game-to-game noise and real
    difference between players. k = noise / real difference. A big k means the
    metric barely separates people and needs a lot of games. If the real
    difference measures as zero or negative, the metric cannot separate these
    players at all and we return infinity.
    """
    by_player: dict[str, list[float]] = {}
    for a in appearances(conn):
        if a.band == band:
            by_player.setdefault(a.player, []).append(a.contribution_rate)

    usable = {p: v for p, v in by_player.items() if len(v) >= 2}
    if len(usable) < min_players:
        return FALLBACK_K

    within: list[float] = []
    means: list[float] = []
    for values in usable.values():
        mean = sum(values) / len(values)
        means.append(mean)
        within.extend((v - mean) ** 2 for v in values)

    n_obs = sum(len(v) for v in usable.values())
    within_var = sum(within) / max(n_obs - len(usable), 1)

    grand = sum(means) / len(means)
    observed_between = sum((m - grand) ** 2 for m in means) / max(
        len(means) - 1, 1)
    avg_n = n_obs / len(usable)

    # Observed spread between players already contains noise. Take it out.
    true_between = observed_between - within_var / avg_n
    if true_between <= 0:
        return math.inf
    return within_var / true_between


def scores(conn: sqlite3.Connection, band: str, *,
           practice_club_id: str | None = None,
           min_appearances: int = MIN_APPEARANCES) -> list[Score]:
    """Players in a band, best first, club adjusted and shrunk."""
    prior = league_prior(conn).get(band, 0.0)
    k = shrinkage_k(conn, band)
    premium = 0.0
    if practice_club_id:
        gaps = practice_premium(conn, practice_club_id)
        premium = gaps.get(band, gaps.get("all", 0.0))

    grouped: dict[str, list[Appearance]] = {}
    for a in appearances(conn):
        if a.band == band:
            grouped.setdefault(a.player, []).append(a)

    out: list[Score] = []
    for player, items in grouped.items():
        n = len(items)
        if n < min_appearances:
            continue

        raw = sum(a.contribution_rate for a in items) / n
        share = (sum(1 for a in items if is_practice(a.club_id, practice_club_id)) / n
                 if practice_club_id else 0.0)
        adjusted = raw - premium * share

        if math.isinf(k):
            shrunk, weight = prior, 1.0
        else:
            shrunk = (n * adjusted + k * prior) / (n + k)
            weight = k / (n + k)

        ratings = [a.rating for a in items if a.rating]
        builds: dict[str, int] = {}
        for a in items:
            builds[a.archetype_id] = builds.get(a.archetype_id, 0) + 1

        out.append(Score(
            player=player, band=band, appearances=n, raw=raw,
            adjusted=adjusted, shrunk=shrunk, prior_weight=weight,
            rating=(sum(ratings) / len(ratings)) if ratings else None,
            practice_share=share, builds=builds,
        ))

    out.sort(key=lambda s: (-s.shrunk, -s.appearances, s.player))
    return out


def wasted(conn: sqlite3.Connection, *, min_each: int = 3) -> list[dict]:
    """Players whose most-played role is not their most productive one.

    The highest value output in the whole tool. Somebody playing their worst
    job every week is a bigger win than any selection tweak.
    """
    grouped: dict[str, dict[tuple[str, str], list[Appearance]]] = {}
    for a in appearances(conn):
        grouped.setdefault(a.player, {}).setdefault(
            (a.band, a.archetype_id), []).append(a)

    findings: list[dict] = []
    for player, roles in grouped.items():
        usable = {role: items for role, items in roles.items()
                  if len(items) >= min_each}
        if len(usable) < 2:
            continue

        def rate(items: list[Appearance]) -> float:
            return sum(a.contribution_rate for a in items) / len(items)

        most_played = max(usable.items(), key=lambda kv: len(kv[1]))
        best = max(usable.items(), key=lambda kv: rate(kv[1]))
        if most_played[0] == best[0]:
            continue

        findings.append({
            "player": player,
            "played": most_played[0],
            "played_games": len(most_played[1]),
            "played_rate": rate(most_played[1]),
            "best": best[0],
            "best_games": len(best[1]),
            "best_rate": rate(best[1]),
            "gain": rate(best[1]) - rate(most_played[1]),
        })

    findings.sort(key=lambda f: -f["gain"])
    return findings


def keeper_effect(conn: sqlite3.Connection) -> list[dict]:
    """What a human in goal is worth, measured separately in each club.

    Split by club on purpose. Pooled across both it would just be measuring
    which league the match was in.
    """
    rows = conn.execute(
        "SELECT mc.club_id, mc.club_name, mc.goals_for, mc.goals_against, "
        "  (SELECT COUNT(*) FROM player_match_stats s "
        "   WHERE s.match_id = mc.match_id AND s.club_id = mc.club_id "
        "     AND s.pos = 'goalkeeper' AND s.is_real_appearance = 1) AS keepers "
        "FROM match_clubs mc JOIN matches m ON m.match_id = mc.match_id "
        "WHERE mc.is_our_club = 1 AND m.validity = 'ok'").fetchall()

    tally: dict[tuple[str, bool], list[tuple[int, int]]] = {}
    names: dict[str, str] = {}
    for r in rows:
        names[str(r["club_id"])] = r["club_name"] or str(r["club_id"])
        key = (str(r["club_id"]), bool(r["keepers"]))
        tally.setdefault(key, []).append(
            (r["goals_for"] or 0, r["goals_against"] or 0))

    out: list[dict] = []
    for club_id in sorted(names):
        entry: dict = {"club": names[club_id]}
        for human in (True, False):
            games = tally.get((club_id, human), [])
            side = "human" if human else "ai"
            entry[side + "_games"] = len(games)
            entry[side + "_ga"] = (sum(g[1] for g in games) / len(games)
                                   if games else None)
            entry[side + "_gf"] = (sum(g[0] for g in games) / len(games)
                                   if games else None)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Text output
# ---------------------------------------------------------------------------

def _fmt(value: float | None, places: int = 2) -> str:
    return format(value, "." + str(places) + "f") if value is not None else " - "


def scores_text(conn: sqlite3.Connection, *,
                practice_club_id: str | None = None) -> str:
    prior = league_prior(conn)
    premium = practice_premium(conn, practice_club_id) if practice_club_id else {}
    overall = premium.get("all")

    out = ["  Goals plus assists per 90, adjusted and shrunk.", ""]
    if overall is not None:
        out.append("  Practice club premium, measured within player: "
                   + ("+" if overall >= 0 else "") + _fmt(overall)
                   + " per 90. Subtracted in proportion to how much of each")
        out.append("  player's record is practice games.")
    else:
        out.append("  Not enough games at both clubs yet to measure the")
        out.append("  practice premium, so no club adjustment is applied.")
    out.append("")

    for band in BANDS:
        k = shrinkage_k(conn, band)
        if band in UNRANKABLE:
            out.append("  " + band.upper() + ": not ranked.")
            if math.isinf(k):
                out.append("      Measured difference between our players "
                           "here is zero. The spread")
                out.append("      we can see is game-to-game noise and "
                           "nothing else.")
            else:
                out.append("      Goals and assists do not describe this job, "
                           "and the stats that")
                out.append("      would are not in EA's data. Noise level "
                           "measured at " + _fmt(k, 1) + " games.")
            out.append("")
            continue

        rows = scores(conn, band, practice_club_id=practice_club_id)
        out.append("  " + band.upper() + "   league average "
                   + _fmt(prior.get(band)) + " per 90, "
                   + ("noise too high to rank" if math.isinf(k)
                      else "needs " + _fmt(k, 1) + " games to half-believe"))
        if not rows:
            out.append("      nobody has " + str(MIN_APPEARANCES)
                       + "+ near-complete games here yet")
        for i, s in enumerate(rows, start=1):
            out.append("      " + str(i) + ". " + s.player.ljust(19)
                       + str(s.appearances).rjust(3) + " gms   raw "
                       + _fmt(s.raw) + "   adj " + _fmt(s.adjusted)
                       + "   SCORE " + _fmt(s.shrunk)
                       + "   " + s.confidence)
        out.append("")

    out.append("  raw is what happened. adj takes the practice club out.")
    out.append("  SCORE pulls small samples toward the league average, so a")
    out.append("  hot three games does not win and a quiet three does not")
    out.append("  lose. The percentage says how much of the score is still")
    out.append("  just the league average rather than the player.")
    return "\n".join(out)


def wasted_text(conn: sqlite3.Connection,
                arch_names: dict[str, str] | None = None) -> str:
    arch_names = arch_names or {}

    def role(pair) -> str:
        band, arch = pair
        name = arch_names.get(arch, arch)
        return band + " / " + name

    findings = wasted(conn)
    out = ["  Players whose most-played role is not their best one.",
           "  Both roles need at least 3 near-complete games.",
           "  Rates are goals plus assists per 90, not club adjusted.", ""]

    if not findings:
        out.append("  Nobody is clearly in the wrong job on the evidence "
                   "we have.")
        return "\n".join(out)

    for f in findings:
        out.append("  " + f["player"])
        out.append("      plays most: " + role(f["played"]).ljust(28)
                   + str(f["played_games"]) + " gms   "
                   + _fmt(f["played_rate"]) + " per 90")
        out.append("      best:       " + role(f["best"]).ljust(28)
                   + str(f["best_games"]) + " gms   "
                   + _fmt(f["best_rate"]) + " per 90")
        out.append("      moving him could be worth " + _fmt(f["gain"])
                   + " per 90 on this evidence")
        out.append("")
    return "\n".join(out)


def keeper_text(conn: sqlite3.Connection) -> str:
    out = ["  What a human in goal is worth, measured in each club "
           "separately.", ""]
    for e in keeper_effect(conn):
        out.append("  " + e["club"])
        out.append("      human keeper  " + str(e["human_games"]).rjust(3)
                   + " games   conceded " + _fmt(e["human_ga"])
                   + "   scored " + _fmt(e["human_gf"]))
        out.append("      AI keeper     " + str(e["ai_games"]).rjust(3)
                   + " games   conceded " + _fmt(e["ai_ga"])
                   + "   scored " + _fmt(e["ai_gf"]))
        if e["human_ga"] is not None and e["ai_ga"] is not None:
            out.append("      difference    "
                       + _fmt(e["ai_ga"] - e["human_ga"])
                       + " goals a game")
        out.append("")
    out.append("  Split by club on purpose. Pooled together it would just be")
    out.append("  measuring which league the game was in.")
    return "\n".join(out)
