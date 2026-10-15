"""Settings for the collector. Everything is overridable by environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Config:
    # Your own clubs. Required. See docs/02-find-your-club-id.md.
    club_ids: list[str] = field(default_factory=lambda: _env_list(
        "CLUBSXI_CLUB_IDS", []))
    platform: str = os.environ.get("CLUBSXI_PLATFORM", "common-gen5")

    # Optional practice club(s), comma separated. Its opposition is often much
    # weaker, and the SAME player produces measurably more there, so
    # comparisons must adjust for it.
    practice_club_id: str = os.environ.get("CLUBSXI_PRACTICE_CLUB", "")
    match_types: list[str] = field(default_factory=lambda: _env_list(
        "CLUBSXI_MATCH_TYPES", ["leagueMatch", "friendlyMatch", "playoffMatch"]))

    # EA caps this at 10 and ignores anything larger. Asking for 10 is asking for all.
    max_result_count: int = int(os.environ.get("CLUBSXI_MAX_RESULT_COUNT", "10"))
    opponent_history_clubs_per_poll: int = int(os.environ.get(
        "CLUBSXI_OPPONENT_HISTORY_CLUBS_PER_POLL", "20"))

    poll_minutes: int = int(os.environ.get("CLUBSXI_POLL_MINUTES", "30"))
    db_path: Path = Path(os.environ.get(
        "CLUBSXI_DB", str(PROJECT_ROOT / "data" / "clubsxi.sqlite3")))

    # Optional extra copy of every raw response as a file on disk. SQLite stays
    # the system of record either way.
    raw_dump_dir: Path | None = (
        Path(os.environ["CLUBSXI_RAW_DUMP_DIR"])
        if os.environ.get("CLUBSXI_RAW_DUMP_DIR") else None)

    # The captain's depth chart. Hand edited, never written by the collector.
    chart_path: Path = Path(os.environ.get(
        "CLUBSXI_CHART", str(PROJECT_ROOT / "config" / "depth_chart.txt")))

    # Who is willing to play where. Hand edited by the captain.
    can_play_path: Path = Path(os.environ.get(
        "CLUBSXI_CAN_PLAY", str(PROJECT_ROOT / "config" / "can_play.txt")))

    # Rewritten after every poll cycle so it is never stale.
    report_path: Path = Path(os.environ.get(
        "CLUBSXI_REPORT", str(PROJECT_ROOT / "data" / "report.txt")))

    # Inspect UI. 127.0.0.1 = this computer only. Docker sets 0.0.0.0.
    web_host: str = os.environ.get("CLUBSXI_WEB_HOST", "127.0.0.1")
    web_port: int = int(os.environ.get("CLUBSXI_WEB_PORT", "8080"))

    request_timeout: int = int(os.environ.get("CLUBSXI_REQUEST_TIMEOUT", "30"))
    max_retries: int = int(os.environ.get("CLUBSXI_MAX_RETRIES", "4"))
    # Gap between the individual calls inside one poll cycle. Keeps us polite.
    call_spacing_seconds: float = float(
        os.environ.get("CLUBSXI_CALL_SPACING_SECONDS", "2.0"))


def load() -> Config:
    return Config()


# ---------------------------------------------------------------------------
# Club and people settings read by the analysis modules at import time.
# ---------------------------------------------------------------------------

def our_club_ids() -> set[str]:
    """Every club id in CLUBSXI_CLUB_IDS. These are "our" clubs."""
    return set(_env_list("CLUBSXI_CLUB_IDS", []))


def season_club_ids() -> set[str]:
    """Clubs whose games count for the current season.

    EA can give a club a new id when a new game year starts. Put only the new
    ids here. Defaults to every id in CLUBSXI_CLUB_IDS.
    """
    return set(_env_list("CLUBSXI_SEASON_CLUB_IDS", [])) or our_club_ids()


def season_start() -> int:
    """Unix time of the first game of the current season. 0 means all games."""
    try:
        return int(os.environ.get("CLUBSXI_SEASON_START", "0") or 0)
    except ValueError:
        return 0


def timezone_name() -> str:
    """Time zone used to group late games into one night. Default UTC."""
    return os.environ.get("CLUBSXI_TIMEZONE", "") or "UTC"


def same_person(path: str | None = None) -> dict[str, str]:
    """EA account name -> person name, from config/same_person.txt.

    One person can play on two EA accounts. Each line is
    "Account name = Person name". Lines that start with # are ignored.
    """
    candidates = [path, os.environ.get("CLUBSXI_SAME_PERSON"),
                  "/config/same_person.txt",
                  str(PROJECT_ROOT / "config" / "same_person.txt")]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            out: dict[str, str] = {}
            with open(candidate, encoding="utf-8") as handle:
                for line in handle:
                    line = line.split("#", 1)[0].strip()
                    if "=" in line:
                        account, person = (x.strip() for x in line.split("=", 1))
                        if account and person:
                            out[account] = person
            return out
    return {}
