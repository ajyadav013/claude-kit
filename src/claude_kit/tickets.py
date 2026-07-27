"""Read the local ticket store and render it as a board, a dependency graph, or a commit graph.

The store lives at ``docs/project/tickets/`` (see ``skills/ticketing-and-traceability/SKILL.md``) and
is split by authority: the per-ticket Markdown file is what a human edits, so it owns ``title`` and
``status``; ``index.json`` is the machine index, so it owns ``commits``, ``branch``, ``relations`` and
persisted ``telemetry``. Reading both and merging on that rule means a hand-edited status is never
silently overwritten by a stale index.

Relations follow the model proven by `quazardous/aiball <https://github.com/quazardous/aiball>`_
(MIT, (c) 2026 David Berlioz - re-expressed here, no code copied). The distinction that matters:
``depends_on``/``blocks`` **gate** whether a ticket can be worked, while ``child_of``/``parent_of``
lineage deliberately does not - a sub-ticket is not blocked merely because its parent is still open.
The board header always prints the **open** count beside **actionable**, so a fully-gated backlog
reads as "blocked", never as "nothing to do".

Nothing here mutates the store; every function is read-only and degrades to an empty result rather
than raising, so a missing store renders a friendly line instead of a traceback.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .telemetry import Telemetry, human_duration, human_tokens

#: Store locations, relative to the project root.
TICKETS_REL = "docs/project/tickets"
INDEX_REL = "docs/project/tickets/index.json"
#: Runtime pipeline snapshot, read (never written) for the stage/gate a ticket sits at.
SNAPSHOT_REL = ".claude/state/pipeline-snapshot.json"

#: Lifecycle. ``BLOCKED`` is derived from unmet dependencies, not written by hand.
STATUSES = ("OPEN", "IN PROGRESS", "IN REVIEW", "DONE")
#: A ticket in one of these is finished and stops gating anything downstream.
TERMINAL = frozenset({"DONE"})

#: Edges that gate workability, and their inverses.
GATING_KINDS = ("depends_on",)
#: Structural lineage - rendered as a tree, deliberately non-gating.
LINEAGE_KINDS = ("child_of", "parent_of")
#: Every edge the store understands.
RELATION_KINDS = (
    "depends_on",
    "blocks",
    "child_of",
    "parent_of",
    "relates_to",
    "duplicates",
)

_TITLE_RE = re.compile(r"^#\s+(?P<id>[A-Z][A-Z0-9]*-\d+)\s*[:\-]\s*(?P<title>.+?)\s*$")
_FIELD_RE = re.compile(r"^[-*]\s+\*\*(?P<key>[^:*]+):?\*\*\s*(?P<value>.*?)\s*$")
_LOG_RE = re.compile(r"^[-*]\s+(?P<entry>.+?)\s*$")


@dataclass
class Ticket:
    """One ticket, merged from its Markdown file and the machine index."""

    id: str
    title: str = ""
    status: str = "OPEN"
    spec: str = ""
    design: str = ""
    branch: str = ""
    files: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    relations: dict[str, list[str]] = field(default_factory=dict)
    work_log: list[str] = field(default_factory=list)
    telemetry: Optional[Telemetry] = None

    @property
    def is_open(self) -> bool:
        return self.status.upper() not in TERMINAL

    def related(self, kind: str) -> list[str]:
        return list(self.relations.get(kind, ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "spec": self.spec,
            "design": self.design,
            "branch": self.branch,
            "files": list(self.files),
            "commits": list(self.commits),
            "relations": {k: list(v) for k, v in self.relations.items()},
            "work_log": list(self.work_log),
            "telemetry": self.telemetry.to_dict() if self.telemetry else None,
        }


@dataclass
class Store:
    """Every ticket in a project, plus the derived lenses."""

    prefix: str = ""
    tickets: dict[str, Ticket] = field(default_factory=dict)
    exists: bool = False

    def ordered(self) -> list[Ticket]:
        """Tickets sorted by numeric id, so ``CKIT-9`` precedes ``CKIT-10``."""
        return sorted(self.tickets.values(), key=lambda t: _id_sort_key(t.id))

    def blockers(self, ticket: Ticket) -> list[str]:
        """Ids of unfinished tickets this one depends on. Empty means nothing gates it."""
        out: list[str] = []
        for kind in GATING_KINDS:
            for other_id in ticket.related(kind):
                other = self.tickets.get(other_id)
                if other is None or other.is_open:
                    out.append(other_id)
        return out

    def is_blocked(self, ticket: Ticket) -> bool:
        return ticket.is_open and bool(self.blockers(ticket))

    def is_actionable(self, ticket: Ticket) -> bool:
        """Open and nothing gates it - the work that can actually start now."""
        return ticket.is_open and not self.blockers(ticket)

    def counts(self) -> dict[str, int]:
        """Header figures. ``open`` is always reported so a gated backlog cannot read as empty."""
        values = list(self.tickets.values())
        return {
            "total": len(values),
            "open": sum(1 for t in values if t.is_open),
            "actionable": sum(1 for t in values if self.is_actionable(t)),
            "blocked": sum(1 for t in values if self.is_blocked(t)),
            "in_progress": sum(1 for t in values if t.status.upper() == "IN PROGRESS"),
            "done": sum(1 for t in values if not t.is_open),
        }

    def branch_sharers(self, ticket: Ticket) -> list[str]:
        """Other ticket ids on the same branch - i.e. those its telemetry figures also cover."""
        if not ticket.branch:
            return []
        return [
            t.id
            for t in self.ordered()
            if t.id != ticket.id and t.branch == ticket.branch
        ]

    def display_status(self, ticket: Ticket) -> str:
        """``BLOCKED`` is derived, so it overrides a stored ``OPEN`` in every rendered view."""
        return "BLOCKED" if self.is_blocked(ticket) else ticket.status.upper()


def _id_sort_key(ticket_id: str) -> tuple[str, int]:
    match = re.match(r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<num>\d+)$", ticket_id)
    if match:
        return (match.group("prefix"), int(match.group("num")))
    return (ticket_id, 0)


def parse_ticket_markdown(text: str) -> dict[str, Any]:
    """Pull id, title, the bold field list, and the work log out of a ticket file."""
    data: dict[str, Any] = {"work_log": []}
    section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _TITLE_RE.match(line)
        if heading:
            data["id"] = heading.group("id")
            data["title"] = heading.group("title")
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section == "work log":
            entry = _LOG_RE.match(line)
            if entry:
                data["work_log"].append(entry.group("entry"))
            continue
        field_match = _FIELD_RE.match(line)
        if not field_match:
            continue
        key = field_match.group("key").strip().lower()
        value = field_match.group("value").strip()
        if key == "status":
            data["status"] = value.upper()
        elif key == "spec":
            data["spec"] = _strip_note(value)
        elif key == "design":
            data["design"] = _strip_note(value)
        elif key == "branch":
            data["branch"] = value
        elif key.startswith("files"):
            data["files"] = [p.strip() for p in value.split(",") if p.strip()]
    return data


def _strip_note(value: str) -> str:
    """Drop the trailing ``(functional - what & why)`` style annotation from a field value."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()


def _load_index(project_root: Path) -> tuple[str, dict[str, Any]]:
    """Return ``(prefix, {id: entry})`` from ``index.json``; empty when absent or malformed."""
    path = project_root / INDEX_REL
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", {}
    if not isinstance(raw, dict):
        return "", {}
    prefix = raw.get("prefix") if isinstance(raw.get("prefix"), str) else ""
    entries = raw.get("tickets")
    if not isinstance(entries, dict):
        # Tolerate a flat ``{id: entry}`` document with no envelope.
        entries = {k: v for k, v in raw.items() if isinstance(v, dict)}
    return prefix or "", entries


def _normalise_relations(raw: Any) -> dict[str, list[str]]:
    """Coerce the relations blob to ``{kind: [id]}``, keeping only known kinds."""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return out
    for kind, value in raw.items():
        if kind not in RELATION_KINDS:
            continue
        if isinstance(value, str):
            out[kind] = [value]
        elif isinstance(value, list):
            out[kind] = [v for v in value if isinstance(v, str) and v]
    return out


def load_store(project_root: Path) -> Store:
    """Read every ticket for ``project_root``. A missing store yields ``Store(exists=False)``."""
    tickets_dir = project_root / TICKETS_REL
    prefix, index = _load_index(project_root)
    store = Store(prefix=prefix, exists=tickets_dir.is_dir())

    if store.exists:
        for path in sorted(tickets_dir.glob("*.md")):
            try:
                parsed = parse_ticket_markdown(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            ticket_id = parsed.get("id") or path.stem
            store.tickets[ticket_id] = Ticket(
                id=ticket_id,
                title=parsed.get("title", ""),
                status=parsed.get("status", "OPEN"),
                spec=parsed.get("spec", ""),
                design=parsed.get("design", ""),
                branch=parsed.get("branch", ""),
                files=parsed.get("files", []),
                work_log=parsed.get("work_log", []),
            )

    # The index supplies machine fields, and any ticket that exists only there.
    for ticket_id, entry in index.items():
        if not isinstance(entry, dict):
            continue
        ticket = store.tickets.get(ticket_id)
        if ticket is None:
            ticket = Ticket(
                id=ticket_id, status=str(entry.get("status", "OPEN")).upper()
            )
            store.tickets[ticket_id] = ticket
            store.exists = True
        ticket.title = ticket.title or str(entry.get("title", ""))
        ticket.spec = ticket.spec or str(entry.get("spec", ""))
        ticket.branch = ticket.branch or str(entry.get("branch", ""))
        commits = entry.get("commits")
        if isinstance(commits, list):
            ticket.commits = [c for c in commits if isinstance(c, str)]
        ticket.relations = _normalise_relations(entry.get("relations"))

    if not store.prefix:
        for ticket_id in store.tickets:
            match = re.match(r"^([A-Z][A-Z0-9]*)-\d+$", ticket_id)
            if match:
                store.prefix = match.group(1)
                break
    return store


def attach_telemetry(store: Store, by_branch: dict[str, Telemetry]) -> None:
    """Attach per-branch telemetry to tickets that name a branch.

    Attribution is **branch-scoped**, because ``gitBranch`` is the only ticket-shaped key a transcript
    record carries. Two tickets developed on one branch therefore receive the *same* figures - the cost
    of that branch, not of either ticket alone. :func:`Store.branch_sharers` exposes the overlap so a
    rendered view can say so rather than implying the number belongs to one ticket.
    """
    for ticket in store.tickets.values():
        if ticket.branch and ticket.branch in by_branch:
            ticket.telemetry = by_branch[ticket.branch]


def pipeline_stage(project_root: Path) -> dict[str, Any]:
    """Current stage/gate from the runtime snapshot. Empty dict when there is no active run."""
    try:
        raw = json.loads((project_root / SNAPSHOT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# --------------------------------------------------------------------------------------------------
# Rendering. Every renderer returns lines; the CLI owns printing so ``--json`` can bypass them.
# --------------------------------------------------------------------------------------------------

_EMPTY_HINT = (
    "no tickets yet - the orchestrator opens one per story at Stage TK "
    "(see .claude/skills/ticketing-and-traceability/SKILL.md)"
)


def _header(store: Store, suffix: str = "") -> str:
    counts = store.counts()
    parts = [
        "{} tickets".format(counts["total"]),
        "{} open".format(counts["open"]),
        "{} actionable".format(counts["actionable"]),
    ]
    if counts["blocked"]:
        parts.append("{} blocked".format(counts["blocked"]))
    if counts["in_progress"]:
        parts.append("{} in progress".format(counts["in_progress"]))
    parts.append("{} done".format(counts["done"]))
    label = store.prefix or "tickets"
    line = "{}  {}".format(label, "  ".join(parts))
    return "{}{}".format(line, suffix)


def _telemetry_cells(ticket: Ticket) -> tuple[str, str, str, str]:
    """``(agent, model, tokens, cache)`` as display strings. ``-`` throughout when there is no data."""
    tel = ticket.telemetry
    if tel is None or tel.empty:
        return ("-", "-", "-", "-")
    return (
        _first_of(tel.agents),
        _first_of([_short_model(m) for m in tel.models]),
        human_tokens(tel.total_tokens),
        human_tokens(tel.cache_read),
    )


def _first_of(values: list[str]) -> str:
    """First value, with ``+N`` when there are more - a column must not hide what it dropped."""
    if not values:
        return "-"
    if len(values) == 1:
        return values[0]
    return "{} +{}".format(values[0], len(values) - 1)


def _short_model(model: str) -> str:
    """``claude-opus-4-8`` -> ``opus-4-8``."""
    return model[len("claude-") :] if model.startswith("claude-") else model


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def render_board(store: Store) -> list[str]:
    """The default view: one row per ticket, most-active first."""
    if not store.tickets:
        return [_header(store), "", _EMPTY_HINT] if store.exists else [_EMPTY_HINT]

    rows: list[tuple[str, ...]] = []
    for ticket in _board_order(store):
        agent, model, tokens, cache = _telemetry_cells(ticket)
        elapsed = ticket.telemetry.elapsed_seconds if ticket.telemetry else None
        rows.append(
            (
                ticket.id,
                _truncate(ticket.title, 34),
                store.display_status(ticket),
                _truncate(agent, 18),
                model,
                tokens,
                cache,
                human_duration(elapsed),
                ", ".join(c[:7] for c in ticket.commits) or "-",
            )
        )

    headers = (
        "ID",
        "TITLE",
        "STATUS",
        "AGENT",
        "MODEL",
        "TOKENS",
        "CACHE",
        "TIME",
        "COMMITS",
    )
    lines = [_header(store), ""] + _table(headers, rows)
    if any(store.branch_sharers(t) for t in store.tickets.values() if t.telemetry):
        lines.append("")
        lines.append(
            "note: telemetry is per branch - tickets sharing a branch show that branch's totals"
        )
    return lines


def _board_order(store: Store) -> list[Ticket]:
    """In progress first, then actionable, then blocked, then done - each by id."""

    def rank(ticket: Ticket) -> int:
        status = store.display_status(ticket)
        if status == "IN PROGRESS":
            return 0
        if status == "IN REVIEW":
            return 1
        if status == "BLOCKED":
            return 3
        return 2 if ticket.is_open else 4

    return sorted(store.ordered(), key=lambda t: (rank(t), _id_sort_key(t.id)))


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    """Left-aligned fixed-width text table sized to its content."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in rows:
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return out


def render_graph(store: Store) -> list[str]:
    """The ticket dependency DAG - lineage as a tree, blockers called out beneath each ticket."""
    if not store.tickets:
        return [_header(store), "", _EMPTY_HINT] if store.exists else [_EMPTY_HINT]

    lines = [_header(store), ""]
    children: dict[str, list[str]] = {}
    for ticket in store.ordered():
        for parent in ticket.related("child_of"):
            children.setdefault(parent, []).append(ticket.id)
    for ticket in store.ordered():
        for child in ticket.related("parent_of"):
            children.setdefault(ticket.id, []).append(child)

    has_parent = {c for kids in children.values() for c in kids}
    roots = [t for t in _board_order(store) if t.id not in has_parent]

    for root in roots:
        lines.extend(_graph_node(store, root, children, set(), ""))
        lines.append("")
    orphans = [
        t
        for t in store.ordered()
        if t.id in has_parent and t.id not in _rendered(roots, children)
    ]
    if orphans:
        lines.append("(cycle detected - shown flat)")
        for ticket in orphans:
            lines.append(_graph_line(store, ticket))
    return lines[:-1] if lines and lines[-1] == "" else lines


def _rendered(roots: list[Ticket], children: dict[str, list[str]]) -> set[str]:
    """Ids reachable from ``roots``, so a relation cycle cannot hide a ticket entirely."""
    seen: set[str] = set()
    stack = [r.id for r in roots]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(children.get(current, ()))
    return seen


def _graph_line(store: Store, ticket: Ticket, prefix: str = "") -> str:
    agent, model, tokens, _cache = _telemetry_cells(ticket)
    elapsed = ticket.telemetry.elapsed_seconds if ticket.telemetry else None
    return "{}{:<9} {:<32} {:<12} {:>8}  {:<10} {}".format(
        prefix,
        ticket.id,
        _truncate(ticket.title, 32),
        store.display_status(ticket),
        tokens,
        model,
        human_duration(elapsed),
    ).rstrip()


def _graph_node(
    store: Store,
    ticket: Ticket,
    children: dict[str, list[str]],
    seen: set[str],
    indent: str,
) -> list[str]:
    """One ticket, its blockers, then its sub-tickets. Cycle-safe via ``seen``."""
    if ticket.id in seen:
        return ["{}└─ (cycle) {}".format(indent, ticket.id)]
    seen = seen | {ticket.id}

    blockers = store.blockers(ticket)
    kids = [c for c in children.get(ticket.id, []) if c in store.tickets]
    remaining = len(blockers) + len(kids)

    lines = [_graph_line(store, ticket, indent)]
    for blocker_id in blockers:
        blocker = store.tickets.get(blocker_id)
        state = "missing" if blocker is None else store.display_status(blocker).lower()
        remaining -= 1
        lines.append(
            "{}{} depends_on {}  ({} - gates this)".format(
                indent, "├─" if remaining else "└─", blocker_id, state
            )
        )
    for child_id in kids:
        remaining -= 1
        branch = "├─" if remaining else "└─"
        lines.append("{}{} child".format(indent, branch))
        stem = "│  " if remaining else "   "
        lines.extend(
            _graph_node(store, store.tickets[child_id], children, seen, indent + stem)
        )
    return lines


def git_commits(project_root: Path, limit: int = 40) -> list[tuple[str, str, str]]:
    """``(sha, refs, subject)`` newest-first from git. Empty when git is absent or this isn't a repo.

    The only place this package shells out. Guarded so a missing ``git`` binary degrades the
    ``--graph=git`` view to a friendly message instead of a traceback.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "--max-count={}".format(limit), "--format=%h\x1f%D\x1f%s"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    out: list[tuple[str, str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def render_git_graph(store: Store, project_root: Path, limit: int = 40) -> list[str]:
    """The commit graph, annotated with the ticket each commit references."""
    commits = git_commits(project_root, limit)
    if not commits:
        return [
            _header(store),
            "",
            "no git history available here (not a repository, or git is not installed)",
        ]

    by_id = {t.id.upper(): t for t in store.tickets.values()}
    lines = [_header(store), ""]
    for sha, refs, subject in commits:
        decoration = "  ({})".format(refs) if refs else ""
        lines.append("* {}{}".format(sha, decoration))
        ticket = _ticket_for_commit(subject, sha, by_id, store)
        if ticket is None:
            lines.append("|   {}".format(_truncate(subject, 62)))
            continue
        agent, model, tokens, _cache = _telemetry_cells(ticket)
        elapsed = ticket.telemetry.elapsed_seconds if ticket.telemetry else None
        lines.append(
            "|   [{}] {}  {} tok  {}  {}".format(
                ticket.id,
                store.display_status(ticket),
                tokens,
                model,
                human_duration(elapsed),
            )
        )
    return lines


def _ticket_for_commit(
    subject: str, sha: str, by_id: dict[str, Ticket], store: Store
) -> Optional[Ticket]:
    """Match a commit to its ticket by the id in the message, else by a recorded commit sha."""
    for candidate in re.findall(r"[A-Z][A-Z0-9]*-\d+", subject.upper()):
        ticket = by_id.get(candidate)
        if ticket is not None:
            return ticket
    for ticket in store.tickets.values():
        if any(
            recorded.startswith(sha) or sha.startswith(recorded)
            for recorded in ticket.commits
        ):
            return ticket
    return None


def render_detail(store: Store, ticket_id: str, project_root: Path) -> list[str]:
    """Everything known about one ticket: links, stage, per-agent telemetry, and the work log."""
    ticket = store.tickets.get(ticket_id) or store.tickets.get(ticket_id.upper())
    if ticket is None:
        known = ", ".join(t.id for t in store.ordered()) or "none"
        return ["unknown ticket {!r} (known: {})".format(ticket_id, known)]

    lines = [
        "{}  {}".format(ticket.id, ticket.title).rstrip(),
        "",
        "  Status    {}".format(store.display_status(ticket)),
    ]
    if ticket.branch:
        lines.append("  Branch    {}".format(ticket.branch))
    if ticket.spec:
        lines.append("  Spec      {}".format(ticket.spec))
    if ticket.design:
        lines.append("  Design    {}".format(ticket.design))

    snapshot = pipeline_stage(project_root)
    if snapshot:
        stage = snapshot.get("stage") or snapshot.get("phase")
        gate = snapshot.get("last_gate_passed")
        if stage:
            lines.append("  Stage     {}".format(stage))
        if gate:
            lines.append("  Gate      {}".format(gate))

    blockers = store.blockers(ticket)
    if blockers:
        lines.append("  Blocked   depends_on {}".format(", ".join(blockers)))
    for kind in RELATION_KINDS:
        if kind in GATING_KINDS:
            continue
        related = ticket.related(kind)
        if related:
            lines.append("  {:<9} {}".format(kind, ", ".join(related)))
    if ticket.commits:
        lines.append("  Commits   {}".format(", ".join(ticket.commits)))
    if ticket.files:
        lines.append("  Files     {}".format(", ".join(ticket.files)))

    tel = ticket.telemetry
    lines.append("")
    if tel is None or tel.empty:
        lines.append("  no telemetry recorded for this ticket")
    else:
        sharers = store.branch_sharers(ticket)
        scope = " for branch {}".format(ticket.branch) if ticket.branch else ""
        lines.append("  TELEMETRY{}".format(scope))
        if sharers:
            # Branch-scoped figures cover every ticket on the branch; say so rather than
            # letting the reader attribute the whole cost to this one.
            lines.append("    shared with {}".format(", ".join(sharers)))
        lines.append("    requests   {}".format(tel.requests))
        lines.append(
            "    tokens     {} in / {} out".format(
                human_tokens(tel.input_tokens), human_tokens(tel.output_tokens)
            )
        )
        lines.append(
            "    cache      {} read / {} write".format(
                human_tokens(tel.cache_read), human_tokens(tel.cache_write)
            )
        )
        lines.append(
            "    models     {}".format(
                ", ".join(_short_model(m) for m in tel.models) or "-"
            )
        )
        lines.append("    agents     {}".format(", ".join(tel.agents) or "-"))
        lines.append("    elapsed    {}".format(human_duration(tel.elapsed_seconds)))

    if ticket.work_log:
        lines.append("")
        lines.append("  WORK LOG")
        for entry in ticket.work_log:
            lines.append("    {}".format(entry))
    return lines
