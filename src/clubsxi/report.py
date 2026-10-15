"""Plain text answers to the two questions the group argues about.

  1. Where has each player actually been seen, and how often?
  2. Who should start, and who backs them up?

Answering those honestly at this sample size means refusing to rank people by
results. The rules come from a design review, recorded in
docs/05-collector.md. Every one of them is covered by a test.

Text on purpose. It reads fine in a terminal today and drops into a Discord
message later without being rewritten.

Every section states its sample size and refuses to answer when the evidence is
thin. That refusal is a feature.
"""
from __future__ import annotations

import sqlite3

from . import analysis

LINE = "-" * 70


def _bar(text: str) -> str:
    return LINE + "\n" + text + "\n" + LINE


def _pct(part: int, whole: int) -> str:
    return format(100 * part / whole, ".0f") + "%" if whole else "0%"


def archetype_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """Confirmed names print plainly. Unconfirmed ones keep a question mark,
    so nobody mistakes EA's list order for a checked fact."""
    labels: dict[str, str] = {}
    for r in conn.execute(
            "SELECT archetype_id, name, verified FROM archetype_map"):
        labels[str(r["archetype_id"])] = (
            r["name"] if r["verified"] else r["name"] + "?")
    return labels


def arch_text(labels: dict[str, str], archetype_id: str) -> str:
    name = labels.get(str(archetype_id))
    return (str(archetype_id) + " " + name) if name else str(archetype_id)


def club_labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["club_id"]: (r["club_name"] or r["club_id"])
            for r in conn.execute(
                "SELECT club_id, MAX(club_name) AS club_name FROM match_clubs "
                "WHERE is_our_club = 1 GROUP BY club_id")}


def evidence_header(conn: sqlite3.Connection, include_messy: bool) -> str:
    c = analysis.evidence_counts(conn)
    counting = c["counting_appearances"]
    total = counting + c["excluded_appearances"]
    rule = ("counting EVERYTHING, including quits and part appearances"
            if include_messy
            else "near-complete appearances in completed matches only")

    return (
        _bar("CLUBSXI EVIDENCE REPORT") + "\n"
        "Matches collected : " + str(c["matches"])
        + "  (" + str(c["clean_matches"]) + " completed, "
        + str(c["dnf_matches"]) + " quit early, "
        + str(c["other_flagged"]) + " otherwise flagged)\n"
        "Counting rule     : " + rule + "\n"
        "Appearances used  : " + str(counting) + " of " + str(total)
        + " (" + _pct(counting, total) + ")\n"
        "Left out          : " + str(c["ghosts"]) + " ghost rows, "
        + str(c["shorts"]) + " part appearances\n"
        "Near-complete     : 90% or more of the longest appearance in the "
        "same match\n"
        "Quit matches      : kept and counted in the club record, left out of\n"
        "                    per-player averages only\n")


def club_record_text(conn: sqlite3.Connection) -> str:
    """Team results, completed and quit-early shown side by side.

    Review rule D5. Opponents quit when they are losing, so hiding those
    games would quietly delete our best nights.
    """
    rows = conn.execute(
        "SELECT mc.club_name, "
        "  SUM(m.validity != 'dnf') AS completed, "
        "  SUM(m.validity = 'dnf') AS quit_early, "
        "  SUM(CASE WHEN m.validity != 'dnf' THEN mc.goals_for END) AS gf, "
        "  SUM(CASE WHEN m.validity != 'dnf' THEN mc.goals_against END) AS ga, "
        "  SUM(m.validity != 'dnf' AND mc.outcome = 'win') AS w, "
        "  SUM(m.validity != 'dnf' AND mc.outcome = 'draw') AS d, "
        "  SUM(m.validity != 'dnf' AND mc.outcome = 'loss') AS l, "
        "  SUM(m.validity = 'dnf' AND mc.outcome = 'win') AS dnf_w, "
        "  SUM(m.validity = 'dnf' AND mc.outcome = 'loss') AS dnf_l "
        "FROM match_clubs mc JOIN matches m ON m.match_id = mc.match_id "
        "WHERE mc.is_our_club = 1 GROUP BY mc.club_id "
        "ORDER BY completed DESC").fetchall()

    out = ["\n" + _bar("CLUB RECORD"), ""]
    for r in rows:
        diff = (r["gf"] or 0) - (r["ga"] or 0)
        out.append(
            (r["club_name"] or "?").ljust(16)
            + "completed " + str(r["completed"]).rjust(3) + "   "
            + str(r["w"]) + "W " + str(r["d"]) + "D " + str(r["l"]) + "L   "
            + str(r["gf"] or 0) + "-" + str(r["ga"] or 0)
            + "  (" + ("+" if diff >= 0 else "") + str(diff) + ")")
        if r["quit_early"]:
            out.append(
                "".ljust(16) + "quit early " + str(r["quit_early"]).rjust(2)
                + "   " + str(r["dnf_w"]) + "W " + str(r["dnf_l"]) + "L"
                + "   counted here, kept out of player averages")
    out.append("")
    return "\n".join(out)


def top_positions_text(conn: sqlite3.Connection, *,
                       club_ids: list[str] | None = None,
                       include_messy: bool = False,
                       limit_players: int = 0) -> str:
    grouped = analysis.top_positions(
        conn, club_ids=club_ids, include_messy=include_messy)
    labels = club_labels(conn)
    arches = archetype_labels(conn)

    out = ["\n" + _bar("WHERE EACH PLAYER HAS ACTUALLY BEEN SEEN"),
           "Ordered by how much we have seen them there. NOT by performance.",
           "",
           "The team numbers are the WHOLE MATCH score in games featuring that",
           "player. There is no event timing in the data, so this is not what",
           "happened while they were on the pitch. Context, not credit.",
           "",
           "Nothing is ordered by results until "
           + str(analysis.PERFORMANCE_MIN_APPEARANCES)
           + " near-complete games in the",
           "same role. Nobody is close. That is the honest answer today.",
           "",
           "A ? after an archetype name means the name comes from EA's list",
           "order and no human has confirmed it in game yet.", ""]

    shown = 0
    for player_id, entry in grouped.items():
        if limit_players and shown >= limit_players:
            break
        shown += 1
        out.append(entry["name"] + "  (" + str(entry["total"])
                   + " games counted)")

        if not entry["ranked"]:
            out.append("   nowhere seen enough to list")
        for s in entry["ranked"]:
            diff = ("+" if s.diff >= 0 else "") + str(s.diff)
            out.append(
                "   " + s.pos.ljust(11)
                + arch_text(arches, s.archetype_id).ljust(17)
                + labels.get(s.club_id, s.club_id).ljust(14)
                + str(s.appearances).rjust(3) + " games   "
                + "team " + diff.rjust(4) + " ("
                + str(s.wins) + "W " + str(s.draws) + "D " + str(s.losses)
                + "L)   EA rating "
                + (format(s.avg_rating, ".2f") if s.avg_rating else " -  ")
                + "   " + s.confidence)

        if entry["thin"]:
            thin = ", ".join(
                s.pos + "/" + arch_text(arches, s.archetype_id) + " at "
                + labels.get(s.club_id, s.club_id) + " x" + str(s.appearances)
                for s in entry["thin"])
            out.append("   barely seen: " + thin)
        out.append("")

    if not shown:
        out.append("Nothing counts yet under this rule.")
    return "\n".join(out)


def combinations_text(conn: sqlite3.Connection, **_ignored) -> str:
    """Deliberately empty. This section used to rank pairs and trios.

    Removed. It was measuring which club the match was in, not
    chemistry. Two completely different pairs came out with identical numbers
    because they were literally the same set of matches: the main-club
    regulars and the practice-club regulars never mix much, so "played with X"
    was standing in for "played at club Y".

    Twenty players also make 190 pairs. At this sample size some of them look
    brilliant on luck alone. Removing a lie is worth more than adding a truth.

    A real version needs about 15 games together WITHIN one club. The most any
    pair has managed across both clubs is 16, so it is not close.
    """
    lines = [
        "",
        _bar("WHO PLAYS WITH WHOM"),
        "Removed on purpose.",
        "",
        "This section used to rank pairs and trios by goal difference.",
        "It was measuring which club the game was in. Two different pairs",
        "gave identical numbers because they were the same matches: the",
        "people who play at the main club and the people who play at the",
        "practice club barely overlap.",
        "",
        "Real evidence about a pairing needs roughly 15 games together at",
        "the same club. Nobody is close, so there is nothing honest to",
        "print here yet.",
        "",
    ]
    return "\n".join(lines)


def depth_chart_text(conn: sqlite3.Connection,
                     chart_path=None, can_play_path=None) -> str:
    """Placeholder until the captain's chart exists.

    The eleven slots and their order come from the captain, filtered by who
    actually owns a build for the slot. Nothing in the API carries exact
    positions and no amount of data will change that, so there is no algorithm
    waiting to be switched on here.
    """
    if chart_path is not None:
        from . import chart as chart_module
        loaded = chart_module.load(chart_path)
        if loaded is not None:
            return ("\n" + _bar("STARTING ELEVEN AND DEPTH CHART") + "\n"
                    + chart_module.render(loaded, conn) + "\n")

    lines = [
        "",
        _bar("STARTING ELEVEN AND DEPTH CHART"),
        "No chart file found.",
        "",
        "This one does not come from the data. Exact positions do not exist",
        "anywhere in EA's payload, and the roster fields describe a player's",
        "build rather than where they line up.",
        "",
        "Confirmed by a human report: the same archetype was",
        "played at LW, at ST and at LCM in one match. Neither the broad",
        "position nor the archetype pins anyone to a slot.",
        "",
        "So the eleven slots, and who is first, second and third choice for",
        "each, are the captain's to set. This tool's job is to hold that",
        "chart, show who owns a build for each slot, and print how often each",
        "person has actually been seen in that broad role.",
        "",
    ]
    return "\n".join(lines)


def full_report(conn: sqlite3.Connection, *,
                club_ids: list[str] | None = None,
                include_messy: bool = False,
                min_games: int = analysis.EXPOSURE_MIN_APPEARANCES,
                limit_players: int = 0,
                chart_path=None, can_play_path=None) -> str:
    return (
        evidence_header(conn, include_messy)
        + club_record_text(conn)
        + top_positions_text(conn, club_ids=club_ids,
                             include_messy=include_messy,
                             limit_players=limit_players)
        + combinations_text(conn, club_ids=club_ids,
                            include_messy=include_messy,
                            min_games=min_games)
        + depth_chart_text(conn, chart_path, can_play_path)
        + _bar("A gauge, not a verdict. Players decide.")
    )
