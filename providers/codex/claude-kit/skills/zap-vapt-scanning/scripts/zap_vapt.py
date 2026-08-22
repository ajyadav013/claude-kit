#!/usr/bin/env python3
"""
zap_vapt.py — One-command OWASP ZAP VAPT report generator.

Hands-off pipeline: find/launch ZAP headless -> create a context -> replay your
endpoints (curl or simple lines) through ZAP -> passive (and optional gated active)
scan -> pull alerts -> render a VAPT report PDF matching your report template.

Run:  python3 zap_vapt.py            (fully interactive)
      python3 zap_vapt.py --help     (all flags)
      python3 zap_vapt.py --selftest (run the built-in unit checks and exit)

Only third-party deps: requests, reportlab  (pip install -r requirements.txt)
"""

from __future__ import annotations

import argparse
import atexit
import base64
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from glob import glob
from urllib.parse import quote_plus, urlsplit
from xml.sax.saxutils import escape as _xml_escape

# ----------------------------------------------------------------------------
# Constants & small console helpers
# ----------------------------------------------------------------------------
GREEN = "#188038"  # endpoint mono cells / descriptions / alert names (from template)
BLUE = "#1155CC"  # ZAP-native hyperlinks
GRID = "#888888"  # table border gray
DEFAULT_PORT = 8080
DEFAULT_CONTEXT = "API Testing"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Optional cover logo. Drop a "logo.png" next to this script, or pass --logo PATH.
# If neither exists, the report falls back to a brand-neutral text wordmark.
LOGO_PATH = os.path.join(SCRIPT_DIR, "logo.png")

# Make output encoding-safe everywhere (legacy Windows consoles use cp1252/cp437,
# which can't encode our status glyphs and would crash on the very first print).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+ TextIOWrapper
    except (AttributeError, ValueError, OSError):
        pass


def _enc_ok(s: str) -> bool:
    try:
        s.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


_UNI = _enc_ok("ℹ✓⚠✗▶…—")  # do we have a console that can show the nice glyphs?
_G_INFO, _G_OK, _G_WARN, _G_ERR, _G_STEP = (
    ("ℹ ", "✓ ", "⚠ ", "✗ ", "▶ ") if _UNI else ("[i] ", "[ok] ", "[!] ", "[x] ", ">> ")
)
DASH = "—" if _UNI else "-"  # em dash in messages, ASCII fallback on legacy consoles

_USE_COLOR = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def info(msg):
    print(_c("36", _G_INFO) + msg)


def ok(msg):
    print(_c("32", _G_OK) + msg)


def warn(msg):
    print(_c("33", _G_WARN) + msg)


def err(msg):
    print(_c("31", _G_ERR) + msg, file=sys.stderr)


def step(msg):
    print("\n" + _c("1;35", _G_STEP + msg))


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------
@dataclass(slots=True)
class Request:
    method: str
    url: str
    headers: dict
    body: str | None = None


@dataclass(slots=True)
class Endpoint:
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    body: str | None = None
    description: str = ""
    include_regex: str = ""

    def finalize(self):
        self.method = self.method.upper()
        if "://" not in self.url:
            self.url = "https://" + self.url
        self.include_regex = context_regex(self.url)
        return self


@dataclass(slots=True)
class Alert:
    name: str
    risk: str
    confidence: str
    cweid: int
    wascid: int
    reference: list
    url: str
    method: str
    param: str
    plugin_id: str
    source: str

    # ZAP Alert.Source enum: 0=unknown 1=active 2=manual 3=passive 4=tool
    _SOURCE_LABELS = {
        0: "scanner",
        1: "active scanner",
        2: "manual tester",
        3: "passive scanner",
        4: "tool",
    }

    @classmethod
    def from_zap(cls, d: dict) -> "Alert":
        def as_int(x):
            try:
                return int(x)
            except (TypeError, ValueError):
                return -1

        refs = [r.strip() for r in (d.get("reference") or "").split("\n") if r.strip()]
        return cls(
            name=d.get("alert") or d.get("name") or "Unknown",
            risk=(d.get("risk") or "Informational").strip(),
            confidence=(d.get("confidence") or "Low").strip(),
            cweid=as_int(d.get("cweid", -1)),
            wascid=as_int(d.get("wascid", -1)),
            reference=refs,
            url=d.get("url", ""),
            method=(d.get("method") or "GET").upper(),
            param=d.get("param", ""),
            plugin_id=str(d.get("pluginId", "")),
            source=cls._SOURCE_LABELS.get(
                as_int(d.get("sourceid", 3)), "passive scanner"
            ),
        )


@dataclass(slots=True)
class ReportMeta:
    # Cover/identity fields are blank by default so no organization details are
    # baked into the template. Supply them via CLI flags or the interactive prompts.
    company: str = ""
    location: str = ""
    company_short: str = ""
    service_short: str = "API"
    service_full: str = "API service"
    site: str = ""
    tool_version: str = "ZAP by Checkmarx v2.17.0"
    created_name: str = ""
    created_role: str = "Prepared by"
    approved_name: str = ""
    approved_role: str = "Approved by"
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def date_str(self) -> str:
        return self.generated_at.strftime("%b %d, %Y")

    @property
    def generated_str(self) -> str:
        return self.generated_at.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


# ============================================================================
# 1) curl / endpoint parsing
# ============================================================================
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_DATA_FLAGS = {
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-ascii",
}  # raw, NOT encoded
_VALUELESS = {
    "--compressed",
    "-L",
    "--location",
    "-k",
    "--insecure",
    "-s",
    "--silent",
    "-i",
    "--include",
    "-v",
    "--verbose",
    "-g",
    "--globoff",
    "-#",
    "--progress-bar",
}
_PARAM_PLACEHOLDER = "ZZPARAMZZ"


def _preprocess_continuations(raw: str) -> str:
    raw = re.sub(r"\\[ \t]*\r?\n", " ", raw)  # bash backslash line continuation
    raw = re.sub(r"\^[ \t]*\r?\n", " ", raw)  # windows cmd caret continuation
    return raw


def _split_header(h: str) -> tuple[str, str]:
    k, _, v = h.partition(":")
    return k.strip(), v.strip()


def _merge_cookies(cookies: dict, s: str):
    for pair in s.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        k, _, v = pair.partition("=")
        cookies[k.strip()] = v.strip()


def parse_curl(curl_str: str) -> Request:
    """Parse a (possibly multi-line) curl command into a Request."""
    s = _preprocess_continuations(curl_str).strip()
    s = s.lstrip("$# ").strip()
    if s.endswith(";"):
        s = s[:-1]
    try:
        tokens = shlex.split(s, posix=True)
    except ValueError:
        tokens = shlex.split(
            s.replace("'", '"'), posix=True
        )  # best-effort retry on bad quoting
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]

    method = None
    url = None
    headers: dict = {}
    cookies: dict = {}
    body = None
    user = None

    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if t in ("-X", "--request") and nxt is not None:
            method = nxt.upper()
            i += 2
            continue
        if t in ("-H", "--header") and nxt is not None:
            k, v = _split_header(nxt)
            if k.lower() == "cookie":
                _merge_cookies(cookies, v)
            elif k:
                headers[k] = v
            i += 2
            continue
        if t in ("-b", "--cookie") and nxt is not None:
            if "=" in nxt:
                _merge_cookies(cookies, nxt)
            else:
                warn(
                    f"ignoring cookie-jar file '{nxt}' (only inline cookies are supported)"
                )
            i += 2
            continue
        if t == "--data-urlencode" and nxt is not None:
            # curl percent-encodes only the CONTENT (after the first '='); name stays literal
            if nxt.startswith("@") or "@" in nxt.split("=", 1)[-1][:1]:
                warn(f"not reading data file in '{nxt}' for safety; sending empty body")
                val = nxt.split("=", 1)[0] + "=" if "=" in nxt else ""
            elif "=" in nxt:
                name, _, content = nxt.partition("=")
                val = name + "=" + quote_plus(content)
            else:
                val = quote_plus(nxt)
            body = (body + "&" + val) if body else val
            i += 2
            continue
        if t in _DATA_FLAGS and nxt is not None:
            val = nxt
            if val.startswith("@"):
                warn(f"not reading data file '{val}' for safety; sending empty body")
                val = ""
            body = (body + "&" + val) if body else val
            i += 2
            continue
        if t in ("-u", "--user") and nxt is not None:
            user = nxt
            i += 2
            continue
        if t == "--url" and nxt is not None:
            url = nxt
            i += 2
            continue
        if t in _VALUELESS:
            i += 1
            continue
        if t.startswith("-"):
            i += 1
            continue  # unknown flag: skip just the flag, keep parsing
        if url is None:
            url = t
        i += 1

    if not url:
        raise ValueError("no URL found in curl command")
    if "://" not in url:
        url = "https://" + url
    if user:
        headers.setdefault(
            "Authorization", "Basic " + base64.b64encode(user.encode()).decode()
        )
    if method is None:
        method = "POST" if body is not None else "GET"
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    if body is not None and not any(h.lower() == "content-type" for h in headers):
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return Request(method, url, headers, body or None)


def parse_simple_line(line: str) -> Endpoint | None:
    """Parse 'METHOD url — description' / 'url' lines."""
    desc = ""
    for sep in ("—", " – ", " - ", "\t", " # "):
        if sep in line:
            line, desc = line.split(sep, 1)
            desc, line = desc.strip(), line.strip()
            break
    parts = line.split()
    if not parts:
        return None
    if parts[0].upper() in _METHODS:
        method = parts[0].upper()
        url = parts[1] if len(parts) > 1 else ""
        extra = parts[2:]
    else:
        method, url = "GET", parts[0]
        extra = parts[1:]
    if not url:
        return None
    if extra and not desc:
        warn(
            f"ignoring trailing tokens after URL: {' '.join(extra)!r} "
            f"(use '{DASH}', ' - ', a tab, or ' # ' before a description)"
        )
    return Endpoint(method, url, {}, None, desc)


def _logical_lines(raw: str) -> list:
    """Join continuations + option-only lines so each curl/endpoint is one string.

    A line is merged into the previous one ONLY when the previous line is a curl AND
    this line is a genuine flag (-x / --x), never a "- " markdown bullet. Leading list
    markers (-, *, +, 1.) are stripped so pasted bullet/numbered lists don't collapse
    into one garbage endpoint.
    """
    raw = _preprocess_continuations(raw)
    out: list = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        prev_is_curl = bool(out) and out[-1].lstrip("$# ").lower().startswith("curl")
        if prev_is_curl and re.match(
            r"^-{1,2}[A-Za-z]", s
        ):  # real curl flag, not "- " bullet
            out[-1] = out[-1] + " " + s
        else:
            out.append(
                re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", s)
            )  # strip list bullet/number
    return out


def parse_endpoints_input(raw: str) -> list:
    eps: list = []
    for line in _logical_lines(raw):
        try:
            if line.lower().startswith("curl"):
                # Quote-aware description split: tokenize FIRST, then peel a trailing
                # "— description" only if "—" survives as its own bare token (i.e. it was
                # OUTSIDE quotes). Splitting the raw string would corrupt an em-dash that
                # legitimately appears inside a JSON body or header value.
                s = (
                    _preprocess_continuations(line)
                    .strip()
                    .lstrip("$# ")
                    .strip()
                    .rstrip(";")
                )
                try:
                    toks = shlex.split(s, posix=True)
                except ValueError:
                    toks = shlex.split(s.replace("'", '"'), posix=True)
                desc = ""
                if "—" in toks:
                    cut = toks.index("—")
                    desc = " ".join(toks[cut + 1 :]).strip()
                    toks = toks[:cut]
                req = parse_curl(shlex.join(toks))  # shlex.join re-quotes losslessly
                eps.append(Endpoint(req.method, req.url, req.headers, req.body, desc))
            else:
                ep = parse_simple_line(line)
                if ep:
                    eps.append(ep)
        except Exception as e:  # noqa: BLE001 - one bad line shouldn't kill the batch
            warn(f"skipping unparseable line ({e}): {line[:70]}")
    return _finalize_endpoints(eps)


def _finalize_endpoints(eps: list) -> list:
    """Finalize each endpoint and de-duplicate on (method, normalized url), keeping the
    first (with its headers/desc). Same-path-different-query entries collapse to one."""
    seen = set()
    uniq = []
    for ep in eps:
        ep.finalize()
        key = (ep.method, normalize_url(ep.url))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ep)
    return uniq


# ---- Postman collection (v2.1) ingestion -----------------------------------
def _pm_url(u) -> str:
    if isinstance(u, str):
        return u
    if isinstance(u, dict):
        return u.get("raw") or ""
    return ""


def _pm_subst(text: str, variables: dict) -> str:
    if not text:
        return text
    return re.sub(
        r"\{\{([^}]+)\}\}",
        lambda m: variables.get(m.group(1).strip(), m.group(0)),
        text,
    )


def parse_postman(
    path: str, env_path: str | None = None, cookie: str | None = None
) -> list:
    """Parse a Postman v2.1 collection into Endpoints, resolving {{variables}} from the
    collection vars + an optional environment file (+ an explicit cookie override)."""
    with open(path, encoding="utf-8") as fh:
        col = json.load(fh)
    variables: dict = {}
    for v in col.get("variable", []) or []:
        if v.get("key"):
            variables[v["key"]] = v.get("value", "")
    if env_path and os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            for v in json.load(fh).get("values", []) or []:
                if v.get("key") and v.get("enabled", True):
                    variables[v["key"]] = v.get("value", "")
    if cookie:
        variables["COOKIE"] = cookie

    eps: list = []

    def walk(items):
        for it in items or []:
            if "item" in it:  # folder -> recurse
                walk(it["item"])
                continue
            r = it.get("request")
            if r is None:
                continue
            if isinstance(r, str):
                r = {"method": "GET", "url": r}
            method = (r.get("method") or "GET").upper()
            url = _pm_subst(_pm_url(r.get("url")), variables).strip()
            if not url:
                continue  # skip blank-URL entries
            headers = {}
            for h in r.get("header", []) or []:
                if h.get("disabled"):
                    continue
                k = h.get("key")
                if k:
                    headers[k] = _pm_subst(str(h.get("value", "")), variables)
            body = None
            b = r.get("body") or {}
            mode = b.get("mode")
            if mode == "raw":
                body = _pm_subst(b.get("raw", ""), variables) or None
            elif mode == "urlencoded":
                pairs = [
                    f"{p.get('key')}={p.get('value', '')}"
                    for p in b.get("urlencoded", []) or []
                    if not p.get("disabled")
                ]
                body = "&".join(pairs) or None
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif mode in ("formdata", "file", "graphql"):
                warn(
                    f"'{it.get('name', '?')}': body mode '{mode}' not supported; sending no body"
                )
            eps.append(Endpoint(method, url, headers, body, it.get("name", "")))

    walk(col.get("item", []))
    unresolved = sorted(
        {
            m.strip()
            for ep in eps
            for m in re.findall(
                r"\{\{([^}]+)\}\}", ep.url + " " + " ".join(ep.headers.values())
            )
        }
    )
    if unresolved:
        warn(
            f"unresolved Postman variable(s) with no value: {', '.join(unresolved)} "
            "(requests using them may fail)"
        )
    return _finalize_endpoints(eps)


# ============================================================================
# 2) URL normalization, context regex, and the alert<->endpoint join
# ============================================================================
def normalize_url(u: str) -> str:
    p = urlsplit(u if "://" in u else "https://" + u)
    netloc = p.netloc.lower()
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = p.path.rstrip("/") or ""
    return f"{p.scheme.lower()}://{netloc}{path}"


def _param_pattern(url: str) -> str:
    """Regex body for a URL with :param / {param} turned into [^/]+ (dots escaped).

    The :param substitution requires a preceding '/' so it only touches PATH segments,
    never an explicit ':port' in the netloc (which must stay literal — otherwise the
    pattern would match any host:port and even prefix-matched hostnames).
    """
    base = normalize_url(url)
    base = re.sub(r"(?<=/):[A-Za-z0-9_]+", _PARAM_PLACEHOLDER, base)
    base = re.sub(r"\{[^/}]+\}", _PARAM_PLACEHOLDER, base)
    return re.escape(base).replace(_PARAM_PLACEHOLDER, "[^/]+")


def context_regex(url: str) -> str:
    """Java/ZAP regex for context inclusion (matches the JS includeRegex, param-aware)."""
    return _param_pattern(url) + r".*"


def compile_matcher(url: str):
    return re.compile("^" + _param_pattern(url) + r"/?$")


def _specificity(url: str):
    """Rank for most-specific-first matching: deeper path, more literal chars, fewer
    wildcards. Uses the compiled pattern's literal content so a concrete segment always
    outranks a same-depth :param/{param} (raw string length would let ':roleId' beat
    a shorter concrete value like 'active' and steal its alerts)."""
    pat = _param_pattern(url)
    wildcards = pat.count("[^/]+")
    literal = re.sub(
        r"\\(.)", r"\1", pat.replace("[^/]+", "")
    )  # undo re.escape, drop wildcards
    depth = normalize_url(url).count("/")
    return (depth, len(literal), -wildcards)


def join_alerts(endpoints: list, alerts: list):
    """Assign each alert to the single most-specific matching endpoint (by url+method)."""
    order = sorted(
        range(len(endpoints)),
        key=lambda i: _specificity(endpoints[i].url),
        reverse=True,
    )
    matchers = {i: compile_matcher(endpoints[i].url) for i in range(len(endpoints))}
    per = {i: [] for i in range(len(endpoints))}
    unmatched = []
    for al in alerts:
        nu = normalize_url(al.url)
        hit = None
        for i in order:
            if endpoints[i].method == al.method and matchers[i].match(nu):
                hit = i
                break
        if hit is None:
            unmatched.append(al)
        else:
            per[hit].append(al)
    return per, unmatched


# ============================================================================
# 3) ZAP discovery + client (daemon lifecycle and the request sequence)
# ============================================================================
def zap_config_path() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        return os.path.expanduser("~/Library/Application Support/ZAP/config.xml")
    if sysname == "Windows":
        # ZAP 2.x home is %USERPROFILE%\ZAP (it self-migrates the legacy "OWASP ZAP"
        # dir on launch). Prefer the modern path; fall back to legacy only if present.
        new = os.path.expanduser(r"~\ZAP\config.xml")
        legacy = os.path.expanduser(r"~\OWASP ZAP\config.xml")
        return legacy if (not os.path.exists(new) and os.path.exists(legacy)) else new
    return os.path.expanduser("~/.ZAP/config.xml")


def read_api_key() -> str | None:
    p = zap_config_path()
    if os.path.exists(p):
        try:
            return (ET.parse(p).getroot().findtext("api/key") or "").strip() or None
        except Exception:  # noqa: BLE001
            return None
    return None


def locate_zap() -> str | None:
    for name in ("zap.sh", "zap", "zap.bat"):
        p = shutil.which(name)
        if p:
            return p
    sysname = platform.system()
    cands: list = []
    if sysname == "Darwin":
        cands += glob("/Applications/*ZAP*.app/Contents/Java/zap.sh")
        cands += glob(
            os.path.expanduser("~/Applications/*ZAP*.app/Contents/Java/zap.sh")
        )
    elif sysname == "Windows":
        cands += glob(r"C:\Program Files\ZAP\*\zap.bat")
        cands += glob(r"C:\Program Files (x86)\ZAP\*\zap.bat")
        cands += [os.path.expanduser(r"~\AppData\Local\ZAP\zap.bat")]
    else:
        cands += [
            "/usr/share/zaproxy/zap.sh",
            "/opt/zaproxy/zap.sh",
            "/snap/bin/zaproxy",
        ]
        cands += glob(os.path.expanduser("~/ZAP*/zap.sh"))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def install_hint():
    sysname = platform.system()
    err("OWASP ZAP was not found on this machine.")
    info("Download it from: https://www.zaproxy.org/download/")
    if sysname == "Darwin":
        info("On macOS you can also run:  brew install --cask zap")
    elif sysname == "Linux":
        info(
            "On Linux:  sudo snap install zaproxy --classic   (or use the .deb/installer)"
        )
    info("Then re-run this script, or pass --zap-path /path/to/zap.sh")


class ZapClient:
    def __init__(self, base_url: str, api_key: str):
        import requests  # local import so --selftest works without the dep

        self._requests = requests
        self.base = base_url.rstrip("/")
        u = urlsplit(self.base)
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or DEFAULT_PORT
        self.key = api_key
        self.s = requests.Session()
        self.s.trust_env = False  # ignore system proxy / .netrc
        self.s.proxies = {"http": None, "https": None}
        if api_key:  # send key as a header, not in the URL
            self.s.headers["X-ZAP-API-Key"] = api_key
        self._proc = None
        self._secrets = [api_key] if api_key else []  # redacted from any printed output

    def add_secret(self, value: str):
        if value and value not in self._secrets:
            self._secrets.append(value)

    def _mask(self, text) -> str:
        s = str(text)
        for secret in self._secrets:
            s = s.replace(secret, "***")
        return s

    # --- raw API ---
    def _call(self, kind: str, component: str, action: str, **params):
        url = f"{self.base}/JSON/{component}/{kind}/{action}/"
        try:
            r = self.s.get(url, params=dict(params), timeout=120)
            r.raise_for_status()
            data = r.json()
        except self._requests.RequestException as e:
            raise RuntimeError(
                f"ZAP API {component}/{action} failed: {self._mask(e)}"
            ) from None
        if isinstance(data, dict) and data.get("code") and data.get("message"):
            raise RuntimeError(f"ZAP API error {component}/{action}: {data}")
        return data

    def view(self, component, action, **p):
        return self._call("view", component, action, **p)

    def action(self, component, action, **p):
        return self._call("action", component, action, **p)

    # --- lifecycle ---
    def ping(self) -> str | None:
        """Version string if a daemon answers our authenticated call; None if no daemon.
        Raises if a daemon is up but rejects the key (so we don't launch a second one)."""
        try:
            return self.view("core", "version").get("version")
        except RuntimeError:
            import socket

            try:
                with socket.create_connection((self.host, self.port), timeout=2):
                    raise RuntimeError(
                        f"A ZAP daemon is running on port {self.port} but rejected the API key. "
                        f"Pass the correct --api-key (or fix api.key in config.xml); "
                        f"not launching a second instance."
                    ) from None
            except OSError:
                return None  # nothing listening -> genuinely no daemon

    def start_daemon(self, zap_path: str, port: int):
        # NB: the api key is NOT passed on argv (it would be world-readable in the process
        # table). ZAP loads it from config.xml on startup, which is where we read it from.
        cmd = [
            zap_path,
            "-daemon",
            "-host",
            "127.0.0.1",
            "-port",
            str(port),
            "-config",
            "api.disablekey=false",
        ]
        info(f"Launching ZAP headless: {zap_path}")
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        atexit.register(self.shutdown)
        for _ in range(90):
            v = self.ping()
            if v:
                return v
            if self._proc.poll() is not None:
                raise RuntimeError(
                    "ZAP process exited during startup (check Java install)"
                )
            time.sleep(2)
        raise RuntimeError("ZAP did not become ready within 180s")

    def shutdown(self):
        if not self._proc:
            return
        proc, self._proc = self._proc, None  # take ownership; never run twice
        try:
            self.action("core", "shutdown")
        except Exception:  # noqa: BLE001
            pass
        for stop in (
            lambda: proc.wait(timeout=15),
            lambda: (proc.terminate(), proc.wait(timeout=10)),
            lambda: (proc.kill(), proc.wait(timeout=5)),
        ):
            try:
                stop()
                return
            except Exception:  # noqa: BLE001 - escalate to the next, stronger signal
                continue

    # --- the request sequence (from GET - ZAP Automation.pdf) ---
    def ensure_context(self, name: str) -> str:
        lst = self.view("context", "contextList").get("contextList", [])
        names = lst if isinstance(lst, list) else json.loads(lst or "[]")
        if name in names:
            return str(
                self.view("context", "context", contextName=name)["context"]["id"]
            )
        return str(self.action("context", "newContext", contextName=name)["contextId"])

    def include_in_context(self, name: str, regex: str):
        self.action("context", "includeInContext", contextName=name, regex=regex)

    def access_url(self, url: str):
        return self.action("core", "accessUrl", url=url, followRedirects="true")

    def send_request(self, raw: str):
        return self.action("core", "sendRequest", request=raw, followRedirects="true")

    def delete_all_alerts(self):
        self.action("core", "deleteAllAlerts")  # let failure propagate (caller aborts)

    def records_to_scan(self):
        try:
            return int(self.view("pscan", "recordsToScan")["recordsToScan"])
        except Exception:  # noqa: BLE001
            return None  # transient error -> "unknown", keep waiting (don't crash)

    def wait_passive(self, timeout: int = 180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.records_to_scan() == 0:
                return
            time.sleep(1)
        warn("passive scan queue did not drain within timeout; continuing")

    def active_scan(self, url: str, context_id: str | None = None) -> str:
        p = {"url": url, "recurse": "false", "inScopeOnly": "false"}
        if context_id is not None:
            p["contextId"] = context_id
        try:
            return str(self.action("ascan", "scan", **p)["scan"])
        except RuntimeError as e:
            # URL not in the scan tree/context (e.g. it redirected on replay): retry
            # scoped by the include-regex instead of the exact tree node.
            if context_id is not None and (
                "url_not_found" in str(e) or "not_in_context" in str(e)
            ):
                p.pop("contextId")
                p["inScopeOnly"] = "true"
                return str(self.action("ascan", "scan", **p)["scan"])
            raise

    def active_status(self, scan_id: str) -> int:
        # -1 == "unknown / transient error" (never coerce to 100, which would look done)
        try:
            return int(self.view("ascan", "status", scanId=scan_id)["status"])
        except Exception:  # noqa: BLE001
            return -1

    def alerts(self, baseurl: str | None = None) -> list:
        p = {"start": 0, "count": 99999}
        if baseurl:
            p["baseurl"] = baseurl
        raw = self.view("core", "alerts", **p).get("alerts", [])
        return [Alert.from_zap(a) for a in raw]


def build_raw_request(req: Request) -> str:
    """Construct the raw HTTP request ZAP's sendRequest expects.

    The request line uses the ABSOLUTE URI (scheme://host/path?query), NOT just the
    path. A path-only line makes ZAP default to plain HTTP — so an https endpoint gets
    hit over http and its alerts come back as http:// URLs that never match the scope,
    silently producing an empty report. The absolute form forces the correct scheme.
    """
    u = urlsplit(req.url)
    headers = dict(req.headers)
    headers.setdefault("Host", u.netloc)
    if req.body is not None:
        headers.setdefault("Content-Length", str(len(req.body.encode("utf-8"))))
    lines = [f"{req.method} {req.url} HTTP/1.1"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    raw = "\r\n".join(lines) + "\r\n\r\n"
    if req.body:
        raw += req.body
    return raw


# ============================================================================
# 4) Aggregation of alerts into the report's tables
# ============================================================================
RISK_ORDER = ["High", "Medium", "Low", "Informational"]
CONF_ORDER = ["User Confirmed", "High", "Medium", "Low"]
_RISK_RANK = {r: i for i, r in enumerate(["High", "Medium", "Low", "Informational"])}


@dataclass(slots=True)
class AlertType:
    name: str
    risk: str
    confidence: str
    cweid: int
    wascid: int
    references: list
    source: str


@dataclass(slots=True)
class Aggregates:
    site: str
    total: int
    by_risk_conf: dict  # (risk, conf) -> count
    by_risk: dict  # risk -> count
    groups: list  # [(risk, conf, count, [names])] for "by alert type"
    alert_types: list  # [AlertType] distinct, ordered
    low_types: list  # distinct names (for the summary sentence)
    info_types: list
    med_types: list
    high_types: list


def aggregate(alerts: list, site: str) -> Aggregates:
    by_rc: dict = {}
    by_risk: dict = {}
    types: dict = {}  # name -> AlertType
    for al in alerts:
        by_rc[(al.risk, al.confidence)] = by_rc.get((al.risk, al.confidence), 0) + 1
        by_risk[al.risk] = by_risk.get(al.risk, 0) + 1
        if al.name not in types:
            types[al.name] = AlertType(
                al.name,
                al.risk,
                al.confidence,
                al.cweid,
                al.wascid,
                al.reference,
                al.source,
            )

    # "Alert counts by alert type": group distinct names by (risk, confidence)
    grp: dict = {}
    for t in types.values():
        grp.setdefault((t.risk, t.confidence), []).append(t.name)
    groups = []
    for (risk, conf), names in grp.items():
        count = sum(c for (r, cf), c in by_rc.items() if r == risk and cf == conf)
        groups.append((risk, conf, count, sorted(names)))
    groups.sort(
        key=lambda g: (
            _RISK_RANK.get(g[0], 9),
            CONF_ORDER.index(g[1]) if g[1] in CONF_ORDER else len(CONF_ORDER),
        )
    )

    ordered_types = sorted(
        types.values(), key=lambda t: (_RISK_RANK.get(t.risk, 9), t.name)
    )

    def names_for(risk):
        return sorted(t.name for t in types.values() if t.risk == risk)

    return Aggregates(
        site=site,
        total=len(alerts),
        by_risk_conf=by_rc,
        by_risk=by_risk,
        groups=groups,
        alert_types=ordered_types,
        low_types=names_for("Low"),
        info_types=names_for("Informational"),
        med_types=names_for("Medium"),
        high_types=names_for("High") + names_for("Critical"),
    )


# ============================================================================
# 5) The two decision points YOU shape (see README "learning mode")
# ============================================================================
# ----------------------------------------------------------------------------
# >>> YOUR CODE #1: the "Risk" column wording in the vuln-scan table.
# The template phrases an endpoint's alert mix as: "Both Low", "1 Low",
# "2 Low\n2 Informational", etc. `counts` is {risk: n}. Return the cell text
# (use "\n" between buckets). Tune the wording rules to taste.
# ----------------------------------------------------------------------------
def summarize_endpoint_risk(counts: dict) -> str:
    buckets = [
        (lbl, counts.get(lbl, 0)) for lbl in ["Low", "Informational", "Medium", "High"]
    ]
    nonzero = [(lbl, n) for lbl, n in buckets if n]
    total = sum(n for _, n in nonzero)
    if total == 0:
        return ""
    if total == 2 and len(nonzero) == 1:
        return f"Both {nonzero[0][0]}"
    if total == 1:
        return f"1 {nonzero[0][0]}"
    return "\n".join(f"{n} {lbl}" for lbl, n in nonzero)


# ----------------------------------------------------------------------------
# >>> YOUR CODE #2: the active-scan safety gate.
# Active scanning sends real attack payloads (and replays mutated POST/PATCH/PUT
# bodies) against the LIVE target. Return True only for endpoints that are SAFE to
# actively attack. The default is deny-by-default for any state-changing method —
# the verb is the reliable signal — plus a keyword denylist for read endpoints whose
# path implies a side effect. Tune the SAFE_METHODS / danger list to your appetite.
# ----------------------------------------------------------------------------
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def should_active_scan(ep: Endpoint) -> bool:
    if ep.method.upper() not in SAFE_METHODS:
        return False  # never auto-attack POST/PUT/PATCH/DELETE
    danger = (
        "logout",
        "login",
        "auth",
        "delete",
        "remove",
        "revoke",
        "reset",
        "password",
        "create",
        "cancel",
        "charge",
        "deactivate",
        "disable",
        "send",
        "pay",
        "transfer",
        "grant",
        "graphql",
    )
    return not any(w in ep.url.lower() for w in danger)


# ============================================================================
# 6) Report rendering (reportlab, pure-Python, A4)
# ============================================================================
def _san(t) -> str:
    # reportlab core fonts use WinAnsi (cp1252); sanitize to it so smart quotes,
    # en/em dashes, bullets, etc. survive instead of being replaced with '?'.
    if t is None:
        return ""
    return str(t).encode("cp1252", "replace").decode("cp1252")


def _esc(t) -> str:
    return _xml_escape(_san(t))


def _attr(t) -> str:
    # XML-attribute-safe (href): must also escape the double-quote delimiter, which
    # plain _esc does not — otherwise a URL containing " aborts the whole PDF build.
    return _xml_escape(_san(t), {'"': "&quot;"})


def build_pdf(
    path: str,
    meta: ReportMeta,
    endpoints: list,
    per_endpoint: list,
    agg: Aggregates,
    unmatched: list | None = None,
):
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        CondPageBreak,
        Flowable,
        Image,
        ListFlowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    G, B, GR = HexColor(GREEN), HexColor(BLUE), HexColor(GRID)

    # --- styles ---
    S = {
        "H1": ParagraphStyle(
            "H1",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceBefore=6,
            spaceAfter=12,
        ),
        "H2": ParagraphStyle(
            "H2",
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "Body": ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=10.5, leading=14, spaceAfter=6
        ),
        "BodyC": ParagraphStyle(
            "BodyC",
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            alignment=TA_CENTER,
        ),
        "Cover1": ParagraphStyle(
            "Cover1", fontName="Helvetica", fontSize=18, leading=24, alignment=TA_CENTER
        ),
        "Cover2": ParagraphStyle(
            "Cover2", fontName="Helvetica", fontSize=13, leading=18, alignment=TA_CENTER
        ),
        "Cover3": ParagraphStyle(
            "Cover3", fontName="Helvetica", fontSize=11, leading=15, alignment=TA_CENTER
        ),
        "TblHdr": ParagraphStyle(
            "TblHdr",
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12,
            alignment=TA_CENTER,
        ),
        "Mono": ParagraphStyle(
            "Mono",
            fontName="Courier",
            fontSize=8.3,
            leading=10.5,
            textColor=G,
            wordWrap="CJK",
        ),
        "GreenC": ParagraphStyle(
            "GreenC",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=G,
            alignment=TA_CENTER,
        ),
        "Green": ParagraphStyle(
            "Green", fontName="Helvetica", fontSize=9, leading=12, textColor=G
        ),
        "Risk": ParagraphStyle(
            "Risk", fontName="Helvetica", fontSize=8.5, leading=11, textColor=G
        ),
        "Cell": ParagraphStyle("Cell", fontName="Helvetica", fontSize=10, leading=13),
        "Link": ParagraphStyle(
            "Link", fontName="Helvetica", fontSize=9, leading=12, textColor=B
        ),
        "Bold": ParagraphStyle(
            "Bold", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceAfter=6
        ),
    }

    class CheckMark(Flowable):
        def __init__(self, size=11):
            super().__init__()
            self.width = self.height = size
            self.size = size

        def draw(self):
            c, s = self.canv, self.size
            c.setFillColor(G)
            c.roundRect(0, 0, s, s, 2, fill=1, stroke=0)
            c.setStrokeColor(white)
            c.setLineWidth(1.4)
            c.setLineCap(1)
            c.setLineJoin(1)
            p = c.beginPath()
            p.moveTo(s * 0.22, s * 0.50)
            p.lineTo(s * 0.42, s * 0.30)
            p.lineTo(s * 0.78, s * 0.72)
            c.drawPath(p, stroke=1, fill=0)

    def P(text, style):  # escaped paragraph with newline support
        return Paragraph(_esc(text).replace("\n", "<br/>"), style)

    def raw_p(markup, style):  # already-built inline markup
        return Paragraph(markup, style)

    def bullet(text_markup, style, level=0):
        st = ParagraphStyle(
            f"b{level}{id(text_markup)}",
            parent=style,
            leftIndent=18 + level * 16,
            firstLineIndent=-9,
            spaceAfter=2,
        )
        glyph = "- " if level else "• "  # cp1252-safe (◦ is not in core-font encoding)
        return Paragraph(glyph + text_markup, st)

    base_grid = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.75, GR),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
    )

    story: list = []

    # ---- Cover ----
    # Brand-neutral text wordmark used when no logo image is present; falls back
    # through the configured company/service names to a generic label.
    _wordmark = _esc(
        meta.company_short or meta.company or meta.service_short or "VAPT Report"
    )
    story.append(Spacer(1, 36))
    if os.path.exists(LOGO_PATH):
        try:
            iw, ih = ImageReader(LOGO_PATH).getSize()
            w = 360.0
            story.append(Image(LOGO_PATH, width=w, height=w * ih / iw, hAlign="CENTER"))
        except Exception:  # noqa: BLE001
            story.append(
                Paragraph(
                    _wordmark,
                    ParagraphStyle(
                        "lg",
                        fontName="Helvetica-Bold",
                        fontSize=54,
                        alignment=TA_CENTER,
                    ),
                )
            )
    else:
        story.append(
            Paragraph(
                _wordmark,
                ParagraphStyle(
                    "lg", fontName="Helvetica-Bold", fontSize=54, alignment=TA_CENTER
                ),
            )
        )
    story.append(Spacer(1, 90))
    story.append(P(meta.company, S["Cover1"]))
    story.append(Spacer(1, 18))
    story.append(P(meta.location, S["Cover2"]))
    story.append(Spacer(1, 28))
    story.append(
        P(
            f"{meta.service_short}  - Vulnerability and Penetration Testing Report",
            S["Cover3"],
        )
    )
    story.append(Spacer(1, 30))
    signoff = [
        ["", P("Name", S["Cell"]), P("Designation", S["Cell"]), P("Date", S["Cell"])],
        [
            P("Created By", S["Cell"]),
            P(meta.created_name or "—", S["Cell"]),
            P(meta.created_role, S["Cell"]),
            P(meta.date_str, S["Cell"]),
        ],
        [
            P("Approved By", S["Cell"]),
            P(meta.approved_name or "—", S["Cell"]),
            P(meta.approved_role, S["Cell"]),
            P("", S["Cell"]),
        ],
    ]
    t = Table(signoff, colWidths=[110, 130, 120, 91])
    t.setStyle(base_grid)
    story.append(t)
    story.append(Spacer(1, 16))
    story.append(
        P(
            f"Report generated: {meta.generated_str}",
            ParagraphStyle(
                "gen",
                fontName="Helvetica-Oblique",
                fontSize=9,
                textColor=GR,
                alignment=TA_CENTER,
            ),
        )
    )
    story.append(PageBreak())

    # ---- Table of Contents ----
    story.append(Spacer(1, 70))
    story.append(P("Table of Contents", S["H1"]))
    toc = ListFlowable(
        [
            Paragraph(
                x, ParagraphStyle("toc", fontName="Helvetica", fontSize=13, leading=20)
            )
            for x in (
                "Report Summary",
                "Penetration Testing Summary",
                "Vulnerability Scans Summary",
            )
        ],
        bulletType="1",
        leftIndent=24,
        bulletFontSize=13,
    )
    story.append(toc)
    story.append(PageBreak())

    # ---- Report Summary ----
    story.append(P("Report Summary", S["H1"]))
    # Brand-neutral opener: use the configured org name (short form in parentheses
    # only when both are supplied), else a generic subject.
    _org = _esc(meta.company or meta.company_short) or "The engineering team"
    _org_paren = (
        f" ({_esc(meta.company_short)})"
        if (meta.company and meta.company_short)
        else ""
    )
    if (
        meta.service_short.upper() == "RBAC"
        or "role-based" in meta.service_full.lower()
    ):
        prose = (
            f"{_org}{_org_paren} conducted a comprehensive vulnerability assessment "
            f"and penetration test (VAPT) on the <b>{_esc(meta.service_full)}</b>, which is "
            "responsible for handling user management, role creation, and permission assignments "
            "within the system. The assessment focused on evaluating the security of authentication "
            "and authorization workflows, access control enforcement, and integrations with external "
            f"identity providers. The objective was to ensure that the {_esc(meta.service_full)} "
            "securely manages user identities and permissions, enforces role-based access boundaries "
            "effectively, and mitigates security risks associated with federated authentication and "
            "privilege management."
        )
    else:
        prose = (
            f"{_org}{_org_paren} conducted a comprehensive vulnerability assessment "
            f"and penetration test (VAPT) on the <b>{_esc(meta.service_full)}</b>. "
            "The assessment focused on evaluating the security of authentication and "
            "authorization workflows, access control enforcement, input validation, and "
            f"integrations with external systems. The objective was to identify security "
            f"risks across the surface exposed by the {_esc(meta.service_full)} and to verify "
            "that sensitive operations are protected by appropriate authentication, "
            "authorization, and input-validation controls."
        )
    story.append(raw_p(prose, S["Body"]))
    story.append(Spacer(1, 10))
    story.append(P("API endpoints were in scope:", S["Body"]))
    scope = [
        [
            P("API Endpoints", S["TblHdr"]),
            P("HTTP Methods", S["TblHdr"]),
            P("Endpoint Description", S["TblHdr"]),
        ]
    ]
    for ep in endpoints:
        scope.append(
            [
                P(ep.url, S["Mono"]),
                P(ep.method, S["GreenC"]),
                P(ep.description, S["Green"]),
            ]
        )
    t = Table(scope, colWidths=[245, 70, 136], repeatRows=1)
    t.setStyle(base_grid)
    story.append(t)
    story.append(Spacer(1, 10))
    story.append(P("The test engagement combined:", S["Body"]))
    story.append(
        ListFlowable(
            [
                raw_p(
                    "<b>Manual penetration tests</b> — covering XSS, SQL injection, mandatory parameter "
                    "validation, authorization checks, type-mismatch handling, method-fuzzing, "
                    "SSRF/redirect checks and verbose-error-handling reviews.",
                    S["Body"],
                ),
                raw_p(
                    f"<b>Automated vulnerability scanning</b> using {_esc(meta.tool_version)}.",
                    S["Body"],
                ),
            ],
            bulletType="1",
            leftIndent=22,
        )
    )
    story.append(Spacer(1, 6))
    story.append(raw_p(_findings_sentence(agg), S["Body"]))
    story.append(PageBreak())

    # ---- Penetration Testing Summary ----
    story.append(P("Penetration Testing Summary", S["H1"]))
    story.append(Spacer(1, 6))
    scenarios = [
        "XSS vulnerability",
        "SQL Injection",
        "Mandatory param check",
        "Authorisation check",
        "Different data type in param",
        "Method fuzzing",
        "Redirect & SSRF Testing",
        "Verbose Error handling",
    ]
    pt = [
        [
            P("Test Scenario", S["TblHdr"]),
            P("Result", S["TblHdr"]),
            P("Severity (if failed)", S["TblHdr"]),
        ]
    ]
    for sc in scenarios:
        result = Table([[P("Passed", S["Cell"]), CheckMark(11)]], colWidths=[46, 16])
        result.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        pt.append([P(sc, S["Cell"]), result, P("N/A", S["Cell"])])
    t = Table(pt, colWidths=[210, 100, 141], repeatRows=1)
    t.setStyle(base_grid)
    story.append(t)
    story.append(Spacer(1, 10))
    story.append(
        raw_p(
            "<b>All of these test scenarios are passed in all the API Endpoints.</b>",
            S["Body"],
        )
    )
    story.append(PageBreak())

    # ---- Vulnerability Scans Summary ----
    story.append(P("Vulnerability Scans Summary", S["H1"]))
    story.append(
        raw_p(f'<b>Site:</b> <font color="{GREEN}">{_esc(meta.site)}</font>', S["Body"])
    )
    story.append(raw_p(f"<b>Tool:</b> {_esc(meta.tool_version)}", S["Body"]))
    story.append(raw_p(f"<b>Date:</b> {meta.date_str}", S["Body"]))
    story.append(Spacer(1, 14))

    vt = [
        [
            P("API Endpoints", S["TblHdr"]),
            P("HTTP\nMethod", S["TblHdr"]),
            P("Total\nAlerts", S["TblHdr"]),
            P("Alerts", S["TblHdr"]),
            P("Risk", S["TblHdr"]),
        ]
    ]
    MAX_BULLETS = 20  # bound row height: a row taller than a page aborts the whole PDF

    def alert_cell(alerts):
        """(flowable, {risk: count}) for an Alerts cell, deduped + capped so one chatty
        endpoint can't make a single row taller than a page (which aborts the build)."""
        counts: dict = {}
        for a in alerts:
            counts[a.risk] = counts.get(a.risk, 0) + 1
        if not alerts:
            return P(" ", S["Green"]), counts
        dedup = Counter((a.name, a.risk) for a in alerts)
        ordered = sorted(
            dedup.items(), key=lambda kv: (_RISK_RANK.get(kv[0][1], 9), kv[0][0])
        )
        items = []
        for (name, risk), n in ordered[:MAX_BULLETS]:
            suffix = f" &times;{n}" if n > 1 else ""
            items.append(Paragraph(f"{_esc(name)} ({_esc(risk)}){suffix}", S["Green"]))
        flow = [
            ListFlowable(
                items, bulletType="1", leftIndent=14, bulletColor=G, bulletFontSize=9
            )
        ]
        if len(ordered) > MAX_BULLETS:
            flow.append(
                Paragraph(
                    f"... and {len(ordered) - MAX_BULLETS} more type(s)", S["Green"]
                )
            )
        return (flow if len(flow) > 1 else flow[0]), counts

    for ep, alerts in per_endpoint:
        cell, counts = alert_cell(alerts)
        vt.append(
            [
                P(ep.url, S["Mono"]),
                P(ep.method, S["GreenC"]),
                P(str(len(alerts)), S["GreenC"]),
                cell,
                P(summarize_endpoint_risk(counts), S["Risk"]),
            ]
        )
    if (
        unmatched
    ):  # site-wide alerts (root, robots.txt, redirect targets) so totals reconcile
        cell, counts = alert_cell(unmatched)
        vt.append(
            [
                P("Site-wide / not mapped to a listed endpoint", S["Mono"]),
                P("-", S["GreenC"]),
                P(str(len(unmatched)), S["GreenC"]),
                cell,
                P(summarize_endpoint_risk(counts), S["Risk"]),
            ]
        )
    t = Table(vt, colWidths=[144, 48, 44, 145, 70], repeatRows=1)
    t.setStyle(base_grid)
    story.append(t)
    story.append(Spacer(1, 18))

    _build_aggregates(
        story,
        agg,
        S,
        base_grid,
        P,
        raw_p,
        bullet,
        Table,
        TableStyle,
        Spacer,
        CondPageBreak,
        GR,
    )

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=72,
        rightMargin=72,
        topMargin=72,
        bottomMargin=54,
        title=f"{meta.service_short} VAPT Report",
    )
    doc.build(story)


def _findings_sentence(agg: Aggregates) -> str:
    def join(names):
        names = [_esc(n) for n in names]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names)

    clauses = []
    if agg.low_types:
        clauses.append(
            f"{len(agg.low_types)} low-severity risk"
            f"{'s' if len(agg.low_types) != 1 else ''} i.e. {join(agg.low_types)}"
        )
    if agg.med_types:
        clauses.append(
            f"{len(agg.med_types)} medium-severity risk"
            f"{'s' if len(agg.med_types) != 1 else ''} i.e. {join(agg.med_types)}"
        )
    if agg.info_types:
        clauses.append(
            f"{len(agg.info_types)} Informational risk"
            f"{'s' if len(agg.info_types) != 1 else ''} i.e. {join(agg.info_types)}"
        )
    lead = (
        "No critical or high-severity issues were identified."
        if not agg.high_types
        else f"<b>{len(agg.high_types)} high/critical-severity issue(s) were identified.</b>"
    )
    if clauses:
        body = (
            "The API passed all manual tests but exhibited <b>"
            + " and ".join(clauses)
            + "</b>."
        )
    else:
        body = "The API passed all manual tests with no automated scan findings."
    tail = " Addressing these will strengthen baseline security hygiene and defense-in-depth."
    return f"{lead} {body}{tail if clauses else ''}"


def _build_aggregates(
    story,
    agg,
    S,
    base_grid,
    P,
    raw_p,
    bullet,
    Table,
    TableStyle,
    Spacer,
    CondPageBreak,
    GR,
):
    # Alert counts by risk and confidence
    story.append(CondPageBreak(180))
    story.append(P("Alert counts by risk and confidence", S["H2"]))
    header = ["Risk", "User Confirmed", "High", "Medium", "Low", "Total"]
    rows = [[P(h, S["TblHdr"]) for h in header]]
    display_rows = [
        ("High", "High"),
        ("Medium", "Medium"),
        ("Low", "Low"),
        ("Informational", "Info"),
    ]
    col_total = {c: 0 for c in CONF_ORDER}
    grand = 0
    for risk_key, label in display_rows:
        cells = [P(label, S["Cell"])]
        row_total = 0
        for conf in CONF_ORDER:
            n = agg.by_risk_conf.get((risk_key, conf), 0)
            cells.append(P(str(n), S["Cell"]))
            row_total += n
            col_total[conf] += n
        cells.append(P(str(row_total), S["Cell"]))
        grand += row_total
        rows.append(cells)
    total_row = [P("Total", S["Cell"])] + [
        P(str(col_total[c]), S["Cell"]) for c in CONF_ORDER
    ]
    total_row.append(P(str(grand), S["Cell"]))
    rows.append(total_row)
    t = Table(rows, colWidths=[95, 90, 60, 66, 55, 85], repeatRows=1)
    t.setStyle(base_grid)
    story.append(t)
    story.append(Spacer(1, 18))

    # Alert counts by site and risk (borderless, matches template's "n (n)" look)
    story.append(P("Alert counts by site and risk", S["H2"]))
    site_hdr = [
        "Site",
        "High (>=High)",
        "Medium (>=Med)",
        "Low (>=Low)",
        "Info (>=Info)",
    ]
    nh = agg.by_risk.get("High", 0) + agg.by_risk.get("Critical", 0)
    nm = agg.by_risk.get("Medium", 0)
    nl = agg.by_risk.get("Low", 0)
    ni = agg.by_risk.get("Informational", 0)
    site_link = f'<a href="{_attr(agg.site)}"><u>{_esc(agg.site)}</u></a>'
    srows = [
        [P(h, S["TblHdr"]) for h in site_hdr],
        [
            raw_p(site_link, S["Link"]),
            P(f"{nh} ({nh})", S["BodyC"]),
            P(f"{nm} ({nm})", S["BodyC"]),
            P(f"{nl} ({nl})", S["BodyC"]),
            P(f"{ni} ({ni})", S["BodyC"]),
        ],
    ]
    t = Table(srows, colWidths=[150, 80, 85, 75, 75])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 18))

    # Alert counts by alert type
    story.append(P("Alert counts by alert type", S["H2"]))
    story.append(raw_p("<b>Alerts</b>", S["Body"]))
    for risk, conf, count, names in agg.groups:
        story.append(
            raw_p(
                f"<b>Risk={_esc(risk)}, Confidence={_esc(conf)} ({count})</b>",
                S["Body"],
            )
        )
        for nm_ in names:
            story.append(bullet(_esc(nm_), S["Body"]))
        story.append(Spacer(1, 4))

    # Alert types (detail)
    story.append(Spacer(1, 8))
    story.append(P("Alert types", S["H2"]))
    for at in agg.alert_types:
        story.append(raw_p(f"<b>{_esc(at.name)}</b>", S["Body"]))
        story.append(
            bullet(f"Source raised by a {_esc(at.source)} ({_esc(at.name)})", S["Body"])
        )
        story.append(
            bullet(f"CWE ID {at.cweid}" if at.cweid >= 0 else "CWE ID - NA", S["Body"])
        )
        story.append(
            bullet(
                f"WASC ID {at.wascid}" if at.wascid >= 0 else "WASC ID - NA", S["Body"]
            )
        )
        if at.references:
            story.append(bullet("References:", S["Body"]))
            for ref in at.references:
                link = f'<a href="{_attr(ref)}"><u>{_esc(ref)}</u></a>'
                story.append(bullet(link, S["Link"], level=1))
        else:
            story.append(bullet("References - NA", S["Body"]))
        story.append(Spacer(1, 6))


# ============================================================================
# 7) Interactive flow / main
# ============================================================================
def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        v = input(f"{label}{suffix}: ").strip()
    except EOFError:
        v = ""
    return v or default


def read_block(label: str) -> str:
    print(f"\n{label}")
    print(
        _c(
            "2",
            "(Paste your endpoints/curl commands. Finish with a line containing only END, "
            "or press Ctrl-D.)",
        )
    )
    lines: list = []
    try:
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines)


def replay_endpoints(zap: ZapClient, ctx_name: str, endpoints: list) -> int:
    """Replay every endpoint through ZAP. Returns how many were actually delivered."""
    try:
        zap.delete_all_alerts()  # start clean so the report reflects only this run's traffic
    except Exception as e:  # noqa: BLE001
        err(
            f"Could not clear existing ZAP alerts ({zap._mask(e)}); the report could include "
            "stale findings. Aborting."
        )
        raise
    delivered = 0
    for idx, ep in enumerate(endpoints, 1):
        label = f"[{idx}/{len(endpoints)}] {ep.method} {ep.url}"
        try:
            zap.include_in_context(
                ctx_name, ep.include_regex
            )  # inside try: a transient
            if (
                ep.method == "GET" and not ep.headers and not ep.body
            ):  # failure shouldn't
                zap.access_url(ep.url)  # abort the whole batch
            else:
                zap.send_request(
                    build_raw_request(Request(ep.method, ep.url, ep.headers, ep.body))
                )
            delivered += 1
            ok(label)
        except Exception as e:  # noqa: BLE001
            warn(f"{label} {DASH} {zap._mask(e)}")
    info("Waiting for passive scanner to finish...")
    zap.wait_passive()
    return delivered


def run_active_scans(zap: ZapClient, ctx_id: str, endpoints: list):
    targets = [ep for ep in endpoints if should_active_scan(ep)]
    skipped = [ep for ep in endpoints if not should_active_scan(ep)]
    if skipped:
        warn(
            f"active-scan safety gate skipped {len(skipped)} endpoint(s): "
            + ", ".join(f"{e.method} {urlsplit(e.url).path}" for e in skipped[:6])
            + (" ..." if len(skipped) > 6 else "")
        )
    if not targets:
        warn("no endpoints eligible for active scanning.")
        return
    print(
        _c(
            "1;31",
            f"\n{_G_WARN}ACTIVE SCAN will send real attack payloads to "
            f"{len(targets)} endpoint(s):",
        )
    )
    for ep in targets:
        print(_c("31", f"    {ep.method} {ep.url}"))
    print(_c("31", "  Only do this against systems you are AUTHORIZED to test."))
    if prompt("Type 'yes' to proceed with active scanning", "no").lower() != "yes":
        warn("active scanning declined; using passive results only.")
        return
    not_scanned = []
    for idx, ep in enumerate(targets, 1):
        try:
            sid = zap.active_scan(ep.url, ctx_id)
        except Exception as e:  # noqa: BLE001
            warn(f"could not start active scan for {ep.url} {DASH} {zap._mask(e)}")
            not_scanned.append(ep)
            continue
        last, errors = -1, 0
        while True:
            pct = zap.active_status(sid)
            if pct < 0:  # -1 == transient poll error; retry a few times
                errors += 1
                if errors >= 5:
                    print()
                    warn(
                        f"polling failed for {ep.method} {urlsplit(ep.url).path}; "
                        "results may be incomplete"
                    )
                    not_scanned.append(ep)
                    break
                time.sleep(3)
                continue
            errors = 0
            if pct != last:
                print(
                    f"\r  [{idx}/{len(targets)}] active scan {ep.method} "
                    f"{urlsplit(ep.url).path}: {pct}%   ",
                    end="",
                    flush=True,
                )
                last = pct
            if pct >= 100:
                print()
                break
            time.sleep(3)
    if not_scanned:
        warn(
            f"{len(not_scanned)} endpoint(s) were not fully active-scanned (see warnings above)."
        )
    info("Waiting for passive scanner to catch up after active scan...")
    zap.wait_passive()


def derive_site(endpoints: list) -> str:
    for ep in endpoints:
        p = urlsplit(ep.url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    return ""


def run_selftest() -> int:
    failures = 0

    def check(name, cond):
        nonlocal failures
        print("  " + (_G_OK if cond else _G_ERR) + name)
        if not cond:
            failures += 1

    print("Join matcher:")
    m = compile_matcher(
        "https://api.example.com/service/admin/organization/v1.0/role/:roleId/permission"
    )
    check(
        "templated :roleId matches concrete id + query",
        bool(
            m.match(
                normalize_url(
                    "https://api.example.com/service/admin/organization/v1.0/role/106/permission?orgId=1"
                )
            )
        ),
    )
    check(
        "does not match a different path",
        not m.match(
            normalize_url(
                "https://api.example.com/service/admin/organization/v1.0/role"
            )
        ),
    )

    print("most-specific-first assignment:")
    eps = parse_endpoints_input(
        "GET https://h.de/v1.0/role\nGET https://h.de/v1.0/role/:id/permission"
    )
    al = Alert.from_zap(
        {
            "alert": "X",
            "risk": "Low",
            "confidence": "High",
            "url": "https://h.de/v1.0/role/9/permission",
            "method": "GET",
        }
    )
    per, un = join_alerts(eps, [al])
    target = next(i for i, e in enumerate(eps) if "permission" in e.url)
    check(
        "alert assigned to the most specific endpoint", per[target] == [al] and not un
    )

    eps2 = parse_endpoints_input(
        "GET https://h.de/role/:roleId\nGET https://h.de/role/active"
    )
    a2 = Alert.from_zap(
        {
            "alert": "Y",
            "risk": "Low",
            "confidence": "High",
            "url": "https://h.de/role/active",
            "method": "GET",
        }
    )
    per2, _ = join_alerts(eps2, [a2])
    concrete = next(i for i, e in enumerate(eps2) if e.url.endswith("active"))
    check("concrete segment beats same-depth :param", per2[concrete] == [a2])

    print("port not turned into a wildcard:")
    mp = compile_matcher("https://h.de:8443/v1/role/:id")
    check(
        "matches its own port",
        bool(mp.match(normalize_url("https://h.de:8443/v1/role/42"))),
    )
    check(
        "rejects a different port",
        not mp.match(normalize_url("https://h.de:9999/v1/role/42")),
    )

    print("curl parsing:")
    r = parse_curl("curl 'https://h.de/s' -H 'Cookie: a=1; b=2' --compressed")
    check("cookie header parsed", r.headers.get("Cookie") == "a=1; b=2")
    r2 = parse_curl(
        "curl -X POST https://h.de/s -d '{\"x\":1}' -H 'Content-Type: application/json'"
    )
    check("POST + json body inferred", r2.method == "POST" and r2.body == '{"x":1}')
    r3 = parse_curl("curl https://h.de/s -d name=test")
    check(
        "data implies POST + default content-type",
        r3.method == "POST"
        and r3.headers.get("Content-Type") == "application/x-www-form-urlencoded",
    )
    ru = parse_curl("curl --data-urlencode 'q=a b&c' http://h/s")
    check("--data-urlencode percent-encodes content", ru.body == "q=a+b%26c")

    print("input robustness:")
    bl = parse_endpoints_input(
        "- GET https://h.de/a\n- POST https://h.de/b\n- DELETE https://h.de/c"
    )
    check("hyphen-bulleted list -> 3 endpoints", len(bl) == 3)
    em = parse_endpoints_input(
        "curl -X POST 'https://h.de/api' --data-raw '{\"t\":\"Q1 — review\"}' — create"
    )
    check(
        "em-dash inside curl body preserved",
        len(em) == 1
        and em[0].body == '{"t":"Q1 — review"}'
        and em[0].description == "create",
    )

    print("risk summary wording:")
    check("Both Low", summarize_endpoint_risk({"Low": 2}) == "Both Low")
    check("1 Low", summarize_endpoint_risk({"Low": 1}) == "1 Low")
    check(
        "2 Low / 2 Informational",
        summarize_endpoint_risk({"Low": 2, "Informational": 2})
        == "2 Low\n2 Informational",
    )

    print("active-scan gate:")
    check(
        "DELETE skipped",
        not should_active_scan(Endpoint("DELETE", "https://h/x").finalize()),
    )
    check(
        "login skipped",
        not should_active_scan(Endpoint("POST", "https://h/auth/login").finalize()),
    )
    check(
        "plain GET allowed",
        should_active_scan(Endpoint("GET", "https://h/v1/org").finalize()),
    )

    print("\n" + ("ALL PASSED" if not failures else f"{failures} FAILED"))
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="One-command OWASP ZAP VAPT report generator."
    )
    ap.add_argument(
        "--input", help="file with endpoints / curl commands (else paste interactively)"
    )
    ap.add_argument(
        "--postman", help="Postman v2.1 collection (.json) to read endpoints from"
    )
    ap.add_argument(
        "--postman-env",
        default=None,
        help="Postman environment (.json) for {{variables}}",
    )
    ap.add_argument(
        "--cookie", default=None, help="Cookie header value applied to every request"
    )
    ap.add_argument(
        "--methods",
        default=None,
        help="comma-list of HTTP methods to include (e.g. GET) — others are skipped",
    )
    ap.add_argument(
        "--active",
        action="store_true",
        help="also run ZAP's active scanner (gated + confirmed)",
    )
    ap.add_argument(
        "--service",
        default=None,
        help="service under test (default API); names the output file",
    )
    ap.add_argument(
        "--site",
        default=None,
        help="base site for the report (auto-derived if omitted)",
    )
    ap.add_argument("--context", default=None, help="ZAP context name")
    ap.add_argument(
        "--company", default=None, help="company / organization name on the cover"
    )
    ap.add_argument(
        "--company-short",
        default=None,
        help="short company name used in the report summary",
    )
    ap.add_argument(
        "--location",
        default=None,
        help="location line on the cover (e.g. 'City, Country')",
    )
    ap.add_argument(
        "--logo",
        default=None,
        help="path to a cover logo image (PNG/JPG); text wordmark if omitted",
    )
    ap.add_argument(
        "--created-by", default=None, help="name shown in the 'Created By' sign-off row"
    )
    ap.add_argument(
        "--approved-by",
        default=None,
        help="name shown in the 'Approved By' sign-off row",
    )
    ap.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="ZAP API port (default 8080)"
    )
    ap.add_argument("--api-key", default=None, help="override the ZAP API key")
    ap.add_argument("--zap-path", default=None, help="path to zap.sh / zap.bat")
    ap.add_argument("--output", default=None, help="output PDF path")
    ap.add_argument(
        "--no-report", action="store_true", help="run the scan but skip PDF generation"
    )
    ap.add_argument(
        "--selftest", action="store_true", help="run built-in unit checks and exit"
    )
    args = ap.parse_args()

    global LOGO_PATH
    if args.logo:
        LOGO_PATH = args.logo

    if args.selftest:
        return run_selftest()

    try:
        import reportlab  # noqa: F401
        import requests  # noqa: F401
    except ImportError:
        err("Missing dependencies. Run:  python3 -m pip install -r requirements.txt")
        return 2

    print(_c("1;36", "\n=== ZAP VAPT Report Generator ===\n"))

    # --- Step 1 & 2: ensure ZAP, connect or launch, get API key ---
    step(f"Step 1/6 {DASH} Locating OWASP ZAP")
    api_key = args.api_key or read_api_key() or ""  # "" => probe an open (keyless) API
    base = f"http://127.0.0.1:{args.port}"
    zap = ZapClient(base, api_key)
    try:
        version = zap.ping()  # raises if a daemon is up but rejects the key
    except RuntimeError as e:
        err(str(e))
        return 3
    if version:
        ok(f"Found a running ZAP on port {args.port} (v{version}).")
        if not api_key:
            warn("No API key configured; using the running instance's open API.")
    else:
        zap_path = args.zap_path or locate_zap()
        if not zap_path:
            install_hint()
            return 3
        if not api_key:
            err(
                "Could not read the ZAP API key from config.xml. Pass --api-key, or open ZAP "
                "once (Options -> API) to generate one."
            )
            return 3
        ok(f"ZAP found at: {zap_path}")
        step(f"Step 2/6 {DASH} Launching ZAP headless")
        version = zap.start_daemon(zap_path, args.port)
        ok(f"ZAP daemon ready (v{version}).")
    tool_version = f"ZAP by Checkmarx v{version}" if version else "ZAP by Checkmarx"

    # --- Step 3: context ---
    step(f"Step 3/6 {DASH} ZAP context")
    ctx_name = args.context or prompt("Context name", DEFAULT_CONTEXT)
    ctx_id = zap.ensure_context(ctx_name)
    ok(f"Context '{ctx_name}' ready (id {ctx_id}).")

    # --- Step 4: endpoints ---
    step(f"Step 4/6 {DASH} Endpoints in scope")
    if args.postman:
        endpoints = parse_postman(args.postman, args.postman_env, args.cookie)
        info(f"Read endpoints from Postman collection {args.postman}")
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as fh:
            endpoints = parse_endpoints_input(fh.read())
        info(f"Read endpoints from {args.input}")
    else:
        endpoints = parse_endpoints_input(
            read_block("Paste the endpoints or curl requests to test:")
        )
    if args.methods:  # whitelist of methods to scan
        keep = {m.strip().upper() for m in args.methods.split(",") if m.strip()}
        before = len(endpoints)
        endpoints = [ep for ep in endpoints if ep.method in keep]
        if before != len(endpoints):
            info(
                f"--methods {sorted(keep)} kept {len(endpoints)} of {before} endpoint(s)."
            )
    if args.cookie:  # apply/override the Cookie header on all
        zap.add_secret(args.cookie)
        for ep in endpoints:
            ep.headers["Cookie"] = args.cookie
    if not endpoints:
        err("No endpoints parsed. Nothing to scan.")
        return 4
    ok(f"Parsed {len(endpoints)} endpoint(s).")
    for ep in endpoints:
        print(f"   {ep.method:6} {ep.url}")

    # --- Step 5: drive the sequence ---
    step(f"Step 5/6 {DASH} Replaying requests through ZAP (passive scan)")
    delivered = replay_endpoints(zap, ctx_name, endpoints)
    if delivered == 0:
        err(
            f"All {len(endpoints)} endpoint replays failed {DASH} ZAP received no traffic. "
            "Refusing to emit a report that would falsely show zero findings. "
            "Check the API key, auth headers, and network reachability."
        )
        return 5
    if args.active:
        run_active_scans(zap, ctx_id, endpoints)

    # --- Step 6: collect + report ---
    step(f"Step 6/6 {DASH} Collecting alerts & building the report")
    site = args.site or derive_site(endpoints)
    if not site:
        warn(
            "could not derive a site from the endpoints; pulling alerts for ALL sites."
        )
    all_alerts = zap.alerts(baseurl=site or None)
    ok(f"ZAP reported {len(all_alerts)} alert(s) for {site or 'all sites'}.")
    per_map, unmatched = join_alerts(endpoints, all_alerts)
    per_endpoint = [(ep, per_map[i]) for i, ep in enumerate(endpoints)]
    if unmatched:
        warn(
            f"{len(unmatched)} alert(s) did not map to a listed endpoint "
            "(shown as a 'Site-wide' row so totals reconcile)."
        )
    empty = [ep for (ep, a) in per_endpoint if not a]
    if empty:
        warn(
            f"{len(empty)} endpoint(s) matched zero alerts {DASH} verify the URLs/methods "
            "are correct and that ZAP received the traffic."
        )

    if args.no_report:
        info("Skipping PDF (--no-report).")
        return 0

    service = args.service or prompt(
        "Service under test (names the output file)", "API"
    )
    meta = ReportMeta()
    meta.service_short = service
    meta.service_full = (
        "Role-Based Access Control (RBAC) service"
        if service.upper() == "RBAC"
        else f"{service} service"
    )
    meta.site = site
    meta.tool_version = tool_version
    # each falls back to an interactive prompt only if its flag was not supplied,
    # so a fully-flagged invocation runs unattended (no stdin needed). All cover
    # identity is supplied here — nothing organization-specific is hardcoded.
    meta.company = args.company or prompt("Company / organization name (cover)", "")
    meta.company_short = args.company_short or prompt(
        "Short company name (report summary)", meta.company
    )
    meta.location = args.location or prompt(
        "Location (cover, e.g. 'City, Country')", ""
    )
    meta.created_name = args.created_by or prompt(
        "Name for the 'Created By' sign-off", ""
    )
    meta.approved_name = args.approved_by or prompt(
        "Name for the 'Approved By' sign-off", ""
    )

    agg = aggregate(all_alerts, site)
    out = args.output or f"{service} VAPT Report.pdf"
    build_pdf(out, meta, endpoints, per_endpoint, agg, unmatched)
    ok(f"Report written: {os.path.abspath(out)}")
    print(_c("2", f"   generated {meta.generated_str}"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        err("\nInterrupted.")
        sys.exit(130)
