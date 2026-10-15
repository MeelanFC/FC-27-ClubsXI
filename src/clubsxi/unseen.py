"""Who is quietly good: rating above what their own numbers predict.

EA gives every player a match rating. Much of it is explained by the obvious
things, goals, assists, passing, man of the match. The rest is EA's engine
seeing positioning, pressing and off-ball work that never reaches any stat we
hold.

So: predict each player's rating from their own box score, then see who beats
their prediction. That gap is the closest thing this data has to "does things
you cannot count".

This module exists for a specific reason. Some good players score almost no
goals. Any output-based chart benches them. This is the check on that chart.

Plain least squares, written out by hand. No third-party packages.
"""
from __future__ import annotations

import sqlite3

FEATURES = ("goals", "assists", "mom", "passes_made", "passes_lost",
            "tackles_made", "tackles_lost")


def _fmt(value: float | None, places: int = 2) -> str:
    return format(value, "." + str(places) + "f") if value is not None else " - "


def rows(conn: sqlite3.Connection) -> list[tuple[str, list[float], float]]:
    """Outfield rows only. Keepers are rated on a completely different scale."""
    found = conn.execute(
        "SELECT COALESCE(p.latest_name, s.player_id) AS player, "
        "  s.goals, s.assists, s.mom, s.passes_made, s.pass_attempts, "
        "  s.tackles_made, s.tackle_attempts, s.rating "
        "FROM player_match_stats s "
        "JOIN matches m ON m.match_id = s.match_id "
        "JOIN match_clubs mc ON mc.match_id = s.match_id "
        "  AND mc.club_id = s.club_id "
        "LEFT JOIN players p ON p.player_id = s.player_id "
        "WHERE mc.is_our_club = 1 AND s.is_real_appearance = 1 "
        "  AND s.appearance_class = 'full' AND m.validity = 'ok' "
        "  AND s.pos != 'goalkeeper' AND s.rating IS NOT NULL "
        "  AND s.rating > 0").fetchall()

    out: list[tuple[str, list[float], float]] = []
    for r in found:
        passes = r["passes_made"] or 0
        attempts = r["pass_attempts"] or 0
        tackles = r["tackles_made"] or 0
        tackle_att = r["tackle_attempts"] or 0
        out.append((r["player"], [
            float(r["goals"] or 0),
            float(r["assists"] or 0),
            float(r["mom"] or 0),
            passes / 10.0,
            max(attempts - passes, 0) / 10.0,
            float(tackles),
            max(tackle_att - tackles, 0) / 10.0,
        ], float(r["rating"])))
    return out


def fit(data: list[tuple[str, list[float], float]]
        ) -> tuple[list[float], float] | None:
    """Least squares via normal equations. Returns (coefficients, r squared).

    Returns None when there is not enough data, which is the honest answer
    early on rather than a set of meaningless numbers.
    """
    width = len(FEATURES) + 1  # plus an intercept
    if len(data) < width * 4:
        return None

    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for _player, features, rating in data:
        x = features + [1.0]
        for i in range(width):
            xty[i] += x[i] * rating
            for j in range(width):
                xtx[i][j] += x[i] * x[j]

    # Tiny ridge term so a feature that never varies cannot blow the solve up.
    for i in range(width):
        xtx[i][i] += 1e-6

    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(xtx[r][col]))
        if abs(xtx[pivot][col]) < 1e-12:
            return None
        xtx[col], xtx[pivot] = xtx[pivot], xtx[col]
        xty[col], xty[pivot] = xty[pivot], xty[col]
        for row in range(col + 1, width):
            factor = xtx[row][col] / xtx[col][col]
            if factor == 0.0:
                continue
            for k in range(col, width):
                xtx[row][k] -= factor * xtx[col][k]
            xty[row] -= factor * xty[col]

    coeffs = [0.0] * width
    for row in reversed(range(width)):
        total = xty[row] - sum(xtx[row][k] * coeffs[k]
                               for k in range(row + 1, width))
        coeffs[row] = total / xtx[row][row]

    predicted = [sum(c * v for c, v in zip(coeffs, f + [1.0]))
                 for _p, f, _r in data]
    actual = [r for _p, _f, r in data]
    mean = sum(actual) / len(actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    ss_tot = sum((a - mean) ** 2 for a in actual)
    return coeffs, (1 - ss_res / ss_tot if ss_tot else 0.0)


def above_expected(conn: sqlite3.Connection, *, min_games: int = 3
                   ) -> tuple[list[dict], float, dict[str, float]]:
    """Who beats the rating their own box score predicts.

    Returns (players, r squared, coefficients). An empty list means there is
    not enough data to fit anything yet.
    """
    data = rows(conn)
    result = fit(data)
    if result is None:
        return [], 0.0, {}
    coeffs, r2 = result

    by_player: dict[str, list[tuple[float, float]]] = {}
    for player, features, rating in data:
        prediction = sum(c * v for c, v in zip(coeffs, features + [1.0]))
        by_player.setdefault(player, []).append((rating, prediction))

    out: list[dict] = []
    for player, pairs in by_player.items():
        if len(pairs) < min_games:
            continue
        actual = sum(p[0] for p in pairs) / len(pairs)
        expected = sum(p[1] for p in pairs) / len(pairs)
        out.append({"player": player, "games": len(pairs),
                    "rating": actual, "expected": expected,
                    "above": actual - expected})

    out.sort(key=lambda d: -d["above"])
    return out, r2, dict(zip(FEATURES + ("intercept",), coeffs))


def text(conn: sqlite3.Connection) -> str:
    players, r2, coeffs = above_expected(conn)

    out = ["  EA rates every player each match. Some of that rating is just",
           "  goals, assists, passing and man of the match. The rest is EA's",
           "  engine seeing positioning and off-ball work that never reaches",
           "  any stat we hold.",
           "",
           "  So: predict each player's rating from their own numbers, then",
           "  see who beats their prediction.", ""]

    if not players:
        out.append("  Not enough games to fit this yet.")
        return "\n".join(out)

    out.append("  The model explains " + str(round(r2 * 100))
               + " percent of EA's rating. The other "
               + str(round((1 - r2) * 100))
               + " percent is what this measures.")
    out.append("")
    out.append("  " + "PLAYER".ljust(20) + "GMS    RATING  EXPECTED    ABOVE")
    for p in players:
        out.append("  " + p["player"].ljust(20)
                   + str(p["games"]).rjust(3) + "    "
                   + _fmt(p["rating"]) + "      " + _fmt(p["expected"])
                   + "    " + ("+" if p["above"] >= 0 else "")
                   + _fmt(p["above"]))

    out.append("")
    out.append("  What EA actually rewards, per unit:")
    labels = [("goals", "a goal"), ("assists", "an assist"),
              ("mom", "man of the match"),
              ("passes_made", "10 passes completed"),
              ("passes_lost", "10 passes LOST"),
              ("tackles_made", "a tackle won"),
              ("tackles_lost", "10 tackles LOST")]
    for key, label in labels:
        out.append("      " + label.ljust(22) + _fmt(coeffs.get(key), 3))

    out.append("")
    out.append("  Someone near the top with few goals is doing something the")
    out.append("  stats cannot see. Do not bench them off a goals chart.")
    return "\n".join(out)
