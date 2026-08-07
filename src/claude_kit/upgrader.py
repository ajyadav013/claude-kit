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
import json
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from claude_kit import __version__, catalog, scaffold
from claude_kit.models import (
    UPGRADE_JOURNAL,
    FileRecord,
    InitOptions,
    ResolvedPlan,
    UpgradeJournal,
)
from claude_kit.validator import _load_init_options, _read_init_options

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
    old: (
        InitOptions | None
    )  # None when merging into an untracked tree (no init-options.json)
    plan: ResolvedPlan
    ref_root: Path
    actions: list[_Action]


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _diff_actions(
    ref: dict[str, "FileRecord"],
    old_map: dict[str, "FileRecord"],
    target: Path,
    *,
    backup_untracked: bool,
) -> list[_Action]:
    """Diff a rendered reference file-set (``ref``) against the live ``target`` tree.

    Shared by :func:`_compare` (upgrade) and :func:`merge_install` (first/merge install). The only
    difference between the two is the **unknown-collision policy**: when a reference file is also live
    but was never recorded in ``old_map`` (``rel`` absent), upgrade treats it as a routine refresh
    (``backup_untracked=False`` — the legacy behavior, since an upgrade always has init-options) while
    a merge-install treats it as a user file to back up before overwriting (``backup_untracked=True``).

    Returns the ordered list of :class:`_Action` (add / update / keep / remove) for :func:`_apply`.
    """
    actions: list[_Action] = []
    for rel, rrec in sorted(ref.items()):
        live = target / rel
        if not live.is_file():
            actions.append(_Action(rel, "add", rrec.owner))
            continue
        if _sha256(live) == rrec.sha256:
            continue  # already identical to the new reference
        if rel in old_map:
            user_modified = _sha256(live) != old_map[rel].sha256
        else:
            # Live file the kit also ships but we never recorded: only a merge into an untracked
            # tree should preserve it (back it up); an upgrade refreshes it silently as before.
            user_modified = backup_untracked
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

    return actions


def _compare(src: Path, target: str | Path) -> _Comparison | str:
    """Render a reference install and diff it against ``target``.

    Returns a :class:`_Comparison`, or a short error string (``"not-installed"`` /
    ``"no-options"``) the callers turn into a ``FAIL`` message. The caller owns cleanup of
    ``ref_root`` (via :func:`_cleanup`).
    """
    target = Path(target).expanduser().resolve()
    claude = target / ".claude"
    if not claude.is_dir():
        return "not-installed"
    old, err = _read_init_options(claude)
    if old is None:
        return "corrupt-options" if err and err.startswith("corrupt") else "no-options"

    plan = catalog.resolve(src, old.selection)
    # Render the reference under the REAL project name so CLAUDE.md/README don't diff spuriously.
    plan.context["project_name"] = target.name
    ref_root = Path(tempfile.mkdtemp(prefix="claude-kit-ref-"))
    # Detect against the REAL target so the reference's commands match the installed ones (the
    # reference itself is rendered into ref_root); otherwise discovered commands would diff.
    scaffold.install_sdlc(src, ref_root, plan, force=True, log=[], detect_target=target)

    ref_opts = _load_init_options(ref_root / ".claude")
    ref = {r.path: r for r in ref_opts.files} if ref_opts else {}
    old_map = {r.path: r for r in old.files}

    actions = _diff_actions(ref, old_map, target, backup_untracked=False)

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


def _journal_path(target: Path) -> Path:
    """Path to the transactional upgrade journal under ``.claude/config/``."""
    return target / ".claude" / "config" / UPGRADE_JOURNAL


def _write_journal(cmp: _Comparison) -> None:
    """Record the planned actions + version transition BEFORE any file is mutated.

    Written before the apply loop and removed only after the new baseline is in place, so its presence
    means an upgrade was interrupted mid-flight. ``upgrade`` is convergent, so the next run finishes and
    clears it; ``doctor`` surfaces it. Gitignored, so it is never committed.
    """
    journal = UpgradeJournal(
        from_version=cmp.old.claude_kit_version if cmp.old else "(untracked)",
        to_version=__version__,
        started_at=datetime.now(timezone.utc).isoformat(),
        actions=[{"rel": a.rel, "kind": a.kind, "owner": a.owner} for a in cmp.actions],
    )
    path = _journal_path(cmp.target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal.to_dict(), indent=2) + "\n", encoding="utf-8")


def _clear_journal(target: Path) -> None:
    """Remove the upgrade journal once the upgrade has committed its new baseline."""
    _journal_path(target).unlink(missing_ok=True)


def _format_preview(cmp: _Comparison) -> list[str]:
    """Build the human-readable diff report from a comparison (no side effects)."""
    msgs: list[str] = []
    old_ver = cmp.old.claude_kit_version if cmp.old else "(untracked)"
    if old_ver != __version__:
        msgs.append(f"INFO  kit version {old_ver} -> {__version__}")
    else:
        msgs.append(f"INFO  kit version {__version__} (unchanged)")

    if not cmp.actions:
        msgs.append("OK    everything up to date — nothing to upgrade")
        return msgs

    order = {"add": 0, "update": 1, "keep": 2, "remove": 3}
    verbs = {
        "add": "add",
        "update": "update",
        "keep": "keep (sidecar kit's version)",
        "remove": "remove (orphan)",
    }
    for act in sorted(cmp.actions, key=lambda a: (order[a.kind], a.rel)):
        note = ""
        if act.kind == "update" and act.user_modified and act.owner != "user-editable":
            note = "  [local changes will be backed up]"
        elif act.kind == "keep":
            note = "  [your edits kept; kit's version as .claude-kit]"
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
            return _apply(result, force=force, journal=True)
        finally:
            _cleanup(result.ref_root)


def merge_install(
    src: Path, target: str | Path, plan: ResolvedPlan, *, force: bool = False
) -> tuple[bool, list[str]]:
    """Non-destructively merge a freshly-resolved ``plan`` into an existing ``target``.

    This is the ``init`` **merge** path (chosen by default when ``.claude/`` already exists). Unlike
    :func:`upgrade` — which re-renders the *recorded* selection — this renders the *new* ``plan`` the
    user just chose, then reconciles it against the live tree with the same owner-aware logic:

    * kit / overlay files are refreshed (a user-modified one is backed up to ``.claude-kit.bak-N/``);
    * user-editable files keep the user's copy, with the new version dropped beside it as a sidecar;
    * kit/overlay files the new plan no longer ships are backed up and removed;
    * **any file the kit doesn't track is left untouched** — no directory is ever ``rmtree``-d.

    Works whether or not the target was previously claude-kit-tracked: with no ``init-options.json``
    the recorded set is empty, so every kit-path collision is treated as a user file and backed up
    before overwrite. Returns the ``(ok, messages)`` contract shared by the other lifecycle commands.
    """
    src = Path(src)
    target = Path(target).expanduser().resolve()
    # Render the reference under the REAL project name so CLAUDE.md/README don't diff spuriously.
    plan.context["project_name"] = target.name
    ref_root = Path(tempfile.mkdtemp(prefix="claude-kit-merge-"))
    try:
        # Detect against the REAL target so the reference's commands match what a real merge
        # writes into the live tree (the reference itself is rendered into ref_root).
        scaffold.install_sdlc(
            src, ref_root, plan, force=True, log=[], detect_target=target
        )
        ref_opts = _load_init_options(ref_root / ".claude")
        ref = {r.path: r for r in ref_opts.files} if ref_opts else {}
        old = _load_init_options(target / ".claude")
        old_map = {r.path: r for r in old.files} if old is not None else {}
        actions = _diff_actions(ref, old_map, target, backup_untracked=True)
        cmp = _Comparison(
            target=target, old=old, plan=plan, ref_root=ref_root, actions=actions
        )
        return _apply(cmp, force=force)
    finally:
        _cleanup(ref_root)


def _apply(
    cmp: _Comparison, *, force: bool, journal: bool = False
) -> tuple[bool, list[str]]:
    """Carry out the planned actions and refresh ``init-options.json``.

    When ``journal`` is set (the ``upgrade`` path), a transactional marker is written under
    ``.claude/config/`` before the first mutation and removed only after the new baseline is in place,
    so an interrupted run leaves a visible journal that the next convergent ``upgrade`` clears. The
    non-destructive ``merge_install`` path leaves it off.
    """
    msgs: list[str] = []
    if not cmp.actions:
        # Convergence: an upgrade interrupted *after* the baseline was written leaves a stale journal
        # on an already-current tree. Re-running clears it even though there is no work left.
        if journal and _journal_path(cmp.target).is_file():
            _clear_journal(cmp.target)
            msgs.append(
                "INFO  cleared a leftover upgrade journal (work already complete)"
            )
        verb = "upgrade" if journal else "merge"
        msgs.append(f"OK    everything up to date — nothing to {verb}")
        return True, msgs

    target, ref_root = cmp.target, cmp.ref_root
    if journal:
        _write_journal(cmp)
    backup_dir = _next_backup_dir(target)
    backed_up = 0
    sidecars_written = 0

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
            # A user-modified user-editable file is classified "keep", never "update"
            # (_diff_actions), so the sidecar decision belongs to that branch alone. The invariant
            # is pinned by test_update_actions_never_carry_a_user_modified_user_editable_file.
            if act.user_modified:
                _backup(act.rel)
            _copy_ref(act.rel)
            msgs.append(f"  ✓ {act.rel}")
        elif act.kind == "keep":
            if force:
                # --force: the documented contract is "overwrite user-modified user-editable
                # files instead of writing sidecars" — with the user's copy backed up first.
                _backup(act.rel)
                _copy_ref(act.rel)
                msgs.append(f"  ✓ {act.rel} (forced; your edits backed up)")
            else:
                sidecar = live.with_name(live.name + _SIDECAR_SUFFIX)
                if sidecar.is_file() and _sha256(sidecar) == _sha256(
                    ref_root / act.rel
                ):
                    # Same-version churn guard: the sidecar already holds exactly the kit's
                    # current copy — rewriting it every run just resets its mtime and falsely
                    # announces a "new version" that doesn't exist.
                    msgs.append(
                        f"  ~ {act.rel} (your edits kept; sidecar already current)"
                    )
                else:
                    shutil.copy2(ref_root / act.rel, sidecar)
                    sidecars_written += 1
                    msgs.append(
                        f"  ~ {act.rel} (kept; kit's version -> {live.name}{_SIDECAR_SUFFIX})"
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

    # Commit point reached: the new baseline is in place, so the transaction is complete.
    if journal:
        _clear_journal(target)

    if backed_up:
        msgs.append(
            f"INFO  backed up {backed_up} modified/removed file(s) -> {backup_dir.name}/"
        )
    if sidecars_written:
        msgs.append(
            "INFO  a .claude-kit sidecar holds the kit's copy of each kept file: "
            "`diff <file> <file>.claude-kit`, merge what you want, then delete the sidecar"
        )
    # Consent transparency (0.76.0): upgrade re-renders the RECORDED selection, so an install
    # whose capture_mode predates the opt-in flip keeps its background capture silently — say so
    # every time rather than assume the original choice was informed (pre-0.76 --defaults wasn't).
    recorded_capture = (
        getattr(cmp.old.selection, "capture_mode", "off") if cmp.old else "off"
    )
    if journal and recorded_capture and recorded_capture != "off":
        msgs.append(
            f"WARN  background learning capture is ON for this install (capture_mode: "
            f"{recorded_capture}, recorded at init and preserved by upgrade). Since 0.76.0 "
            "capture is opt-in on fresh installs. Audit what runs with `claude-kit "
            "privacy-report`; disable by re-running init and choosing Off, or by removing the "
            "capture entries from .claude/settings.json"
        )
    msgs.append("OK    upgrade complete" if journal else "OK    merge complete")
    return True, msgs


def _explain_error(code: str, target: str | Path) -> tuple[bool, list[str]]:
    """Translate a ``_compare`` error code into a ``(False, [FAIL …])`` report."""
    if code == "not-installed":
        return False, [
            f"FAIL  no .claude/ at {Path(target).expanduser().resolve()} — run `claude-kit init` first"
        ]
    if code == "corrupt-options":
        return False, [
            "FAIL  .claude/config/init-options.json is unreadable (invalid JSON) — repair it "
            "or re-run `claude-kit init --force` to re-create it"
        ]
    return False, [
        "FAIL  no .claude/config/init-options.json — this install predates upgrade tracking; "
        "re-run `claude-kit init --force` to start tracking"
    ]
