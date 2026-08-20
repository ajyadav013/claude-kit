# Release and recovery runbook

CI builds the wheel and sdist exactly once. Its `verified-dist` artifact is checksum-verified and
wheel-smoked before the privileged publish workflow may consume it through `workflow_run`. Publishing
never rebuilds and never uses `skip-existing`.

## Normal release

1. Bump every version ledger and add a non-empty `CHANGELOG.md` section.
2. Merge to `main` only after all required CI jobs pass.
3. CI uploads `verified-dist`; the publish workflow authenticates the source run, repository,
   `main` branch, push event, success conclusion, and exact head SHA.
4. A PyPI 404 permits publishing. A 200 permits recovery only when filenames and SHA-256 digests are
   byte-identical. Any other status, network ambiguity, missing file, or digest difference fails.
5. The workflow creates GitHub build provenance, publishes through OIDC with PEP 740 attestations,
   downloads the PyPI files, re-verifies their bytes, and finally tags the verified commit and attaches
   the same wheel, sdist, and `SHA256SUMS` to the GitHub Release.

## Recover an interrupted run

Use **Run workflow** on `Publish verified distributions` and provide the numeric run ID of the
successful `main` push CI run that produced the artifact. The workflow re-authenticates that run; a
PR, scheduled, failed, foreign-repository, non-main, or expired-artifact run is rejected.

- If PyPI has no version, the workflow resumes attestation and publish.
- If PyPI already has byte-identical files, upload is skipped and post-publish/GitHub Release repair
  continues. This is verified recovery, not a permissive skip.
- If PyPI has different filenames or digests, stop. PyPI releases are immutable: bump the version,
  document the incident, and release a new artifact. Never overwrite checksums or recreate files.
- If the GitHub tag exists at another commit, stop and investigate. The workflow will not move it.
  If the tag is correct but assets are absent, recovery re-verifies and uploads the exact CI files.
  An unexpected existing asset fails recovery rather than being retained; after upload the Release
  must contain exactly the wheel, sdist, and `SHA256SUMS` from `verified-dist`.

If the source CI artifact expired, rerun CI on the same commit only after confirming the checkout is
unchanged. The resulting run is a new evidence source; use its run ID. Do not build distributions on a
workstation or inside the publish workflow.
