"""Exporter — project a resolved claude-kit plan into non-Claude-Code agent formats.

claude-kit installs a Claude Code **configuration** under ``.claude/`` and runs a multi-agent, gated
``/sdlc`` pipeline. A teammate working in **Cursor** (or VS Code / GitHub Copilot) uses that editor's
*own* single agent, which can't consume ``.claude/`` or run the enforced pipeline. This module
re-targets the **same** :class:`~claude_kit.models.ResolvedPlan` (from
:func:`claude_kit.catalog.resolve`) to the formats those agents read natively:

* ``cursor`` — ``.cursor/rules/*.mdc`` (one per rule, with derived frontmatter; a synthesized
  ``000-project.mdc`` charter that is always applied) + ``.cursor/mcp.json``.
* ``agents`` — a root ``AGENTS.md`` (project charter + single-agent SDLC workflow + rule index +
  an honest "what doesn't port" note).
* ``copilot`` — ``.github/copilot-instructions.md`` (the same synthesized document as ``agents``).

It is a **projection of the existing plan** — it adds no stack knowledge and touches neither
``catalog.resolve()`` nor the catalog data (golden rules #1 and #6). Fidelity is asymmetric and stated
honestly: rules, the charter, and MCP port cleanly; the *enforced* gates, independent reviewer
subagents, and automated defect loop are Claude-Code-only and become single-agent **guidance** here.

It writes **no application code and no Docker** — configuration only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from claude_kit import scaffold
from claude_kit.models import ResolvedPlan
from claude_kit.render import render_text

#: The export targets this module understands (validated by the CLI before calling in).
VALID_TARGETS: tuple[str, ...] = ("cursor", "agents", "copilot")

#: Language id → auto-attach glob for a Cursor overlay rule (keyed on *language values* from the
#: render context, never framework names — so no per-stack branching, matching golden rule #6).
_LANG_GLOBS: dict[str, str] = {
    "typescript": "**/*.ts,**/*.tsx",
    "javascript": "**/*.js,**/*.jsx",
    "node": "**/*.ts,**/*.js",
    "python": "**/*.py",
    "go": "**/*.go",
    "rust": "**/*.rs",
    "java": "**/*.java",
}

#: Database id → auto-attach glob for a Cursor database-overlay rule (best-effort; omitted when
#: there is no reliable file signal, e.g. document stores — the rule then loads by description).
_DB_GLOBS: dict[str, str] = {
    "postgres": "**/*.sql",
    "mysql": "**/*.sql",
}

#: Max length of a derived rule description (Cursor picks rules by matching this short summary).
_DESC_CAP = 200

#: Honest fidelity note appended to every export — what claude-kit's Claude Code home gives you that a
#: single-agent editor cannot. Stack-agnostic; the same text rides Cursor, AGENTS.md, and Copilot.
_FIDELITY_NOTE = """\
## What ports from Claude Code — and what doesn't

claude-kit's home is **Claude Code**, where this configuration runs as a multi-agent SDLC pipeline with
**enforced** quality gates: independent reviewer subagents, a parallel security scan, and a defect loop
that *blocks* a change from advancing on an unproven verdict. Those gates and subagents are
Claude-Code-only.

**What this export gives you here**

- The full **engineering rule set**, plus the **design-system / stack overlays** for your stack.
- The **project charter** above (stack, commands, independent lanes).
- The **SDLC workflow** as a single-agent self-check checklist.
- Your configured **MCP servers** (Cursor target only).

**What it does not reproduce:** the enforced gates, the independent reviewer subagents, and the
automated defect loop. Apply the workflow as **self-discipline** — you are one agent playing every
role. Where a rule is cited as `.claude/rules/<name>.md`, the same content is exported here as
`.cursor/rules/<name>.mdc` (Cursor) or summarized in the rule index below (AGENTS.md / Copilot).
"""


# --- text helpers ----------------------------------------------------------------------------------


def _humanize(name: str) -> str:
    """Turn a rule filename into a readable title (``react-patterns.md`` -> ``React patterns``)."""
    stem = Path(name).stem.replace("-", " ").replace("_", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else name


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a leading YAML frontmatter block off a rule's markdown (``({}, text)`` when absent).

    Overlay rules may open with Claude Code ``paths:`` frontmatter (scoped rule loading). The block
    is parsed so targets can project it, and the returned body starts at the real markdown so no
    export ever emits a double frontmatter. A malformed block is treated as body text, not an error.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[end + 5 :].lstrip("\n")


def _rule_title(text: str, name: str) -> str:
    """Return the rule's H1 heading, or a humanized filename if it has none."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return _humanize(name)


def _rule_lead(text: str) -> str:
    """Return the first real prose sentence after the H1 (skipping blank/heading/quote lines)."""
    seen_h1 = False
    for line in text.splitlines():
        s = line.strip()
        if not seen_h1:
            if s.startswith("# "):
                seen_h1 = True
            continue
        if not s or s.startswith(("#", ">", "-", "*", "|", "`")):
            continue
        # First sentence only, de-emphasized markdown stripped of surrounding asterisks.
        sentence = s.split(". ")[0].rstrip(".").replace("**", "")
        return sentence
    return ""


def _cap(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` characters, appending an ellipsis when it was cut."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _rule_description(text: str, name: str) -> str:
    """Derive a short, agent-facing description: the title plus its lead sentence (capped)."""
    title = _rule_title(text, name)
    lead = _rule_lead(text)
    return _cap(f"{title} — {lead}" if lead else title, _DESC_CAP)


# --- Cursor .mdc derivation ------------------------------------------------------------------------


def _overlay_lane(name: str, stack_dirs: dict[str, str], payload: Path) -> str | None:
    """Return which stack lane (frontend/backend/database) an overlay rule file belongs to."""
    stacks = payload / "templates" / "stacks"
    for kind, stack_dir in stack_dirs.items():
        if stack_dir and (stacks / stack_dir / "rules" / name).is_file():
            return kind
    return None


def _overlay_glob(name: str, plan: ResolvedPlan, payload: Path) -> str | None:
    """Pick the auto-attach glob for an overlay rule from its lane's language/db (or None)."""
    lane = _overlay_lane(name, plan.stack_dirs, payload)
    if lane == "frontend":
        return _LANG_GLOBS.get(plan.context.get("frontend_language", ""))
    if lane == "backend":
        return _LANG_GLOBS.get(plan.context.get("backend_language", ""))
    if lane == "database":
        return _DB_GLOBS.get(plan.context.get("database", ""))
    return None


def _rule_to_mdc(name: str, text: str, plan: ResolvedPlan, payload: Path) -> str:
    """Render a rule's markdown as a Cursor ``.mdc`` file with derived YAML frontmatter.

    Core rules are agent-requested (``description`` only, ``alwaysApply: false``) — mirroring Claude
    Code's on-demand rule loading. Overlay rules additionally get ``globs`` so Cursor auto-attaches
    them when editing matching files: the rule's own ``paths:`` frontmatter (Claude Code's scoped
    loading) projects verbatim when present, falling back to the lane's language/db table. The
    source frontmatter is stripped from the body so the ``.mdc`` carries exactly one block. Values
    are JSON-quoted so the frontmatter is always valid YAML (an unquoted glob such as
    ``**/*.{ts,tsx}`` would be misread as a YAML flow mapping).
    """
    meta, body = _split_frontmatter(text)
    lines = [
        f"description: {json.dumps(_rule_description(body, name), ensure_ascii=False)}"
    ]
    if name in set(plan.overlay_rules):
        paths = meta.get("paths")
        if isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths):
            glob: str | None = ",".join(paths)
        else:
            glob = _overlay_glob(name, plan, payload)
        if glob:
            lines.append(f"globs: {json.dumps(glob, ensure_ascii=False)}")
    lines.append("alwaysApply: false")
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.strip() + "\n"


def _project_mdc(body: str) -> str:
    """Wrap the shared charter body as the always-applied ``000-project.mdc`` rule."""
    frontmatter = (
        "---\n"
        'description: "claude-kit project charter and single-agent SDLC workflow"\n'
        "alwaysApply: true\n"
        "---\n\n"
    )
    return frontmatter + body


# --- shared content synthesizer --------------------------------------------------------------------


def _charter_body(payload: Path, plan: ResolvedPlan) -> str:
    """Build the shared "project charter" body used by every target.

    Composed of the rendered stack charter (existing ``CLAUDE.stack.md.tmpl``), the single-agent SDLC
    workflow guide, and the honest fidelity note. Stack-agnostic and command-concrete: it renders with
    the plan's own ``context`` (labels + real per-stack commands).
    """
    parts: list[str] = []
    stack_tmpl = payload / "templates" / "CLAUDE.stack.md.tmpl"
    if stack_tmpl.is_file():
        parts.append(
            render_text(stack_tmpl.read_text(encoding="utf-8"), plan.context).rstrip()
        )
    guide_tmpl = payload / "templates" / "export" / "sdlc-workflow-guide.md.tmpl"
    if guide_tmpl.is_file():
        parts.append(
            render_text(guide_tmpl.read_text(encoding="utf-8"), plan.context).rstrip()
        )
    parts.append(_FIDELITY_NOTE.rstrip())
    return "\n\n".join(parts) + "\n"


def _iter_rules(payload: Path, plan: ResolvedPlan) -> list[tuple[str, Path]]:
    """Return ``(name, path)`` for every core rule then every resolved overlay rule (on disk)."""
    out: list[tuple[str, Path]] = []
    for md in sorted((payload / "rules").glob("*.md")):
        out.append((md.name, md))
    for name in plan.overlay_rules:
        found = scaffold._find_overlay(payload, plan.stack_dirs, "rules", name)
        if found:
            out.append((name, found))
    return out


def _rule_index(payload: Path, plan: ResolvedPlan) -> str:
    """Build the markdown rule index (one line per rule) for the AGENTS.md / Copilot document."""
    lines = [
        "## Engineering rules (index)",
        "",
        "claude-kit installs these conventions. In Claude Code they load on demand and are enforced "
        "through the pipeline; apply them here as well. The full text of each rule is available by "
        "exporting the Cursor target (`.cursor/rules/*.mdc`), or under `.claude/rules/` if this "
        "project also uses Claude Code.",
        "",
        "**Core rules**",
        "",
    ]
    core = sorted((payload / "rules").glob("*.md"))
    for md in core:
        text = md.read_text(encoding="utf-8")
        lead = _rule_lead(text) or _rule_title(text, md.name)
        lines.append(f"- **{md.stem}** — {_cap(lead, _DESC_CAP)}")
    overlays = [
        (name, found)
        for name in plan.overlay_rules
        if (found := scaffold._find_overlay(payload, plan.stack_dirs, "rules", name))
    ]
    if overlays:
        lines += ["", "**Stack overlays**", ""]
        for name, found in overlays:
            _, body = _split_frontmatter(found.read_text(encoding="utf-8"))
            lead = _rule_lead(body) or _rule_title(body, name)
            lines.append(f"- **{Path(name).stem}** — {_cap(lead, _DESC_CAP)}")
    return "\n".join(lines) + "\n"


def _agents_document(payload: Path, plan: ResolvedPlan) -> str:
    """Assemble the full AGENTS.md / Copilot document (charter + workflow + rule index)."""
    header = (
        "# Project agent guide\n\n"
        "> Exported by **claude-kit**. This file gives your editor's agent claude-kit's engineering "
        "standards and SDLC discipline. It is a projection of a Claude Code configuration — see the "
        "fidelity note at the end for what carries over and what doesn't.\n"
    )
    return (
        header + "\n" + _charter_body(payload, plan) + "\n" + _rule_index(payload, plan)
    )


# --- MCP transform ---------------------------------------------------------------------------------


def _to_cursor_mcp(mcp_servers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Project the resolved MCP configs into Cursor's ``.cursor/mcp.json`` shape.

    Cursor infers stdio (``command``/``args``/``env``) vs remote (``url``/``headers``) from the keys
    present, so the claude-kit ``type`` discriminator is dropped. Every other key is passed through
    verbatim.
    """
    out: dict[str, dict[str, Any]] = {}
    for sid, cfg in mcp_servers.items():
        projected = {k: v for k, v in cfg.items() if k != "type"}
        out[sid] = projected
    return {"mcpServers": out}


# --- writing ---------------------------------------------------------------------------------------


def _emit(
    path: Path,
    text: str,
    *,
    root: Path,
    force: bool,
    dry_run: bool,
    written: list[str],
) -> None:
    """Write ``text`` to ``path``, sidecar'ing an existing file unless ``force`` (no-op on dry run).

    Exported files are regenerable projections, so ``--force`` refreshes them in place. Without
    ``--force`` an existing file is preserved and the new content lands beside it as a ``.claude-kit``
    sidecar (the same non-destructive convention the installer uses). ``dry_run`` records the intended
    path and writes nothing.
    """
    rel = path.relative_to(root).as_posix()
    if dry_run:
        written.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        sidecar = path.with_name(path.name + ".claude-kit")
        sidecar.write_text(text, encoding="utf-8")
        written.append(sidecar.relative_to(root).as_posix())
    else:
        path.write_text(text, encoding="utf-8")
        written.append(rel)


def _write_cursor(
    payload: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool,
    dry_run: bool,
    written: list[str],
) -> None:
    """Emit the Cursor target: ``.cursor/rules/*.mdc`` (+ charter) and ``.cursor/mcp.json``."""
    rules_dir = target / ".cursor" / "rules"
    _emit(
        rules_dir / "000-project.mdc",
        _project_mdc(_charter_body(payload, plan)),
        root=target,
        force=force,
        dry_run=dry_run,
        written=written,
    )
    for name, path in _iter_rules(payload, plan):
        text = path.read_text(encoding="utf-8")
        _emit(
            rules_dir / f"{Path(name).stem}.mdc",
            _rule_to_mdc(name, text, plan, payload),
            root=target,
            force=force,
            dry_run=dry_run,
            written=written,
        )
    if plan.mcp_servers:
        _emit(
            target / ".cursor" / "mcp.json",
            json.dumps(_to_cursor_mcp(plan.mcp_servers), indent=2) + "\n",
            root=target,
            force=force,
            dry_run=dry_run,
            written=written,
        )


def _write_agents(
    payload: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool,
    dry_run: bool,
    written: list[str],
) -> None:
    """Emit the universal ``AGENTS.md`` at the project root."""
    _emit(
        target / "AGENTS.md",
        _agents_document(payload, plan),
        root=target,
        force=force,
        dry_run=dry_run,
        written=written,
    )


def _write_copilot(
    payload: Path,
    target: Path,
    plan: ResolvedPlan,
    *,
    force: bool,
    dry_run: bool,
    written: list[str],
) -> None:
    """Emit ``.github/copilot-instructions.md`` (the same document as the ``agents`` target)."""
    _emit(
        target / ".github" / "copilot-instructions.md",
        _agents_document(payload, plan),
        root=target,
        force=force,
        dry_run=dry_run,
        written=written,
    )


_WRITERS = {
    "cursor": _write_cursor,
    "agents": _write_agents,
    "copilot": _write_copilot,
}


def export_targets(
    payload: Path,
    target_dir: Path,
    plan: ResolvedPlan,
    targets: list[str],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Export ``plan`` into ``target_dir`` for each requested target.

    Args:
        payload: Payload root (contains ``rules/`` and ``templates/``).
        target_dir: Project root to write the exported config into.
        plan: The resolved install plan from :func:`claude_kit.catalog.resolve`.
        targets: Any of :data:`VALID_TARGETS` (``cursor`` / ``agents`` / ``copilot``).
        force: Overwrite existing exported files instead of writing ``.claude-kit`` sidecars.
        dry_run: Report what would be written without touching the filesystem.

    Returns:
        The sorted list of project-relative paths written (or, on a dry run, that would be written).

    Raises:
        ValueError: If ``targets`` contains an unknown target id.
    """
    unknown = [t for t in targets if t not in VALID_TARGETS]
    if unknown:
        raise ValueError(
            f"unknown export target(s): {', '.join(unknown)} "
            f"(choices: {', '.join(VALID_TARGETS)})"
        )
    target_dir = Path(target_dir)
    written: list[str] = []
    # De-duplicate while preserving the caller's order.
    for name in dict.fromkeys(targets):
        _WRITERS[name](
            payload,
            target_dir,
            plan,
            force=force,
            dry_run=dry_run,
            written=written,
        )
    return sorted(written)
