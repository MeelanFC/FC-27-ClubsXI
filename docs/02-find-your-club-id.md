# Find your club id, and find other clubs

ClubsXI needs the club id of each club that you follow. A club id is a number,
for example `1234567`.

## Procedure 1: find your club id by name (recommended)

1. Open a terminal in the project folder.
2. Run this command. Replace `My Club` with your club name.

   ```bash
   python run.py find "My Club"
   ```

3. Read the list. Each line shows a club id, a club name and a game count.
4. Copy the id of your club.
5. Make sure that it is your club. Do procedure 3.

The name search is not reliable. It can return many clubs with the same
name, or a club id from an earlier game year. Always do procedure 3.

## Procedure 2: find your club id in a browser

1. Open this address in a browser. Replace `My Club` with your club name.

   ```
   https://proclubs.ea.com/api/fc/allTimeLeaderboard/search?platform=common-gen5&clubName=My Club
   ```

2. Find your club in the list.
3. Copy the number in `clubId`.

If the browser shows "Access Denied", use procedure 1. A plain `curl`
command also gets "Access Denied", even with browser headers (tested
October 2026). [03-ea-api.md](03-ea-api.md) explains this.

## Procedure 3: make sure that the id is your club

1. Put the id in `.env`, after `CLUBSXI_CLUB_IDS=`.
2. Run `python run.py check`.
3. Read the line. It shows the club name and the number of members.
4. Optional: write your own EA name after `CLUBSXI_CHECK_PLAYER=` in `.env`.
   Run `python run.py check` again. The line must say that your name is present.

## Procedure 4: find the club id from a tracker site

Some fan sites show Pro Clubs matches. Their match pages often show the club
id in the web address or in the match data.

1. Find one of your recent matches on the site.
2. Look for a number of 5 to 8 digits next to your club name or in the address.
3. Do procedure 3 with that number.

## A new game year can give your club a new id

When FC26 changed to FC27, EA gave existing clubs new club ids. The old ids
returned empty match lists. The collector saw nothing, and no error showed.

If your match count stops growing after a new game year starts:

1. Find the new id with procedure 1.
2. Add the new id to `CLUBSXI_CLUB_IDS`. Keep the old id there too, so that
   the old matches still count as yours.
3. Put only the new ids in `CLUBSXI_SEASON_CLUB_IDS`.
4. Write the Unix time of the first game of the new season in
   `CLUBSXI_SEASON_START`. Unix time is seconds since 1 January 1970 (UTC).
   You can convert a date on any "epoch converter" web page.

## Find other clubs from your own matches

Every match holds the club id of the opponent. ClubsXI uses this to collect
other clubs' matches. Those matches give the large sample that the tests need.

There are three ways to find other clubs:

1. **Your matches.** In `/clubs/matches`, the keys of `clubs` are the two club
   ids of that match. One is yours. The other is the opponent.
2. **Your club record.** `/clubs/overallStats` has `lastOpponent0` to
   `lastOpponent9`. These are the ids of your last 10 opponents.
3. **The leaderboard.** `/allTimeLeaderboard?platform=common-gen5` returns the
   top 100 clubs with their ids.

The collector does way 1 automatically. It is called the opponent history
backfill. [05-collector.md](05-collector.md) explains it.
