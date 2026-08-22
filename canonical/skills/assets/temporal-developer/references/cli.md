# `temporal` CLI — the developer dev loop

The same commands work against the dev server, a self-hosted cluster, or Temporal Cloud — only the
connection descriptor changes. **Always pass `--output json`** so output is parseable.

## Dev server

```bash
temporal server start-dev                 # in-memory, single process — DEV ONLY
temporal server start-dev --db-filename temporal.db   # persist state across restarts
```

Loses all state on restart unless `--db-filename` is set; never use it for production. Default
frontend address is `localhost:7233`; the Web UI is served too (default `localhost:8233`).

## Start vs execute

```bash
# Start asynchronously — returns Workflow ID + Run ID immediately
temporal workflow start --output json \
  --type YourWorkflow --task-queue YourTaskQueue \
  --workflow-id YourId --input '{"k": "v"}'

# Start AND block until completion — streams progress; non-zero exit = failed/cancelled/timed out
temporal workflow execute --output json \
  --type YourWorkflow --task-queue YourTaskQueue --input '{"k": "v"}'
```

`--type` and `--task-queue` are required; `--workflow-id` is optional (server generates a UUID).
`execute` is ideal for one-shot smoke tests in the dev loop. Useful start flags: `--id-reuse-policy`
(`AllowDuplicate` | `AllowDuplicateFailedOnly` | `RejectDuplicate` | `TerminateIfRunning`),
`--id-conflict-policy` (`Fail` | `UseExisting` | `TerminateExisting`), `--execution-timeout` /
`--run-timeout`, `--search-attribute KEY=VALUE`, `--cron` (legacy — prefer `temporal schedule create`).

## Interacting with a running workflow

```bash
# Signal (fire-and-forget mutation)
temporal workflow signal --output json -w YourId --name YourSignal --input '{"k":"v"}'

# Query (read-only; works on running AND completed workflows)
temporal workflow query --output json -w YourId --name YourQuery

# Update is a COMMAND GROUP, not one command:
temporal workflow update execute -w YourId --name YourUpdate --input '{"k":"v"}'      # start + wait for result
temporal workflow update start   -w YourId --name YourUpdate --wait-for-stage accepted # start + wait for accept
temporal workflow update result  -w YourId --update-id YourUpdateId                    # fetch a prior update's result
temporal workflow update describe -w YourId --update-id YourUpdateId                   # status
```

Gotchas: `--wait-for-stage` on `update start` only accepts `accepted`; `update` alone does nothing.

## Inspecting & dev-only lifecycle

```bash
temporal workflow show --output json -w YourId    # full Event History (save for replay tests)
temporal workflow list --output json --query '<visibility query>'
temporal workflow terminate -w YourId             # DEV ONLY — kill a stale execution
```

`workflow show --output json` is how you capture a history to feed a **replay test** (`testing.md`).
For bulk operations (`--query` batch signal/terminate), schedules, and ops tooling, see the upstream
`skill-temporal-developer` references and `skill-temporal-ops`.
