"""Diff and safe-upgrade of a scaffolded claude-kit configuration.

The strategy is **render-and-compare**: re-render a pristine reference install of the *recorded*
selection into a throwaway temp dir (reusing :func:`claude_kit.scaffold.install_sdlc`, so no install
logic is duplicated), then compare that reference tree against the live ``target`` tree. Each file's
recorded ``owner`` (kit / overlay / user-editable) plus whether it was modified since install (live
checksum vs. the checksum in ``.claude/config/init-options.json``) decides the action:

* **kit** / **overlay** files are refreshed to the new content (a user-modified one is backed up first).
* **user-editable** files (``CLAUDE.md``, ``settings.json``, ``.mcp.json``, ``CONTINUITY.md``,
  ``agent-memory/``) are *never* clobbered: if the user changed one, the new version is written
  alongside as a ``.claude-kit`` sidecar so they can merge it (``--force`` overwrites instead).
* Files the current kit no longer ships (orphans) are backed up and removed — but only kit/overlay
  ones; a user's own files are left untouched.

``diff`` previews these actions and writes nothing; ``upgrade`` applies them and then refreshes
``init-options.json`` with the new checksums and kit version. Both return the ``(ok, messages)``
contract shared by the other lifecycle commands.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from claude_kit import catalog, scaffold
from claude_kit.models import InitOptions
from claude_kit.validator import _load_init_options

#: Sidecar suffix for a new version of a user-modified, protected file.
_SIDECAR_SUFFIX = ".claude-kit"


@dataclass(frozen=True)
class _Action:
    """One planned change to a single file, relative to the project root."""

    rel: str
    kind: str  # "add" | "update" | "keep" | "remove"
    owner: str  # "kit" | "overlay" | "user-editable"
    user_modified: bool = False


@dataclass
class _Comparison:
    """The result of comparing a freshly-rendered reference tree against the live install."""

    target: Path
    old: InitOptions
    plan: object  # ResolvedPlan
    ref_root: Path
    actions: list[_Action]


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _compare(src: Path, target: Path) -> _Comparison | str:
    """Render a reference install and diff it against ``target``.

    Returns a :class:`_Comparison`, or a short error string (``"not-installed"`` /
    ``"no-options"``) the callers turn into a ``FAIL`` message. The caller owns cleanup of
    ``ref_root`` (via :func:`_cleanup`).
    """
    target = Path(target).expanduser().resolve()
    claude = target / ".claude"
    if not claude.is_dir():
        return "not-installed"
    old = _load_init_options(claude)
    if old is None:
        return "no-options"

    plan = catalog.resolve(src, old.selection)
    # Render the reference under the REAL project name so CLAUDE.md/README don't diff spuriously.
    plan.context["project_name"] = target.name
    ref_root = Path(tempfile.mkdtemp(prefix="claude-kit-ref-"))
    scaffold.install_sdlc(src, ref_root, plan, force=True, log=[])

    ref_opts = _load_init_options(ref_root / ".claude")
    ref = {r.path: r for r in ref_opts.files} if ref_opts else {}
    old_map = {r.path: r for r in old.files}

    actions: list[_Action] = []
    for rel, rrec in sorted(ref.items()):
        live = target / rel
        if not live.is_file():
            actions.append(_Action(rel, "add", rrec.owner))
            continue
        if _sha256(live) == rrec.sha256:
            continue  # already identical to the new reference
        old_sha = old_map[rel].sha256 if rel in old_map else None
        user_modified = old_sha is not None and _sha256(live) != old_sha
        if rrec.owner == "user-editable":
            actions.append(
                _Action(
                    rel,
                    "keep" if user_modified else "update",
                    rrec.owner,
                    user_modified,
                )
            )
        else:
            actions.append(_Action(rel, "update", rrec.owner, user_modified))

    # Orphans: recorded kit/overlay files the current kit no longer ships for this selection.
    for rel, orec in sorted(old_map.items()):
        if rel in ref or orec.owner == "user-editable":
            continue
        if (target / rel).is_file():
            actions.append(_Action(rel, "remove", orec.owner))

    return _Comparison(
        target=target, old=old, plan=plan, ref_root=ref_root, actions=actions
    )


def _cleanup(ref_root: Path) -> None:
    """Remove the throwaway reference render."""
    shutil.rmtree(ref_root, ignore_errors=True)


def _next_backup_dir(target: Path) -> Path:
    """Return a fresh, non-existing ``.claude-kit.bak-N/`` directory under ``target``."""
    n = 1
    while (target / f".claude-kit.bak-{n}").exists():
        n += 1
    return target / f".claude-kit.bak-{n}"


def _format_preview(cmp: _Comparison) -> list[str]:
    """Build the human-readable diff report from a comparison (no side effects)."""
    from claude_kit import __version__

    msgs: list[str] = []
    if cmp.old.claude_kit_version != __version__:
        msgs.append(f"INFO  kit version {cmp.old.claude_kit_version} -> {__version__}")
    else:
        msgs.append(f"INFO  kit version {__version__} (unchanged)")

    if not cmp.actions:
        msgs.append("OK    everything up to date — nothing to upgrade")
        return msgs

    order = {"add": 0, "update": 1, "keep": 2, "remove": 3}
    verbs = {
        "add": "add",
        "update": "update",
        "keep": "keep (sidecar new version)",
        "remove": "remove (orphan)",
    }
    for act in sorted(cmp.actions, key=lambda a: (order[a.kind], a.rel)):
        note = ""
        if act.kind == "update" and act.user_modified and act.owner != "user-editable":
            note = "  [local changes will be backed up]"
        elif act.kind == "keep":
            note = "  [your edits kept; new version as .claude-kit]"
        msgs.append(f"  {verbs[act.kind]:<28} {act.rel} ({act.owner}){note}")

    counts: dict[str, int] = {}
    for act in cmp.actions:
        counts[act.kind] = counts.get(act.kind, 0) + 1
    summary = ", ".join(f"{counts[k]} {k}" for k in order if k in counts)
    msgs.append(f"INFO  {summary}")
    return msgs


def diff(target: str | Path) -> tuple[bool, list[str]]:
    """Preview what an upgrade would change (no writes). Returns ``(ok, messages)``."""
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        result = _compare(src, target)
        if isinstance(result, str):
            return _explain_error(result, target)
        try:
            return True, _format_preview(result)
        finally:
            _cleanup(result.ref_root)


def upgrade(target: str | Path, *, force: bool = False) -> tuple[bool, list[str]]:
    """Apply the upgrade: refresh kit/overlay files, protect user edits, prune orphans.

    Args:
        target: Project root to upgrade.
        force: Overwrite user-modified *user-editable* files instead of writing sidecars.

    Returns:
        ``(ok, messages)``.
    """
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        result = _compare(src, target)
        if isinstance(result, str):
            return _explain_error(result, target)
        try:
            return _apply(result, force=force)
        finally:
            _cleanup(result.ref_root)


def _apply(cmp: _Comparison, *, force: bool) -> tuple[bool, list[str]]:
    """Carry out the planned actions and refresh ``init-options.json``."""
    msgs: list[str] = []
    if not cmp.actions:
        msgs.append("OK    everything up to date — nothing to upgrade")
        return True, msgs

    target, ref_root = cmp.target, cmp.ref_root
    backup_dir = _next_backup_dir(target)
    backed_up = 0

    def _backup(rel: str) -> None:
        nonlocal backed_up
        live = target / rel
        if not live.is_file():
            return
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, dest)
        backed_up += 1

    def _copy_ref(rel: str) -> None:
        live = target / rel
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ref_root / rel, live)

    for act in cmp.actions:
        live = target / act.rel
        if act.kind == "add":
            _copy_ref(act.rel)
            msgs.append(f"  + {act.rel}")
        elif act.kind == "update":
            if act.user_modified:
                _backup(act.rel)
            if act.owner == "user-editable" and act.user_modified and not force:
                # Protect: keep the user's file, drop the new version beside it.
                shutil.copy2(
                    ref_root / act.rel, live.with_name(live.name + _SIDECAR_SUFFIX)
                )
                msgs.append(
                    f"  ~ {act.rel} (kept; new version -> {live.name}{_SIDECAR_SUFFIX})"
                )
            else:
                _copy_ref(act.rel)
                msgs.append(f"  ✓ {act.rel}")
        elif act.kind == "keep":
            shutil.copy2(
                ref_root / act.rel, live.with_name(live.name + _SIDECAR_SUFFIX)
            )
            msgs.append(
                f"  ~ {act.rel} (kept; new version -> {live.name}{_SIDECAR_SUFFIX})"
            )
        elif act.kind == "remove":
            _backup(act.rel)
            live.unlink(missing_ok=True)
            msgs.append(f"  - {act.rel} (orphan removed)")

    # Adopt the reference's config verbatim as the new baseline. Recording the kit's CANONICAL
    # checksums (not the live ones) is what keeps a *kept* user-editable file detectable as
    # user-modified on the next upgrade — re-recording its live sha would make the next run treat
    # it as pristine and clobber the user's edits.
    ref_config = ref_root / ".claude" / "config"
    dst_config = target / ".claude" / "config"
    dst_config.mkdir(parents=True, exist_ok=True)
    for name in ("init-options.json", "stack-catalog.snapshot.yaml"):
        if (ref_config / name).is_file():
            shutil.copy2(ref_config / name, dst_config / name)

    if backed_up:
        msgs.append(
            f"INFO  backed up {backed_up} modified/removed file(s) -> {backup_dir.name}/"
        )
    msgs.append("OK    upgrade complete")
    return True, msgs


def _explain_error(code: str, target: str | Path) -> tuple[bool, list[str]]:
    """Translate a ``_compare`` error code into a ``(False, [FAIL …])`` report."""
    if code == "not-installed":
        return False, [
            f"FAIL  no .claude/ at {Path(target).expanduser().resolve()} — run `claude-kit init` first"
        ]
    return False, [
        "FAIL  no .claude/config/init-options.json — this install predates upgrade tracking; "
        "re-run `claude-kit init --force` to start tracking"
    ]
