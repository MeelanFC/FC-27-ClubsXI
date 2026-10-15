# The player score, and how it was tested

This file explains the player score on the Scores and Squad pages, how a
score becomes a rating out of 10, and how the methods were tested.

## 1. Why not EA's match rating

EA's `rating` partly follows the result. The same actions get a higher rating
in a win. A score built on it would reward people for being on a good team.
ClubsXI uses its own score. It uses no EA rating points.

## 2. The player score

Code: `src/clubsxi/player_score.py`.

The score is "goals that this person added in this match, from what they did".
Each action has a value in goals. The values were fitted on 1,086 club sides
from other clubs' FC27 league matches, with the number of humans held fixed.

| Action | Count from | Goals per action |
|---|---|---|
| Shot in the box | codes 13 + 14 | +0.42 |
| Shot from outside the box | codes 18 + 19 | +0.17 |
| Through ball | code 152 | +0.056 |
| Line break | codes 8 + 184 + 10 | +0.044 |
| Skill-move beat | code 38 | +0.13 |
| Foul won | code 4 | +0.07 |
| Pass completed | `passesmade` | +0.007 |
| Interception | code 6 | +0.10 |
| Ball won | codes 108 + 109 + 110 | +0.07 |
| Ball lost | codes 105 + 106 + 107 | -0.028 |
| Pass failed | `passattempts` - `passesmade` | -0.035 |
| Penalty given away | code 94 | -0.66 |
| Save | `saves` | +0.30 (rough, not fitted) |

How the values were found:

- Shots: goals per shot of each kind.
- Creating actions: how much each adds to the team's shot value.
- Defending actions: how much each lowers goals let in.
- Saves: about one in three saved shots would have been a goal.

Goals and assists are shown, but they are **not** in the score. Finishing
changes a lot from match to match.

### Reduced score for friendlies

Friendlies have no hidden counters. They get a reduced score from labelled
fields only: shots (+0.33), completed and failed passes, tackles won (as ball
won, +0.07) and saves. The page marks them as reduced. The season table and
the Squad page use league and playoff matches only.

### How well the score works

Checked on one club's own league matches. These matches were not used to fit
the values.

- The difference in team scores follows the real goal difference with
  r = 0.62. EA's rating sums reach only r = 0.51.
- A person's score in odd matches follows their even matches with r = 0.78.
  The score is steady.
- Forwards score higher by the nature of the job. So each person is compared
  with the club's average **in the same line**.

## 3. From score to rating out of 10

Code: `ratings()` in `src/clubsxi/picker.py`. The cards show this rating.

For each line (GK, DEF, MID, ATK):

1. Take each person's scores in that line (league and playoff, season only).
2. Find the club average in that line. Call it `mu`.
3. Shrink each person's average toward `mu`:

   ```
   shrunk = (sum of scores + k * mu) / (number of games + k)
   ```

   `k` per line: ATK 16, MID 8, DEF 20, GK 20. A person with few games stays
   near the average.
4. Find the spread: the standard deviation of the plain averages of the
   regulars (5 or more games). With fewer than 3 regulars, use 0.3.
5. Scale: `rating = 6.5 + (shrunk - mu) / spread`.
6. Limit the rating to 1.0 to 9.9.

So 6.5 is the club average in that line, and one point is one spread.

Version B of the Squad page uses a recent rating. It is the same, but matches
in the last 30 days count two times.

The `k` values come from the data. ATK 16 and MID 8 were measured on other
clubs. DEF and GK showed no stable difference between people, so their `k`
is large and their ratings stay near 6.5.

## 4. How the methods were tested

### Signal tests (per counter)

Used to choose which counters enter the score and the picker. Details are in
[04-hidden-counters.md](04-hidden-counters.md), section 7.

- Steady: split-half reliability of a person's average.
- Goes with winning: correlation with the team's goal difference, measured
  on **other** matches than the ones that made the average. The same-match
  version is inflated: goals plus assists for forwards gave +0.54 on the same
  matches and +0.17 on other matches.

### Walk-forward test (whole picker)

A walk-forward test predicts each match from earlier matches only. Nothing
from the match itself, or from later matches, can leak in.

Procedure:

1. Sort the finished league and playoff matches by time.
2. Use the first 20 matches as history only.
3. For each later match, rebuild ratings, usual lines and move costs from
   earlier matches only.
4. Predict the goal difference: the sum of the model parts plus an offset.
   The offset is the average error on earlier predicted matches.
5. Compare the prediction with the real goal difference (MSE, MAE, r).
6. Resample the matches (bootstrap) to see how often a model beats another.

Results on one club (one season of matches):

| Model | MSE | MAE |
|---|---|---|
| Past average result only | 4.69 | 1.68 |
| + human count | 4.71 | 1.72 |
| + move cost (first size) | 5.54 | 1.87 |
| + player score | 5.47 | 1.87 |

Results on other clubs (89 clubs, 542 matches, sizes fit on half the clubs):

- Human count lowered the error by 11.7 percent, in 100 percent of splits.
- Move cost gave no gain.
- Player score lowered the error by 0.2 to 0.4 percent, in 70 to 74 percent
  of splits. Its best size is about half its goal value.

What this means:

1. On one club, nothing clearly beats "the club's usual goal difference".
2. The number of humans is the only part that clearly predicts results.
3. The first move cost was 4 to 7 times too large. It was cut in half.
4. The player score adds a little. It is used at half size, only in ATK and
   MID, and only as a tie-break.
5. Leave-one-match-out testing was tried and rejected. It is biased against
   the player score by its design.

With the new sizes, the full formula on the club's matches gave MSE 4.81
and MAE 1.63, against 5.02 and 1.67 for the average only. It won in 65 percent
of resamples. That is better than before, and still mostly noise.

### Review results

Four independent reviews tested one idea each on one club's FC27 league
matches and about 800 other-club matches:

- 90 to 95 percent of one match result is luck, AI teammates and the opponent.
- Each extra human against the opponent adds about +0.25 goal difference.
- Pairs, units and "keep the lineup together" showed no signal (p from 0.76 to 0.91).
- On/off and plus-minus numbers were noise at one season of matches.
- Individual stats have a small real signal. About 5 matches are needed in a
  line; 3 are too few to start a person on numbers alone.

## 5. Two methods that failed

Both were built, both were wrong. Do not repeat them.

1. **Rank by games played.** This measures who turns up. It punishes people
   who change build. It can drop a club's best forward.
2. **Rank by raw goals plus assists.** A practice club often plays weaker
   teams. The same player produces more there. The fix: remove
   the measured practice gap per person, then shrink toward an average.

Another bug to avoid: a person with **no** games on a build must not get the
build's league average. That puts missing evidence above real evidence.
