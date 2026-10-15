"""Command line entry point.

  python -m clubsxi poll     one cycle, then exit
  python -m clubsxi run      poll forever on the configured interval
  python -m clubsxi status   what is in the database right now
  python -m clubsxi find "Club Name"   search EA for a club id by name
  python -m clubsxi check    confirm the clubs resolve (and CLUBSXI_CHECK_PLAYER is in them)
  python -m clubsxi web      start the inspect UI (read only)
  python -m clubsxi report   print the evidence report as text
  python -m clubsxi rebuild  recompute appearance flags after a rule change
  python -m clubsxi chart    show the captain depth chart, checked
  python -m clubsxi xi       top 3 builds per player, and a starting XI
  python -m clubsxi form     adjusted player scores, wasted players, keeper
  python -m clubsxi builds   what each build does, and who is on a weak one
  python -m clubsxi squad    best builds per person, and a 4-3-3 three deep
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import config, db
from .collector import poll_once, run_forever
from .ea_client import EaClient
from . import report as report_module
from .web import serve

# Optional: an EA name that must appear in every club roster. "check" warns if it does not.
VALIDATION_PLAYER_NAME = os.environ.get("CLUBSXI_CHECK_PLAYER", "").strip()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _cmd_status(cfg: config.Config) -> int:
    conn = db.connect(cfg.db_path)
    print("database: " + str(cfg.db_path))
    for name, value in db.counts(conn).items():
        print("  " + name.ljust(20) + str(value))

    roster = conn.execute(
        "SELECT club_id, COUNT(*) AS snaps, MAX(fetched_at) AS last "
        "FROM member_snapshots GROUP BY club_id").fetchall()
    if roster:
        import datetime
        print()
        print("roster snapshots:")
        for r in roster:
            when = datetime.datetime.fromtimestamp(r["last"])
            print("  " + r["club_id"] + "  " + str(r["snaps"])
                  + " snapshots, newest " + when.strftime("%Y-%m-%d %H:%M"))

    rows = conn.execute(
        "SELECT started_at, matches_new, matches_duplicate, calls_failed, errors "
        "FROM poll_log ORDER BY id DESC LIMIT 5").fetchall()
    print("\nlast polls:")
    for row in rows:
        import datetime
        when = datetime.datetime.fromtimestamp(row["started_at"])
        print("  " + when.strftime("%Y-%m-%d %H:%M")
              + "  new=" + str(row["matches_new"])
              + " dup=" + str(row["matches_duplicate"])
              + " failed_calls=" + str(row["calls_failed"])
              + ("  ERRORS" if row["errors"] else ""))
    return 0


def _cmd_check(cfg: config.Config) -> int:
    client = EaClient(cfg.request_timeout, cfg.max_retries)
    ok = True
    for club_id in cfg.club_ids:
        info = client.club_info(cfg.platform, club_id)
        members = client.members_stats(cfg.platform, club_id)

        if not info.ok:
            print("FAIL club " + club_id + ": " + str(info.error or info.status))
            ok = False
            continue

        name = (info.data.get(club_id) or {}).get("name", "?")
        names = []
        if members.ok and isinstance(members.data, dict):
            names = [m.get("name") for m in members.data.get("members", [])]

        if not VALIDATION_PLAYER_NAME:
            print("OK   " + club_id + "  " + str(name) + "  members=" + str(len(names)))
            continue
        found = VALIDATION_PLAYER_NAME.lower() in [
            str(n).lower() for n in names if n]
        print(("OK   " if found else "WARN ") + club_id + "  " + str(name)
              + "  members=" + str(len(names))
              + ("  " + VALIDATION_PLAYER_NAME + " present"
                 if found else "  " + VALIDATION_PLAYER_NAME + " NOT in member list"))
        ok = ok and found
    return 0 if ok else 1


def _cmd_find(cfg: config.Config, name: str) -> int:
    """Search EA for clubs by name and print their ids. Name search is not
    reliable, so always confirm the id with "check" afterwards."""
    if not name.strip():
        print('Say which club, for example:  python run.py find "My Club"')
        return 1
    client = EaClient(cfg.request_timeout, cfg.max_retries)
    result = client.get("/allTimeLeaderboard/search",
                        {"platform": cfg.platform, "clubName": name.strip()})
    if not result.ok or not isinstance(result.data, list):
        print("EA search failed: " + str(result.error or result.status))
        return 1
    if not result.data:
        print("No club found with that name.")
        return 1
    for club in result.data:
        print(str(club.get("clubId", "?")).ljust(12) + str(club.get("clubName", "?"))
              + "  games=" + str(club.get("gamesPlayed", "?")))
    print("Put the right id in CLUBSXI_CLUB_IDS, then run: python run.py check")
    return 0


def _cmd_web(cfg: config.Config) -> int:
    """The viewer never writes. It opens the database read only."""
    import sqlite3

    if not cfg.db_path.exists():
        print("no database yet at " + str(cfg.db_path)
              + ". Let the collector run one cycle first.")
        return 1

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    our_clubs = {
        row["club_id"]: row["club_name"] or row["club_id"]
        for row in conn.execute(
            "SELECT club_id, MAX(club_name) AS club_name FROM match_clubs "
            "WHERE is_our_club = 1 GROUP BY club_id")
    }
    conn.close()
    for club_id in cfg.club_ids:
        our_clubs.setdefault(club_id, club_id)

    serve(cfg.db_path, cfg.web_host, cfg.web_port, our_clubs)
    return 0


def _cmd_report(cfg: config.Config, args) -> int:
    import sqlite3

    if not cfg.db_path.exists():
        print("no database yet at " + str(cfg.db_path))
        return 1

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        print(report_module.full_report(
            conn,
            club_ids=[args.club] if args.club else None,
            include_messy=args.include_messy,
            min_games=args.min_games,
            limit_players=args.players,
            chart_path=cfg.chart_path,
            can_play_path=cfg.can_play_path,
        ))
    finally:
        conn.close()
    return 0


def _cmd_chart(cfg: config.Config) -> int:
    import sqlite3

    from . import chart as chart_module

    loaded = chart_module.load(cfg.chart_path)
    if loaded is None:
        print("no chart yet at " + str(cfg.chart_path))
        print("Copy config/depth_chart.txt there and edit it.")
        return 1

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    can, wont = chart_module.load_can_play(cfg.can_play_path)
    try:
        print("TOP THREE FOR EACH POSITION")
        print()
        print(chart_module.band_depth_text(conn, can=can, wont=wont))
        print("DEPTH CHART, SPREAD ACROSS THE FORMATION")
        print()
        print(chart_module.render(loaded, conn, can=can, wont=wont))
    finally:
        conn.close()
    return 0


def _cmd_builds(cfg: config.Config) -> int:
    import sqlite3

    from . import builds

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        print("WHAT EACH BUILD ACTUALLY DOES")
        print()
        print(builds.profiles_text(conn))
        print()
        print("WHO IS ON THE WRONG BUILD")
        print()
        print(builds.suggestions_text(conn))
    finally:
        conn.close()
    return 0


def _cmd_form(cfg: config.Config) -> int:
    import sqlite3

    from . import report as report_mod
    from . import strength, unseen

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        names = {k: v for k, v in report_mod.archetype_labels(conn).items()}
        print("HOW MUCH A HUMAN KEEPER IS WORTH")
        print()
        print(strength.keeper_text(conn))
        print()
        print("PLAYERS IN THE WRONG JOB")
        print()
        print(strength.wasted_text(conn, names))
        print()
        print("WHO IS QUIETLY GOOD")
        print()
        print(unseen.text(conn))
        print()
        print("ADJUSTED PLAYER SCORES")
        print()
        print(strength.scores_text(
            conn, practice_club_id=cfg.practice_club_id))
    finally:
        conn.close()
    return 0


def _cmd_squad(cfg: config.Config) -> int:
    import sqlite3

    from . import report as report_mod
    from . import squad

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        names = report_mod.archetype_labels(conn)
        print("TOP THREE CANDIDATES BY BROAD POSITION")
        print()
        print(squad.top_three_text(
            conn, names, practice_club_id=cfg.practice_club_id))
        print()
        print("BEST BUILDS PER PERSON")
        print()
        print(squad.builds_text(conn, names, practice_club_id=cfg.practice_club_id))
        print("THE 4-3-3, THREE DEEP")
        print()
        print(squad.eleven_text(conn, names, practice_club_id=cfg.practice_club_id))
    finally:
        conn.close()
    return 0


def _cmd_xi(cfg: config.Config, args) -> int:
    import sqlite3

    from . import xi as xi_module

    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    clubs = [args.club] if args.club else None
    try:
        print("TOP THREE BUILDS PER PLAYER")
        print()
        print(xi_module.top_roles_text(conn, club_ids=clubs))
        print("SUGGESTED STARTING ELEVEN")
        print()
        print(xi_module.starting_eleven_text(conn, club_ids=clubs))
    finally:
        conn.close()
    return 0


def _cmd_tonight(cfg: config.Config, args) -> int:
    import sqlite3

    from . import chart as chart_module
    from . import tonight as tonight_module

    loaded = chart_module.load(cfg.chart_path)
    if loaded is None:
        print("no chart yet at " + str(cfg.chart_path))
        return 1

    names = [n for n in args.online.split(",") if n.strip()]
    if not names:
        print("Say who is online, for example:")
        print("  python run.py tonight --online "
              "\"PlayerOne, PlayerTwo, PlayerThree\"")
        return 1

    can, wont = chart_module.load_can_play(cfg.can_play_path)
    conn = sqlite3.connect(
        "file:" + str(cfg.db_path) + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        plan = tonight_module.plan(loaded, conn, names, can=can, wont=wont)
        print("Tonight, " + str(len(names)) + " online, formation "
              + loaded.formation)
        print()
        print(tonight_module.render(plan, conn, can=can, wont=wont))
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clubsxi")
    parser.add_argument("command",
                        choices=["poll", "run", "status", "check", "find", "web",
                                 "report", "rebuild", "chart",
                                 "tonight", "xi", "form", "builds", "squad"],
                        help="poll once, run forever, show status, check clubs, "
                             "or start the inspect UI")
    parser.add_argument("name", nargs="?", default="",
                        help="find only: the club name to search for")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--club", help="only this clubId (report only)")
    parser.add_argument("--include-messy", action="store_true",
                        help="count quits and short spells too (report only)")
    parser.add_argument("--min-games", type=int, default=5,
                        help="games a combination needs before it is shown")
    parser.add_argument("--players", type=int, default=0,
                        help="limit how many players the report lists")
    parser.add_argument("--online", default="",
                        help="tonight only: comma separated names who are on")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    cfg = config.load()

    if not cfg.club_ids and args.command in ("poll", "run", "check"):
        print("CLUBSXI_CLUB_IDS is empty. Put your club id in the .env file.")
        print("See docs/02-find-your-club-id.md.")
        return 2

    if args.command == "status":
        return _cmd_status(cfg)
    if args.command == "check":
        return _cmd_check(cfg)
    if args.command == "find":
        return _cmd_find(cfg, args.name)

    if args.command == "web":
        return _cmd_web(cfg)
    if args.command == "report":
        return _cmd_report(cfg, args)
    if args.command == "chart":
        return _cmd_chart(cfg)
    if args.command == "tonight":
        return _cmd_tonight(cfg, args)
    if args.command == "squad":
        return _cmd_squad(cfg)
    if args.command == "xi":
        return _cmd_xi(cfg, args)
    if args.command == "form":
        return _cmd_form(cfg)
    if args.command == "builds":
        return _cmd_builds(cfg)

    conn = db.connect(cfg.db_path)
    logging.getLogger("clubsxi").info(
        "clubs=%s platform=%s types=%s interval=%dm db=%s",
        ",".join(cfg.club_ids), cfg.platform,
        ",".join(cfg.match_types), cfg.poll_minutes, cfg.db_path)

    if args.command == "rebuild":
        from . import ingest
        result = ingest.reclassify_appearances(conn)
        conn.commit()
        for key, value in result.items():
            print("  " + key.ljust(24) + str(value))
        return 0

    if args.command == "poll":
        outcome = poll_once(conn, cfg)
        return 1 if outcome.calls_failed == outcome.calls_made else 0

    run_forever(conn, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
