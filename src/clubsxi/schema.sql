-- ClubsXI collector schema. SQLite is the system of record.
-- Rule: nothing is ever deleted. Bad data is flagged, not removed.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Every successful or failed EA call, kept whole and untouched.
CREATE TABLE IF NOT EXISTS raw_responses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at   INTEGER NOT NULL,          -- unix seconds
    url          TEXT    NOT NULL,
    endpoint     TEXT    NOT NULL,
    params_json  TEXT    NOT NULL,
    http_status  INTEGER NOT NULL,
    error        TEXT,
    body         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_raw_fetched_at ON raw_responses (fetched_at);
CREATE INDEX IF NOT EXISTS ix_raw_endpoint   ON raw_responses (endpoint);

-- One row per EA match, globally unique, no matter which of our clubs saw it.
CREATE TABLE IF NOT EXISTS matches (
    match_id          TEXT PRIMARY KEY,
    match_timestamp   INTEGER,             -- unix seconds, from EA
    match_type        TEXT NOT NULL,       -- leagueMatch / friendlyMatch / playoffMatch
    winner_by_dnf     INTEGER NOT NULL DEFAULT 0,
    club_count        INTEGER NOT NULL,
    validity          TEXT NOT NULL,       -- ok / dnf / incomplete / suspicious
    validity_notes    TEXT,
    first_seen_at     INTEGER NOT NULL,
    raw_response_id   INTEGER REFERENCES raw_responses (id),
    source            TEXT NOT NULL DEFAULT 'own',
    seed_club_id      TEXT,
    raw_json          TEXT NOT NULL        -- the single match object, verbatim
);
CREATE INDEX IF NOT EXISTS ix_matches_ts   ON matches (match_timestamp);
CREATE INDEX IF NOT EXISTS ix_matches_type ON matches (match_type);

CREATE TABLE IF NOT EXISTS opponent_history_fetches (
    club_id TEXT PRIMARY KEY,
    fetched_at INTEGER NOT NULL,
    calls_made INTEGER NOT NULL DEFAULT 0,
    calls_failed INTEGER NOT NULL DEFAULT 0,
    matches_seen INTEGER NOT NULL DEFAULT 0,
    matches_new INTEGER NOT NULL DEFAULT 0
);

-- Snapshot of a club's standing at the time we ingested a match.
-- Never look this up later and pretend it was historical.
CREATE TABLE IF NOT EXISTS club_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id        TEXT    NOT NULL,
    fetched_at     INTEGER NOT NULL,
    skill_rating   INTEGER,
    games_played   INTEGER,
    wins           INTEGER,
    losses         INTEGER,
    ties           INTEGER,
    goals          INTEGER,
    goals_against  INTEGER,
    raw_json       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snap_club ON club_snapshots (club_id, fetched_at);

-- One row per side of a match. Two rows per normal match.
CREATE TABLE IF NOT EXISTS match_clubs (
    match_id          TEXT    NOT NULL REFERENCES matches (match_id),
    club_id           TEXT    NOT NULL,
    club_name         TEXT,
    is_our_club       INTEGER NOT NULL DEFAULT 0,
    goals_for         INTEGER,
    goals_against     INTEGER,
    outcome           TEXT,               -- win / draw / loss / unknown
    ea_result         TEXT,               -- EA's own raw result code
    winner_by_dnf     INTEGER NOT NULL DEFAULT 0,
    human_count       INTEGER NOT NULL DEFAULT 0,
    real_human_count  INTEGER NOT NULL DEFAULT 0,  -- excludes ghosts
    team_id           TEXT,
    season_id         TEXT,
    club_snapshot_id  INTEGER REFERENCES club_snapshots (id),
    raw_json          TEXT    NOT NULL,
    PRIMARY KEY (match_id, club_id)
);
CREATE INDEX IF NOT EXISTS ix_mc_club ON match_clubs (club_id);

-- People. The numeric EA id is the identity. Names change, ids do not.
CREATE TABLE IF NOT EXISTS players (
    player_id    TEXT PRIMARY KEY,
    latest_name  TEXT,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);

-- Every name a player has ever appeared under.
CREATE TABLE IF NOT EXISTS player_names (
    player_id   TEXT NOT NULL REFERENCES players (player_id),
    name        TEXT NOT NULL,
    first_seen  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    PRIMARY KEY (player_id, name)
);

-- One row per human, per club, per match.
CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id           TEXT    NOT NULL REFERENCES matches (match_id),
    club_id            TEXT    NOT NULL,
    player_id          TEXT    NOT NULL REFERENCES players (player_id),
    player_name        TEXT,
    pos                TEXT,               -- broad only: goalkeeper/defender/midfielder/forward
    archetype_id       TEXT,               -- raw EA id, never a guessed name
    seconds_played     INTEGER,
    game_time          INTEGER,
    rating             REAL,
    goals              INTEGER,
    assists            INTEGER,
    shots              INTEGER,
    passes_made        INTEGER,
    pass_attempts      INTEGER,
    tackles_made       INTEGER,
    tackle_attempts    INTEGER,
    saves              INTEGER,
    goals_conceded     INTEGER,
    clean_sheets_any   INTEGER,
    clean_sheets_def   INTEGER,
    clean_sheets_gk    INTEGER,
    red_cards          INTEGER,
    mom                INTEGER,
    wins               INTEGER,
    losses             INTEGER,
    user_result        TEXT,
    vpro_hack_reason   TEXT,
    event_aggregate_0  TEXT,               -- undecoded EA event counters, kept raw
    event_aggregate_1  TEXT,
    event_aggregate_2  TEXT,
    event_aggregate_3  TEXT,
    appearance_class   TEXT NOT NULL,      -- full / short / ghost
    is_real_appearance INTEGER NOT NULL,
    extras_json        TEXT NOT NULL,      -- every field we did not name above
    raw_json           TEXT NOT NULL,
    PRIMARY KEY (match_id, club_id, player_id)
);
CREATE INDEX IF NOT EXISTS ix_pms_player ON player_match_stats (player_id);
CREATE INDEX IF NOT EXISTS ix_pms_slice  ON player_match_stats (player_id, pos, archetype_id);

-- Lineups are a reading of player_match_stats, not a second copy of it.
CREATE VIEW IF NOT EXISTS lineups AS
SELECT
    p.match_id,
    p.club_id,
    p.player_id,
    p.player_name,
    p.pos,
    p.archetype_id,
    p.is_real_appearance,
    m.match_timestamp,
    m.match_type
FROM player_match_stats p
JOIN matches m ON m.match_id = p.match_id;

-- What happened on each poll cycle.
CREATE TABLE IF NOT EXISTS poll_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       INTEGER NOT NULL,
    finished_at      INTEGER,
    calls_made       INTEGER NOT NULL DEFAULT 0,
    calls_failed     INTEGER NOT NULL DEFAULT 0,
    matches_seen     INTEGER NOT NULL DEFAULT 0,
    matches_new      INTEGER NOT NULL DEFAULT 0,
    matches_duplicate INTEGER NOT NULL DEFAULT 0,
    errors           TEXT
);

-- Empty on purpose. Only fill a row once a human has confirmed the mapping
-- in game. Raw archetype_id on player_match_stats is always the truth.
CREATE TABLE IF NOT EXISTS archetype_map (
    archetype_id TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    verified     INTEGER NOT NULL DEFAULT 0,
    note         TEXT
);

-- ---------------------------------------------------------------------------
-- Roster snapshots. Review rule D2 and D9.
--
-- /members/stats describes a club's CURRENT roster and each member's CURRENT
-- pro build. It is never per match. These rows are timestamped and must never
-- be projected backwards onto matches that were played earlier.
--
-- Confirmed by inspection: positionCount is four club-wide broad
-- counts, not a per-member exact-position counter. There is nothing to diff.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS member_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    club_id             TEXT    NOT NULL,
    fetched_at          INTEGER NOT NULL,
    member_count        INTEGER NOT NULL,
    position_count_json TEXT,          -- club-wide broad counts, verbatim
    raw_response_id     INTEGER REFERENCES raw_responses (id),
    raw_json            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msnap_club ON member_snapshots (club_id, fetched_at);

-- One row per member per snapshot.
--
-- WARNING: /members/stats carries no numeric EA player id, only the display
-- name. player_id here is a SOFT link resolved by name at snapshot time. It
-- can be wrong or NULL. Never merge match history on it.
CREATE TABLE IF NOT EXISTS member_snapshot_rows (
    snapshot_id        INTEGER NOT NULL REFERENCES member_snapshots (id),
    club_id            TEXT    NOT NULL,
    name               TEXT    NOT NULL,
    player_id          TEXT,            -- soft, name-matched, may be NULL
    pro_name           TEXT,
    pro_pos            TEXT,            -- raw EA code. 0/5/14/25 seen so far.
    favorite_position  TEXT,            -- broad only
    pro_style          TEXT,
    pro_overall        INTEGER,
    pro_height         INTEGER,
    pro_nationality    TEXT,
    games_played       INTEGER,
    win_rate           INTEGER,
    goals              INTEGER,
    assists            INTEGER,
    rating_ave         REAL,
    passes_made        INTEGER,
    pass_success_rate  INTEGER,
    tackles_made       INTEGER,
    tackle_success_rate INTEGER,
    shot_success_rate  INTEGER,
    clean_sheets_def   INTEGER,
    clean_sheets_gk    INTEGER,
    man_of_the_match   INTEGER,
    red_cards          INTEGER,
    extras_json        TEXT    NOT NULL,
    raw_json           TEXT    NOT NULL,
    PRIMARY KEY (snapshot_id, club_id, name)
);
CREATE INDEX IF NOT EXISTS ix_msrow_name   ON member_snapshot_rows (name);
CREATE INDEX IF NOT EXISTS ix_msrow_player ON member_snapshot_rows (player_id);

-- Candidate meanings for pro_pos. Nothing here is fact until a human confirms
-- it in game, exactly like archetype_map.
CREATE TABLE IF NOT EXISTS pro_pos_map (
    pro_pos  TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    note     TEXT
);

-- ---------------------------------------------------------------------------
-- Archetype names.
--
-- verified = 1 means a human named the build in game and a live match row
-- carried that archetype id for that same player. All 13 ids were confirmed
-- this way in FC26 and FC27. See docs/03-ea-api.md.
-- ---------------------------------------------------------------------------

INSERT INTO archetype_map (archetype_id, name, verified, note) VALUES
  ('1',  'Shot Stopper',   1, 'goalkeeper build, confirmed in game'),
  ('2',  'Sweeper Keeper', 1, 'goalkeeper build, confirmed in game'),
  ('3',  'Progressor',     1, 'defender build, confirmed in game'),
  ('4',  'Boss',           1, 'defender build, confirmed in game'),
  ('5',  'Disruptor',      1, 'confirmed in game; FC27 replaced Engine with Disruptor'),
  ('6',  'Marauder',       1, 'confirmed in game'),
  ('7',  'Recycler',       1, 'midfielder build, confirmed in game'),
  ('8',  'Maestro',        1, 'midfielder build, confirmed in game'),
  ('9',  'Creator',        1, 'midfielder build, confirmed in game'),
  ('10', 'Spark',          1, 'attacker build, confirmed in game'),
  ('11', 'Magician',       1, 'attacker build, confirmed in game'),
  ('12', 'Finisher',       1, 'attacker build, confirmed in game'),
  ('13', 'Target',         1, 'attacker build, confirmed in game')
ON CONFLICT (archetype_id) DO UPDATE SET
    -- A name only ever gains confirmation, never loses it.
    verified = MAX(archetype_map.verified, excluded.verified),
    name     = excluded.name,
    note     = CASE WHEN excluded.verified >= archetype_map.verified
                    THEN excluded.note ELSE archetype_map.note END;
