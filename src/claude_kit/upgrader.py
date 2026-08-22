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
import os
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import yaml

from claude_kit import __version__, catalog, scaffold
from claude_kit.models import (
    FileRecord,
    InitOptions,
    InstallRequest,
    ResolvedPlan,
    Runtime,
    StateLayout,
)
from claude_kit.runtime_scaffold import (
    RuntimeInstallError,
    install_runtime,
    preview_runtime_install,
    transition_runtime,
)
from claude_kit.secure_fs import (
    ProjectFS,
    ProjectTransaction,
    UnsafePathError,
    normalize_relative_path,
    recover_interrupted_transaction,
)
from claude_kit.validator import _load_init_options, _read_init_options

#: Sidecar suffix for a new version of a user-modified, protected file.
_SIDECAR_SUFFIX = ".claude-kit"
_LEGACY_STATE_LAYOUT = StateLayout.legacy_claude()


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


def _inside(target: Path, rel: str) -> bool:
    """Return True when ``target / rel`` still resolves inside ``target``.

    :func:`claude_kit.models.contained_relpath` already rejects ``..`` and absolute paths when the
    manifest is parsed, which stops the textual attack. This is the second half: a *symlinked*
    directory inside the project (say ``.claude/rules`` pointing at ``~``) makes an innocent-looking
    relative path resolve outside the root anyway. Since :func:`_apply` unlinks orphans, that is
    worth a check at the moment of use rather than trusting the parse alone.
    """
    try:
        ProjectFS(target).assert_safe(rel)
    except (OSError, UnsafePathError):
        return False
    return True


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
    fs = ProjectFS(target)
    fs.assert_tree_safe(_LEGACY_STATE_LAYOUT.root)
    for rel, rrec in sorted(ref.items()):
        rel = normalize_relative_path(rel)
        live = fs.assert_safe(rel)
        if not fs.is_file(rel):
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
    # This is the only branch that *deletes*, and its paths come from the on-disk manifest rather
    # than from the reference render — so containment is re-checked here even though the manifest
    # was already validated at parse time (see _inside).
    for rel, orec in sorted(old_map.items()):
        if rel in ref or orec.owner == "user-editable":
            continue
        if not _inside(target, rel):
            raise UnsafePathError(
                f"refusing unsafe orphan path {rel!r} from init-options manifest"
            )
        if fs.is_file(rel):
            actions.append(_Action(rel, "remove", orec.owner))

    return actions


def _compare(src: Path, target: str | Path) -> _Comparison | str:
    """Render a reference install and diff it against ``target``.

    Returns a :class:`_Comparison`, or a short error string (``"not-installed"`` /
    ``"no-options"``) the callers turn into a ``FAIL`` message. The caller owns cleanup of
    ``ref_root`` (via :func:`_cleanup`).
    """
    target = Path(os.path.abspath(os.fspath(Path(target).expanduser())))
    fs = ProjectFS(target)
    claude = target / _LEGACY_STATE_LAYOUT.root
    if not fs.is_dir(_LEGACY_STATE_LAYOUT.root):
        return "not-installed"
    fs.assert_tree_safe(_LEGACY_STATE_LAYOUT.root)
    snapshot_rel = _LEGACY_STATE_LAYOUT.stack_snapshot
    if fs.is_file(snapshot_rel):
        try:
            snapshot = yaml.safe_load(fs.read_text(snapshot_rel))
        except yaml.YAMLError as exc:
            raise UnsafePathError(
                f"cannot upgrade: installed stack snapshot is invalid YAML ({exc})"
            ) from exc
        if isinstance(snapshot, dict) and "schema_version" in snapshot:
            schema = snapshot["schema_version"]
            if isinstance(schema, bool) or not isinstance(schema, int) or schema != 1:
                qualifier = "future " if isinstance(schema, int) and schema > 1 else ""
                raise UnsafePathError(
                    "cannot upgrade without understanding the installed snapshot: "
                    f"unsupported {qualifier}stack snapshot schema_version {schema!r} "
                    "(supported: 1); upgrade claude-kit before retrying"
                )
    old, err = _read_init_options(claude)
    if old is None:
        return "corrupt-options" if err and err.startswith("corrupt") else "no-options"

    try:
        plan = catalog.resolve(src, old.selection)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        return f"invalid-selection:{exc}"
    # Render the reference under the REAL project name so CLAUDE.md/README don't diff spuriously.
    plan.context["project_name"] = target.name
    ref_root = Path(tempfile.mkdtemp(prefix="claude-kit-ref-")).resolve()
    # Detect against the REAL target so the reference's commands match the installed ones (the
    # reference itself is rendered into ref_root); otherwise discovered commands would diff.
    scaffold.install_sdlc(src, ref_root, plan, force=True, log=[], detect_target=target)

    ref_opts = _load_init_options(ref_root / _LEGACY_STATE_LAYOUT.root)
    ref = {r.path: r for r in ref_opts.files} if ref_opts else {}
    old_map = {r.path: r for r in old.files}

    actions = _diff_actions(ref, old_map, target, backup_untracked=False)

    return _Comparison(
        target=target, old=old, plan=plan, ref_root=ref_root, actions=actions
    )


def _cleanup(ref_root: Path) -> None:
    """Remove the throwaway reference render."""
    if not ref_root.name.startswith(("claude-kit-ref-", "claude-kit-merge-")):
        raise UnsafePathError(
            f"refusing unexpected reference cleanup target: {ref_root}"
        )
    if ref_root.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        raise UnsafePathError(
            f"refusing reference cleanup outside temp directory: {ref_root}"
        )
    if not ref_root.exists():
        return
    fs = ProjectFS(ref_root)
    for entry in ref_root.iterdir():
        fs.assert_tree_safe(normalize_relative_path(entry.name))
    shutil.rmtree(ref_root)


def _next_backup_dir(target: Path) -> Path:
    """Return a fresh, non-existing ``.claude-kit.bak-N/`` directory under ``target``."""
    fs = ProjectFS(target)
    n = 1
    while fs.exists(f".claude-kit.bak-{n}"):
        n += 1
    return fs.path(f".claude-kit.bak-{n}")


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


def _native_options(fs: ProjectFS) -> InitOptions:
    """Load and fail closed on the runtime-neutral native manifest."""

    try:
        document = json.loads(fs.read_text(StateLayout.neutral().manifest))
        if not isinstance(document, dict):
            raise ValueError("document root must be an object")
        options = InitOptions.from_dict(document)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeInstallError(f"native init-options is corrupt: {exc}") from exc
    if options.state_layout != StateLayout.neutral():
        raise RuntimeInstallError(
            "native install does not use the neutral state layout"
        )
    return options


def _native_diff(fs: ProjectFS) -> tuple[bool, list[str]]:
    """Validate and preview a native same-runtime refresh without mutation."""

    try:
        options = _native_options(fs)
        with ExitStack() as stack:
            src = scaffold.payload_dir(stack)
            plan = catalog.resolve(src, options.selection)
            request = InstallRequest(options.selection, options.runtime)
            projection, desired = preview_runtime_install(src, fs.root, plan, request)
    except (
        FileNotFoundError,
        OSError,
        RuntimeInstallError,
        TypeError,
        ValueError,
    ) as exc:
        return False, [f"FAIL  cannot preview native runtime upgrade: {exc}"]

    missing = [path for path in desired if not fs.exists(path)]
    drifted = [
        record.path
        for record in options.files
        if record.owner in {"kit", "overlay"}
        and fs.is_file(record.path)
        and hashlib.sha256(fs.read_bytes(record.path)).hexdigest() != record.sha256
    ]
    messages = [
        "OK    native upgrade preview validated for runtime(s): "
        + ", ".join(options.runtimes),
        f"INFO  rendering version: installed={options.rendering_version}, "
        f"current={max(projection.rendering_versions.values())}",
        f"INFO  desired inventory: {len(desired)} files; missing={len(missing)}; "
        f"locally modified kit files={len(drifted)}",
    ]
    for path in missing[:10]:
        messages.append(f"  add                         {path}")
    for path in drifted[:10]:
        messages.append(
            f"  preserve local edit         {path} (new copy will use sidecar)"
        )
    if not missing and not drifted and options.claude_kit_version == __version__:
        messages.append("OK    native install is structurally up to date")
    return True, messages


def _native_upgrade(
    fs: ProjectFS,
    *,
    force: bool,
    runtime: str | Runtime | None,
    confirm_runtime_removal: bool,
) -> tuple[bool, list[str]]:
    """Refresh or explicitly transition one native runtime installation."""

    try:
        options = _native_options(fs)
        selected = options.runtime if runtime is None else Runtime.parse(runtime)
        with ExitStack() as stack:
            source = scaffold.payload_dir(stack)
            plan = catalog.resolve(source, options.selection)
            request = InstallRequest(options.selection, selected)
            if selected is options.runtime:
                log = install_runtime(source, fs.root, plan, request, force=force)
            else:
                log = transition_runtime(
                    source,
                    fs.root,
                    plan,
                    request,
                    force=force,
                    confirm_removal=confirm_runtime_removal,
                )
    except (
        FileNotFoundError,
        OSError,
        RuntimeInstallError,
        TypeError,
        ValueError,
    ) as exc:
        return False, [f"FAIL  native runtime upgrade refused: {exc}"]
    messages = list(log)
    messages.append(
        "OK    native runtime transition complete"
        if selected is not options.runtime
        else "OK    native runtime upgrade complete"
    )
    return True, messages


def diff(target: str | Path) -> tuple[bool, list[str]]:
    """Preview what an upgrade would change (no writes). Returns ``(ok, messages)``."""
    try:
        fs = ProjectFS(target)
        if fs.is_file(StateLayout.neutral().manifest):
            return _native_diff(fs)
    except (OSError, UnsafePathError) as exc:
        return False, [f"FAIL  {exc}"]
    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        try:
            result = _compare(src, target)
        except UnsafePathError as exc:
            return False, [f"FAIL  {exc}"]
        if isinstance(result, str):
            return _explain_error(result, target)
        try:
            return True, _format_preview(result)
        finally:
            _cleanup(result.ref_root)


def upgrade(
    target: str | Path,
    *,
    force: bool = False,
    runtime: str | Runtime | None = None,
    confirm_runtime_removal: bool = False,
) -> tuple[bool, list[str]]:
    """Apply the upgrade: refresh kit/overlay files, protect user edits, prune orphans.

    Args:
        target: Project root to upgrade.
        force: Overwrite user-modified *user-editable* files instead of writing sidecars.

    Returns:
        ``(ok, messages)``.
    """
    try:
        native_fs = ProjectFS(target)
        if native_fs.is_file(StateLayout.neutral().manifest):
            return _native_upgrade(
                native_fs,
                force=force,
                runtime=runtime,
                confirm_runtime_removal=confirm_runtime_removal,
            )
    except (OSError, UnsafePathError) as exc:
        return False, [f"FAIL  {exc}"]

    if runtime is not None:
        return False, [
            "FAIL  runtime transitions require neutral .ckit state; run "
            "`ckit migrate-state` or `ckit init --runtime <runtime> --migrate-state` first"
        ]

    with ExitStack() as stack:
        src = scaffold.payload_dir(stack)
        result: _Comparison | str | None = None
        try:
            try:
                fs = ProjectFS(target)
                with fs.mutation_lease(exclusive=True):
                    recover_interrupted_transaction(fs, preserve_root=True)
                    result = _compare(src, fs.root)
                    if isinstance(result, str):
                        return _explain_error(result, target)
                    return _apply(result, force=force, journal=True, fs=fs)
            except UnsafePathError as exc:
                return False, [f"FAIL  {exc}"]
        finally:
            if isinstance(result, _Comparison):
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
    target = Path(os.path.abspath(os.fspath(Path(target).expanduser())))
    fs: ProjectFS | None = None
    # Render the reference under the REAL project name so CLAUDE.md/README don't diff spuriously.
    plan.context["project_name"] = target.name
    ref_root = Path(tempfile.mkdtemp(prefix="claude-kit-merge-")).resolve()
    try:
        fs = ProjectFS(target)
        with fs.mutation_lease(exclusive=True):
            recover_interrupted_transaction(fs, preserve_root=True)
            # Detect against the REAL target so the reference's commands match what a real merge
            # writes into the live tree (the reference itself is rendered into ref_root).
            scaffold.install_sdlc(
                src, ref_root, plan, force=True, log=[], detect_target=target
            )
            ref_opts = _load_init_options(ref_root / _LEGACY_STATE_LAYOUT.root)
            ref = {r.path: r for r in ref_opts.files} if ref_opts else {}
            old = _load_init_options(target / _LEGACY_STATE_LAYOUT.root)
            old_map = {r.path: r for r in old.files} if old is not None else {}
            actions = _diff_actions(ref, old_map, target, backup_untracked=True)
            cmp = _Comparison(
                target=target, old=old, plan=plan, ref_root=ref_root, actions=actions
            )
            return _apply(cmp, force=force, fs=fs)
    except UnsafePathError as exc:
        return False, [f"FAIL  {exc}"]
    finally:
        _cleanup(ref_root)


def _apply(
    cmp: _Comparison,
    *,
    force: bool,
    journal: bool = False,
    fs: ProjectFS | None = None,
) -> tuple[bool, list[str]]:
    """Carry out planned actions inside a rollback-capable project transaction."""
    msgs: list[str] = []
    fs = fs or ProjectFS(cmp.target)
    if not cmp.actions:
        # Backward compatibility: clear a schema-1 convergence-only journal left
        # by an older claude-kit after its baseline had already committed.
        if journal and fs.is_file(_LEGACY_STATE_LAYOUT.journal):
            fs.unlink(_LEGACY_STATE_LAYOUT.journal)
            msgs.append(
                "INFO  cleared a leftover upgrade journal (work already complete)"
            )
        verb = "upgrade" if journal else "merge"
        msgs.append(f"OK    everything up to date — nothing to {verb}")
        return True, msgs

    target, ref_root = cmp.target, cmp.ref_root
    backup_dir = _next_backup_dir(target)
    backup_rel = fs.relpath(backup_dir)
    backed_up = 0
    sidecars_written = 0

    def _backup(rel: str) -> None:
        nonlocal backed_up
        rel = normalize_relative_path(rel)
        if not fs.is_file(rel):
            return
        fs.copy_file(fs.path(rel), f"{backup_rel}/{rel}")
        backed_up += 1

    def _copy_ref(rel: str) -> None:
        safe_rel = normalize_relative_path(rel)
        fs.copy_file(ref_root / safe_rel, safe_rel)

    transaction_actions = [
        {"rel": act.rel, "kind": act.kind, "owner": act.owner} for act in cmp.actions
    ]
    operation = "upgrade" if journal else "merge"
    old_version = cmp.old.claude_kit_version if cmp.old else "(untracked)"
    with ProjectTransaction(
        fs,
        operation=operation,
        from_version=old_version,
        to_version=__version__,
        actions=transaction_actions,
    ):
        for act in cmp.actions:
            rel = normalize_relative_path(act.rel)
            live = fs.path(rel)
            if act.kind == "add":
                _copy_ref(rel)
                msgs.append(f"  + {rel}")
            elif act.kind == "update":
                if act.user_modified:
                    _backup(rel)
                _copy_ref(rel)
                msgs.append(f"  ✓ {rel}")
            elif act.kind == "keep" and force:
                _backup(act.rel)
                _copy_ref(rel)
                msgs.append(f"  ✓ {rel} (forced; your edits backed up)")
            elif act.kind == "keep":
                sidecar = live.with_name(live.name + _SIDECAR_SUFFIX)
                sidecar_rel = fs.relpath(sidecar)
                if fs.is_file(sidecar_rel) and _sha256(fs.path(sidecar_rel)) == _sha256(
                    ref_root / rel
                ):
                    msgs.append(f"  ~ {rel} (your edits kept; sidecar already current)")
                else:
                    fs.copy_file(ref_root / rel, sidecar_rel)
                    sidecars_written += 1
                    msgs.append(
                        f"  ~ {rel} (kept; kit's version -> {live.name}{_SIDECAR_SUFFIX})"
                    )
            elif act.kind == "remove":
                _backup(rel)
                fs.unlink(rel, missing_ok=True)
                msgs.append(f"  - {rel} (orphan removed)")

        # Adopt the canonical reference checksums rather than the live checksum of
        # a protected file whose user-owned contents were kept.
        for relative in (
            _LEGACY_STATE_LAYOUT.manifest,
            _LEGACY_STATE_LAYOUT.stack_snapshot,
        ):
            source = ref_root / relative
            if source.is_file():
                fs.copy_file(source, relative)

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
            f"FAIL  {_LEGACY_STATE_LAYOUT.manifest} is unreadable — it is not valid JSON, or a "
            "recorded file path is not project-relative (a path containing '..' or a leading '/' "
            "is refused, since upgrade resolves recorded paths against this project and may "
            "delete them). Repair it, or re-run `claude-kit init --force` to re-create it"
        ]
    if code.startswith("invalid-selection:"):
        detail = code.partition(":")[2]
        return False, [
            f"FAIL  {_LEGACY_STATE_LAYOUT.manifest} contains a selection that does not resolve "
            f"against this kit's catalog ({detail}) — repair it or re-run "
            "`claude-kit init --force`"
        ]
    return False, [
        f"FAIL  no {_LEGACY_STATE_LAYOUT.manifest} — this install predates upgrade tracking; "
        "re-run `claude-kit init --force` to start tracking"
    ]
