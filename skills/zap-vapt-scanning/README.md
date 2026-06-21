# OWASP ZAP VAPT Scanning & Reporting

A complete, self-contained setup for running an OWASP ZAP **VAPT** (Vulnerability Assessment &
Penetration Testing) scan against an API and rendering a finished **PDF report** — driven by the
single-file tool `scripts/zap_vapt.py`.

## What this skill covers

- **One-command ZAP automation**: locate/launch ZAP headless, read its API key from `config.xml`,
  create a context, replay endpoints, passive-scan, collect alerts, shut ZAP down.
- **Flexible endpoint input**: curl commands (copy-as-cURL), simple `METHOD url — description` lines,
  or a **Postman v2.1 collection** (`--postman`, with `--postman-env` and `--cookie`).
- **Param-aware alert join**: `:id`/`{id}` path params match concrete URLs; alerts attach to the
  most-specific endpoint; unmatched alerts roll up into a reconciling "Site-wide" row.
- **Branded report, configured at run time**: cover (logo or text wordmark), company/location,
  in-scope endpoint table, an 8-scenario manual pen-test summary, and ZAP-style aggregate tables
  (risk×confidence, site×risk, by alert type) with CWE/WASC/reference detail.
- **Safety**: passive by default; active scanning is deny-by-default for state-changing verbs and
  requires a typed `yes`.
- **Self-test**: `--selftest` runs 18 built-in unit checks (URL matching, curl parsing, the
  active-scan gate, risk wording) with no ZAP required.

## How to use

```bash
pip install -r scripts/requirements.txt
python3 scripts/zap_vapt.py            # interactive
python3 scripts/zap_vapt.py --help     # all flags
python3 scripts/zap_vapt.py --selftest # verify the logic (no ZAP needed)
```

See `references/operating-guide.md` for the full operating procedure, CLI reference, execution flow,
exit codes, and troubleshooting. A fully-flagged unattended invocation is shown in `SKILL.md`.

## Configuration, not hardcoding

The report's identity — company / organization name, short name, location, logo, and the
Created By / Approved By sign-off names — is **always supplied at run time** via CLI flags (or the
interactive prompts). The `ReportMeta` defaults ship blank/neutral, so the template carries no
organization-specific content. Provide a `--logo` image for branding, or let it fall back to a
brand-neutral text wordmark.

## Safety & authorization

Only run this against systems you are **authorized to test**. The tool sends real HTTP traffic to the
target. `--active` (active scanning) sends crafted attack payloads and is gated behind a deny-by-
default safety filter plus a typed confirmation — enable it only with explicit owner sign-off. Keep
real session cookies and API keys out of any committed input files.

## Requirements

- Python 3.8+, plus `requests` and `reportlab` (`scripts/requirements.txt`).
- OWASP ZAP installed (https://www.zaproxy.org/download/) and a Java runtime.

## Provenance

Derived from a production internal VAPT automation tool, genericized so all branding and sign-off
identity are run-time configuration rather than embedded values.
