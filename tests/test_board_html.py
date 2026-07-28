"""board_html: the HTML board is self-contained, escapes untrusted text, and groups by column."""

from __future__ import annotations

from datetime import datetime

from claude_kit import board_html, telemetry, tickets
from tests.test_tickets import write_store

FIXED = datetime(2026, 7, 28, 12, 0, 0)


def _render(tmp_path, spec, index=None, refresh=10, branch="feat/x"):
    write_store(tmp_path, spec, index=index, branch=branch)
    store = tickets.load_store(tmp_path)
    return store, board_html.render_html(store, refresh=refresh, generated_at=FIXED)


def test_ticket_title_is_escaped_not_injected(tmp_path):
    """Ticket titles are untrusted text — a script tag must render as text, never execute."""
    _, html = _render(tmp_path, [("PROJ-1", "<script>alert(1)</script>", "OPEN")])

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # The only <script in the document must be the escaped literal, i.e. none at all.
    assert "<script" not in html


def test_branch_and_relation_ids_are_escaped(tmp_path):
    _, html = _render(
        tmp_path,
        [("PROJ-1", "safe", "OPEN")],
        branch='feat/"><img src=x onerror=alert(1)>',
    )
    assert "onerror=alert(1)>" not in html
    assert "&lt;img" in html or "&quot;&gt;" in html


def test_document_is_self_contained(tmp_path):
    """No CDN, no fonts, no images, no JS — opening the board makes zero network requests."""
    _, html = _render(tmp_path, [("PROJ-1", "a thing", "OPEN")])

    assert "<style>" in html, "CSS must be inline"
    for forbidden in ("http://", "https://", "<script", "<img", "@import", "<link"):
        assert forbidden not in html, (
            f"{forbidden!r} would make the board non-self-contained"
        )


def test_refresh_meta_tag_present_and_disableable(tmp_path):
    _, live = _render(tmp_path, [("PROJ-1", "t", "OPEN")], refresh=5)
    assert '<meta http-equiv="refresh" content="5">' in live
    assert "auto-refreshing every 5s" in live

    _, static = _render(tmp_path, [("PROJ-1", "t", "OPEN")], refresh=0)
    assert 'http-equiv="refresh"' not in static
    assert "static snapshot" in static


def test_tickets_land_in_the_right_columns(tmp_path):
    store, html = _render(
        tmp_path,
        [
            ("PROJ-1", "moving", "IN PROGRESS"),
            ("PROJ-2", "reviewing", "IN REVIEW"),
            ("PROJ-3", "ready", "OPEN"),
            ("PROJ-4", "stuck", "OPEN"),
            ("PROJ-5", "finished", "DONE"),
        ],
        index={"tickets": {"PROJ-4": {"relations": {"depends_on": ["PROJ-1"]}}}},
    )
    assert board_html._column_of(store, store.tickets["PROJ-1"]) == "IN PROGRESS"
    assert board_html._column_of(store, store.tickets["PROJ-2"]) == "IN REVIEW"
    assert board_html._column_of(store, store.tickets["PROJ-3"]) == "ACTIONABLE"
    assert board_html._column_of(store, store.tickets["PROJ-4"]) == "BLOCKED"
    assert board_html._column_of(store, store.tickets["PROJ-5"]) == "DONE"
    for column in ("IN PROGRESS", "IN REVIEW", "ACTIONABLE", "BLOCKED", "DONE"):
        assert column in html


def test_blocked_card_names_its_blocker(tmp_path):
    _, html = _render(
        tmp_path,
        [("PROJ-1", "first", "OPEN"), ("PROJ-2", "second", "OPEN")],
        index={"tickets": {"PROJ-2": {"relations": {"depends_on": ["PROJ-1"]}}}},
    )
    assert "blocked by PROJ-1" in html


def test_done_card_never_claims_to_be_blocked(tmp_path):
    """Regression: a finished ticket rendered 'DONE · blocked by X', which is a contradiction."""
    _, html = _render(
        tmp_path,
        [("PROJ-1", "first", "OPEN"), ("PROJ-2", "second", "DONE")],
        index={"tickets": {"PROJ-2": {"relations": {"depends_on": ["PROJ-1"]}}}},
    )
    assert "blocked by" not in html


def test_header_always_shows_open_and_actionable_even_at_zero(tmp_path):
    """The lens invariant: a fully-gated backlog must not render as an empty one.

    Every open ticket here is blocked, so actionable is 0 — the exact case where omitting the open
    count would make a backlog full of real work look like there is nothing to do.
    """
    _, html = _render(
        tmp_path,
        [("PROJ-1", "a", "OPEN"), ("PROJ-2", "b", "OPEN")],
        index={
            "tickets": {
                "PROJ-1": {"relations": {"depends_on": ["PROJ-2"]}},
                "PROJ-2": {"relations": {"depends_on": ["PROJ-1"]}},
            }
        },
    )
    assert "<strong>2</strong> open" in html
    assert "<strong>0</strong> actionable" in html


def test_telemetry_appears_on_the_card(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")], branch="feat/x")
    store = tickets.load_store(tmp_path)
    tickets.attach_telemetry(
        store,
        {
            "feat/x": telemetry.Telemetry(
                requests=4,
                output_tokens=12_500,
                cache_read=2_000_000,
                models=["claude-opus-4-8"],
                agents=["developer"],
            )
        },
    )
    html = board_html.render_html(store, generated_at=FIXED)
    assert "opus-4-8" in html
    assert "12.5k tok" in html
    assert "2.0M cache" in html
    assert "developer" in html


def test_empty_store_renders_a_hint_not_an_error(tmp_path):
    store = tickets.load_store(tmp_path)
    html = board_html.render_html(store, generated_at=FIXED)
    assert "No tickets yet" in html
    assert "<html" in html and "</html>" in html


def test_untitled_ticket_does_not_render_blank(tmp_path):
    directory = tmp_path / tickets.TICKETS_REL
    directory.mkdir(parents=True)
    (directory / "x.md").write_text("- **Status:** OPEN\n", encoding="utf-8")
    html = board_html.render_html(tickets.load_store(tmp_path), generated_at=FIXED)
    assert "(untitled)" in html
