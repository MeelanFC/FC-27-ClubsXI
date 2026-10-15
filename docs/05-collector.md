# The collector

The collector asks EA for data, saves it, and checks it. It is the only part
of ClubsXI that writes to the database. Code: `src/clubsxi/collector.py`,
`src/clubsxi/ingest.py`, `src/clubsxi/db.py`.

## 1. One poll, step by step

For each club id in `CLUBSXI_CLUB_IDS`, the collector does these steps:

1. It gets `/members/stats` and saves a roster snapshot.
2. It gets `/clubs/overallStats` for the club and saves a standings snapshot.
   This happens every poll, so that the club's rating never freezes.
3. For each match type (`leagueMatch`, `friendlyMatch`, `playoffMatch`), it
   gets `/clubs/matches` with `maxResultCount=10`.
4. It compares each `matchId` with the matches already saved.
5. For each new match, it gets `/clubs/overallStats` for both sides. Each club
   is asked once per poll. The answer is kept in a cache for that poll.
6. It saves the new match (see section 3).

After all clubs:

7. It does the opponent history backfill (section 4).
8. It writes a row in `poll_log` with the counts and errors.
9. It writes a text report to `CLUBSXI_REPORT`.

With one club, a poll makes 5 calls, plus one standings call for each new
opponent. The collector waits `CLUBSXI_CALL_SPACING_SECONDS` (default 2)
between calls.

## 2. Rules for safety

- **Every response is saved raw**, also failures. Table `raw_responses` keeps
  the address, the parameters, the HTTP status, the error and the full body.
  You can always analyse the data again later.
- **Nothing is deleted.** Bad matches get a flag, not removal.
- **Unknown fields are kept.** Each player row stores fields that ClubsXI does
  not name in `extras_json`, and the full object in `raw_json`.
- **One bad match does not stop a poll.** The collector rolls back that match,
  writes the error, and continues.
- **Retries.** A failed call is tried up to 4 times, with a wait of 2, 4 and
  8 seconds. A 4xx error other than 403 or 429 is not tried again, because the
  request itself is wrong.
- **Alert.** After 3 polls in a row where every call failed, the log shows
  `ALERT`. The usual causes are an EA outage or headers that need an update.
- **Clean stop.** On SIGINT or SIGTERM the collector finishes the current poll
  and stops.

## 3. How one match is saved

Code: `ingest.ingest_match()`. The same input always gives the same rows.

1. The match gets a **validity** flag:

   | Validity | Rule |
   |---|---|
   | `incomplete` | Not 2 clubs, no player block, or a missing score. |
   | `suspicious` | A player has `vprohackreason` other than 0. |
   | `dnf` | `winnerByDnf` is set. One side quit. |
   | `ok` | None of the above. |

2. Each side becomes a row in `match_clubs` with goals for, goals against and
   outcome (win, draw, loss). Sides in `CLUBSXI_CLUB_IDS` get `is_our_club = 1`.
3. Each player becomes a row in `player_match_stats`, with an **appearance class**:

   | Class | Rule | Counts as an appearance |
   |---|---|---|
   | `ghost` | 0 seconds played | No |
   | `short` | Under 90 percent of the longest appearance on that side | Yes, but not near-complete |
   | `full` | 90 percent or more | Yes |

   The 90 percent compares players inside the match, so no fixed minute
   value is needed.
4. The numeric EA player id is the identity. A name change adds a row to
   `player_names`. It does not create a new person.
5. The match records its `source`: `own` (from your clubs' lists) or
   `opponent_history` (from the backfill), plus the `seed_club_id` for the backfill.

## 4. Opponent history backfill

Your own matches give a small sample. Tests need hundreds of other clubs'
matches. The backfill gets them at a low cost.

1. After each poll, the collector lists opponents of your clubs that it has
   not asked before.
2. It takes up to `CLUBSXI_OPPONENT_HISTORY_CLUBS_PER_POLL` of them (default 20;
   0 turns the backfill off).
3. For each one, it first writes a claim row in `opponent_history_fetches`
   and commits it.
4. Then it asks for that club's last 10 league, friendly and playoff matches.
   That is 3 calls, with no retries.
5. It saves new matches with `source = 'opponent_history'`.

Rules:

- Each club is asked **once only**. A failed call is not tried again. A stop
  in the middle leaves the club claimed. This keeps the call count small and
  known.
- Only clubs that played one of your clubs qualify. A club found only in an
  opponent's history never starts its own backfill. This stops the backfill
  from growing without limit.
- A match that is already saved keeps its first source and is not counted twice.

With 50 waiting opponents, the first poll makes about 60 extra calls, the
next about 60, and the third about 30.

## 5. Snapshots: roster and standings

- `member_snapshots` and `member_snapshot_rows` save `/members/stats` every
  poll. These describe the roster **now**. Never apply them to older matches.
- Members have no numeric id. The link to a player is a name match, and it is
  empty when the name is unknown or ambiguous. Never join match history on it.
- `club_snapshots` saves a club's standing when a match is saved. It is the
  only way to know an opponent's rating at about the time of the match.

Matches and snapshots are different things. A saved match is a fixed fact.
A snapshot is a picture of "now" that is old by the next day.

## 6. Analysis rules that come from the data

A design review set these rules. Tests cover each rule.

- Quit matches are kept and counted. Opponents often quit when they lose.
  Removing those matches would remove the group's best nights.
- A near-complete appearance is 90 percent of the longest in that match side.
- "Team goals" is the score of the whole match. EA gives no event times, so
  "while on the pitch" cannot be measured.
- Ghost appearances never count.
- Main and practice clubs stay separate in reports. They are never pooled
  without a label.
- Opposition at a practice club is often weaker. The same player produced
  about +0.28 to +0.59 more goals plus assists per 90 minutes there. The code
  measures this gap per person (`strength.practice_premium`) and removes it.

## 7. Poll timing

The default is 30 minutes. The wait starts after a poll ends, so the real gap
is about 31 minutes. With 12 to 15 minute matches, a club needs more than
2.5 hours of non-stop play to push out an unsaved match.
