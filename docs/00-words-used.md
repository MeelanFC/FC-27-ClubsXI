# Words used in these docs

Each term has one meaning in all the docs.

| Term | Meaning |
|---|---|
| Pro Clubs | The EA FC game mode where each human controls one player in a club. |
| Club | A Pro Clubs team. EA gives each club a number, the **club id**. |
| Main club | The club that you play competitive games with. |
| Practice club | A second club that some groups use for practice games. Optional. |
| Scrim | A friendly match between your main club and your practice club. |
| Match type | One of `leagueMatch`, `friendlyMatch` or `playoffMatch`. |
| Endpoint | One web address of the EA API, for example `/clubs/matches`. |
| Parameter | A value that you add to an endpoint address, for example `clubIds=123`. |
| Field | One named value in an EA response, for example `goals`. |
| Raw response | The full text that EA sent, before any change. |
| Collector | The part of ClubsXI that asks EA for data and saves it. |
| Poll | One run of the collector: it asks EA for data one time. |
| Viewer | The read-only web pages of ClubsXI. |
| Line | One of the four broad position groups: GK, DEF, MID, ATK. |
| Band | The same as a line, with EA's words: goalkeeper, defender, midfielder, forward. |
| Slot | One named spot in a formation, for example LB, CB or ST. |
| Build | The archetype a player uses in a match, for example Finisher. EA calls it `archetypeid`. |
| Appearance | One player in one match. |
| Ghost appearance | An appearance where EA says the player played 0 seconds. |
| Short appearance | An appearance under 90 percent of the longest one in that club side. |
| Full appearance | An appearance of 90 percent or more of the longest one. |
| DNF | "Did not finish". One side quit the match early. EA sets `winnerByDnf`. |
| Hidden counters | The `match_event_aggregate_0..3` fields. They hold numbered event counts. |
| Code | One number in the hidden counters, for example `174` (dribbles). |
| Snapshot | A copy of data at one time, with the time saved beside it. |
| Shrink | Pull a small sample toward an average, so few games cannot give an extreme value. |
| k | "Games of average" that a shrink adds. A bigger k pulls harder. |
| Walk-forward test | A test that predicts each game from earlier games only. |
| Split-half test | Compare a person's odd games with their even games. Same result means steady. |
| GD | Goal difference: goals for minus goals against. |
| Gold, silver, bronze | Starter, next in, and the person after that, on the Squad page. |
