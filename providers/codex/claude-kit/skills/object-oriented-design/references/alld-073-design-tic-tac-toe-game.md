---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/tic-tac-toe.md
author: ashishps1
license-note: ideas absorbed in own words; no text or code reproduced
---

# Minimal turn-based game decomposition (tic-tac-toe)

## What it teaches

The smallest useful illustration of separating a game's three concerns:
state (the grid), rules (what makes a move legal, what ends the game), and
flow (whose turn it is, when to stop, what to announce). Even in a
toy-sized problem, the design resists putting everything in one class and
instead draws the same boundaries you would want in any turn-based system.

## Key patterns & decisions

- **Board owns state and rule queries.** The grid entity exposes operations
  to place a mark, test whether someone has completed a line
  (row/column/diagonal), and test whether the grid is exhausted — but it
  does not know about turns or players' identities beyond their symbols.
- **Game as the controller loop.** A separate controller object sequences
  turns, asks the board whether a proposed move is legal, alternates the
  active player, and decides between win and draw outcomes. Flow logic
  never leaks into the board.
- **Player as a thin identity object.** A player is just a name bound to a
  symbol; all decision-making stays outside it. Two-player alternation is
  the controller's job.
- **Explicit terminal-state distinction.** The end of the game is one of
  two clearly separated predicates — a winning line exists, or the board is
  full without one — checked in that order so a full board with a win is
  never misreported as a draw.
- **Move validation before mutation.** Illegal moves (occupied cell,
  out-of-range coordinates) are rejected up front, keeping the board's
  state transitions total and predictable.
- **Thin entry point.** The top-level program only wires players into a
  game and starts it, keeping construction separate from play — the same
  composition-root discipline used in larger systems.

## When to apply / trade-offs

- Use this state/rules/flow split as the default skeleton for any
  turn-based interaction: board games, wizard-style multi-step forms, or
  approval workflows. The controller-vs-state boundary is what lets rules
  be unit-tested without a UI.
- The design hard-codes a 3x3 grid and two players; generalizing to NxN or
  N-in-a-row pushes the win check toward incremental evaluation around the
  last move rather than a full-board scan — worth doing only when the board
  grows.
- A natural next refinement is a game-status enumeration or a small state
  machine (in-progress / won / drawn) so that callers cannot advance a
  finished game; the described design implies this but keeps it informal.

## Fidelity check

1. *Claim:* the grid entity answers rule queries but does not manage turns.
   *Support:* the capture assigns move placement, winner detection, and
   board-fullness checks to the board class, while turn handling and
   player interaction are listed under the game class.
2. *Claim:* the controller validates moves and declares the outcome.
   *Support:* the capture states the game class validates moves, manages
   player turns, and determines a winner or a draw.
3. *Claim:* a draw is defined by exhaustion of the grid without a winning
   line. *Support:* the capture's requirements say the game ends in a draw
   when all cells are filled and no player has three in a row.
