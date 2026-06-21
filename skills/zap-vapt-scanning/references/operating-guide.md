# Operating & Understanding Guide for `zap_vapt.py`

> Give this file to any agent (with shell access to the `scripts/` folder) and it will be able to
> **understand** the tool and **run it on the user's behalf** to produce a VAPT report.
> Read it top-to-bottom before acting. Section 5 is the operating procedure; sections 8–13 are the
> reference + troubleshooting you'll need while running it.

---

## 1. TL;DR — what this is and the problem it solves

`zap_vapt.py` is a **single-file Python tool** that automates an OWASP ZAP **VAPT**
(Vulnerability Assessment & Penetration Testing) run and renders a finished **PDF report**.

The problem it solves: producing a VAPT report for every project used to be a slow, manual,
tribal-knowledge process (drive the ZAP GUI, copy the API key, replay endpoints, read alerts,
hand-format a report). This tool encodes that entire runbook so **anyone — or any agent — can run
one command and get the report.** No ZAP expertise required.

**Output:** a file named `<Service> VAPT Report.pdf` (default `API VAPT Report.pdf`) written to the
current directory, stamped with the date/time it was generated. The layout (cover page, table of
contents, report summary with in-scope endpoints, penetration-testing summary, and a full ZAP-style
vulnerability breakdown) is generic — **all branding and sign-off identity are supplied at run time**,
nothing is hardcoded.

---

## 2. Prerequisites (verify these first)

| Need | How to check | If missing |
|---|---|---|
| **Python 3.8+** | `python3 --version` | install Python 3 |
| **Python deps** (`requests`, `reportlab`) | `python3 -c "import requests, reportlab"` | `python3 -m pip install -r requirements.txt` (add `--break-system-packages` only if pip refuses on a managed system) |
| **OWASP ZAP** installed | macOS: `ls /Applications/*ZAP*.app`; Linux: `which zap.sh || ls /usr/share/zaproxy`; Windows: check `%PROGRAMFILES%\ZAP` | Download from https://www.zaproxy.org/download/ — macOS: `brew install --cask zap`; Linux: `sudo snap install zaproxy --classic` |
| **Java (JRE/JDK)** — ZAP needs it | `java -version` | install a JRE (e.g. Temurin) |

The script auto-discovers ZAP and **reads ZAP's API key itself** from ZAP's `config.xml`
(macOS `~/Library/Application Support/ZAP/config.xml`, Linux `~/.ZAP/config.xml`,
Windows `%USERPROFILE%\ZAP\config.xml`). You normally do **not** need to find or type the key.
The script launches ZAP **headless** and shuts it down when finished.

---

## 3. Folder file map (`scripts/`)

| File | What it is |
|---|---|
| `zap_vapt.py` | The tool. The only thing you run. |
| `requirements.txt` | `requests`, `reportlab`. |
| `endpoints.example.txt` | Example input file showing both accepted formats. |
| `logo.png` *(optional, you provide)* | Cover logo. If absent (or `--logo` not passed) the report uses a brand-neutral text wordmark. |

---

## 4. Quickstart

**Interactive (a human running it):**
```bash
python3 -m pip install -r requirements.txt
python3 zap_vapt.py
```
It then asks for: context name, the endpoints (paste or file), service, company, short company name,
location, and the two sign-off names.

**Fully unattended (what an agent should use — no prompts, no stdin):**
```bash
python3 zap_vapt.py \
  --input endpoints.txt \
  --context "API Testing" \
  --service "API" \
  --site "https://api.example.com" \
  --company "<COMPANY NAME>" \
  --company-short "<Company Ltd.>" \
  --location "<City, Country>" \
  --created-by "<Preparer name>" \
  --approved-by "<Approver name>" \
  --logo logo.png \
  --output "API VAPT Report.pdf" < /dev/null
```
This finds/launches ZAP, replays the endpoints in `endpoints.txt`, passive-scans, and writes the
PDF — with zero interaction. Every `<…>` value comes **from the user**, not from a default.
(Add `--active` only with explicit authorization; see §11.)

---

## 5. Agent operating procedure (follow this to run it for the user)

1. **Pre-flight.** Verify deps and ZAP per §2. If a dep is missing, install it. If ZAP is missing,
   tell the user how to install it (don't try to silently install a GUI app).
2. **Collect inputs from the user** (ask for whatever they haven't given — none of this is
   hardcoded, so it must be supplied):
   - The **endpoints** to test — as `curl` commands (best: copy-as-cURL from browser DevTools, with
     real cookies/auth) or as simple `METHOD url — description` lines. See §6.
   - **Context name** (any label, e.g. "API Testing").
   - **Service** name (e.g. "API", "Billing", "RBAC") — also names the output file.
   - **Company / organization** name for the cover, a **short company name** for the summary, the
     **location** line, and the two sign-off names (**Created By** / **Approved By**).
   - **Logo** path (optional) — pass `--logo`; otherwise a text wordmark is used.
   - **Site** base URL (optional; auto-derived from the endpoints if omitted).
   - Whether to run an **active scan** (default NO — see §11; only if they confirm authorization).
3. **Write the endpoints to a file** (e.g. `endpoints.txt`) rather than pasting interactively —
   it's more reliable. One curl or one `METHOD url — desc` per logical entry.
4. **Run unattended** with the flags from §4 (always pass `--input`, `--context`, `--service`, and
   the identity flags the user gave you, and ideally `--site`; redirect `< /dev/null`).
5. **Watch stdout.** Each step prints progress. Handle these signals:
   - `✗`/non-zero exit → read the message, consult §12, fix, re-run.
   - `⚠ N endpoint(s) matched zero alerts` → the URL/method may be wrong, or the target didn't
     respond; verify with the user.
   - `⚠ ... did not map to a listed endpoint` → harmless; those become a "Site-wide" row.
6. **Deliver the result.** On exit 0, report the absolute path of the generated PDF
   (`<Service> VAPT Report.pdf`) and the alert summary line. Offer to open or move it.

**Do NOT** pass `--active` without the user's explicit authorization — it sends real attack
payloads and still requires a typed `yes` (which blocks unattended runs by design).

---

## 6. Endpoint input formats

Two formats, freely mixable in the same file. Lines starting with `#` are comments. Markdown
bullets (`-`, `*`, `1.`) and numbered lists are tolerated (the marker is stripped).

**A) `curl` commands** — paste straight from "Copy as cURL". Multi-line (trailing `\`) is fine.
Method, URL, headers, cookies (`-H`/`-b`), and body (`-d`/`--data*`) are extracted and replayed
exactly. Add a description with a trailing em dash:
```
curl 'https://api.example.com/v1/session' \
  -H 'Cookie: session=...' --compressed — get session details
```

**B) Simple lines** — `METHOD url — description` (or just `url`):
```
GET  https://api.example.com/v1/org — get all org details
POST https://api.example.com/v1/role — create a new role
```

**Path parameters** `:id` / `:roleId` / `{id}` are understood: they match the concrete values ZAP
actually sees (e.g. `/role/:roleId/permission` matches `/role/106/permission?orgId=1`). For the
richest results give **concrete** URLs (real ids/cookies via curl); templated URLs still work
(responses, even 404s, produce the passive header findings).

The description is what shows in the report's "in scope" table. Anything after `—` / ` - ` / a tab /
` # ` on a simple line is the description; on a curl line, use ` — description`.

**C) Postman v2.1 collection** — `--postman collection.json` (optionally `--postman-env env.json`).
Recursively reads every request (method, URL, enabled headers, raw/urlencoded body); the request
name becomes the description. `{{variables}}` resolve from the collection vars + the env file.
Postman collections usually ship the auth cookie **empty** (secrets aren't committed) — supply it
with `--cookie '<value>'` (applied to every request and masked in output). Disabled headers are
skipped (matching Postman). Use `--methods GET` to exclude state-changing requests (e.g. a
destructive `PUT`/`DELETE`) so nothing is mutated on the target.

Worked example (authenticated, passive, destructive verbs excluded — replace every placeholder):
```bash
python3 zap_vapt.py --postman "collection.json" \
  --cookie 'session=...' --methods GET \
  --context "API Testing" --service "Billing" --site "https://api.example.com" \
  --company "<COMPANY NAME>" --company-short "<Company Ltd.>" --location "<City, Country>" \
  --created-by "<Preparer name>" --approved-by "<Approver name>" \
  --output "Billing VAPT Report.pdf"
```

---

## 7. CLI reference & exit codes

| Flag | Meaning |
|---|---|
| `--input FILE` | Read endpoints from FILE (else paste interactively). |
| `--postman FILE` | Read endpoints from a Postman v2.1 collection (`.json`). |
| `--postman-env FILE` | Postman environment `.json` to resolve `{{variables}}`. |
| `--cookie VALUE` | Cookie header value applied to **every** request (resolves an empty `{{COOKIE}}`; registered as a masked secret). |
| `--methods LIST` | Comma-list of HTTP methods to include, e.g. `GET` — others are skipped (use to exclude state-changing verbs). |
| `--context NAME` | ZAP context name (default "API Testing"). |
| `--service NAME` | Service under test; names the output file (default "API"). |
| `--site URL` | Base site for the report (auto-derived from endpoints if omitted). |
| `--company NAME` | Company / organization name on the cover. |
| `--company-short NAME` | Short company name used in the report summary. |
| `--location TEXT` | Location line on the cover (e.g. "City, Country"). |
| `--logo PATH` | Cover logo image (PNG/JPG); a text wordmark is used if omitted. |
| `--created-by NAME` | Name shown in the "Created By" sign-off row. |
| `--approved-by NAME` | Name shown in the "Approved By" sign-off row. |
| `--active` | Also run ZAP's active scanner (gated + requires typed `yes`). |
| `--port N` | ZAP API port (default 8080). |
| `--api-key KEY` | Override the ZAP API key (else read from config.xml). |
| `--zap-path PATH` | Path to `zap.sh` / `zap.bat` if auto-detect fails. |
| `--output FILE` | Output PDF path (default `<Service> VAPT Report.pdf`). |
| `--no-report` | Run the scan but skip PDF generation. |
| `--selftest` | Run built-in unit checks and exit (no ZAP needed). |

**Exit codes:** `0` success · `1` selftest failed · `2` missing Python deps · `3` ZAP not found /
no API key / a daemon is up but rejected the key · `4` no endpoints parsed · `5` all replays failed
(ZAP got no traffic — report refused to avoid a false "clean" result) · `130` interrupted (Ctrl-C).

---

## 8. How it works — the execution flow

The run maps to six steps; internally each is a small set of ZAP REST API calls
(`GET http://127.0.0.1:8080/JSON/{component}/{view|action}/{action}/`, key sent via the
`X-ZAP-API-Key` header):

1. **Locate ZAP & get the key** — find `zap.sh`/`zap.bat`; read `api.key` from ZAP's `config.xml`.
2. **Start/attach daemon** — reuse a ZAP already listening on the port, else launch it headless and
   wait until `core/view/version` answers; auto-shutdown on exit (only if we started it).
3. **Context** — `context/view/contextList` → create with `context/action/newContext` (or reuse).
4. **Endpoints** — parse curls / simple lines into a list (method, url, headers, body, description).
5. **Replay + scan** — clear old alerts (`core/action/deleteAllAlerts`); for each endpoint:
   `context/action/includeInContext` (a param-aware regex), then replay it —
   `core/action/accessUrl` for a plain GET, or `core/action/sendRequest` with a raw HTTP request
   (absolute-URI request line) for anything with headers/body or a non-GET method. Wait for the
   passive scanner to drain (`pscan/view/recordsToScan == 0`). If `--active`: confirm, then
   `ascan/action/scan` per safe endpoint and poll `ascan/view/status`.
6. **Collect & render** — pull alerts (`core/view/alerts`), join each alert to its endpoint by a
   param-aware regex (most-specific endpoint wins; unmatched alerts become a "Site-wide" row),
   aggregate the counts, then render the PDF with reportlab.

---

## 9. Script architecture (so you can read/modify it)

All in `zap_vapt.py`, top to bottom:
- **Console helpers** — encoding-safe status glyphs (degrade to ASCII on legacy consoles).
- **Data model** (`@dataclass`): `Request`, `Endpoint`, `Alert`, `AlertType`, `Aggregates`,
  `ReportMeta`.
- **Parsing** — `parse_curl`, `parse_simple_line`, `_logical_lines`, `parse_endpoints_input`,
  `parse_postman`.
- **Join** — `normalize_url`, `_param_pattern`, `context_regex`, `compile_matcher`, `_specificity`,
  `join_alerts`.
- **`ZapClient`** — discovery (`locate_zap`, `read_api_key`, `zap_config_path`), lifecycle
  (`start_daemon`, `ping`, `shutdown`), and the request sequence (`ensure_context`,
  `include_in_context`, `access_url`, `send_request`, `wait_passive`, `active_scan`, `alerts`).
  `build_raw_request` builds the raw HTTP for `send_request`.
- **Aggregation** — `aggregate` → `Aggregates`.
- **Report** — `build_pdf` + `_build_aggregates` + `_findings_sentence` (reportlab, A4, pure Python).
- **Decision points you can tune** — `summarize_endpoint_risk` and `should_active_scan`
  (marked `>>> YOUR CODE`). See §14.
- **`main()`** — argparse + the interactive flow. `run_selftest()` powers `--selftest`.

---

## 10. What the report contains

1. **Cover** — logo (or text wordmark), company, location, "<Service> - Vulnerability and
   Penetration Testing Report", a sign-off table (Created By / Approved By with name, designation,
   date), and a generation timestamp.
2. **Table of Contents.**
3. **Report Summary** — engagement prose (adapts to the service type) + the in-scope endpoint table
   (URL, method, description) + a dynamically-computed findings sentence.
4. **Penetration Testing Summary** — the standard 8-scenario manual-test table (XSS, SQLi, authz,
   etc.), all marked "Passed" (a manual attestation; edit the pen-test table if any failed).
5. **Vulnerability Scans Summary** — per-endpoint alert table (deduped, with a reconciling
   "Site-wide" row) + ZAP-style aggregate tables (risk×confidence, site×risk, by alert type) +
   per-alert-type detail (Source/CWE/WASC/References).

---

## 11. Safety & authorization

- **Only scan systems you are authorized to test.** This tool sends real traffic to the target.
- **Passive scanning** (default) just observes responses to the requests you listed — low risk.
- **Active scanning** (`--active`) sends crafted attack payloads and replays mutated request
  bodies. The gate `should_active_scan()` **denies all state-changing verbs by default**
  (POST/PUT/PATCH/DELETE are never auto-attacked) plus any URL whose path looks side-effecting
  (login/logout/delete/charge/etc.). Even then, the run pauses for a typed `yes`. Do not enable
  `--active` on production without explicit owner sign-off.

---

## 12. Troubleshooting

| Symptom (stdout / exit) | Likely cause | Fix |
|---|---|---|
| `Missing dependencies` (exit 2) | `requests`/`reportlab` not installed | `python3 -m pip install -r requirements.txt` |
| `OWASP ZAP was not found` (exit 3) | ZAP not installed / not in a known path | install ZAP, or pass `--zap-path /path/to/zap.sh` |
| `Could not read the ZAP API key` (exit 3) | config.xml absent (ZAP never launched) or key disabled | open ZAP once to generate a key, or pass `--api-key KEY` |
| `daemon is running ... but rejected the API key` (exit 3) | a ZAP is up with a different key | pass the correct `--api-key`, or stop that ZAP |
| `ZAP process exited during startup (check Java install)` | Java missing/broken | install/repair a JRE; verify `java -version` |
| `ZAP did not become ready within 180s` | slow start / port busy | retry; or use a free `--port`; check nothing else owns 8080 |
| `No endpoints parsed` (exit 4) | empty/malformed input | check the `--input` file format (§6) |
| `All endpoint replays failed ... no traffic` (exit 5) | wrong target / network / auth all failed | check URLs, cookies/auth headers, connectivity |
| `N endpoint(s) matched zero alerts` (warning) | URL/method mismatch, or target returned nothing scannable | verify the exact URL+method; for auth'd APIs include valid cookies |
| Garbled glyphs (`?`/`[i]`) in output | legacy Windows console (cp437/cp1252) | cosmetic only; the tool degrades to ASCII automatically |
| Cover shows a text wordmark, not a logo | no `--logo` / `logo.png` present | pass `--logo PATH` (or drop `logo.png` next to the script) |

---

## 13. Design gotchas — do NOT "fix" these (they are intentional)

If you read the code and are tempted to "simplify", know that these were deliberate fixes for real
bugs found in testing/review:
- **Absolute-URI request line** in `build_raw_request` (`METHOD https://host/path HTTP/1.1`). A
  path-only line makes ZAP default to **HTTP**, so https endpoints get hit over http and their
  alerts (`http://…`) never match the scope → a silently empty report.
- **Param-aware join, most-specific-first** (`_specificity`, `compile_matcher`). Ranking by literal
  content (not raw string length) prevents a templated `:param` endpoint from stealing a concrete
  endpoint's alerts. The `:param` substitution requires a preceding `/` so an explicit `:port` is
  never turned into a wildcard (which would expand scope to any host:port).
- **Alert dedup + cap** in the per-endpoint cell. A chatty endpoint with many alert instances would
  otherwise create one table row taller than a page → `LayoutError` aborts the whole PDF.
- **cp1252 sanitize + `_attr` href escaping.** reportlab core fonts are WinAnsi; unescaped `"` in a
  URL aborts the build, and non-cp1252 chars must be sanitized.
- **API key via `X-ZAP-API-Key` header** (not the URL) and **masked in error messages**; the key is
  **not** passed on the daemon command line.
- **Fail-loud, not silent:** zero delivered → refuse to emit a "clean" report (exit 5); a failed
  active-scan poll never counts as "done"; clearing stale alerts is fatal if it fails.

To confirm everything still works after any edit: `python3 zap_vapt.py --selftest` (18 checks,
no ZAP required).

---

## 14. Customization points

Two functions are intentionally left simple to tune (marked `>>> YOUR CODE` in `zap_vapt.py`):
- **`summarize_endpoint_risk(counts)`** — the wording of the "Risk" column
  (`"Both Low"`, `"1 Low"`, `"2 Low\n2 Informational"`).
- **`should_active_scan(ep)`** — the active-scan safety gate. Default is deny-by-default for
  state-changing verbs; relax it (carefully) only for endpoints you explicitly want fuzzed.

Also editable: `ReportMeta` defaults (all blank/neutral — supply real values via flags), the static
pen-test table, and the report prose in `build_pdf` (it already branches on the service type, with a
detailed access-control narrative when the service is "RBAC" and a generic narrative otherwise).
