# Run, deploy, back up and test

## 1. Run on your own computer

You need Python 3.10 or newer. No packages are needed to run ClubsXI.

1. Copy `.env.example` to `.env`.
2. Write your club id after `CLUBSXI_CLUB_IDS=`.
3. Open a terminal in the project folder.
4. Run `python run.py check`.
5. Run `python run.py run`. Keep the terminal open. It saves new matches every 30 minutes.
6. Open a second terminal in the same folder.
7. Run `python run.py web`.
8. Open `http://localhost:8080`.

`run.py` reads `.env` and points Python at `src/`. Nothing is installed.
The database is `data/clubsxi.sqlite3`.

## 2. Commands

| Command | What it does |
|---|---|
| `python run.py find "Club Name"` | Searches EA for club ids by name. |
| `python run.py check` | Confirms that each club id works. |
| `python run.py poll` | One poll, then stops. |
| `python run.py run` | Polls forever. |
| `python run.py status` | Row counts and the last polls. |
| `python run.py web` | Starts the viewer (read only). |
| `python run.py report` | Prints the text report. |
| `python run.py rebuild` | Computes the appearance flags again after a rule change. |
| `python run.py squad` | Best builds per person and a 4-3-3, as text. |
| `python run.py chart` | Checks `config/depth_chart.txt` against real matches. |
| `python run.py tonight --online "A, B, C"` | A plan for tonight from the people online. |
| `python run.py xi`, `form`, `builds` | Older text views. |

## 3. Run on a home server with Docker

You need Docker with the Compose plugin. The image is `python:3.12-alpine`
with no extra packages.

1. Copy the project folder to the server.
2. In the folder, copy `.env.example` to `.env`.
3. Write your club id in `.env`.
4. Run `docker compose up -d --build`.
5. Run `docker compose ps`. Wait until both containers show `healthy`.
   The collector shows `starting` for the first few minutes. That is normal.
6. On the server, open `http://localhost:8080`. To open it from other computers
   on your home network, change `127.0.0.1:8080:8080` to `8080:8080` in
   `docker-compose.yml`, run step 4 again, and open
   `http://SERVER-ADDRESS:8080`.

Two containers start:

| Container | Job |
|---|---|
| `clubsxi-collector` | Polls EA and writes the database. The only writer. |
| `clubsxi-web` | Serves the viewer. Opens the database read only. |

The database is in the Docker volume `clubsxi-data`. The `config/` folder is
mounted read only, so you can edit the captain files on the server.

### Security

- The viewer has no login. Do not open port 8080 to the internet. Use your
  home network or a private VPN.
- Both containers run as a normal user, with a read-only file system, no
  Linux capabilities, and CPU and memory limits.
- The collector needs only outbound HTTPS.

### Check that it works

```bash
docker compose logs -f collector
```

```bash
docker compose exec collector python -m clubsxi status
```

The collector's health check passes when a poll finished in the last
3 poll intervals (90 minutes by default).

### Update to a new version

1. Copy the new code over the old folder. Keep `.env` and `config/`.
2. Run `docker compose up -d --build`.

The database stays in the volume. The schema upgrades itself.

### Add a club later

1. Add the id to `CLUBSXI_CLUB_IDS` in `.env`.
2. Run `docker compose up -d`.

## 4. Back up

All data is in one file. Back it up while the collector runs:

```bash
docker compose exec collector python -c "import sqlite3; s=sqlite3.connect('/data/clubsxi.sqlite3'); d=sqlite3.connect('/tmp/backup.sqlite3'); s.backup(d); d.close()"
```

```bash
docker compose cp collector:/tmp/backup.sqlite3 ./clubsxi-backup.sqlite3
```

You can also back up the whole Docker volume `clubsxi-data`.

Rule: never run two collectors on one database file. SQLite allows only one
writer. For a second group, use a second folder with its own volume.

## 5. All settings

Put settings in `.env`. Only `CLUBSXI_CLUB_IDS` is required.

| Setting | Default | Meaning |
|---|---|---|
| `CLUBSXI_CLUB_IDS` | (none) | Your club ids, comma separated. |
| `CLUBSXI_PRACTICE_CLUB` | (none) | Practice club ids. Their gap is removed from comparisons. |
| `CLUBSXI_SEASON_CLUB_IDS` | all club ids | Club ids that count for this season. |
| `CLUBSXI_SEASON_START` | `0` | Unix time of the first match of the season. 0 = all. |
| `CLUBSXI_CHECK_PLAYER` | (none) | A name that `check` looks for in each roster. |
| `CLUBSXI_TIMEZONE` | `UTC` | Time zone for "one night" on the Scrims page. |
| `CLUBSXI_PLATFORM` | `common-gen5` | EA platform label. |
| `CLUBSXI_MATCH_TYPES` | all three | Match types to ask for. |
| `CLUBSXI_POLL_MINUTES` | `30` | Wait between polls. |
| `CLUBSXI_MAX_RESULT_COUNT` | `10` | EA's cap. Do not raise it. |
| `CLUBSXI_OPPONENT_HISTORY_CLUBS_PER_POLL` | `20` | Opponents to backfill per poll. 0 = off. |
| `CLUBSXI_CALL_SPACING_SECONDS` | `2.0` | Wait between calls. |
| `CLUBSXI_REQUEST_TIMEOUT` | `30` | Seconds before a call fails. |
| `CLUBSXI_MAX_RETRIES` | `4` | Attempts per call. |
| `CLUBSXI_DB` | `data/clubsxi.sqlite3` | Database file. |
| `CLUBSXI_REPORT` | `data/report.txt` | Text report, written after each poll. |
| `CLUBSXI_RAW_DUMP_DIR` | (off) | Also write each raw response to a file here. |
| `CLUBSXI_WEB_HOST` | `127.0.0.1` | Viewer address. `127.0.0.1` = this computer only. Docker sets `0.0.0.0`. |
| `CLUBSXI_WEB_PORT` | `8080` | Viewer port. |
| `CLUBSXI_CHART` | `config/depth_chart.txt` | Depth chart file. |
| `CLUBSXI_CAN_PLAY` | `config/can_play.txt` | Who can play where. |
| `CLUBSXI_POSITIONS` | `config/positions.txt` | Spot pins for the Squad page. |
| `CLUBSXI_PRIMARY_SLOTS` | `config/primary_slots.txt` | Gold pins for the Cards page. |
| `CLUBSXI_SAME_PERSON` | `config/same_person.txt` | Two accounts, one person. |

## 6. Tests

1. Install the test tools: `pip install pytest numpy`.
2. Run `python -m pytest` in the project folder.

The tests use synthetic EA data in `tests/fixtures/`. It has the same shape as
real EA responses. All names, ids and numbers are made up by
`tools/make_fixtures.py`, which you can run again to rebuild them.
`tests/conftest.py` sets the fake club ids: 100001 (main), 100002 (practice)
and 100003 (an old season id).

The tests check, among other things:

- a second poll adds no duplicates,
- ghost appearances and quits get their flags,
- unknown fields are kept,
- friendlies with no counters count as unknown, not zero,
- the picker never puts an outfield person in goal while a keeper is online,
- a later match can never change an earlier walk-forward prediction.

If a pytest plugin on your computer fails to load, run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
```
