---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/snake-and-ladder.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Snake and Ladder: session isolation and a singleton game manager

## What it teaches

On the surface this is a trivial turn-based board game, but the interesting
requirement is the last one: many independent groups must be able to play at
the same time. That pushes the design toward a clean split between a *game
session* (one board, one set of players, one dice, one game loop) and a
*session manager* (a single registry that creates sessions and lets each run
independently). The board-game mechanics become almost incidental; the durable
lesson is how to package per-session state so sessions cannot interfere.

The entity model is deliberately flat and data-like: the board knows its cell
count and holds the jump table (which cell teleports you where, whether that
jump is a snake going down or a ladder going up); snakes and ladders are tiny
records of a start and end position; a player is a name plus a current
position; the dice is the single source of randomness. The session object owns
the loop — roll, advance, apply any jump at the landing cell, check for a
winner, rotate to the next player — and terminates when someone reaches the
final cell.

Concurrency is handled at the coarsest possible grain: the manager launches
each session on its own thread. Because a session touches only its own board,
players, and dice, no locking is needed inside the game logic at all —
isolation by ownership rather than by synchronization.

## Key patterns & decisions

- Session-scoped state: every mutable thing (positions, turn order) lives
  inside one game object, so concurrent sessions share nothing.
- Singleton manager as the factory and registry for active sessions — one
  well-known entry point that spawns games rather than a global game.
- One-thread-per-session concurrency: parallelism at the session boundary,
  zero locks inside, because ownership guarantees isolation.
- Snakes and ladders modeled as the same abstract idea — a positional jump
  from one cell to another — differing only in direction, stored as simple
  start/end pairs the board consults after each move.
- Dice isolated as its own object so randomness is injectable and the game
  loop is deterministic under test.
- Turn rotation as a simple queue-like cycle inside the session loop, ending
  on a reach-the-final-cell condition.

## When to apply / trade-offs

This is the pattern for any multi-tenant interactive system where sessions
are independent: game servers, collaborative editing rooms, per-customer
workflow runs. Prefer isolation-by-ownership over shared-state locking
whenever the domain permits it — it is simpler and scales without contention.
Trade-offs: a raw thread per session stops scaling in the thousands (a real
system would use an event loop or worker pool), and a singleton manager is a
global that complicates testing and horizontal scale-out; it works here
because the exercise is single-process. Also note the jump table is fixed at
board setup — fine for this game, but a design that regenerates jumps
mid-game would need the board to become mutable and session-locked.

## Fidelity check

1. Claim: the design supports concurrent independent games via a manager that
   runs each session separately. Support: the capture describes a singleton
   game-manager that keeps a list of active games, starts a new game from a
   list of player names, and runs each game on its own thread.
2. Claim: the board owns the snake/ladder jump data and resolves post-move
   position changes. Support: the capture states the board holds snake and
   ladder positions and exposes a way to get the adjusted position after
   landing on one.
3. Claim: the session object runs the whole game loop through a win
   condition. Support: the capture describes a game class whose play routine
   cycles players through dice rolls and position updates, applying snakes
   and ladders, until a player reaches the final cell.
