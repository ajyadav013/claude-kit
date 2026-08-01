"""from_config: friendly YAML is normalised, and malformed/typo'd config fails loudly."""

from __future__ import annotations

import sys

import pytest

from claude_kit import catalog, prompts


def _write(tmp_path, body: str):
    p = tmp_path / "init.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_bare_mcp_string_is_normalised_to_a_list(tmp_path, payload):
    """`mcp: github` (a scalar) becomes ["github"] instead of being iterated char-by-char."""
    cfg = _write(tmp_path, "mcp: github\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.mcp == ["github"]
    # ...and it resolves to a real server, not 'g','i','t',... :
    plan = catalog.resolve(payload, sel)
    assert "github" in plan.mcp_servers


def test_mcp_wrong_shape_is_rejected(tmp_path, payload):
    """A mapping (or any non-string-list) for a list field fails with a clear message."""
    cfg = _write(tmp_path, "mcp:\n  github: true\n")
    with pytest.raises(ValueError, match="mcp"):
        prompts.from_config(cfg, payload)


def test_unknown_config_key_is_rejected(tmp_path, payload):
    """A typo'd top-level key (databse) is reported rather than silently ignored."""
    cfg = _write(tmp_path, "databse: postgres\n")
    with pytest.raises(ValueError, match="unknown config key"):
        prompts.from_config(cfg, payload)


def test_teams_string_is_normalised(tmp_path, payload):
    """A bare `teams: engineering` becomes a one-element list."""
    cfg = _write(tmp_path, "scope: organization\nteams: engineering\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.teams == ["engineering"]


def test_bare_string_backend_lane_gets_its_own_default_framework(tmp_path, payload):
    """`backend: go` must yield go's net-http — never the global default's fastapi, a
    framework the user never wrote and the catalog doesn't even define for that lane."""
    cfg = _write(tmp_path, "backend: go\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.backend_language == "go"
    assert sel.backend_framework == "net-http"
    # ...and the selection actually resolves (go + the default react frontend):
    plan = catalog.resolve(payload, sel)
    assert "go-patterns.md" in plan.overlay_rules


def test_nested_backend_without_framework_gets_lane_default(tmp_path, payload):
    """The nested form with only a language behaves the same as the bare string."""
    cfg = _write(tmp_path, "backend: { language: go }\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.backend_framework == "net-http"


def test_none_lanes_default_like_the_interactive_flow(tmp_path, payload):
    """`frontend: none` / `backend: none` fall back to the lane's own no-op defaults
    (language "none", framework "none") — matching what the interactive prompts produce."""
    cfg = _write(tmp_path, "frontend: none\nbackend: none\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.frontend_language == "none"
    assert sel.backend_framework == "none"


def test_default_lanes_keep_the_catalog_defaults(tmp_path, payload):
    """An empty-ish config still resolves to the global catalog defaults."""
    cfg = _write(tmp_path, "profile: lean\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.frontend_framework == "react"
    assert sel.frontend_language == "typescript"
    assert sel.backend_language == "python"
    assert sel.backend_framework == "fastapi"


def test_explicit_framework_beats_the_lane_default(tmp_path, payload):
    """A framework the user DID write is never second-guessed by the lane lookup."""
    cfg = _write(tmp_path, "backend: { language: go, framework: net-http }\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.backend_framework == "net-http"


def test_malformed_yaml_is_a_friendly_valueerror(tmp_path, payload):
    """A YAML syntax error becomes a one-line ValueError (the CLI renders those as
    `error: … / exit 2`) instead of a raw PyYAML ScannerError escaping to the user."""
    cfg = _write(tmp_path, "profile: standard\n  backend: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        prompts.from_config(cfg, payload)


# --- interactive parsers (R5): the paths a real human hits ---------------------------------
#
# Before these, only the EOFError->default branch was executed (proved with a line tracer in
# the round-2 review); the numeric-selection, re-prompt, multi-select, and yes/no parsing that
# an actual interactive `init` exercises had zero coverage.


def _feed(monkeypatch, answers: list[str]) -> None:
    """Monkeypatch input() to return the answers in order; fail loudly if over-consumed."""
    it = iter(answers)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:  # pragma: no cover - a failure aid, not a path under test
            pytest.fail(
                f"input() called more times than answers provided (at {prompt!r})"
            )

    monkeypatch.setattr("builtins.input", fake_input)


def _tty(monkeypatch, is_tty: bool) -> None:
    """Make the capture consent gate see (or not see) a real terminal on stdin.

    The interactive capture preselection is `off` unless stdin is a tty (EOF/piped answers are
    not consent) — tests that emulate a human at a terminal must say so explicitly.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: is_tty)


def test_ask_strips_and_defaults(monkeypatch):
    _feed(monkeypatch, ["  spaced  ", ""])
    assert prompts._ask("q", "dflt") == "spaced"
    assert prompts._ask("q", "dflt") == "dflt"


def test_choose_one_accepts_number_and_id(monkeypatch):
    options = [{"id": "alpha", "label": "Alpha"}, {"id": "beta", "label": "Beta"}]
    _feed(monkeypatch, ["2"])
    assert prompts._choose_one("T", options, "alpha") == "beta"
    _feed(monkeypatch, ["beta"])
    assert prompts._choose_one("T", options, "alpha") == "beta"


def test_choose_one_reprompts_until_valid(monkeypatch, capsys):
    options = [{"id": "alpha", "label": "Alpha"}, {"id": "beta", "label": "Beta"}]
    _feed(
        monkeypatch, ["bogus", "99", "1"]
    )  # unknown id, out-of-range number, then valid
    assert prompts._choose_one("T", options, "beta") == "alpha"
    out = capsys.readouterr().out
    assert out.count("please enter one of the listed ids or numbers") == 2


def test_choose_one_planned_options_are_visible_but_not_selectable(monkeypatch, capsys):
    options = [
        {"id": "live-one", "label": "Live"},
        {"id": "soon", "label": "Soon", "status": "planned"},
    ]
    # Choosing the planned id is rejected; numbering covers live options only, so "1" = live-one.
    _feed(monkeypatch, ["soon", "1"])
    assert prompts._choose_one("T", options, "live-one") == "live-one"
    out = capsys.readouterr().out
    assert "(coming soon)" in out
    assert "2)" not in out  # the planned entry got no selectable number


@pytest.mark.parametrize(
    ("resp", "expected"),
    [
        ("y", True),
        ("yes", True),
        ("TRUE", True),
        ("1", True),
        ("n", False),
        ("no", False),
        ("False", False),
        ("0", False),
    ],
)
def test_ask_bool_recognised_answers(monkeypatch, resp, expected):
    _feed(monkeypatch, [resp])
    assert prompts._ask_bool("q", default=not expected) is expected


def test_ask_bool_garbage_falls_back_to_default(monkeypatch):
    _feed(monkeypatch, ["maybe", "maybe"])
    assert prompts._ask_bool("q", default=True) is True
    assert prompts._ask_bool("q", default=False) is False


def test_choose_many_empty_and_none_mean_no_selection(monkeypatch):
    options = [{"id": "github", "label": "GitHub"}]
    _feed(monkeypatch, [""])
    assert prompts._choose_many("T", options) == []
    _feed(monkeypatch, ["none"])
    assert prompts._choose_many("T", options) == []


def test_choose_many_mixed_ids_numbers_dedup_and_unknowns(monkeypatch, capsys):
    options = [
        {"id": "github", "label": "GitHub"},
        {"id": "linear", "label": "Linear"},
        {"id": "jira", "label": "Jira"},
    ]
    # id + number + duplicate id + unknown token, comma/space separated.
    _feed(monkeypatch, ["github, 2 github bogus"])
    assert prompts._choose_many("T", options) == ["github", "linear"]
    assert "ignoring unknown selection: bogus" in capsys.readouterr().out


def test_interactive_full_flow_numbers_and_ids(monkeypatch, payload):
    """Drive the whole question sequence the way a human would: numbers AND ids.

    Live menu numbering (planned lanes get no number): frontend 1) none 2) react;
    backend 1) none 2) python 3) go.
    """
    _tty(
        monkeypatch, True
    )  # a human at a terminal — the capture default is the recommendation
    _feed(
        monkeypatch,
        [
            "2",  # frontend framework -> react (numeric)
            "typescript",  # frontend language (id)
            "2",  # backend language -> python (numeric)
            "",  # backend framework -> default (fastapi)
            "postgres",  # database (id)
            "enterprise",  # profile (id)
            "",  # learning capture -> profile default
            "github linear",  # MCP multi-select
            "individual",  # usage scope (no org questions follow)
        ],
    )
    sel = prompts.interactive(payload)
    assert sel.frontend_framework == "react"
    assert sel.frontend_language == "typescript"
    assert sel.backend_language == "python"
    assert sel.backend_framework == "fastapi"
    assert sel.database == "postgres"
    assert sel.profile == "enterprise"
    assert sel.capture_mode == "session-end-catchup"  # non-lean default
    assert sel.mcp == ["github", "linear"]
    assert sel.scope == "individual"


def test_interactive_none_frontend_skips_language_question(monkeypatch, payload):
    """The `none` lane declares no languages, so no language question consumes an answer."""
    _tty(
        monkeypatch, True
    )  # pin the `off` below to the LEAN branch, not the non-tty branch
    _feed(
        monkeypatch,
        [
            "none",  # frontend framework -> the lane-less entry
            "3",  # backend language -> go (if a language Q leaked in, alignment breaks here)
            "",  # backend framework -> default (net-http)
            "none",  # database
            "lean",  # profile
            "",  # learning capture -> lean defaults to off
            "",  # MCP -> none
            "individual",  # scope
        ],
    )
    sel = prompts.interactive(payload)
    assert sel.frontend_framework == "none"
    assert sel.frontend_language == "none"
    assert sel.backend_language == "go"
    assert sel.backend_framework == "net-http"
    assert sel.capture_mode == "off"  # lean's intentionally-minimal default
    assert sel.mcp == []


def test_interactive_organization_scope_asks_the_org_questions(monkeypatch, payload):
    _feed(
        monkeypatch,
        [
            "",  # frontend -> default (react)
            "",  # language -> default (typescript)
            "",  # backend -> default (python)
            "",  # framework -> default (fastapi)
            "",  # database -> default (postgres)
            "",  # profile -> default (standard)
            "",  # capture -> default
            "",  # MCP -> none
            "organization",  # scope -> unlocks the org block
            "engineering, product",  # teams (multi)
            "autonomous-pr",  # autonomy
            "regulated",  # review strictness
            "n",  # org packs -> declined
        ],
    )
    sel = prompts.interactive(payload)
    assert sel.scope == "organization"
    assert sel.teams == ["engineering", "product"]
    assert sel.autonomy == "autonomous-pr"
    assert sel.review_strictness == "regulated"
    assert sel.org_packs is False


# --- capture consent (0.76.0): EOF/piped stdin is not consent -------------------------------


def test_interactive_non_tty_stdin_defaults_capture_off(monkeypatch, payload):
    """Accepting the capture default without a real terminal must mean OFF.

    A piped/EOF stdin self-answers every prompt with its default — if the default were the
    recommendation, an unattended `init` would grant capture consent nobody gave.
    """
    _tty(monkeypatch, False)
    _feed(
        monkeypatch,
        [
            "2",  # frontend -> react
            "typescript",
            "2",  # backend -> python
            "",  # framework -> fastapi
            "postgres",
            "enterprise",  # a profile whose tty default WOULD be the recommendation
            "",  # capture -> default, which must now be off
            "",  # MCP -> none
            "individual",
        ],
    )
    sel = prompts.interactive(payload)
    assert sel.capture_mode == "off"


def test_interactive_non_tty_explicit_mode_is_still_honored(monkeypatch, payload):
    """Only the *default* flips off a tty — an explicitly named mode is a recorded choice."""
    _tty(monkeypatch, False)
    _feed(
        monkeypatch,
        [
            "2",
            "typescript",
            "2",
            "",
            "postgres",
            "standard",
            "session-end",  # explicit selection, not a default fallback
            "",
            "individual",
        ],
    )
    sel = prompts.interactive(payload)
    assert sel.capture_mode == "session-end"


def test_config_capture_mode_true_is_rejected_as_ambiguous(tmp_path, payload):
    """YAML 1.1 parses bare `on`/`true` as booleans — there is no mode named True, and guessing
    one would be manufactured consent. from_config must fail loudly and name the real modes."""
    cfg = _write(tmp_path, "capture_mode: on\n")
    with pytest.raises(ValueError, match="ambiguous"):
        prompts.from_config(cfg, payload)


def test_config_capture_mode_bare_off_means_off(tmp_path, payload):
    """Bare `off` also parses as a boolean (False) — but its intent is unambiguous: off."""
    cfg = _write(tmp_path, "capture_mode: off\n")
    sel = prompts.from_config(cfg, payload)
    assert sel.capture_mode == "off"
