---
source: https://github.com/ashishps1/awesome-low-level-design/blob/main/problems/chess-game.md
author: ashishps1 for in-repo problems
license-note: ideas absorbed in own words; no text or code reproduced
---

# Object-oriented decomposition of a two-player chess engine

## What it teaches

This LLD exercise is the canonical demonstration of polymorphic behavior over a
shared abstraction. Chess has one board, two players, and six kinds of pieces
that differ only in how they are permitted to move. The design captures that by
defining a single abstract piece type carrying the state every piece shares
(which side it belongs to, where it sits on the grid) and one abstract
legality-check operation. Each concrete piece kind then supplies only its own
movement rule. Everything else — turn alternation, move validation, and
end-of-game detection — is layered on top without ever caring which specific
piece is involved.

The decomposition splits responsibilities across four collaborating layers:

- a piece hierarchy that answers "could this piece, in principle, make this
  move" for its own kind;
- a board that owns the 8x8 grid, knows what occupies each square, and is the
  authority on whether a proposed move is valid in context (including detecting
  terminal states such as checkmate and stalemate);
- a player object whose role is simply to submit moves;
- a game controller that wires the pieces together, enforces alternating turns,
  and decides when the game has ended and with what result.

A small value object representing a single move (the piece plus its target
square) travels between these layers, which keeps the player-to-game interface
narrow and makes moves easy to log or replay later.

## Key patterns & decisions

- Abstract base class with one polymorphic legality method; each piece subtype
  overrides it, so adding a new piece kind never touches the game loop.
- Separation of piece-local legality (can this shape of move happen at all)
  from board-level validation (is the path clear, is the king left in check) —
  two distinct validation layers.
- A dedicated game-controller object that owns turn order and terminal-state
  detection, keeping the board a passive data authority rather than a rules
  engine for flow.
- Move reified as a small immutable value object rather than passing raw
  coordinates through method parameters.
- Thin entry-point class that only bootstraps the game, keeping the domain
  model runnable and testable without any UI.

## When to apply / trade-offs

Reach for this shape whenever a domain has many variants of one concept that
differ only in behavior, not in interface: pricing rules, discount strategies,
validation policies. The trade-off in chess specifically is that some rules
(castling, en passant, promotion) are interactions between pieces and history,
not properties of a single piece — a pure per-piece legality method struggles
with them, and real engines push that logic up into the board/game layer. The
lesson generalizes: put variant-local logic in the variant, but resist forcing
cross-cutting rules into the polymorphic method just to keep the hierarchy
"pure."

## Fidelity check

1. Claim: the design uses one abstract piece type with a single overridable
   legality operation. Support: the capture describes an abstract base class
   for pieces holding color and position and declaring an abstract can-move
   check, with king/queen/rook/bishop/knight/pawn classes each implementing
   their own movement logic.
2. Claim: the board, not the pieces, is responsible for detecting terminal
   game states. Support: the capture assigns checkmate and stalemate
   determination, along with move-validity checking and piece placement, to
   the board class.
3. Claim: a separate controller object manages turn flow and outcome.
   Support: the capture describes a game class that initializes the board,
   handles alternating player turns, and determines the result, with a
   distinct top-level class serving only as the application entry point.
