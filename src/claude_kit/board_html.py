"""Render the ticket board as one self-contained HTML file.

The terminal board answers "what is in flight" while you are in the shell; this answers it in a
browser window you can leave open on a second screen. It is a **file, not a service** — no daemon, no
socket, no framework. A ``<meta http-equiv="refresh">`` tag makes the browser re-read the file on an
interval, and the ``capture-ticket-telemetry`` Stop hook rewrites that file as the session progresses,
so the two together produce live progress with nothing running in the background.

Self-contained is a hard requirement, not a preference: the CSS is inline and there are no script
tags, no fonts, and no images, so opening the board never makes a network request and never leaks a
project's ticket titles to a CDN. Everything interpolated goes through :func:`html.escape` — ticket
titles, work-log lines, and branch names are untrusted text as far as this module is concerned.

The **no-JS rule is load-bearing twice over.** Besides the network property, ``"<script" not in
html`` is the whole XSS assertion in ``tests/test_board_html.py`` — one absolute with no exceptions
to reason about. So the interactive parts are pure CSS: cards are anchors, and each issue view is
revealed by ``:target``. That buys click-through detail without buying a script to audit.

Optional rows are **omitted, never emptied**. A ticket with no design doc renders no design row at
all rather than a label with nothing after it, which is what keeps a sparse board readable — and
what ``test_card_renders_sparse_telemetry_without_empty_fragments`` pins.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Optional

from .models import StateLayout
from .state import detect_state_layout
from .telemetry import human_duration, human_tokens
from .tickets import GATING_KINDS, RELATION_KINDS, Store, Ticket

#: Legacy board location retained as a public compatibility constant.
BOARD_REL = ".claude/state/ticket-board.html"


def board_rel(project_root: str | Path) -> str:
    """Return the board path in the project's one active mutable-state root.

    A ticket-only directory has no install marker from which to infer a runtime.  Keep the
    historical ``.claude`` destination for that ambiguous compatibility case; every native install
    has a neutral manifest, so Codex and dual-runtime projects unambiguously write to ``.ckit``.
    """

    layout = detect_state_layout(
        project_root, fresh_default=StateLayout.legacy_claude()
    )
    return f"{layout.state}/ticket-board.html"


#: Columns, in reading order: what is moving, what is stuck, what could start, what is finished.
#: ``ACTIONABLE`` is derived (open, unblocked, not already moving) rather than a stored status.
_COLUMNS = (
    ("IN PROGRESS", "moving"),
    ("IN REVIEW", "review"),
    ("ACTIONABLE", "ready"),
    ("BLOCKED", "blocked"),
    ("DONE", "done"),
)

_CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #14181f; --muted: #5b6675;
  --line: #d9dee6; --shadow: 0 1px 2px rgba(20,24,31,.08);
  --moving: #1f6feb; --review: #8250df; --ready: #1a7f37; --blocked: #b35900; --done: #6e7781;
  --panel: #ffffff; --sunken: #f0f2f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --card: #161b22; --ink: #e6edf3; --muted: #9198a1;
    --line: #30363d; --shadow: none;
    --moving: #58a6ff; --review: #bc8cff; --ready: #3fb950; --blocked: #d29922; --done: #8b949e;
    --panel: #161b22; --sunken: #0d1117;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: var(--bg); color: var(--ink);
  font: 14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; margin-bottom: 14px; }
h1 { font-size: 20px; margin: 0; letter-spacing: -.01em; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px;
  font-size: 12px; color: var(--muted); background: var(--card);
}
.chip strong { color: var(--ink); font-weight: 600; }

/* Pipeline strip - the "which gate are we on" line, only drawn during an active run. */
.strip {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 12px; margin-bottom: 18px; font-size: 12px;
}
.strip .lead { color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.strip .tally { margin-left: auto; padding-left: 12px; }
.gate { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); }
.gate + .gate::before { content: "\\203a"; color: var(--line); margin-right: 3px; }
.gate.passed { color: var(--ready); }
.gate.here { color: var(--moving); font-weight: 600; }
.gate .dot { font-size: 11px; }
.aborted { color: var(--blocked); font-weight: 600; }

.board { display: flex; gap: 12px; align-items: flex-start; overflow-x: auto; padding-bottom: 8px; }
/* Five columns must fit a 1280px laptop without clipping the last one:
   (1280 - 48 body padding - 4 gaps) / 5 = ~236, so 200 leaves room to spare. Wider screens
   share the surplus via flex-grow; narrower ones scroll, which is what overflow-x is for. */
.col { flex: 1 1 200px; min-width: 200px; }
.col h2 {
  font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  margin: 0 0 10px; display: flex; justify-content: space-between; align-items: center;
  position: sticky; top: 0; background: var(--bg); padding: 6px 0; z-index: 1;
}
.count { color: var(--muted); font-weight: 500; }

/* A card is an anchor: the whole thing is the click target for its issue view. */
a.card {
  display: block; text-decoration: none; color: inherit;
  background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; box-shadow: var(--shadow);
}
a.card:hover { border-color: var(--accent); }
a.card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.id { font: 600 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }
.title { margin: 2px 0 8px; font-weight: 500; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 12px; color: var(--muted); }
.meta span { white-space: nowrap; }
.note { margin-top: 8px; font-size: 12px; color: var(--blocked); }
.sha { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.empty { color: var(--muted); font-size: 12px; font-style: italic; padding: 8px 0; }

/* Who worked it: initials in a ring. Text, never an image - the board ships no binary assets. */
.who { display: inline-flex; gap: 4px; margin-top: 8px; }
.pip {
  width: 22px; height: 22px; border-radius: 999px; background: var(--sunken);
  border: 1px solid var(--line); color: var(--muted);
  font: 600 10px/20px ui-sans-serif, sans-serif; text-align: center; letter-spacing: .02em;
}

/* Issue views: hidden until their anchor is the fragment in the URL. */
.issue {
  display: none; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 18px 20px; margin-top: 22px; box-shadow: var(--shadow);
}
.issue:target { display: block; }
.issue h3 { margin: 0 0 2px; font-size: 16px; }
.issue .key { font: 600 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); }
.issue .close { float: right; font-size: 12px; color: var(--muted); text-decoration: none; }
.issue .close:hover { color: var(--ink); }
.rows { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin-top: 14px; }
.rows dt { color: var(--muted); font-size: 12px; }
.rows dd { margin: 0; font-size: 13px; overflow-wrap: anywhere; }
.issue h4 {
  margin: 18px 0 6px; font-size: 11px; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted);
}
.log { margin: 0; padding-left: 18px; font-size: 13px; }
.log li { margin-bottom: 3px; }
.shared { color: var(--blocked); font-size: 12px; }

footer { margin-top: 22px; font-size: 12px; color: var(--muted); }
footer code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
"""


def _column_of(store: Store, ticket: Ticket) -> str:
    status = store.display_status(ticket)
    if status in ("IN PROGRESS", "IN REVIEW", "BLOCKED"):
        return status
    return "ACTIONABLE" if ticket.is_open else "DONE"


def _initials(agent: str) -> str:
    """Two letters for an agent name: ``developer`` -> DE, ``sdlc-code-reviewer`` -> SR."""
    parts = [p for p in agent.replace("_", "-").replace(" ", "-").split("-") if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _avatars(agents: list[str]) -> str:
    """Initial pips for the agents seen on this ticket's branch; empty string for none."""
    if not agents:
        return ""
    pips = "".join(
        '<span class="pip" title="{}">{}</span>'.format(escape(a), escape(_initials(a)))
        for a in agents
    )
    return '<div class="who">{}</div>'.format(pips)


def _short_model(model: str) -> str:
    return model[len("claude-") :] if model.startswith("claude-") else model


def _status_strip(stage: Optional[dict[str, Any]], gates: Optional[list[str]]) -> str:
    """The gate chain with the current position marked; empty when no run is active.

    A run that was aborted says so instead of pretending to sit on a gate — the snapshot keeps
    ``stage == "aborted"`` and no further gate may be recorded against it.
    """
    if not stage:
        return ""
    current = stage.get("stage") or stage.get("phase") or ""
    if current == "aborted":
        return (
            '<div class="strip"><span class="lead">pipeline</span>'
            '<span class="aborted">run aborted</span></div>'
        )
    passed = stage.get("last_gate_passed") or ""
    ordered = list(gates or [])
    if not ordered:
        # No profile snapshot to order against: say where we are without inventing a chain.
        bits = []
        if current:
            bits.append(
                '<span class="gate here">{}</span>'.format(escape(str(current)))
            )
        if passed:
            bits.append(
                '<span class="gate passed">last passed {}</span>'.format(
                    escape(str(passed))
                )
            )
        if not bits:
            return ""
        return '<div class="strip"><span class="lead">pipeline</span>{}</div>'.format(
            "".join(bits)
        )

    cutoff = ordered.index(passed) if passed in ordered else -1
    cells = []
    for i, gate in enumerate(ordered):
        if i <= cutoff:
            cls, dot = "gate passed", "✓"
        elif gate == current:
            cls, dot = "gate here", "●"
        else:
            cls, dot = "gate", "○"
        cells.append(
            '<span class="{}"><span class="dot">{}</span>{}</span>'.format(
                cls, dot, escape(gate)
            )
        )
    done = cutoff + 1
    return (
        '<div class="strip"><span class="lead">pipeline</span>{}'
        '<span class="lead tally">gate {}/{}</span></div>'
    ).format("".join(cells), done, len(ordered))


def _card(store: Store, ticket: Ticket, accent: str) -> str:
    meta: list[str] = []
    agents: list[str] = []
    tel = ticket.telemetry
    if tel is not None and not tel.empty:
        if tel.models:
            meta.append(_short_model(tel.models[0]))
        meta.append("{} tok".format(human_tokens(tel.total_tokens)))
        if tel.cache_read:
            meta.append("{} cache".format(human_tokens(tel.cache_read)))
        meta.append(human_duration(tel.elapsed_seconds))
        agents = list(tel.agents)
    if ticket.branch:
        meta.append(ticket.branch)

    parts = [
        '<a class="card" href="#{}" style="--accent: var(--{})">'.format(
            escape(ticket.id), escape(accent)
        ),
        '<div class="id">{}</div>'.format(escape(ticket.id)),
        '<div class="title">{}</div>'.format(escape(ticket.title or "(untitled)")),
    ]
    if meta:
        parts.append(
            '<div class="meta">{}</div>'.format(
                "".join("<span>{}</span>".format(escape(m)) for m in meta)
            )
        )
    blockers = store.blockers(ticket)
    if blockers:
        parts.append(
            '<div class="note">blocked by {}</div>'.format(escape(", ".join(blockers)))
        )
    if ticket.commits:
        parts.append(
            '<div class="meta"><span class="sha">{}</span></div>'.format(
                escape(", ".join(c[:7] for c in ticket.commits))
            )
        )
    parts.append(_avatars(agents))
    parts.append("</a>")
    return "".join(parts)


def _row(label: str, value: str) -> str:
    """One definition row, or nothing at all. Never a label with an empty value beside it."""
    if not value:
        return ""
    return "<dt>{}</dt><dd>{}</dd>".format(escape(label), escape(value))


def _issue(store: Store, ticket: Ticket, stage: Optional[dict[str, Any]]) -> str:
    """The full detail view for one ticket — the browser twin of ``tickets.render_detail``."""
    rows = [
        _row("Status", store.display_status(ticket)),
        _row("Branch", ticket.branch),
        _row("Spec", ticket.spec),
        _row("Design", ticket.design),
    ]
    if stage:
        rows.append(_row("Stage", str(stage.get("stage") or stage.get("phase") or "")))
        rows.append(_row("Gate", str(stage.get("last_gate_passed") or "")))
    rows.append(_row("Blocked by", ", ".join(store.blockers(ticket))))
    for kind in RELATION_KINDS:
        if kind in GATING_KINDS:
            continue
        rows.append(_row(kind.replace("_", " "), ", ".join(ticket.related(kind))))
    rows.append(_row("Commits", ", ".join(c[:7] for c in ticket.commits)))
    rows.append(_row("Files", ", ".join(ticket.files)))

    parts = [
        '<section class="issue" id="{}">'.format(escape(ticket.id)),
        '<a class="close" href="#">× close</a>',
        '<div class="key">{}</div>'.format(escape(ticket.id)),
        "<h3>{}</h3>".format(escape(ticket.title or "(untitled)")),
        '<dl class="rows">{}</dl>'.format("".join(r for r in rows if r)),
    ]

    tel = ticket.telemetry
    if tel is not None and not tel.empty:
        sharers = store.branch_sharers(ticket)
        tel_rows = [
            _row("Requests", str(tel.requests) if tel.requests else ""),
            _row(
                "Tokens",
                "{} in / {} out".format(
                    human_tokens(tel.input_tokens), human_tokens(tel.output_tokens)
                ),
            ),
        ]
        if tel.cache_read or tel.cache_write:
            tel_rows.append(
                _row(
                    "Cache",
                    "{} read / {} write".format(
                        human_tokens(tel.cache_read), human_tokens(tel.cache_write)
                    ),
                )
            )
        tel_rows.append(_row("Elapsed", human_duration(tel.elapsed_seconds)))
        tel_rows.append(_row("Models", ", ".join(_short_model(m) for m in tel.models)))
        tel_rows.append(_row("Agents", ", ".join(tel.agents)))
        parts.append("<h4>Telemetry</h4>")
        if sharers:
            # Figures are per branch, so they cover every ticket on it. Say so, rather than
            # letting the reader attribute the whole cost to this one.
            parts.append(
                '<div class="shared">branch shared with {}</div>'.format(
                    escape(", ".join(sharers))
                )
            )
        parts.append(
            '<dl class="rows">{}</dl>'.format("".join(r for r in tel_rows if r))
        )

    if ticket.work_log:
        parts.append("<h4>Work log</h4>")
        parts.append(
            '<ul class="log">{}</ul>'.format(
                "".join("<li>{}</li>".format(escape(line)) for line in ticket.work_log)
            )
        )
    parts.append("</section>")
    return "".join(parts)


def _chips(store: Store) -> str:
    counts = store.counts()
    # `open` is always shown beside `actionable`, so a fully-gated backlog cannot read as empty.
    shown = [
        ("open", counts["open"]),
        ("actionable", counts["actionable"]),
        ("blocked", counts["blocked"]),
        ("in progress", counts["in_progress"]),
        ("done", counts["done"]),
    ]
    return "".join(
        '<span class="chip"><strong>{}</strong> {}</span>'.format(value, escape(label))
        for label, value in shown
        if value or label in ("open", "actionable")
    )


def render_html(
    store: Store,
    *,
    refresh: int = 10,
    generated_at: Optional[datetime] = None,
    stage: Optional[dict[str, Any]] = None,
    gates: Optional[list[str]] = None,
) -> str:
    """Return the whole board as one HTML document.

    ``refresh`` is the browser reload interval in seconds; ``0`` omits the meta tag entirely, for a
    one-off snapshot you want to keep rather than watch. ``generated_at`` is injectable so tests can
    pin the timestamp. ``stage`` is the pipeline snapshot (``tickets.pipeline_stage``) and ``gates``
    the profile's execution-ordered gate list — both injected rather than read here, so this stays a
    pure renderer, and both optional because a repo with no active run is a normal state.
    """
    grouped: "dict[str, list[Ticket]]" = {name: [] for name, _ in _COLUMNS}
    for ticket in store.ordered():
        grouped[_column_of(store, ticket)].append(ticket)

    columns = []
    for name, accent in _COLUMNS:
        items = grouped[name]
        cards = (
            "".join(_card(store, t, accent) for t in items)
            or '<div class="empty">nothing here</div>'
        )
        columns.append(
            '<section class="col"><h2 style="color: var(--{})">{}'
            '<span class="count">{}</span></h2>{}</section>'.format(
                escape(accent), escape(name), len(items), cards
            )
        )

    stamp = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    meta_refresh = (
        '\n  <meta http-equiv="refresh" content="{}">'.format(int(refresh))
        if refresh and refresh > 0
        else ""
    )
    if store.tickets:
        body = '<div class="board">{}</div>{}'.format(
            "".join(columns),
            "".join(_issue(store, t, stage) for t in store.ordered()),
        )
    else:
        body = (
            '<div class="empty">No tickets yet — the orchestrator opens one per story '
            "at Stage TK.</div>"
        )
    live = (
        "auto-refreshing every {}s".format(int(refresh))
        if refresh and refresh > 0
        else "static snapshot"
    )

    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">{meta_refresh}
  <title>{prefix} tickets</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>{prefix} tickets</h1>
    <div class="chips">{chips}</div>
  </header>
  {strip}
  {body}
  <footer>
    Generated {stamp} · {live} · click a ticket to open it, × to close · telemetry is per branch,
    so tickets sharing a branch show that branch's totals.
    Regenerate with <code>claude-kit tickets --html</code>.
  </footer>
</body>
</html>
""".format(
        meta_refresh=meta_refresh,
        prefix=escape(store.prefix or "Project"),
        css=_CSS,
        chips=_chips(store),
        strip=_status_strip(stage, gates),
        body=body,
        stamp=escape(stamp),
        live=escape(live),
    )
