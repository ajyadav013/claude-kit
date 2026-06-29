"""Structured report records for ``--json`` output.

Check-style commands return ``(ok, list[str])`` where each line carries a fixed 6-char status token
(``"OK    "``, ``"FAIL  "``, ``"WARN  "``, ``"INFO  "``). :meth:`Report.from_lines` parses those
back into structured records so the CLI can emit machine-readable JSON **without** changing any
producer or the byte-for-byte human output — the text path still prints the original lines verbatim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

#: Fixed 6-char prefixes the producers emit, mapped to a canonical level. Order matters only for
#: readability; prefixes are mutually exclusive.
LEVEL_PREFIXES = {
    "FAIL  ": "fail",
    "WARN  ": "warn",
    "INFO  ": "info",
    "OK    ": "ok",
}


@dataclass
class Message:
    """One report line: a parsed status ``level`` plus the remaining ``text``."""

    level: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "text": self.text}


@dataclass
class Report:
    """A command's overall ``ok`` flag plus its parsed messages."""

    ok: bool
    messages: list[Message] = field(default_factory=list)

    @classmethod
    def from_lines(cls, ok: bool, lines: list[str]) -> Report:
        """Parse ``(ok, lines)`` from a producer into a structured report."""
        msgs: list[Message] = []
        for line in lines:
            for prefix, level in LEVEL_PREFIXES.items():
                if line.startswith(prefix):
                    msgs.append(Message(level, line[len(prefix) :]))
                    break
            else:
                msgs.append(Message("plain", line))
        return cls(ok=ok, messages=msgs)

    def to_dict(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "ok": self.ok,
            "messages": [m.to_dict() for m in self.messages],
        }
        if extra:
            doc.update(extra)
        return doc

    def to_json(self, *, extra: dict[str, Any] | None = None) -> str:
        return json.dumps(self.to_dict(extra=extra), indent=2)
