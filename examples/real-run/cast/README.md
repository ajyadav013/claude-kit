# Terminal recording — the gate checks

![gate checks passing](gate-checks.svg)

A genuine recording of the sample app's gate checks (`build` → `vet` → `gofmt` → `test`) running
green: **7 tests pass, 85.2% coverage**. The output and timing are real.

- **`gate-checks.cast`** — [asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/). Replay it:

  ```bash
  asciinema play examples/real-run/cast/gate-checks.cast
  ```

- **`gate-checks.svg`** — a static render of the same captured output (the image above), for inline
  viewing without asciinema.

## Provenance (how it was made)

`asciinema` isn't required to produce this — it was recorded with a ~40-line standard-library Python
`pty` recorder driving the real command, so the captured bytes and inter-chunk timing are genuine:

```bash
python3 record.py gate-checks.cast bash -c 'cd ../sample-app && bash run-checks.sh'
```

This is a recording of real commands, not a re-enactment. To re-record it yourself, run
`bash ../sample-app/run-checks.sh` under `asciinema rec` (or any terminal recorder).
