# FC 27 ClubsXI: stats tracker and lineup picker for EA SPORTS FC 27 Pro Clubs

ClubsXI keeps every EA FC Pro Clubs match that your club plays. It then uses
those matches to show who should start, and where.

Works with **EA SPORTS FC 27 Clubs** (also called Pro Clubs, FC Clubs or
FC 27 Clubs) and was first built on FC 26. It uses the Pro Clubs API at
`proclubs.ea.com`, the same data that Pro Clubs stat tracker sites use.

Search words: Pro Clubs, EA FC Clubs, FC 27 Pro Clubs, FC 26 Pro Clubs,
Clubs stats, Pro Clubs tracker, Pro Clubs API, Pro Clubs match history,
Pro Clubs lineup, best XI, archetypes.

EA keeps only the last 10 matches of each match type. Older matches are lost.
ClubsXI asks EA for new matches every 30 minutes and saves them in one
database file. Then a web page shows the matches, the players, a player
score, and a best eleven.

ClubsXI is not made by EA and is not linked to EA. EA SPORTS FC and Pro Clubs
are trademarks of Electronic Arts. It uses EA's undocumented web data, which has no
official documentation and can change at any time.

## What you get

- A collector. It saves every match, roster and raw EA response.
- A web viewer (read only) with these pages: Overview, Matches, Players,
  Positions, Squad, Scrims, Scores and Poll log.
- A player score that uses actions, not EA's match rating.
- A Squad page that picks a best eleven from the people who play now.
- Full notes on the EA API, including the hidden event counters.

## Quick start (about 10 minutes)

You need Python 3.10 or newer. ClubsXI uses only the Python standard library.

1. Download this project to a folder on your computer.
2. Find your club id. Follow [docs/02-find-your-club-id.md](docs/02-find-your-club-id.md).
3. Copy `.env.example` to a new file named `.env`.
4. In `.env`, write your club id after `CLUBSXI_CLUB_IDS=`.
5. Open a terminal in the project folder.
6. Run `python run.py check`. Make sure that the line starts with `OK`.
7. Run `python run.py poll`. This saves the matches EA has now.
8. Run `python run.py web`.
9. Open `http://localhost:8080` in a browser.
10. To save new matches all the time, run `python run.py run` and keep it open.

To run it all day on a home server, use Docker. Follow
[docs/10-run-and-deploy.md](docs/10-run-and-deploy.md).

## Read the docs in this order

| File | Topic |
|---|---|
| [00-words-used.md](docs/00-words-used.md) | The words these docs use |
| [01-what-it-solves.md](docs/01-what-it-solves.md) | The problem, in plain words |
| [02-find-your-club-id.md](docs/02-find-your-club-id.md) | Find your club id and other clubs |
| [03-ea-api.md](docs/03-ea-api.md) | Every EA endpoint, parameter and field |
| [04-hidden-counters.md](docs/04-hidden-counters.md) | The decoded hidden event counters |
| [05-collector.md](docs/05-collector.md) | How matches are collected and checked |
| [06-data-model.md](docs/06-data-model.md) | The database tables |
| [07-player-score-and-testing.md](docs/07-player-score-and-testing.md) | The player score and how it was tested |
| [08-squad-picker.md](docs/08-squad-picker.md) | How the best eleven is picked |
| [09-card-ui.md](docs/09-card-ui.md) | The flat card design, with its CSS |
| [10-run-and-deploy.md](docs/10-run-and-deploy.md) | Commands, Docker, backups, tests |
| [11-problems-and-fixes.md](docs/11-problems-and-fixes.md) | Problems found, and how they were fixed |

## Project layout

```
src/clubsxi/     the code (collector, analysis, web viewer)
config/          files you edit by hand (all optional)
tests/           tests and synthetic EA data (no real players)
tools/           optional analysis scripts
docs/            the documentation
```

## Tests

```bash
python -m pytest
```

One test needs NumPy. Install it with `pip install pytest numpy`.

## License

MIT. See [LICENSE](LICENSE).
