# The EA Pro Clubs API

This file lists every EA endpoint that ClubsXI uses, what each parameter does,
what each field means, and what was learned by trial and error.

EA does not document this API. All facts here come from live calls made in FC26
and FC27. The API can change without notice.

## 1. Access

- Base address: `https://proclubs.ea.com/api/fc`
- No API key. No login. Read only.
- The same base address works for FC26 and FC27. `/api/fc27` returns 404.

### The 403 problem and the fix

EA's site is behind Akamai, a service that blocks requests that do not look
like a browser. A request without browser headers gets **HTTP 403 Access Denied**.

Send all of these headers with every request:

```
accept: application/json
accept-language: en-US,en;q=0.9
sec-ch-ua: "Chromium";v="126", "Not-A.Brand";v="24", "Google Chrome";v="126"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-origin
referer: https://proclubs.ea.com/
x-requested-with: XMLHttpRequest
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
```

`src/clubsxi/ea_client.py` sends them. In testing, Python's standard
`urllib` with these headers got HTTP 200. `curl` with the same headers
got 403. Akamai can also check the connection itself, not only the headers.
If you write your own client, test it first.

### Platform

Use `platform=common-gen5`. Crossplay makes this the right label for most
clubs. `pc` returned the same club. `common-gen4` and `nx` returned nothing.

### Rate limits

EA publishes no rate limit. No limit was hit in more than 100 test calls. The
collector waits 2 seconds between calls (`CLUBSXI_CALL_SPACING_SECONDS`).
EA has outages. A client must accept 403, 404, 5xx, plain text and empty lists
without a crash.

## 2. Endpoints that work

| Endpoint | Parameters | Returns |
|---|---|---|
| `/clubs/matches` | `platform`, `clubIds`, `matchType`, `maxResultCount` | Full match objects. The main data source. |
| `/clubs/info` | `platform`, `clubIds` | Name, clubId, regionId, teamId, customKit. A map keyed by club id. |
| `/clubs/overallStats` | `platform`, `clubIds` | skillRating, wins, draws, losses, goals, promotions, last 10 results and opponents. |
| `/members/stats` | `platform`, `clubId` | Current roster with season totals per member. Note: `clubId`, not `clubIds`. |
| `/members/career/stats` | `platform`, `clubId` | Current roster with career totals. |
| `/allTimeLeaderboard/search` | `platform`, `clubName` | Clubs whose name matches, with all-time records. |
| `/allTimeLeaderboard` | `platform` | Top 100 clubs, with skillRating and current division. |
| `/settings` | none | A lookup table of divisions (keys 1 to 10). |
| `/club/playoffAchievements` | `platform`, `clubId` | Found in the code of EA's own club pages. Note: `club`, singular. Not used by ClubsXI. |

These returned 404 in FC26 and FC27: `/clubs/seasonalStats`,
`/clubs/matchStats`, `/seasonalLeaderboard`, `/members/archetypes`,
`/members/positions`, `/archetypes`, `/positions`, `/clubs/members`,
`/clubs/playoffAchievements` (plural), `/clubs/archetypes`.

## 3. `/clubs/matches`: rules found by trial and error

These rules are the most important facts in this file.

1. **Only 10 matches per match type.** `maxResultCount` is capped at 10.
   A value of 20, 50 or 100 still returns 10. No value returns 5.
2. **No paging.** These parameters were tried and ignored: `offset`, `page`,
   `cursor`, `from`, `start`, `skip`, `before`, `beforeMatchId`,
   `timestamp`, `gmt`. Each returned the same newest 10 matches.
3. **One club per call.** `clubIds=a,b` returns
   `Invalid query parameter: clubIds`.
4. **Three match types only.** `leagueMatch`, `friendlyMatch` and
   `playoffMatch` work. `cupMatch`, `dropInMatch`, `rushMatch`,
   `seasonMatch`, `seasonalMatch` and `clubMatch` return
   `Invalid query parameter: matchType`.
5. **Bad parameters return plain text, not JSON.** Treat a non-JSON body as an error.

Result: a match is lost when 10 newer matches of the same type arrive before
you save it. A heavy night can play 10 league matches in about 2.5 hours
(12 to 15 minutes each). Poll every 30 minutes.

## 4. The match object

Top-level keys: `matchId`, `timestamp`, `timeAgo`, `clubs`, `players`, `aggregate`.

| Key | Meaning |
|---|---|
| `matchId` | Unique id of the match. The same on both clubs' lists. Use it to remove duplicates. |
| `timestamp` | Unix time of the match. |
| `timeAgo` | `{"number": .., "unit": ..}`, for display only. |
| `clubs` | A map: club id -> that side's result. Two entries. |
| `players` | A map: club id -> player id -> player object. Humans only. |
| `aggregate` | The player values summed per club. |

### Fields in `clubs[clubId]`

| Field | Meaning |
|---|---|
| `goals`, `goalsAgainst`, `score` | Goals for and against this side. |
| `result` | EA's result code for this side. ClubsXI works out win, draw or loss from the goals. |
| `wins`, `losses`, `ties` | 1 or 0 for this match. |
| `winnerByDnf` | Not 0 when one side quit before the end. |
| `matchType` | A number code for the match type. |
| `season_id`, `gameNumber`, `date`, `TEAM` | Extra values. Stored, not used. |
| `details` | `name`, `clubId`, `regionId`, `teamId`, `customKit` (kit colours, crest, stadium name). Can be `null`. |

### Fields in each player object

All values are strings. Convert them when you read them. Store them raw.

| Field | Meaning |
|---|---|
| `playername` | The EA name shown in game. A person can change it. |
| (the map key) | The numeric EA player id. It does not change. Use it as the identity. |
| `pos` | Broad position only: `goalkeeper`, `defender`, `midfielder`, `forward`. |
| `archetypeid` | The build, a number 1 to 13. See section 6. |
| `secondsPlayed`, `gameTime` | Seconds on the pitch. The two were equal in every row checked. |
| `rating` | EA's match rating. It partly follows the result. |
| `goals`, `assists`, `shots` | As named. |
| `passesmade`, `passattempts` | Completed passes and all passes. |
| `tacklesmade`, `tackleattempts` | Won tackles and all tackles. |
| `saves`, `goalsconceded` | Keeper values. |
| `ballDiveSaves`, `crossSaves`, `goodDirectionSaves`, `parrySaves`, `punchSaves`, `reflexSaves` | Save types. |
| `cleansheetsany`, `cleansheetsdef`, `cleansheetsgk` | Clean sheet flags. |
| `redcards`, `mom` | Red cards, man of the match. |
| `wins`, `losses`, `userResult`, `SCORE` | Result values for this player. |
| `realtimegame`, `realtimeidle` | Real-time seconds in the match and idle. Not used. |
| `match_event_aggregate_0` to `_3` | The hidden counters. See [04-hidden-counters.md](04-hidden-counters.md). |
| `vprohackreason` | Always `0` in every row seen. Not 0 may mean a modified pro. ClubsXI flags the match as `suspicious`. |
| `vproattr` | Usually `NH`. Elsewhere a long attribute string. |
| `namespace` | Not known. Stored. |

FC27 has the same 39 player fields as FC26. None were added or removed.

### What the match object does NOT have

- No exact position (LB, CB, ST). Only the four broad values in `pos`.
- No formation.
- No left or right.
- No event times. You cannot know who was on the pitch when a goal was scored.
- No AI players. AI teammates do not appear in `players`.
- No possession percent and no expected goals. These are only on the in-game screen.

## 5. Data quality facts

- **Ghost appearances.** Some rows have `secondsPlayed = 0`. In one sample,
  about 2 percent of rows. These people did not play. Do not count them.
- **Friendlies have no hidden counters.** All `match_event_aggregate` fields
  are empty in friendly matches. Treat those stats as unknown, not zero.
- **Rage quits.** When one side quits, that side's labelled stats are wiped
  (for example almost no shots or passes left, while the in-game screen showed many). Only
  the side that stayed has usable stats.
- **Some league rows have empty counters too.** Treat them as unknown.

## 6. Builds (`archetypeid`)

All 13 ids were confirmed. Each was named by a player in game and matched to
a live match row for that same player.

| id | Build | Usual line |
|---|---|---|
| 1 | Shot Stopper | GK |
| 2 | Sweeper Keeper | GK |
| 3 | Progressor | DEF (centre back) |
| 4 | Boss | DEF (centre back) |
| 5 | Disruptor (FC27 replaced Engine with Disruptor) | DEF or MID |
| 6 | Marauder | DEF (full back) or MID |
| 7 | Recycler | MID |
| 8 | Maestro | MID |
| 9 | Creator | MID or ATK |
| 10 | Spark | ATK (wing) |
| 11 | Magician | ATK |
| 12 | Finisher | ATK (striker) |
| 13 | Target | ATK (striker) |

The ids go in order from keeper to striker. A tracker site that labels builds
showed the same names for the same ids.

Facts about builds:

- The build does not fix the position. The same build was played at LW, ST
  and LCM in one match.
- People change build between matches. One person used five builds.
- The word before a build name on some tracker sites ("Defensive Spark") is
  only the broad `pos` value.

## 7. `/members/stats`

Returns two keys: `members` and `positionCount`.

- `positionCount` is four club-wide counts, for example
  `{"midfielder": 5, "goalkeeper": 2, "forward": 4, "defender": 6}`.
  It is not per member. You cannot find positions by comparing snapshots.
- `members` has one entry per member with current-season totals:
  `name`, `gamesPlayed`, `winRate`, `goals`, `assists`, `ratingAve`,
  `passesMade`, `passSuccessRate`, `tacklesMade`, `tackleSuccessRate`,
  `shotSuccessRate`, `cleanSheetsDef`, `cleanSheetsGK`, `manOfTheMatch`,
  `redCards`, `favoritePosition`, `proName`, `proPos`, `proStyle`,
  `proHeight`, `proNationality`, `proOverall`, and `prevGoals` to `prevGoals10`.
- **There is no numeric player id.** Only the display name. A link from a
  member to a match player is a name match. ClubsXI links a name only when it
  is not ambiguous. Otherwise it stores no link.
- `favoritePosition` is broad only.
- `proPos` held only the values 0, 5, 14 and 25 in more than 700 rows. In the
  classic EA position table these are GK, CB, CM and ST. It is **not** where a
  person plays: it rarely matched a human report. It may be the
  position that the pro was built as. This is not confirmed.
- `proName`, `proOverall`, `proHeight` and similar describe the build **now**.
  Save them with a time. Never apply them to older matches.
- The totals here are EA's own season totals. They are often higher than the
  sum of your saved matches, because matches that were lost between polls are
  still in EA's totals.

## 8. `/clubs/overallStats`

Returns a list with one object per club: `skillRating`, `gamesPlayed`,
`wins`, `losses`, `ties`, `goals`, `goalsAgainst`, `promotions`,
`relegations`, `lastMatch0` to `lastMatch9`, `lastOpponent0` to
`lastOpponent9`, streaks and `leagueAppearances`.

- It describes the club **now**. There is no history. To know an opponent's
  strength at the time of a match, save a snapshot when you save the match.
- A brand new club can return an empty list. That is normal.
- `gamesPlayed` was not always current in FC27.

## 9. Sources and community work

- Community decoders of the hidden counters (not EA; treat as hints):
  `https://github.com/1erkandogan/fc27-clubs-api` and
  `https://github.com/Interactive-63/eafc-pro-clubs-api-research`.
- Community API clients: `https://github.com/carlos-menezes/fc-clubs-api`.
- Fan request to EA for exact positions (no EA answer): EA Forums,
  "FC27 Clubs API, Please Expose More Player Stats and Exact Positions".
