# Frozen Claude 0.83 baseline

`generated/` is a characterization of the last Claude-only installer at immutable commit
`04161917bd3c1aef270f9979e5abeabe3cd755e6` (claude-kit 0.83.0). It is intentionally not produced
by the current checkout's renderer. The regeneration script archives that commit, starts a clean
Python process with only the archived `src/` on `PYTHONPATH`, and rejects any other commit or tree.

The three case files record every installed regular file's project-relative path, SHA-256, mode,
and size; parsed agent and skill frontmatter; exact assembled hook settings; and ordered gate policy
plus digest. `generated/legacy-0.83/project/` contains an exact standard-install init manifest and
stack snapshot, together with a portable schema-v1 pipeline snapshot for migration tests. Schema v1
is deliberate: 0.83 reads it as an explicit migration input, and unlike schema v2 it contains no
machine-derived absolute repository root.

Reviewed regeneration command:

```bash
python scripts/regenerate_frozen_claude_fixtures.py \
  --source-commit 04161917bd3c1aef270f9979e5abeabe3cd755e6 --write
```

Byte-for-byte verification uses the same pinned source with `--check`. A shallow clone must fetch
that exact commit before either command can run; the script never falls back to `HEAD`.
