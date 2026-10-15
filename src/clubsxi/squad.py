"""The squad command: top builds per person, and a 4-3-3 with three names a slot.

Two questions the group argues about, answered from evidence:

  1. What are each person's best builds?  Only builds they have actually
     played get a number. A build with no games says "no evidence". Nothing
     inherits a league average it never earned.

  2. Who starts, and running what?  A 4-3-3: one keeper, four defenders,
     three midfielders, three forwards. Every slot shows a starter, a bench
     name and a reserve, each with the build they should run.

How a player is scored, by broad position:

  forward, midfielder   goals plus assists per 90, near-complete games only,
                        with the measured practice-club premium taken out,
                        then pulled toward the league average by the measured
                        noise level (strength.py).
  defender              EA match rating above what the player's own numbers
                        predict (unseen.py), pulled toward zero the same way.
                        Goals do not describe this job. Interceptions are
                        shown beside it, not mixed into it.
  goalkeeper            not scored. Listed by games in goal with goals
                        conceded per game. There is nothing honest to rank on.

A build is scored the same way as the player, but only on games in that build,
and it is pulled toward the PLAYER'S OWN pooled number rather than the league.
So "best build" means "beats his other builds", which is the real question.

One person can play on two EA accounts (config/same_person.txt). Their records
are kept apart everywhere else, but here their games are pooled as one person.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from . import strength, unseen

FORMATION = (("goalkeeper", 1), ("defender", 4), ("midfielder", 3), ("forward", 3))
TIERS = ("starter", "bench", "reserve")

# Same human, two EA ids: account -> person, from config/same_person.txt.
from . import config as _config
SAME_PERSON = _config.same_person()

# Decoded from match stat pages. See docs/03-ea-api.md.
CODE_INTERCEPTIONS = 6

MIN_BUILD_GAMES = 2      # a build needs this many games to get its own number
MIN_PLAYER_GAMES = 3     # a player needs this many in a band to be picked

ROLE_WORDS = {
    "1": "keeper", "2": "sweeping keeper",
    "3": "ball-playing defender", "4": "stopper", "5": "engine defender",
    "6": "holding midfielder", "7": "deep passer", "8": "deep playmaker",
    "9": "creative midfielder", "10": "quick attacker", "11": "dribbling attacker",
    "12": "finisher", "13": "target striker",
}


@dataclass
class Game:
    player: str
    band: str
    archetype: str
    club_id: str
    seconds: int
    goals: int
    assists: int
    rating: float | None
    conceded: int
    interceptions: int
    features: list[float]

    @property
    def n90(self) -> float:
        return max(self.seconds, 1) / strength.MATCH_SECONDS


@dataclass
class BuildScore:
    archetype: str
    games: int
    value: float          # shrunk score, comparable within the band
    raw: float
    rating: float | None
    interceptions_90: float
    note: str = ""


@dataclass
class PlayerBand:
    player: str
    band: str
    games: int
    value: float
    rating: float | None
    interceptions_90: float
    conceded_per_game: float | None
    builds: list[BuildScore] = field(default_factory=list)

    @property
    def best_build(self) -> BuildScore | None:
        return self.builds[0] if self.builds else None


def _codes(*fields: str | None) -> dict[int, int]:
    out: dict[int, int] = {}
    for text in fields:
        for part in (text or "").split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                out[int(k)] = int(v)
    return out


def games(conn: sqlite3.Connection) -> list[Game]:
    rows = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS player, s.pos, "
        "  s.archetype_id, s.club_id, s.seconds_played, s.goals, s.assists, "
        "  s.rating, s.goals_conceded, s.mom, s.passes_made, s.pass_attempts, "
        "  s.tackles_made, s.tackle_attempts, s.event_aggregate_0, "
        "  s.event_aggregate_1, s.event_aggregate_2, s.event_aggregate_3 "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1 AND s.is_real_appearance = 1 "
        "  AND s.appearance_class = 'full' AND m.validity = 'ok'").fetchall()
    out: list[Game] = []
    for r in rows:
        passes = r["passes_made"] or 0
        attempts = r["pass_attempts"] or 0
        tackles = r["tackles_made"] or 0
        tackle_att = r["tackle_attempts"] or 0
        codes = _codes(r["event_aggregate_0"], r["event_aggregate_1"],
                       r["event_aggregate_2"], r["event_aggregate_3"])
        out.append(Game(
            player=_person(r["player"]), band=r["pos"] or "unknown",
            archetype=str(r["archetype_id"]), club_id=str(r["club_id"]),
            seconds=r["seconds_played"] or 0, goals=r["goals"] or 0,
            assists=r["assists"] or 0, rating=r["rating"],
            conceded=r["goals_conceded"] or 0,
            interceptions=codes.get(CODE_INTERCEPTIONS, 0),
            features=[float(r["goals"] or 0), float(r["assists"] or 0),
                      float(r["mom"] or 0), passes / 10.0,
                      max(attempts - passes, 0) / 10.0, float(tackles),
                      max(tackle_att - tackles, 0) / 10.0],
        ))
    return out


def _shrink_k(values_by_player: dict[str, list[float]]) -> float:
    """Games needed to half-believe a number. Same maths as strength.shrinkage_k."""
    usable = {p: v for p, v in values_by_player.items() if len(v) >= 2}
    if len(usable) < 4:
        return strength.FALLBACK_K
    within: list[float] = []
    means: list[float] = []
    for values in usable.values():
        mean = sum(values) / len(values)
        means.append(mean)
        within.extend((v - mean) ** 2 for v in values)
    n_obs = sum(len(v) for v in usable.values())
    within_var = sum(within) / max(n_obs - len(usable), 1)
    grand = sum(means) / len(means)
    between = sum((m - grand) ** 2 for m in means) / max(len(means) - 1, 1)
    true_between = between - within_var / (n_obs / len(usable))
    if true_between <= 0:
        return math.inf
    return within_var / true_between


def _shrunk(values: list[float], prior: float, k: float) -> float:
    n = len(values)
    if math.isinf(k):
        return prior
    return (n * sum(values) / n + k * prior) / (n + k)


def per_game_values(conn: sqlite3.Connection, all_games: list[Game],
                    practice_club_id: str | None) -> dict[str, dict]:
    """One number per game, per band, plus the band's prior and noise level."""
    premium = strength.practice_premium(conn, practice_club_id) if practice_club_id else {}
    league = strength.league_prior(conn)
    outfield = [(g.player, g.features, g.rating) for g in all_games
                if g.band != "goalkeeper" and g.rating]
    fit = unseen.fit(outfield)
    coeffs = fit[0] if fit else None

    bands: dict[str, dict] = {}
    for band in ("forward", "midfielder", "defender"):
        values: dict[str, list[float]] = {}
        per_game: dict[int, float] = {}
        for g in all_games:
            if g.band != band:
                continue
            if band == "defender":
                if coeffs is None or not g.rating:
                    continue
                v = g.rating - sum(c * x for c, x in zip(coeffs, g.features + [1.0]))
            else:
                v = (g.goals + g.assists) / g.n90
                if strength.is_practice(g.club_id, practice_club_id):
                    v -= premium.get(band, premium.get("all", 0.0))
            per_game[id(g)] = v
            values.setdefault(g.player, []).append(v)
        bands[band] = {
            "per_game": per_game,
            "prior": 0.0 if band == "defender" else league.get(band, 0.0),
            "k": _shrink_k(values),
            "unit": ("rating above expected" if band == "defender"
                     else "goals + assists per 90, practice adjusted"),
        }
    return bands


def player_bands(conn: sqlite3.Connection, *, practice_club_id: str | None
                 ) -> dict[str, list[PlayerBand]]:
    """Every (player, band) with a score, plus their builds inside it."""
    all_games = games(conn)
    bands = per_game_values(conn, all_games, practice_club_id)

    grouped: dict[tuple[str, str], list[Game]] = {}
    for g in all_games:
        grouped.setdefault((g.player, g.band), []).append(g)

    out: dict[str, list[PlayerBand]] = {b: [] for b, _ in FORMATION}
    for (player, band), items in grouped.items():
        if band not in out:
            continue
        n = len(items)
        ratings = [g.rating for g in items if g.rating]
        rating = sum(ratings) / len(ratings) if ratings else None
        n90 = sum(g.n90 for g in items)
        int90 = sum(g.interceptions for g in items) / n90 if n90 else 0.0

        if band == "goalkeeper":
            pb = PlayerBand(player, band, n, 0.0, rating, int90,
                            sum(g.conceded for g in items) / n)
            by_build: dict[str, list[Game]] = {}
            for g in items:
                by_build.setdefault(g.archetype, []).append(g)
            for arch, bg in by_build.items():
                r = [g.rating for g in bg if g.rating]
                pb.builds.append(BuildScore(
                    arch, len(bg), -sum(g.conceded for g in bg) / len(bg),
                    sum(g.conceded for g in bg) / len(bg),
                    sum(r) / len(r) if r else None, 0.0))
            pb.builds.sort(key=lambda b: (-b.games, -b.value))
            out[band].append(pb)
            continue

        info = bands[band]
        vals = [info["per_game"][id(g)] for g in items if id(g) in info["per_game"]]
        if not vals:
            continue
        own = sum(vals) / len(vals)
        pb = PlayerBand(player, band, n,
                        _shrunk(vals, info["prior"], info["k"]),
                        rating, int90, None)

        by_build = {}
        for g in items:
            by_build.setdefault(g.archetype, []).append(g)
        for arch, bg in by_build.items():
            bv = [info["per_game"][id(g)] for g in bg if id(g) in info["per_game"]]
            if not bv:
                continue
            r = [g.rating for g in bg if g.rating]
            b90 = sum(g.n90 for g in bg)
            note = "" if len(bv) >= MIN_BUILD_GAMES else "one game, not scored"
            value = (_shrunk(bv, own, info["k"]) if len(bv) >= MIN_BUILD_GAMES
                     else own)
            pb.builds.append(BuildScore(
                arch, len(bg), value, sum(bv) / len(bv),
                sum(r) / len(r) if r else None,
                sum(g.interceptions for g in bg) / b90 if b90 else 0.0, note))
        pb.builds.sort(key=lambda b: (b.note != "", -b.value, -b.games))
        out[band].append(pb)

    for band, rows in out.items():
        if band == "goalkeeper":
            rows.sort(key=lambda p: (-p.games, p.conceded_per_game or 0))
        else:
            rows.sort(key=lambda p: (-p.value, -p.games, p.player))
    return out


def _person(name: str) -> str:
    return SAME_PERSON.get(name, name)


def pick(conn: sqlite3.Connection, *, practice_club_id: str | None
         ) -> tuple[dict[str, dict[str, list[PlayerBand | None]]], dict]:
    """Starter, bench and reserve for every slot of the 4-3-3.

    One person, one slot per tier. Positions are filled in order of how
    strong the evidence is: keeper first (only one exists), then forwards and
    midfielders, whose numbers are goals and assists, then defenders from
    whoever is left, because the defender number is the weakest.
    """
    by_band = player_bands(conn, practice_club_id=practice_club_id)
    eligible = {band: [p for p in rows if p.games >= MIN_PLAYER_GAMES]
                for band, rows in by_band.items()}
    order = [bn for name in ("goalkeeper", "forward", "midfielder", "defender")
             for bn in FORMATION if bn[0] == name]

    chosen: dict[str, dict[str, list[PlayerBand | None]]] = {
        band: {tier: [] for tier in TIERS} for band, _ in FORMATION}
    for tier in TIERS:
        used_this_tier: set[str] = set()
        for band, slots in order:
            pool = [p for p in eligible[band]
                    if _person(p.player) not in used_this_tier
                    and not _already_placed(chosen, band, p.player)]
            for _ in range(slots):
                if pool:
                    p = pool.pop(0)
                    used_this_tier.add(_person(p.player))
                    chosen[band][tier].append(p)
                else:
                    chosen[band][tier].append(None)

    info = {"eligible": {b: len(v) for b, v in eligible.items()}}
    return chosen, info


def _already_placed(chosen, band: str, player: str) -> bool:
    """A person is listed once per band across tiers."""
    for tier in TIERS:
        for p in chosen[band][tier]:
            if p is not None and _person(p.player) == _person(player):
                return True
    return False


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def _fmt(value: float | None, places: int = 2) -> str:
    return format(value, "." + str(places) + "f") if value is not None else "  -  "


def _build_label(arch: str, names: dict[str, str]) -> str:
    name = names.get(arch, arch)
    if arch not in names:
        name = name + "?"
    return name + " (" + ROLE_WORDS.get(arch, "") + ")"


def top_three(conn: sqlite3.Connection, *, practice_club_id: str | None
              ) -> dict[str, list[PlayerBand]]:
    """Top three evidence-backed candidates in each broad position.

    The position is the EA band, not an exact tactical slot. Rankings use the
    same role-specific values as the squad selector and include both clubs.
    """
    by_band = player_bands(conn, practice_club_id=practice_club_id)
    return {band: rows[:3] for band, rows in by_band.items()}


def top_three_text(conn: sqlite3.Connection, names: dict[str, str], *,
                   practice_club_id: str | None) -> str:
    """Render the combined-evidence top three for each EA broad position."""
    ranked = top_three(conn, practice_club_id=practice_club_id)
    out = [
        "  TOP THREE BY EA BROAD POSITION, BOTH CLUBS COMBINED",
        "  These are candidate rankings, not exact historical slots.",
        "  EA records goalkeeper, defender, midfielder and forward only.",
        "  Holding and attacking jobs use different evidence; no universal",
        "  player score is being invented.", "",
    ]
    for band in ("goalkeeper", "defender", "midfielder", "forward"):
        out.append("  " + band.upper())
        rows = ranked.get(band, [])
        if not rows:
            out.append("      insufficient evidence")
            out.append("")
            continue
        for rank, player in enumerate(rows, start=1):
            build = player.best_build
            build_label = (_build_label(build.archetype, names)
                           if build else "no observed build")
            line = ("      " + str(rank) + ". " + player.player
                    + "  " + build_label + "  " + str(player.games)
                    + " games")
            if band == "goalkeeper":
                line += "  conceded " + _fmt(player.conceded_per_game) + " per game"
            else:
                line += "  rating " + _fmt(player.rating)
                if band == "forward":
                    line += "  value " + _fmt(player.value) + " G+A/90"
                elif band == "midfielder":
                    line += "  value " + _fmt(player.value)
                else:
                    line += "  value " + _fmt(player.value) + " rating residual"
            out.append(line)
        out.append("")
    out.extend([
        "  Both clubs contribute evidence. Club and opponent context remain",
        "  visible in the detailed evidence; practice data is not silently",
        "  discarded or promoted.",
        "  A broad-position candidate still needs human role confirmation before",
        "  being called a specific LB, CDM, CAM, ST or wing player.",
    ])
    return "\n".join(out)


def builds_text(conn: sqlite3.Connection, names: dict[str, str], *,
                practice_club_id: str | None) -> str:
    by_band = player_bands(conn, practice_club_id=practice_club_id)
    per_player: dict[str, list[PlayerBand]] = {}
    for rows in by_band.values():
        for pb in rows:
            per_player.setdefault(pb.player, []).append(pb)

    out = ["  Every build a person has played, best first within each position.",
           "  Forwards and midfielders: goals + assists per 90, practice games",
           "  adjusted, pulled toward the player's own average when thin.",
           "  Defenders: EA rating above what their own numbers predict.",
           "  Interceptions per 90 shown for everyone. Keepers: goals conceded.",
           "  A build with one game is listed but not scored.", ""]
    for player in sorted(per_player, key=lambda p: -sum(pb.games for pb in per_player[p])):
        alts = sorted(a for a, p in SAME_PERSON.items() if p == player and a != player)
        out.append("  " + player + ("   (also plays as " + ", ".join(alts) + ")" if alts else ""))
        rank = 0
        for pb in sorted(per_player[player], key=lambda x: -x.games):
            for b in pb.builds:
                rank += 1
                if rank > 3 and b.note:
                    continue
                line = ("      " + str(rank) + ". " + pb.band.ljust(11)
                        + _build_label(b.archetype, names).ljust(34)
                        + str(b.games).rjust(3) + " gms")
                if pb.band == "goalkeeper":
                    line += "   conceded " + _fmt(b.raw) + " a game"
                elif b.note:
                    line += "   " + b.note
                elif pb.band == "defender":
                    line += ("   rating " + ("+" if b.value >= 0 else "")
                             + _fmt(b.value) + " vs expected")
                else:
                    line += "   " + _fmt(b.value) + " per 90"
                if pb.band != "goalkeeper":
                    line += "   int/90 " + _fmt(b.interceptions_90, 1)
                if b.rating is not None:
                    line += "   EA " + _fmt(b.rating, 2)
                out.append(line)
        out.append("")
    return "\n".join(out)


def eleven_text(conn: sqlite3.Connection, names: dict[str, str], *,
                practice_club_id: str | None) -> str:
    chosen, info = pick(conn, practice_club_id=practice_club_id)
    out = ["  4-3-3. Three names a slot: starter, bench, reserve. Each with the",
           "  build to run, which is their best-scoring build in that position.",
           "  A person appears once per tier. Two accounts of one person count as one.",
           "  Needs " + str(MIN_PLAYER_GAMES) + " near-complete games in the position to be picked.",
           ""]
    out.append("  " + "SLOT".ljust(14) + "STARTER".ljust(40) + "BENCH".ljust(40) + "RESERVE")
    for band, slots in FORMATION:
        for i in range(slots):
            cells = []
            for tier in TIERS:
                p = chosen[band][tier][i] if i < len(chosen[band][tier]) else None
                if p is None:
                    cells.append("nobody with " + str(MIN_PLAYER_GAMES) + " games")
                    continue
                b = p.best_build
                label = p.player + ", " + (names.get(b.archetype, b.archetype) if b else "?")
                label += " " + str(p.games) + "g"
                cells.append(label)
            slot = band[:3].upper() + (str(i + 1) if slots > 1 else "")
            out.append("  " + slot.ljust(14) + cells[0].ljust(40)
                       + cells[1].ljust(40) + cells[2])
        out.append("")
    out.append("  Eligible per position: " + ", ".join(
        b + " " + str(n) for b, n in info["eligible"].items()))
    out.append("")
    out.append("  Keeper is listed by games in goal, not ranked. Defenders are")
    out.append("  ranked on rating above expected, which is weaker evidence than")
    out.append("  goals for forwards. Treat defender order as a lean, not a verdict.")
    return "\n".join(out)
