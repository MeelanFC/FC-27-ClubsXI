# Problems found, and how they were fixed

Each item has the symptom, the cause and the fix. Use this list when
something looks wrong.

## EA API

**1. Every call returns HTTP 403 Access Denied.**
- Cause: Akamai blocks requests that do not look like a browser.
- Fix: send the full browser header set in [03-ea-api.md](03-ea-api.md). If it
  still fails, update the `user-agent` and `sec-ch-ua` values to a current
  Chrome version in `src/clubsxi/ea_client.py`. `curl` got 403 even
  with the headers; Python worked.

**2. Old matches are missing.**
- Cause: EA keeps only the last 10 matches per match type, with no paging.
- Fix: poll every 30 minutes. Matches lost before the first poll cannot be
  recovered.

**3. The match count stops growing after a new game year starts.**
- Cause: EA gave the clubs new club ids. The old ids return empty lists with
  no error.
- Fix: find the new ids ([02-find-your-club-id.md](02-find-your-club-id.md)),
  add them to `CLUBSXI_CLUB_IDS`, and set `CLUBSXI_SEASON_CLUB_IDS` and
  `CLUBSXI_SEASON_START`.

**4. A name search returns the wrong club.**
- Cause: names are not unique, and the search can return an old id.
- Fix: always confirm the id with `python run.py check`.

**5. `clubIds=a,b` returns "Invalid query parameter".**
- Cause: EA accepts one club per call.
- Fix: one call per club.

**6. A bad parameter returns text, not JSON.**
- Fix: treat a non-JSON body as an error. The client does this.

## Data

**7. Friendlies show zero dribbles, zero shots on target and zero balls won.**
- Cause: EA sends no hidden counters in friendlies. The old code read the
  empty fields as zero.
- Fix: an empty counter row means "unknown". Those stats are left out of
  averages, not added as zero.

**8. A player shows in the lineup but did not play.**
- Cause: ghost appearances, with 0 seconds played.
- Fix: these rows get `appearance_class = 'ghost'` and never count.

**9. One side of a quit match has almost no stats.**
- Cause: EA wipes the labelled stats of the side that quit.
- Fix: in a rage quit, use only the side that stayed. The match keeps its
  `dnf` flag. It is not deleted.

**10. The roster says a person is a defender, but they play midfield.**
- Cause: `favoritePosition` and `proPos` describe the build, not the
  position played. `proPos` rarely matched reality.
- Fix: use only `pos` from each match.

**11. A roster member does not link to a match player.**
- Cause: `/members/stats` has no numeric id. The link is by name.
- Fix: the code links only when the name is not ambiguous. Otherwise the
  link stays empty. A wrong link is worse than no link.

**12. EA's season totals are higher than the saved matches.**
- Cause: EA counts matches that were lost between polls.
- Fix: none needed. The Players page shows both numbers.

## Analysis

**13. The best forward was dropped from the eleven.**
- Cause: the first picker ranked people by games played.
- Fix: games played only breaks ties now.

**14. Practice-club players looked better than they were.**
- Cause: weaker opponents at the practice club.
- Fix: the code measures each person's practice gap and removes it.

**15. A person with no games on a build ranked above people who played it.**
- Cause: the person got the build's league average with no evidence.
- Fix: a build with no games shows "no evidence" and gets no number.

**16. Two modules used different shrink strengths.**
- Cause: one module used a fixed k of 5. Another measured k at 9.5.
- Fix: measure k from the data. `strength.py`, `slot_ranking.py` and the
  picker now measure it. If you add a module, measure k there too.

**17. The picker moved people out of defence and goal.**
- Cause: the player score was used in every line. It cannot rank defenders
  or keepers once club strength is removed.
- Fix: the score counts only in ATK and MID, only in the person's main line.

**18. The move cost was too large.**
- Cause: the size came from all clubs. On one club it was 4 to 7 times too big.
- Fix: the cost was cut in half, and into goal it keeps the full size, so an
  outfield person never beats the AI keeper.

**19. A "goes with winning" test gave numbers that were too good.**
- Cause: the test used the same matches for the average and for the result.
- Fix: test on other matches only (split halves, walk-forward).

## Running

**20. The Squad page failed on a new, small database.**
- Cause: the picker needs other clubs' players to measure noise.
- Fix: with too few people, the picker uses safe defaults and the page still
  shows. It gets better as the backfill collects matches.

**21. Two collectors on one database.**
- Cause: SQLite allows one writer.
- Fix: run one collector per database. The viewer opens the database read only.

## Known limits

- The 90 percent rule compares players inside one club side, not across the
  whole match. A test review suggested the whole match. This is not changed yet.
- Code 217 is not exactly "shots on target". One blocked shot can be in it.
- Crosses (36, 37) and key passes are not decoded.
- Left and right, and exact positions, are not in the API.
