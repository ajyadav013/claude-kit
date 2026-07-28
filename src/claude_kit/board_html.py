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
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Optional

from .telemetry import human_duration, human_tokens
from .tickets import Store, Ticket

#: Where the Stop hook writes the board, relative to the project root. Gitignored via
#: ``.claude/state/``, so a live-updating board produces no commit noise.
BOARD_REL = ".claude/state/ticket-board.html"

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
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --card: #161b22; --ink: #e6edf3; --muted: #9198a1;
    --line: #30363d; --shadow: none;
    --moving: #58a6ff; --review: #bc8cff; --ready: #3fb950; --blocked: #d29922; --done: #8b949e;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: var(--bg); color: var(--ink);
  font: 14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; margin-bottom: 20px; }
h1 { font-size: 20px; margin: 0; letter-spacing: -.01em; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px;
  font-size: 12px; color: var(--muted); background: var(--card);
}
.chip strong { color: var(--ink); font-weight: 600; }
.board { display: flex; gap: 16px; align-items: flex-start; overflow-x: auto; padding-bottom: 8px; }
.col { flex: 1 1 260px; min-width: 260px; }
.col h2 {
  font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  margin: 0 0 10px; display: flex; justify-content: space-between; align-items: center;
}
.count { color: var(--muted); font-weight: 500; }
.card {
  background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--accent);
  border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; box-shadow: var(--shadow);
}
.id { font: 600 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }
.title { margin: 2px 0 8px; font-weight: 500; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 12px; color: var(--muted); }
.meta span { white-space: nowrap; }
.note { margin-top: 8px; font-size: 12px; color: var(--blocked); }
.sha { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.empty { color: var(--muted); font-size: 12px; font-style: italic; padding: 8px 0; }
footer { margin-top: 22px; font-size: 12px; color: var(--muted); }
footer code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
"""


def _column_of(store: Store, ticket: Ticket) -> str:
    status = store.display_status(ticket)
    if status in ("IN PROGRESS", "IN REVIEW", "BLOCKED"):
        return status
    return "ACTIONABLE" if ticket.is_open else "DONE"


def _card(store: Store, ticket: Ticket, accent: str) -> str:
    meta: list[str] = []
    tel = ticket.telemetry
    if tel is not None and not tel.empty:
        if tel.models:
            meta.append(_short_model(tel.models[0]))
        meta.append("{} tok".format(human_tokens(tel.total_tokens)))
        if tel.cache_read:
            meta.append("{} cache".format(human_tokens(tel.cache_read)))
        meta.append(human_duration(tel.elapsed_seconds))
        if tel.agents:
            meta.append(", ".join(tel.agents))
    if ticket.branch:
        meta.append(ticket.branch)

    parts = [
        '<article class="card" style="--accent: var(--{})">'.format(escape(accent)),
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
    parts.append("</article>")
    return "".join(parts)


def _short_model(model: str) -> str:
    return model[len("claude-") :] if model.startswith("claude-") else model


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
) -> str:
    """Return the whole board as one HTML document.

    ``refresh`` is the browser reload interval in seconds; ``0`` omits the meta tag entirely, for a
    one-off snapshot you want to keep rather than watch. ``generated_at`` is injectable so tests can
    pin the timestamp.
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
        body = '<div class="board">{}</div>'.format("".join(columns))
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
  {body}
  <footer>
    Generated {stamp} · {live} · telemetry is per branch, so tickets sharing a branch
    show that branch's totals. Regenerate with <code>claude-kit tickets --html</code>.
  </footer>
</body>
</html>
""".format(
        meta_refresh=meta_refresh,
        prefix=escape(store.prefix or "Project"),
        css=_CSS,
        chips=_chips(store),
        body=body,
        stamp=escape(stamp),
        live=escape(live),
    )
