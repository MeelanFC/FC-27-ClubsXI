# The squad picker

The Squad page picks a best eleven for a 4-3-3, plus backups. It has two
versions with a toggle: **B (captain's rules)**, the default, and **A (by the
numbers)**. Code: `src/clubsxi/picker.py`. The page is rebuilt when a new
match is saved.

## 1. Who is in the pool

1. Read your clubs' league and playoff matches of this season
   (`CLUBSXI_SEASON_CLUB_IDS`, `CLUBSXI_SEASON_START`).
2. Join two accounts of one person (`config/same_person.txt`).
3. Count each person's games per line. Matches in the last 30 days count
   two times. The line with the most games is the person's **main line**.
4. Keep only people seen in the last 7 days. These are **active**.
5. A person with 25 percent or more of their games in goal is a **keeper**.

## 2. Version A: by the numbers

For each active person and each line, a gain in goals per match:

```
gain = human value + fit - move cost
```

| Part | Value |
|---|---|
| Human value | GK +0.98 over AI, any outfield line +0.29 |
| Fit | ATK and MID only, main line only: 0.5 x (shrunk score - club line average), with k = 16 (ATK) or 8 (MID). Plus 0.001 per game in that line, as a tie-break. |
| Move cost | From the share of the person's games in that line: under 10 percent 0.6, 10 to 25 percent 0.2, over 25 percent 0. Times 1.5 for GK and DEF, 1.0 for MID, 0.5 for ATK. Into goal: two times again. |
| Second line | A line with 25 percent or more that is not the main line costs 0.1 x the line multiplier. |
| Newcomers | Under 3 games in all: 0 where the build fits the line, else 0.2 x the multiplier, at most 0.25. |

Rules:

- An outfield person never goes in goal while a keeper is active.
- The search is exact. It tries every placement of every active person into
  GK 1, DEF 4, MID 3, ATK 3 or "out", and keeps the one with the highest total
  gain. A dynamic program over the count filled in each line keeps this fast.
- A person whose best gain is below 0 stays out, so an AI takes the spot.
- People not in the eleven go to the bench or reserve of their best line.

Then the line is put into named spots:

- **Attack (LW, ST, RW).** The most striker-like person goes first. "Striker-like"
  is box shots a game minus chances made a game, each against the club's
  attackers. Finisher and Target builds go to ST. Other builds go to a wing.
- **Defence (LB, CB, CB, RB).** Boss and Progressor go to CB. Other builds go
  to full back. Stats could not tell full backs from centre backs on other
  clubs (no better than chance), so the build decides.
- `config/positions.txt` can pin a person to a named spot.
- Left and right are not in the data.

## 3. Version B: the captain's rules

Version B uses rating points (6.5 = club average in that line) and named slots:
GK 1, CB 2, FB 2 (full back), MID 3, ST 1, W 2 (wing).

```
gain = human bonus + (line rating - 6.5) - off-line cost - build cost + 0.01 x games in that line
```

| Part | Value |
|---|---|
| Human bonus | GK 10, others 3. Any human beats any rating gap. |
| Line rating | The recent rating (last 30 days count two times). No rating: 6.0. |
| Off-line cost | Not the main line and not natural: 0.5 with 3 or more games there; else 2.0 x line multiplier (GK and DEF 1.5, MID 1.0, ATK 0.5). |
| Natural line | The build fits the line and 25 percent or more of games are there. Then no off-line cost. |
| Goal | A person who is not a keeper: -5 more in goal. |
| Build cost | Boss or Progressor at FB -1.0. Marauder at CB -0.5. Striker build on a wing or wing build at ST -0.2. Any other misfit -1.0. |

Build fit per slot: GK = Shot Stopper, Sweeper Keeper. CB = Boss, Progressor.
FB = Marauder. ST = Finisher, Target. W = Spark, Magician, Creator.

The rules in plain words:

1. Full-back spots go to full-back builds. Centre-back spots go to Boss or
   Progressor.
2. Close ratings are a tie. Recent form decides first, then experience.
3. A versatile person (25 percent of games outside defence) can move from CB
   to full back at no cost.
4. Pick for the whole team. The exact search puts each person where the team
   loses the least.
5. Move a person off their natural spot only when they are clearly better
   there. Another known line costs 0.5 points. A new line costs 2 points or more.
6. Where the captain has no rule, the data decides.

### Backups in version B: one person, one place

1. Each active person who does not start is placed once, at the slot where
   they add the most and where there is room.
2. Every card gets a silver before any card gets a bronze.
3. Each round is an exact search. Each placed person adds 10 to the total, so
   empty spots fill first.
4. Keepers fill only the goal card. Outfield people never fill the goal card.

## 4. The Cards page (head-to-head ranking)

Code: `src/clubsxi/slot_ranking.py` and `src/clubsxi/formation.py`. This is
an older, separate view at `/cards`.

1. Use near-complete appearances (90 percent of the longest in the match).
2. Put each match in a line by EA's band. Only this season's matches decide
   the order. Older matches show as history.
3. Each line has 3 or 4 numbers that passed the signal tests.
4. Shrink small samples toward the club's typical player in that line. The
   number of "games of typical" comes from the noise in one match against the
   real spread between people, measured on other clubs, capped at 15.
5. Compare each person head to head with each other candidate, per number.
   The order is the average share of comparisons won.
6. A person needs 3 games in the line. "How sure" is how often the person is
   gold when the games are resampled 100 times.
7. Each person is gold on one card only. `config/primary_slots.txt` can pin it.

## 5. Captain controls

All files are in `config/`. All are optional.

| File | What it does |
|---|---|
| `same_person.txt` | Joins two EA accounts of one person. |
| `positions.txt` | Pins a person to LW, ST, RW, W, CB, LB, RB or FB on the Squad page. |
| `primary_slots.txt` | Pins a person's gold card on the Cards page. |
| `depth_chart.txt` | A hand-written depth chart for `python run.py chart`. |
| `can_play.txt` | Who will or will not play a band, for `chart` and `tonight`. |

Command line extras: `python run.py tonight --online "Name1, Name2"` plans
one night from the depth chart and the people online.
