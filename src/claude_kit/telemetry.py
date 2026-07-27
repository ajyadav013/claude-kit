"""Read-only telemetry derived from Claude Code session transcripts.

The ticket store (``docs/project/tickets/``) records *what* changed and *why*; it cannot say what the
work cost. Claude Code writes one JSONL transcript per session under ``~/.claude/projects/<slug>/``,
and each record carries the metadata this module aggregates: token usage, model id, timestamp, the
agent name, and — critically — the ``gitBranch`` the turn ran on, which is how telemetry is attributed
back to a ticket without any agent self-reporting its own usage.

**Metadata only.** Nothing here reads or stores message content, tool input, or file contents — only
usage counters, model ids, timestamps, agent names, and the branch. Same posture as the learning-capture
filter documented in ``SECURITY.md``.

Two correctness rules this module exists to enforce:

1. **Deduplicate by ``requestId``.** Streaming writes the *same* usage block once per update, so a naive
   sum over-counts badly (measured 3.3x on a real session: 622 usage records collapse to 219 requests).
2. **Cache is not a footnote.** Cache reads routinely dwarf fresh input by three orders of magnitude, so
   they are carried as their own counters rather than folded into ``input_tokens``.

Every entry point degrades to an empty result rather than raising: a missing transcript directory, an
unreadable file, or a malformed line is a reason to report "no telemetry", never to fail a render.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

#: Where Claude Code keeps per-project session transcripts.
PROJECTS_ROOT = Path.home() / ".claude" / "projects"

#: Placeholder the transcript uses for non-model turns (hook output, local errors). Not a real model.
SYNTHETIC_MODEL = "<synthetic>"

#: Cap on how many project directories the ``cwd`` fallback scan will probe, and how many lines it
#: reads from each candidate before giving up. Bounds a pathological ``~/.claude/projects``.
_MAX_SCAN_DIRS = 200
_MAX_SCAN_LINES = 50


def slugify_project(project_root: Path) -> str:
    """Return the ``~/.claude/projects`` directory name Claude Code uses for ``project_root``.

    Every non-alphanumeric character becomes ``-``; the leading ``/`` therefore yields a leading ``-``.
    This is a *fast path only* — :func:`transcript_dir` verifies the guess against the ``cwd`` recorded
    inside the transcript, because the encoding of dots and underscores cannot be confirmed from any
    local path and a wrong guess would silently find zero transcripts.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(project_root))


def _read_cwd(path: Path) -> Optional[str]:
    """Return the ``cwd`` a transcript reports, reading at most a few lines. ``None`` if absent."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= _MAX_SCAN_LINES:
                    break
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def _dir_matches(candidate: Path, project_root: Path) -> bool:
    """True when ``candidate`` holds transcripts whose recorded ``cwd`` is ``project_root``."""
    for transcript in _newest_first(candidate):
        cwd = _read_cwd(transcript)
        if cwd is not None:
            return Path(cwd) == project_root
    return False


def _newest_first(directory: Path) -> list[Path]:
    """Transcripts in ``directory``, newest first. Empty when the directory is unusable."""
    try:
        files = [p for p in directory.glob("*.jsonl") if p.is_file()]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def transcript_dir(
    project_root: Path, projects_root: Optional[Path] = None
) -> Optional[Path]:
    """Locate the transcript directory for ``project_root``, or ``None`` if there isn't one.

    Tries the derived slug first, then confirms it against the ``cwd`` the transcript records. Falls
    back to scanning the sibling directories when the guess is absent or points somewhere else, so a
    project whose path encoding differs from the guess still resolves.
    """
    root = (projects_root or PROJECTS_ROOT).expanduser()
    project_root = project_root.expanduser().resolve()
    if not root.is_dir():
        return None

    guess = root / slugify_project(project_root)
    if guess.is_dir() and _dir_matches(guess, project_root):
        return guess

    try:
        candidates = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates[:_MAX_SCAN_DIRS]:
        if candidate != guess and _dir_matches(candidate, project_root):
            return candidate
    return None


def parse_timestamp(raw: Any) -> Optional[datetime]:
    """Parse a transcript ISO-8601 timestamp, tolerating the ``Z`` suffix.

    ``datetime.fromisoformat`` only accepts ``Z`` from Python 3.11, and this package supports 3.9 — so
    the suffix is normalised explicitly rather than relying on the running interpreter.
    """
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Telemetry:
    """Aggregated, deduplicated usage for a set of transcript records."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    models: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    @property
    def total_tokens(self) -> int:
        """Fresh tokens billed as input plus output. Excludes cache, which is counted separately."""
        return self.input_tokens + self.output_tokens

    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Wall-clock span between the first and last record — not active compute time."""
        if self.first_seen is None or self.last_seen is None:
            return None
        return max(0.0, (self.last_seen - self.first_seen).total_seconds())

    @property
    def empty(self) -> bool:
        return self.requests == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "models": list(self.models),
            "agents": list(self.agents),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "elapsed_seconds": self.elapsed_seconds,
        }


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a transcript, skipping anything unreadable."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _usage_key(record: dict[str, Any]) -> Optional[str]:
    """Stable identity for one billed request, used to collapse repeated streaming writes.

    Only ``requestId`` counts. A usage block without one is not a billed API request — in practice
    those are the ``<synthetic>`` records Claude Code writes for hook output and local errors, which
    carry zero tokens. Falling back to ``uuid`` would count each of them as its own request and
    inflate the request total without moving any token figure.
    """
    value = record.get("requestId")
    if isinstance(value, str) and value:
        return value
    return None


def scan(paths: Iterable[Path], branch: Optional[str] = None) -> "dict[str, Telemetry]":
    """Aggregate ``paths`` into ``{gitBranch: Telemetry}``, deduplicating by request identity.

    ``branch`` restricts the scan to a single branch; omit it to get every branch. Records with no
    ``gitBranch`` are grouped under ``""``. A request seen in more than one file is counted once.
    """
    groups: dict[str, Telemetry] = {}
    seen: set[str] = set()

    for path in paths:
        for record in _iter_records(path):
            usage = record.get("message", {}).get("usage")
            if not isinstance(usage, dict):
                continue

            record_branch = record.get("gitBranch") or ""
            if branch is not None and record_branch != branch:
                continue

            key = _usage_key(record)
            if key is None or key in seen:
                continue
            seen.add(key)

            entry = groups.setdefault(record_branch, Telemetry())
            entry.requests += 1
            entry.input_tokens += _as_int(usage.get("input_tokens"))
            entry.output_tokens += _as_int(usage.get("output_tokens"))
            entry.cache_read += _as_int(usage.get("cache_read_input_tokens"))
            entry.cache_write += _as_int(usage.get("cache_creation_input_tokens"))

            model = record.get("message", {}).get("model")
            if (
                isinstance(model, str)
                and model
                and model != SYNTHETIC_MODEL
                and model not in entry.models
            ):
                entry.models.append(model)

            agent = record.get("agentName")
            if isinstance(agent, str) and agent and agent not in entry.agents:
                entry.agents.append(agent)

            stamp = parse_timestamp(record.get("timestamp"))
            if stamp is not None:
                if entry.first_seen is None or stamp < entry.first_seen:
                    entry.first_seen = stamp
                if entry.last_seen is None or stamp > entry.last_seen:
                    entry.last_seen = stamp

    return groups


def _as_int(value: Any) -> int:
    """Coerce a usage counter to int; anything non-numeric contributes zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def collect(
    project_root: Path, projects_root: Optional[Path] = None
) -> "dict[str, Telemetry]":
    """Telemetry for ``project_root`` keyed by branch. Empty dict when no transcripts are found."""
    directory = transcript_dir(project_root, projects_root)
    if directory is None:
        return {}
    return scan(_newest_first(directory))


def human_tokens(count: Optional[int]) -> str:
    """Compact token count: ``281.0k``, ``46.6M``. ``-`` when unknown."""
    if count is None:
        return "-"
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        return "{:.1f}k".format(count / 1_000)
    return "{:.1f}M".format(count / 1_000_000)


def human_duration(seconds: Optional[float]) -> str:
    """Compact duration: ``48m``, ``1h12m``, ``2d3h``. ``-`` when unknown."""
    if seconds is None:
        return "-"
    total = int(seconds)
    if total < 60:
        return "{}s".format(total)
    minutes, _ = divmod(total, 60)
    if minutes < 60:
        return "{}m".format(minutes)
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return "{}h{:02d}m".format(hours, minutes)
    days, hours = divmod(hours, 24)
    return "{}d{}h".format(days, hours)
