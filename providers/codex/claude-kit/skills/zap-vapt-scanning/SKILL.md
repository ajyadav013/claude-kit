---
name: zap-vapt-scanning
description: Automated OWASP ZAP VAPT scan against an API, rendering a PDF report via bundled scripts/zap_vapt.py. Only for systems you are authorized to test. Do NOT use for white-box pentesting (use shannon-ai-pentest).
---

# OWASP ZAP VAPT Scanning & Reporting

A complete, runnable setup that automates an OWASP ZAP VAPT run and produces a PDF report. The tool
is `scripts/zap_vapt.py` — a single stdlib-plus-`requests`/`reportlab` script with no other moving
parts. All branding and report identity are **configuration supplied at run time**; nothing
organization-specific is baked in.

## When to use

- The user wants to **security-test an API** / run a **VAPT** or **DAST** pass and get a report.
- The user has a list of **endpoints**, a **curl** export, or a **Postman collection** to scan.
- The user wants to **automate OWASP ZAP** (headless, no GUI clicking) end to end.
- Do **not** use against any system the user is not clearly authorized to test (see Safety).

## Core conventions

- **The tool is self-contained.** Run `scripts/zap_vapt.py`; it finds/launches ZAP, reads ZAP's API
  key from `config.xml` itself, scans, and writes `<Service> VAPT Report.pdf`. Deps: `requests`,
  `reportlab` (`pip install -r scripts/requirements.txt`). Verify any change with
  `python3 scripts/zap_vapt.py --selftest` (18 checks, no ZAP needed).
- **Ask the user for report identity — never invent or hardcode it.** Before generating a report,
  collect: company / organization name (`--company`), short company name (`--company-short`),
  location (`--location`), "Created By" and "Approved By" names (`--created-by` / `--approved-by`),
  optional logo (`--logo`; otherwise a brand-neutral text wordmark is used), and the service label
  (`--service`). All `ReportMeta` defaults are blank/neutral by design.
- **Prefer an input file + a fully-flagged, unattended run** (`< /dev/null`) over interactive paste —
  it's reproducible. Write endpoints to `endpoints.txt` (see `scripts/endpoints.example.txt`).
- **Passive by default.** A normal run only replays the listed requests and observes responses.
- **Active scanning is gated.** `--active` sends real attack payloads; it is deny-by-default for
  state-changing verbs and still requires a typed `yes`. Pass it only with explicit authorization.
- **Path params** (`:id`, `:roleId`, `{id}`) are matched to concrete URLs; alerts join to the
  most-specific endpoint, and unmatched alerts roll up into a reconciling "Site-wide" row.
- **Fail-loud:** if ZAP received no traffic the tool refuses to emit a falsely "clean" report
  (exit 5). Read the exit code (see the operating guide) and fix the cause rather than retrying blind.

## Example — unattended run

```bash
pip install -r scripts/requirements.txt        # one-time: requests, reportlab

python3 scripts/zap_vapt.py \
  --input endpoints.txt \
  --context "API Testing" \
  --service "Billing" \
  --site "https://api.example.com" \
  --company "<COMPANY NAME>" \
  --company-short "<Company Ltd.>" \
  --location "<City, Country>" \
  --created-by "<Preparer name>" \
  --approved-by "<Approver name>" \
  --logo logo.png \
  --output "Billing VAPT Report.pdf" < /dev/null
```

Every `<…>` value comes from the user. Omit `--logo` to use the text wordmark. Add `--active` only
after the user confirms they are authorized to actively attack the target.

`endpoints.txt` accepts curl commands, `METHOD url — description` lines, or both (mixed); or read a
Postman v2.1 collection directly with `--postman collection.json --cookie '<session>' --methods GET`.

## Anti-patterns

- ❌ Hardcoding a company name, location, logo, or sign-off names into the script or a wrapper —
  always pass them as flags/prompts. The template ships brand-neutral.
- ❌ Running `--active` (or scanning at all) without explicit authorization for the target.
- ❌ Pasting endpoints interactively for an automated run — write a file and pass `--input`.
- ❌ Treating a zero-alert report as "secure" when warnings show replays failed or endpoints matched
  zero alerts — that usually means wrong URLs/auth, not a clean target.
- ❌ "Simplifying" the absolute-URI request line, the param-aware join, or the cp1252 escaping —
  these are deliberate fixes (see operating guide §13).
- ❌ Committing real session cookies, API keys, or a populated Postman env — keep secrets out of
  input files; `--cookie` values are masked in output but should still never be committed.

## References

- `scripts/zap_vapt.py` — the tool (single file).
- `scripts/requirements.txt` — `requests`, `reportlab`.
- `scripts/endpoints.example.txt` — both input formats, annotated.
- `references/operating-guide.md` — full operating procedure, CLI reference, execution flow,
  troubleshooting, exit codes, and the intentional design gotchas.
