---
name: shell-review
description: Audits shell scripts (bash/POSIX sh) for correctness, safety, portability — exit-code propagation, shebang choice, quoting, mktemp+trap, shellcheck. Do NOT use for non-shell code (use code-review-and-quality).
---

# Shell Script Review

> A stack-agnostic shell-audit lens re-derived from the MIT-licensed
> [`athola/claude-night-market`](https://github.com/athola/claude-night-market) `shell-review` skill
> (project-specific logging/guard conventions dropped — these are the universal checks). Shell is the
> one language nearly every repo ships (CI, git hooks, build, wrapper scripts) and the easiest to get
> subtly wrong, so it earns its own pass. Verify fixes with `shellcheck`.

## When to use

- Reviewing CI/CD pipeline scripts, git-hook scripts, build automation, `run-*.sh` wrappers
- Before committing any change to a `.sh` file (or a `#!`-shebang script)

**Not for:** non-shell code (→ `code-review-and-quality`); authoring a fresh script from scratch.

## 1. Exit codes — failures must propagate

The default pipeline exit code is the **last** command's, which silently masks earlier failures:

```bash
# BAD — grep succeeds when it finds lines, hiding a make failure
if make typecheck 2>&1 | grep -v '^make'; then echo "passed"; fi   # runs even when make failed
```

- Start scripts with `set -euo pipefail` (`-e` exit on error, `-u` error on unset var, `pipefail`
  propagate pipeline failures). `set -e` is for executables, not sourced libraries.
- When you must filter output but keep the status, **capture separately**:
  ```bash
  out=$(make typecheck 2>&1) || rc=$?
  printf '%s\n' "$out" | grep -v '^make' || true
  exit "${rc:-0}"
  ```
- Check the status of commands whose failure matters; don't `cmd | true`-away real errors.

## 2. Portability — match shebang to features used

```bash
#!/bin/sh             # POSIX — most portable
#!/usr/bin/env bash   # bash via env — use when you rely on bash features
```

If the script uses bash-only constructs, the shebang must be bash. Common bash-isms (and POSIX
alternatives): `[[ … ]]` → `[ … ]`; `(( … ))` → `$(( … ))`; arrays → positional params/files;
`${var//a/b}` → `sed`; `<<<` here-string → `printf … |`; `<(cmd)` process-sub → temp file; `source` →
`.`; `function f {}` → `f() {}`. Either restrict to POSIX **or** declare bash in the shebang — don't
run bash-isms under `#!/bin/sh`.

## 3. Safety patterns

- **Quote and brace variables:** `"${VAR}"`, `"${1}"`, `"${@}"` (not `$VAR`/`$@`) — unquoted
  expansion word-splits and globs. This is the single most common shell bug.
- **Require values explicitly:** `: "${CONFIG:?CONFIG must be set}"` instead of branching on unset.
- **`cd` in a subshell** so a failed `cd` can't run later commands in the wrong directory:
  `( cd "${dir}" && do_work )`.
- **Temp files with `mktemp` + `trap … EXIT` cleanup**; never predictable `/tmp/$$` names.
- **`printf` over `echo`** for anything with backslashes/leading-dash/variable data (`echo` behavior
  varies across shells).
- Don't pipe untrusted input into `eval`/`sh`; avoid `curl … | sh`.

## 4. Structure

- **Library vs executable:** a *library* (meant to be sourced) defines functions, sets no `set -e`,
  and has no execute bit; an *executable* defines `main()`, ends with `main "${@}"`, and is `chmod +x`.
  Don't give a library the execute bit or a `main`.
- Keep functions small; give an executable a `usage()`; run `shfmt` for consistent formatting.
- A sourced library that wasn't loaded should fail loudly at the call site rather than silently
  no-op.

## 5. Tooling & grounded findings

- **`shellcheck <script>`** is the backstop — run it and treat warnings as findings; many of the above
  are SC-coded. **`shfmt -d`** for formatting drift.
- Report each finding **grounded** (per `code-review-and-quality`): `file:line` + a verbatim anchor +
  the issue + a concrete fix. Re-verify the citation before reporting.

## Output

One finding per line: `path:Lline — <category>: <issue>. Fix: <remediation>.` End with a one-line
verdict (`N findings: X exit-code, Y safety, Z portability` or `Clean — shellcheck passes`).

## Related

- `code-review-and-quality` — general review; this is the shell-specific lens
- `ci-cd-and-automation` / `git-workflow-and-versioning` — where most reviewed shell lives (pipelines, hooks)
- `safety-critical-patterns` — the same "check return values / bound loops" discipline, language-neutral
