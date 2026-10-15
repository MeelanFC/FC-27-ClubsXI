# The hidden event counters

Each player object has four fields named `match_event_aggregate_0` to
`match_event_aggregate_3`. EA does not name what is inside. This file gives
the decoded meanings and the tests behind them.

## 1. Format

Each field is a text list of `code:count` pairs, separated by commas:

```
0:2,5:1,6:3,11:1,30:12,32:4,34:6,214:1
```

To read it:

1. Join the four fields.
2. Split the text at each comma.
3. Split each part at the colon. The first number is the code. The second is the count.
4. Add the counts of the same code.
5. A missing code means 0, but only when the row has some counters.

An empty field in all four places means "unknown". This is normal in friendly
matches and in some league rows. Never read it as zero.

The code that does this is `ev()` in `src/clubsxi/picker.py`.

## 2. How the codes were decoded

Three methods were used:

1. **Tracker site screenshots.** A fan site shows named stats per player for a
   match. Each named stat was compared with every code. One code matched all
   10 players exactly for each stat. Then 36 more rows from 4 more matches were
   checked.
2. **Equality tests.** A code was compared with EA's named fields (for
   example `goals`) over thousands of rows.
3. **The in-game Match Facts screen.** The full-time screen of 3 league
   matches was photographed. Team totals were compared with code sums for
   both teams.

Only full-time matches count as proof. In a rage quit the counters are cut
differently.

## 3. Confirmed codes

"Confirmed" means a direct match with a labelled source.

| Code | Meaning | Evidence |
|---|---|---|
| 214 | Goals | Equals `goals` in 97.8 percent of 6,671 full-time rows. |
| 11 | Assists | Equals `assists` in 97.1 percent of rows. |
| 217 + 218 | Shots | Sum equals `shots` in 96.2 percent of rows. |
| 30 + 32 + 34 | Passes completed (forward + back + sideways) | Sum equals `passesmade` in 94.9 percent of rows. |
| 164 | Tackles won | Equals `tacklesmade` in 89.0 percent of rows. |
| 267 | Saves where the keeper dived the right way | Equals `goodDirectionSaves` in 97.7 percent of keeper rows. |
| 174 | Dribbles | Tracker screenshots, 34 of 36 rows not zero, all equal. |
| 6 | Interceptions | Tracker screenshots, 22 rows not zero; in-game screen exact for 2 full-human matches. |
| 9 | Clearances | Tracker screenshots, 6 rows not zero. |
| 5 | Blocks | Tracker screenshots, only 3 rows not zero. The weakest of these. |
| 115 | Second assists | Tracker screenshots, 4 rows not zero. |
| 108, 109, 110 | Possession won in the defensive, middle and attacking third | Team totals equal in 4 of 4 matches. |
| 105, 106, 107 | Possession lost in the defensive, middle and attacking third | Team totals equal in 4 of 4 matches. |
| 8 | Defensive line broken around | In-game screen, exact for both teams. |
| 184 | Defensive line broken through | In-game screen, exact for both teams. |
| 10 | Defensive line broken over | In-game screen, exact for both teams. |
| 145 | Corners taken | In-game screen, exact for both teams. |
| 4 | Fouls suffered (free kicks won) | In-game screen exact; across 1,262 team-games it goes with the opponent's fouls (r = 0.43), not their shots (r = 0.02). |
| 13 + 14 | Shots inside the box | In-game screen, exact in 3 of 3 matches. |
| 157 | Set-piece passes | In-game screen, exact on the full-human side in 3 matches. |

All won possession is 108 + 109 + 110. All lost is 105 + 106 + 107.

## 4. Codes that add up exactly, with names not fully proven

| Relation | Rows that match |
|---|---|
| 13 + 18 = 217 | 100 percent |
| 14 + 19 = 218 | 95 to 99 percent |
| 99 + 100 + 101 + 102 + 103 = 219 | 100 percent |
| 229 + 230 = 164 | 97 percent |
| 38 (skill-move beats) is never more than 112 (players beaten) | 100 percent |
| 112 is never more than 174 (dribbles) | 99.3 percent |

Likely names:

- 13 and 14: shots on and off target from inside the box. 18 and 19: from outside.
- 217 is "on target" in most matches, but one blocked shot can land in it.
  Do not call it on target in reports.
- 99 to 103: "out of position" feedback, severity 1 to 5. 219 is the total.
- 229: standing tackles won. 230: slide tackles won (fouls per game are
  higher when 230 is above 0).

## 5. Likely codes

These pass logic checks but have no direct labelled match.

| Code | Likely meaning | Check |
|---|---|---|
| 104 | Caught offside | Forwards 0.17 a game, midfielders 0.04, defenders 0.00. |
| 94 | Penalty given away | Never more than code 3 (80 of 80); defenders 0.047 a game, forwards 0.003. |
| 3 | Fouls in the defensive area | Defenders 0.14 a game against 0.03. |
| 2 | Fouls elsewhere | Community hint. |
| 118 | Assists from through balls | Never more than assists in 98.8 percent; never more than 152. |
| 152 | Through balls | 152 equals the in-game "through passes" for humans. |
| 143 | First-time passes | Never more than passes made in 97.0 percent; fits the in-game screen. |
| 38 | Skill-move beats | Always inside 112. |
| 16 | Finesse shots | Exact in 2 full-time matches, failed in 1 rage quit. |
| 202 | Shots aimed at the near side | Exact in 2 full-time matches, failed in 1 rage quit. |
| 95 | Yellow cards | Exact in 2 matches; yellows not more than fouls only 67.5 percent. Weak. |
| 24 / 25, 26 / 27, 28 / 29 | Short, medium, long passes, completed / failed | Pair sums match the tracker panel. |
| 30 / 31, 32 / 33, 34 / 35 | Forward, backward, sideways passes, completed / failed | Pair sums match the tracker panel. |
| 55 to 58 | Keeper feedback after the 1st, 2nd, 3rd, 4th goal let in | Only 0 or 1; 4 rows break the order. |
| 59 | Goals let in after the 4th | Fits all rows, but only 2 informative rows. |
| 175, 176, 177, 182, 183, 207, 212 | Pass decision feedback ("no good option", "good option", "best option", and others) | Community hints only. |

## 6. Codes that are still not known

- 36 and 37: something about crosses. Neither fits the in-game cross count in
  every match.
- 114: maybe key passes. It is not the same as 118.
- 111: not possession (failed against the in-game possession value).
- 153 and 204: one of them is offside passes. A match with offsides is needed.
- 49 to 54 and 268: keeper codes with no match to a named save type.
- About 40 more codes have no supported meaning.

These are **not** in the API at all, as far as tested: possession percent,
expected goals, ball recovery time, dribble success rate, key passes, duels
won, aerial duels.

## 7. Which counters help to pick players

A counter is useful only when it passes two tests on other clubs' league games:

- **Steady:** a split-half test. A person's average in odd games must match
  their even games.
- **Goes with winning:** a person's average must go with their team's goal
  difference.

About 30 to 40 people per line were tested. Anything under about 0.3 is noise.

| Line | Counter | Steady | Goes with winning | Used |
|---|---|---|---|---|
| DEF | First-time pass share (143 / pass attempts) | 0.66 | +0.36 | Yes |
| DEF | Dribbles (174), fewer is better | 0.76 | -0.38 | Yes |
| DEF | Penalties given away (94), fewer is better | 0.50 | -0.40 | Yes |
| ATK | Skill-move beats (38) | 0.76 | +0.37 | Yes |
| ATK | Line breaks (8 + 184 + 10) | 0.82 | +0.20 | Yes |
| ATK | Through balls (152) | 0.92 | +0.17 | Yes |
| MID | Shots in the box (13 + 14) | 0.80 | +0.15 | Yes |
| MID | Line breaks | 0.24 | | No |
| any | Crosses, cross accuracy, slide tackles, fouls, offsides, fouls won, finesse shots, corners | | | No |

Raw clearances, blocks and interceptions go with the **other** team shooting
more. They show how much defending was needed, not how well it was done. Do
not use them to rank defenders.
