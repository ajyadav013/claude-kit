---
source: https://algomaster.io/learn/lld/command
author: algomaster.io (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Command pattern: requests as first-class objects with built-in undo

## What it teaches

The chapter motivates the Command pattern through a smart-home hub. A naive
controller holds a direct field for every device and a dedicated method for
every action, which means each new device grows the controller, no action can
be reversed without bespoke bookkeeping, nothing can be queued or scheduled
(actions exist only as method calls, not values), and every trigger surface
(button, app, voice, timer) must re-couple to the device classes.

The fix is to reify each action into an object that carries everything needed
to run it — a reference to the target device plus the execution logic — behind
a tiny common interface (run, and usually reverse). Four roles emerge: the
command interface; concrete commands that bind one action to one receiver; the
receiver, which is a plain domain object with no knowledge that commands
exist; and the invoker (remote, scheduler), which holds only the interface
type and can therefore fire any command without ever importing a device class.
The restaurant analogy: the order slip is the command, the waiter the invoker,
the chef the receiver — waiter and chef never need to know each other's job.

## Key patterns & decisions

- Reify requests as objects: an action becomes a value you can store, pass,
  queue, log, delay, or replay, rather than a hardwired method call.
- Invoker depends only on the command interface: adding a hundred device types
  changes zero lines in the remote/scheduler class.
- Undo via history stack: the invoker pushes each executed command and pops to
  reverse; each command owns its own reversal logic.
- Two undo strategies: symmetric actions (on/off) undo by invoking the inverse
  operation; value-setting actions (set temperature, delete text) must
  snapshot the prior state inside execute so undo can restore it — a
  memento-lite move embedded in the command.
- Two-stack undo/redo: a text-editor example uses an undo stack plus a redo
  stack, where redo re-executes the popped command and any brand-new action
  clears the redo stack (a new action starts a new timeline).
- Interface design judgment: only bake undo into the base interface if all
  commands are reversible; otherwise split out a reversible-command interface
  or default it to a no-op.
- Receivers stay infrastructure-free: domain objects never depend on the
  command machinery, so they remain reusable and independently testable.

## When to apply / trade-offs

Reach for Command when you need undo/redo, deferred or scheduled execution,
audit logging of operations, or many trigger points sharing one action.
Skip it when actions are trivial, never reversed, and fired from one place —
the pattern adds one class per action, which is real ceremony. The chapter's
comparison table makes the trade explicit: the naive controller is simpler up
front but loses on coupling, extension cost, undo, queuing, and reuse.

## Fidelity check

1. Claim: the invoker never imports concrete device classes. Support: the
   capture stresses that the refactored remote depends solely on the command
   interface and that adding new device types requires no change to it.
2. Claim: stateful commands must capture prior state before executing.
   Support: the capture contrasts the light on/off commands (undo = call the
   opposite method) with the temperature command, which must record the old
   temperature because "set to 22" has no intrinsic inverse; the editor's
   delete command likewise saves removed text during execution.
3. Claim: a new action wipes the redo stack. Support: the editor walkthrough
   notes that performing a delete after undos makes redo unavailable,
   described as standard behavior because a fresh action forks the timeline.
