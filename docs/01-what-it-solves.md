# What ClubsXI solves

## The problem

A Pro Clubs group often has 15 to 25 people. Only 11 can play at one time.
People join and leave during the night. The group argues about two questions:

1. Where does each person play best, and with which build?
2. Who starts tonight, and where?

The game gives little help:

- EA keeps only the last 10 matches of each match type. A busy night pushes
  older matches out. After that, they are lost.
- EA shows only four broad positions: goalkeeper, defender, midfielder and
  forward. It never says LB, CB or ST.
- EA's match rating partly follows the result. A player on a winning side
  gets a higher rating for the same actions.
- Most stats are hidden in numbered codes with no names.

## What ClubsXI does

1. It saves every match before EA deletes it. The database becomes the only
   full history of your club.
2. It keeps every raw EA response. You can analyse the data again later with
   better methods.
3. It decodes the hidden counters into named stats (dribbles, interceptions,
   shots in the box and more).
4. It gives each person a player score that comes from actions, not from the
   result.
5. It picks a best eleven from the people who play now. The picker puts
   humans first, keeps people near the line they usually play, and uses the
   score only where tests show that it helps.
6. It shows all of this on a simple web page that any group member can open.

## What ClubsXI does not do

- It does not know exact positions. EA does not send them.
- It does not know left from right.
- It cannot predict one match well. Tests show that 90 to 95 percent of one
  match result comes from luck, AI teammates and the opponent.
- It does not replace the captain. The captain can override every pick with
  plain text files in `config/`.

## What the tests found, in short

These results come from one club's games and from the games of about 1,100
other clubs. [07-player-score-and-testing.md](07-player-score-and-testing.md)
gives the numbers.

- The biggest effect is the number of humans on the pitch. Each extra human
  against the opponent adds about 0.25 goals of goal difference a game.
- Keeping people in the line they usually play helps a little.
- A build that does not fit the line costs about 0.9 goals a game on other
  clubs.
- Pairs and "chemistry" showed no effect.
- Individual numbers help only a little. They break ties.
