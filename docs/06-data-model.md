# The data model

ClubsXI uses one SQLite file. The default path is `data/clubsxi.sqlite3`
(`/data/clubsxi.sqlite3` in Docker). The full schema is
`src/clubsxi/schema.sql`. The collector creates the tables when it starts.

Two rules apply to every table:

1. Nothing is deleted. Bad data gets a flag.
2. Raw data is kept next to the parsed data, so that it can be parsed again.

## Tables

| Table | One row per | Main columns |
|---|---|---|
| `raw_responses` | EA call | `fetched_at`, `url`, `endpoint`, `params_json`, `http_status`, `error`, `body` |
| `matches` | match | `match_id` (key), `match_timestamp`, `match_type`, `validity`, `validity_notes`, `winner_by_dnf`, `source`, `seed_club_id`, `raw_json` |
| `match_clubs` | side of a match | `match_id`, `club_id`, `club_name`, `is_our_club`, `goals_for`, `goals_against`, `outcome`, `human_count`, `real_human_count`, `club_snapshot_id` |
| `players` | person (EA player id) | `player_id`, `latest_name`, `first_seen`, `last_seen` |
| `player_names` | name a person used | `player_id`, `name`, `first_seen`, `last_seen` |
| `player_match_stats` | appearance | `match_id`, `club_id`, `player_id`, `pos`, `archetype_id`, `seconds_played`, `rating`, `goals`, `assists`, `shots`, `passes_made`, `pass_attempts`, `tackles_made`, `tackle_attempts`, `saves`, `goals_conceded`, `event_aggregate_0..3`, `appearance_class`, `is_real_appearance`, `extras_json`, `raw_json` |
| `club_snapshots` | club standing at one time | `club_id`, `fetched_at`, `skill_rating`, `games_played`, `wins`, `losses`, `ties`, `goals`, `goals_against`, `raw_json` |
| `member_snapshots` | roster call | `club_id`, `fetched_at`, `member_count`, `position_count_json`, `raw_json` |
| `member_snapshot_rows` | member in a roster call | `name`, `player_id` (soft link, can be empty), `pro_pos`, `favorite_position`, `pro_overall`, season totals, `extras_json` |
| `opponent_history_fetches` | opponent asked by the backfill | `club_id`, `fetched_at`, `calls_made`, `calls_failed`, `matches_seen`, `matches_new` |
| `poll_log` | poll | `started_at`, `finished_at`, `calls_made`, `calls_failed`, `matches_seen`, `matches_new`, `matches_duplicate`, `errors` |
| `archetype_map` | build id | `archetype_id`, `name`, `verified`, `note` |
| `pro_pos_map` | `proPos` value | Empty on purpose. Fill a row only after a human confirms it in game. |
| `schema_meta` | setting | `schema_version` |

There is also one view, `lineups`. It joins `player_match_stats` with
`matches` to read back the full squad of any match.

## Keys and identity

- A match is unique by `matchId`. Both clubs see the same id. The match is
  saved once, from whichever club sees it first.
- A person is unique by the numeric EA player id. Names are only display.
- A side is unique by (`match_id`, `club_id`).
- An appearance is unique by (`match_id`, `club_id`, `player_id`).

## Upgrades

`db.connect()` runs the schema each time. Every `CREATE` uses
`IF NOT EXISTS`, so an old database keeps its data. New columns are added
with `ALTER TABLE` only when they are missing. After a change to the
appearance rules, run `python run.py rebuild` to compute the flags again from
the raw JSON.

## Useful queries

Count saved matches per club:

```sql
SELECT club_id, COUNT(*) FROM match_clubs WHERE is_our_club = 1 GROUP BY club_id;
```

All real appearances of one person:

```sql
SELECT m.match_timestamp, s.pos, s.archetype_id, s.goals, s.assists
FROM player_match_stats s JOIN matches m ON m.match_id = s.match_id
WHERE s.player_id = ? AND s.is_real_appearance = 1
ORDER BY m.match_timestamp;
```

Polls that had errors:

```sql
SELECT started_at, calls_failed, errors FROM poll_log WHERE calls_failed > 0;
```
