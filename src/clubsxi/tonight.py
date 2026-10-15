"""Who plays where tonight.

The depth chart answers "who normally". This answers the question actually
asked at 9pm: seven people are online, where does each of them go?

How it decides, in order:

  1. Eligibility. A player is eligible for a band if they have really played
     there, or the captain has said they can in config/can_play.txt.
  2. Scarcity first. The slot with the fewest eligible people online gets
     filled first. Fill the easy slots first and you strand the hard ones.
  3. Habit. Within a slot, the person with the most near-complete games in
     that broad band goes in, then the most recent.

What it deliberately does NOT do is rank people by results. Nobody has the 20
games in a role that the review set as the floor for judging performance, so
this is about coverage, not quality. Anything left over is AI.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import chart as chart_module

# The one thing we have real evidence for: a human in goal is worth a lot.
# Games with a human keeper conceded far fewer goals than games with AI.
# Few games had no keeper, so this is a strong hint, not a measured constant.
GK_FIRST = True


@dataclass
class Assignment:
    slot: str
    player: str
    band: str
    games: int
    reason: str


@dataclass
class Plan:
    assignments: list[Assignment]
    ai_slots: list[str]
    unused: list[str]
    unknown_names: list[str]
    warnings: list[str]
    slot_order: list[str]


def _resolve(names: list[str], known: set[str]) -> tuple[list[str], list[str]]:
    """Matches what was typed against real player names, case insensitively."""
    lookup = {k.lower(): k for k in known}
    found: list[str] = []
    missing: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        exact = lookup.get(name.lower())
        if exact:
            found.append(exact)
            continue
        partial = [real for low, real in lookup.items()
                   if name.lower() in low]
        if len(partial) == 1:
            found.append(partial[0])
        else:
            missing.append(name)
    return found, missing


def plan(chart: chart_module.Chart, conn: sqlite3.Connection,
         available: list[str], *,
         can: dict[str, set[str]] | None = None,
         wont: dict[str, set[str]] | None = None) -> Plan:
    can = can or {}
    wont = wont or {}
    games = chart_module.broad_appearances(conn)
    last = chart_module._last_seen(conn)

    known = chart_module.known_names(conn) | set(can)
    players, unknown = _resolve(available, known)

    def eligible(player: str, band: str) -> bool:
        if band in wont.get(player, set()):
            return False
        return games.get((player, band), 0) > 0 or band in can.get(player, set())

    def habit(player: str, band: str) -> tuple:
        return (-games.get((player, band), 0),
                -last.get((player, band), 0),
                player)

    slots = [s for s in chart.slots if s.broad]
    left = list(players)
    assignments: list[Assignment] = []
    filled: set[str] = set()

    # Goalkeeper is settled BEFORE anything else, when someone online can do
    # it. Filling the easy slots first is exactly how you strand the keeper,
    # and AI in goal is the one gap we have real numbers for.
    if GK_FIRST:
        for slot in slots:
            if slot.broad != "goalkeeper":
                continue
            keepers = [p for p in left if eligible(p, "goalkeeper")]
            if not keepers:
                continue
            keepers.sort(key=lambda p: habit(p, "goalkeeper"))
            pick = keepers[0]
            left.remove(pick)
            filled.add(slot.name)
            assignments.append(Assignment(
                slot.name, pick, "goalkeeper",
                games.get((pick, "goalkeeper"), 0),
                "keeper filled first, AI in goal costs the most"))

    # The captain's own starters go in next if they are online. His word wins.
    for slot in slots:
        starter = slot.pick(0)
        if starter and starter in left and eligible(starter, slot.broad):
            left.remove(starter)
            filled.add(slot.name)
            assignments.append(Assignment(
                slot.name, starter, slot.broad,
                games.get((starter, slot.broad), 0),
                "captain's first choice"))

    # Then scarcity. Keeper first when anyone online can do it, because that
    # is the only gap we have real numbers for.
    while left:
        options = []
        for slot in slots:
            if slot.name in filled:
                continue
            candidates = [p for p in left if eligible(p, slot.broad)]
            if candidates:
                options.append((slot, sorted(candidates,
                                             key=lambda p: habit(p, slot.broad))))
        if not options:
            break

        def urgency(item):
            slot, candidates = item
            keeper = 0 if (GK_FIRST and slot.broad == "goalkeeper") else 1
            return (keeper, len(candidates), slot.name)

        options.sort(key=urgency)
        slot, candidates = options[0]
        pick = candidates[0]
        left.remove(pick)
        filled.add(slot.name)
        reason = ("only one option online"
                  if len(candidates) == 1
                  else "most games in that role of those online")
        if GK_FIRST and slot.broad == "goalkeeper":
            reason = "keeper filled first, AI in goal costs the most"
        assignments.append(Assignment(
            slot.name, pick, slot.broad,
            games.get((pick, slot.broad), 0), reason))

    order = {s.name: i for i, s in enumerate(slots)}
    assignments.sort(key=lambda a: order.get(a.slot, 99))
    ai_slots = [s.name for s in slots if s.name not in filled]

    warnings: list[str] = []
    keeper_slots = [s.name for s in slots if s.broad == "goalkeeper"]
    if any(name in ai_slots for name in keeper_slots):
        warnings.append(
            "NO HUMAN KEEPER. Games with a human in goal usually concede "
            "far fewer goals than games with AI in goal. It is the biggest "
            "gap the data shows. Worth someone taking a turn.")
    if len(ai_slots) > len(slots) // 2:
        warnings.append(
            str(len(ai_slots)) + " of " + str(len(slots))
            + " slots are AI. Expect the shape to be loose.")

    return Plan(
        assignments=assignments,
        ai_slots=ai_slots,
        unused=left,
        unknown_names=unknown,
        warnings=warnings,
        slot_order=[s.name for s in slots],
    )


def alternatives(conn: sqlite3.Connection, player: str, *,
                 can: dict[str, set[str]] | None = None,
                 wont: dict[str, set[str]] | None = None,
                 limit: int = 3) -> list[tuple[str, int]]:
    """A player's top bands by how much they have actually played there."""
    can = can or {}
    wont = wont or {}
    games = chart_module.broad_appearances(conn)

    rows = [(band, count) for (name, band), count in games.items()
            if name == player and band not in wont.get(player, set())]
    for band in can.get(player, set()):
        if band not in {b for b, _ in rows} and band not in wont.get(player, set()):
            rows.append((band, 0))

    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows[:limit]


def render(p: Plan, conn: sqlite3.Connection, *,
           can: dict[str, set[str]] | None = None,
           wont: dict[str, set[str]] | None = None) -> str:
    out: list[str] = []

    if p.unknown_names:
        out.append("Could not match these names: "
                   + ", ".join(p.unknown_names))
        out.append("")

    out.append("  " + "SLOT".ljust(6) + "PLAYER".ljust(20)
               + "GAMES".ljust(8) + "WHY")

    placed = {a.slot: a for a in p.assignments}
    for slot in p.slot_order:
        a = placed.get(slot)
        if a:
            out.append("  " + a.slot.ljust(6) + a.player.ljust(20)
                       + (str(a.games) + " " + a.band[:3]).ljust(8) + a.reason)
        else:
            out.append("  " + slot.ljust(6) + "AI".ljust(20)
                       + "".ljust(8) + "nobody online can cover it")

    if p.warnings:
        out.append("")
        for warning in p.warnings:
            out.append("  ! " + warning)

    if p.unused:
        out.append("")
        out.append("  Online but not placed: " + ", ".join(p.unused))
        out.append("  Every slot they can play is already taken.")

    out.append("")
    out.append("  Other places each of tonight's players could go:")
    for a in p.assignments:
        others = alternatives(conn, a.player, can=can, wont=wont)
        text = ", ".join(band + " (" + str(n) + ")" for band, n in others)
        out.append("    " + a.player.ljust(20) + text)

    out.append("")
    out.append("  This is about COVERAGE, not who is better. Nobody has the")
    out.append("  20 games in a role needed to judge that yet. Numbers are")
    out.append("  near-complete games in that broad band. Move anyone you")
    out.append("  like; the point is that no slot is quietly left to AI.")
    return "\n".join(out)
