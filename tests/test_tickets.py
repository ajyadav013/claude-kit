"""tickets: the store parses, dependency edges gate work, lineage does not, renderers never raise."""

from __future__ import annotations

import json
from pathlib import Path

from claude_kit import telemetry, tickets

TICKET_TEMPLATE = """# {id}: {title}

- **Status:** {status}
- **Spec:** docs/specs/thing_spec.md          (functional - what & why)
- **Branch:** {branch}
- **Files (declared scope):** src/one.py, src/two.py

## Why
Because the spec says so.

## Work Log
- 2026-07-27 - did a thing - so the thing works - files: src/one.py
"""


def write_store(
    root: Path,
    tickets_spec: "list[tuple[str, str, str]]",
    index: "dict | None" = None,
    branch: str = "feat/x",
) -> Path:
    """Write ``docs/project/tickets/`` from ``[(id, title, status), ...]``."""
    directory = root / tickets.TICKETS_REL
    directory.mkdir(parents=True, exist_ok=True)
    for ticket_id, title, status in tickets_spec:
        (directory / f"{ticket_id}-slug.md").write_text(
            TICKET_TEMPLATE.format(
                id=ticket_id, title=title, status=status, branch=branch
            ),
            encoding="utf-8",
        )
    if index is not None:
        (directory / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return directory


def test_missing_store_is_reported_not_raised(tmp_path):
    store = tickets.load_store(tmp_path)
    assert not store.exists and store.tickets == {}
    # Every renderer must still produce something printable.
    assert tickets.render_board(store)
    assert tickets.render_graph(store)
    assert tickets.render_detail(store, "ANY-1", tmp_path)


def test_markdown_fields_are_parsed(tmp_path):
    write_store(tmp_path, [("PROJ-1", "Add invoice export", "IN PROGRESS")])
    ticket = tickets.load_store(tmp_path).tickets["PROJ-1"]

    assert ticket.title == "Add invoice export"
    assert ticket.status == "IN PROGRESS"
    assert ticket.spec == "docs/specs/thing_spec.md", "the trailing note is stripped"
    assert ticket.files == ["src/one.py", "src/two.py"]
    assert ticket.work_log == [
        "2026-07-27 - did a thing - so the thing works - files: src/one.py"
    ]


def test_markdown_status_wins_over_the_index(tmp_path):
    """A human edits the Markdown; the index is a machine mirror that can lag behind."""
    write_store(
        tmp_path,
        [("PROJ-1", "T", "DONE")],
        index={"prefix": "PROJ", "tickets": {"PROJ-1": {"status": "OPEN"}}},
    )
    assert tickets.load_store(tmp_path).tickets["PROJ-1"].status == "DONE"


def test_index_supplies_commits_and_relations(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "T", "OPEN")],
        index={
            "prefix": "PROJ",
            "tickets": {
                "PROJ-1": {"commits": ["abc1234"], "relations": {"blocks": ["PROJ-2"]}}
            },
        },
    )
    ticket = tickets.load_store(tmp_path).tickets["PROJ-1"]
    assert ticket.commits == ["abc1234"]
    assert ticket.related("blocks") == ["PROJ-2"]


def test_unknown_relation_kinds_are_dropped(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "T", "OPEN")],
        index={"tickets": {"PROJ-1": {"relations": {"smells_like": ["PROJ-9"]}}}},
    )
    assert tickets.load_store(tmp_path).tickets["PROJ-1"].relations == {}


def test_malformed_index_does_not_break_the_store(tmp_path):
    directory = write_store(tmp_path, [("PROJ-1", "T", "OPEN")])
    (directory / "index.json").write_text("{not json", encoding="utf-8")

    store = tickets.load_store(tmp_path)
    assert store.tickets["PROJ-1"].title == "T"
    assert store.prefix == "PROJ", "prefix falls back to the id scheme"


def test_open_dependency_blocks_but_done_dependency_does_not(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "first", "OPEN"), ("PROJ-2", "second", "OPEN")],
        index={"tickets": {"PROJ-2": {"relations": {"depends_on": ["PROJ-1"]}}}},
    )
    store = tickets.load_store(tmp_path)
    assert store.is_blocked(store.tickets["PROJ-2"])
    assert not store.is_actionable(store.tickets["PROJ-2"])
    assert store.display_status(store.tickets["PROJ-2"]) == "BLOCKED"

    store.tickets["PROJ-1"].status = "DONE"
    assert not store.is_blocked(store.tickets["PROJ-2"])
    assert store.is_actionable(store.tickets["PROJ-2"])


def test_lineage_does_not_gate(tmp_path):
    """A sub-ticket is not blocked merely because its parent is still open (aiball's rule)."""
    write_store(
        tmp_path,
        [("PROJ-1", "parent", "OPEN"), ("PROJ-2", "child", "OPEN")],
        index={"tickets": {"PROJ-2": {"relations": {"child_of": ["PROJ-1"]}}}},
    )
    store = tickets.load_store(tmp_path)
    assert store.is_actionable(store.tickets["PROJ-2"])


def test_dependency_on_an_unknown_ticket_still_blocks(tmp_path):
    """A dangling blocker is unresolved, so it must gate — never silently vanish."""
    write_store(
        tmp_path,
        [("PROJ-1", "t", "OPEN")],
        index={"tickets": {"PROJ-1": {"relations": {"depends_on": ["GONE-9"]}}}},
    )
    store = tickets.load_store(tmp_path)
    assert store.blockers(store.tickets["PROJ-1"]) == ["GONE-9"]


def test_counts_always_report_open_beside_actionable(tmp_path):
    """A fully-gated backlog must read as blocked, never as 'nothing to do'."""
    write_store(
        tmp_path,
        [("PROJ-1", "a", "IN PROGRESS"), ("PROJ-2", "b", "OPEN")],
        index={"tickets": {"PROJ-2": {"relations": {"depends_on": ["PROJ-1"]}}}},
    )
    store = tickets.load_store(tmp_path)
    counts = store.counts()

    assert counts == {
        "total": 2,
        "open": 2,
        "actionable": 1,
        "blocked": 1,
        "in_progress": 1,
        "done": 0,
    }
    assert "2 open" in tickets.render_board(store)[0]


def test_ids_sort_numerically(tmp_path):
    write_store(tmp_path, [("PROJ-9", "nine", "OPEN"), ("PROJ-10", "ten", "OPEN")])
    store = tickets.load_store(tmp_path)
    assert [t.id for t in store.ordered()] == ["PROJ-9", "PROJ-10"]


def test_board_puts_in_progress_first_and_done_last(tmp_path):
    write_store(
        tmp_path,
        [
            ("PROJ-1", "done", "DONE"),
            ("PROJ-2", "open", "OPEN"),
            ("PROJ-3", "active", "IN PROGRESS"),
        ],
    )
    store = tickets.load_store(tmp_path)
    order = [t.id for t in tickets._board_order(store)]
    assert order == ["PROJ-3", "PROJ-2", "PROJ-1"]


def test_relation_cycle_does_not_hang_the_graph(tmp_path):
    """Two tickets each claiming the other as parent must still render, and terminate."""
    write_store(
        tmp_path,
        [("PROJ-1", "a", "OPEN"), ("PROJ-2", "b", "OPEN")],
        index={
            "tickets": {
                "PROJ-1": {"relations": {"child_of": ["PROJ-2"]}},
                "PROJ-2": {"relations": {"child_of": ["PROJ-1"]}},
            }
        },
    )
    store = tickets.load_store(tmp_path)
    rendered = "\n".join(tickets.render_graph(store))
    assert "PROJ-1" in rendered and "PROJ-2" in rendered


def test_graph_nests_children_under_parents(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "parent", "OPEN"), ("PROJ-2", "child", "OPEN")],
        index={"tickets": {"PROJ-2": {"relations": {"child_of": ["PROJ-1"]}}}},
    )
    lines = tickets.render_graph(tickets.load_store(tmp_path))
    child_line = next(line for line in lines if "PROJ-2" in line)
    assert child_line.startswith(" "), "a child is indented beneath its parent"


def test_telemetry_attaches_by_branch(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")], branch="feat/x")
    store = tickets.load_store(tmp_path)
    entry = telemetry.Telemetry(
        requests=3, output_tokens=1500, models=["claude-opus-4-8"]
    )
    tickets.attach_telemetry(store, {"feat/x": entry})

    assert store.tickets["PROJ-1"].telemetry is entry
    assert "1.5k" in "\n".join(tickets.render_board(store))


def test_telemetry_for_another_branch_is_not_attached(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")], branch="feat/mine")
    store = tickets.load_store(tmp_path)
    tickets.attach_telemetry(store, {"feat/theirs": telemetry.Telemetry(requests=9)})
    assert store.tickets["PROJ-1"].telemetry is None


def test_shared_branch_is_disclosed_not_implied(tmp_path):
    """Branch-scoped figures cover every ticket on the branch — the view must say so."""
    write_store(
        tmp_path,
        [("PROJ-1", "a", "OPEN"), ("PROJ-2", "b", "OPEN")],
        branch="feat/shared",
    )
    store = tickets.load_store(tmp_path)
    tickets.attach_telemetry(
        store, {"feat/shared": telemetry.Telemetry(requests=2, output_tokens=10)}
    )

    assert store.branch_sharers(store.tickets["PROJ-1"]) == ["PROJ-2"]
    assert "per branch" in "\n".join(tickets.render_board(store))
    assert "shared with PROJ-2" in "\n".join(
        tickets.render_detail(store, "PROJ-1", tmp_path)
    )


def test_detail_reports_unknown_ticket(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    lines = tickets.render_detail(tickets.load_store(tmp_path), "PROJ-77", tmp_path)
    assert "unknown ticket" in lines[0] and "PROJ-1" in lines[0]


def test_detail_includes_work_log_and_no_telemetry_note(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    text = "\n".join(
        tickets.render_detail(tickets.load_store(tmp_path), "PROJ-1", tmp_path)
    )
    assert "WORK LOG" in text
    assert "no telemetry recorded" in text


def test_detail_reads_the_pipeline_stage(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    snapshot = tmp_path / tickets.SNAPSHOT_REL
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps({"stage": "build", "last_gate_passed": "code-review"}),
        encoding="utf-8",
    )
    text = "\n".join(
        tickets.render_detail(tickets.load_store(tmp_path), "PROJ-1", tmp_path)
    )
    assert "build" in text and "code-review" in text


def test_git_graph_without_a_repo_says_so(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    text = "\n".join(tickets.render_git_graph(tickets.load_store(tmp_path), tmp_path))
    assert "no git history" in text


def test_commit_is_matched_to_its_ticket_by_id_in_the_subject(tmp_path):
    write_store(tmp_path, [("PROJ-7", "t", "OPEN")])
    store = tickets.load_store(tmp_path)
    matched = tickets._ticket_for_commit(
        "feat: add export [PROJ-7]",
        "abc1234",
        {"PROJ-7": store.tickets["PROJ-7"]},
        store,
    )
    assert matched is not None and matched.id == "PROJ-7"


def test_commit_is_matched_by_recorded_sha_when_the_subject_is_silent(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-7", "t", "OPEN")],
        index={"tickets": {"PROJ-7": {"commits": ["abc1234def"]}}},
    )
    store = tickets.load_store(tmp_path)
    matched = tickets._ticket_for_commit("chore: tidy", "abc1234", {}, store)
    assert matched is not None and matched.id == "PROJ-7"


def test_first_of_discloses_dropped_values():
    assert tickets._first_of([]) == "-"
    assert tickets._first_of(["a"]) == "a"
    assert tickets._first_of(["a", "b", "c"]) == "a +2"


def test_to_dict_is_json_serialisable(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    store = tickets.load_store(tmp_path)
    tickets.attach_telemetry(store, {"feat/x": telemetry.Telemetry(requests=1)})
    json.dumps(store.tickets["PROJ-1"].to_dict())  # must not raise


# --- git graph, detail and blocker rendering -----------------------------------------------------
# These renderers were the module's largest uncovered region (F-016). `render_git_graph`'s whole
# annotation loop had never executed, because every existing test ran against a tmp_path that is
# not a git repository, so `git_commits` returned [] and the function short-circuited on its
# friendly "no git history" branch. Faking the commit list exercises the loop deterministically and
# without a git binary; `git_commits` itself is covered separately by faking `subprocess.run`, so
# the shell-out and the rendering are tested independently rather than through each other.


def test_git_graph_annotates_each_commit_with_its_ticket(tmp_path, monkeypatch):
    write_store(tmp_path, [("PROJ-7", "add export", "IN_PROGRESS")])
    monkeypatch.setattr(
        tickets,
        "git_commits",
        lambda root, limit=40: [
            ("abc1234", "HEAD -> main", "feat: add export [PROJ-7]"),
            ("def5678", "", "chore: unrelated tidy-up"),
        ],
    )
    store = tickets.load_store(tmp_path)
    text = "\n".join(tickets.render_git_graph(store, tmp_path))

    assert "* abc1234  (HEAD -> main)" in text, "a decorated commit must show its refs"
    assert "* def5678" in text and "(HEAD" not in text.split("def5678")[1]
    assert "[PROJ-7]" in text, "the matched commit must be annotated with its ticket"
    # The unmatched commit falls back to its subject rather than being dropped or mis-attributed.
    assert "chore: unrelated tidy-up" in text


def test_git_commits_parses_the_record_separator_format(tmp_path, monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "abc1234\x1fHEAD -> main\x1ffeat: one\ndef5678\x1f\x1ffix: two\nmalformed-line\n"

    monkeypatch.setattr(tickets.subprocess, "run", lambda *a, **k: _Proc())
    got = tickets.git_commits(tmp_path)
    assert got == [
        ("abc1234", "HEAD -> main", "feat: one"),
        ("def5678", "", "fix: two"),
    ], (
        "a line without two separators is not a commit record and must be skipped, not padded"
    )


def test_git_commits_degrades_to_empty_when_git_is_missing(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("git: not found")

    monkeypatch.setattr(tickets.subprocess, "run", _boom)
    assert tickets.git_commits(tmp_path) == []


def test_git_commits_treats_a_nonzero_exit_as_no_history(tmp_path, monkeypatch):
    class _Proc:
        returncode = 128
        stdout = "fatal: not a git repository"

    monkeypatch.setattr(tickets.subprocess, "run", lambda *a, **k: _Proc())
    assert tickets.git_commits(tmp_path) == []


def test_a_commit_matching_no_ticket_returns_none(tmp_path):
    write_store(tmp_path, [("PROJ-1", "t", "OPEN")])
    store = tickets.load_store(tmp_path)
    assert tickets._ticket_for_commit("chore: tidy", "0000000", {}, store) is None


def test_detail_lists_links_relations_and_commits(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "the feature", "OPEN"), ("PROJ-2", "the blocker", "OPEN")],
        index={
            "tickets": {
                "PROJ-1": {
                    "commits": ["abc1234"],
                    "relations": {
                        "depends_on": ["PROJ-2"],
                        "relates_to": ["PROJ-9"],
                    },
                }
            }
        },
    )
    store = tickets.load_store(tmp_path)
    text = "\n".join(tickets.render_detail(store, "PROJ-1", tmp_path))

    assert "Spec      docs/specs/thing_spec.md" in text
    assert "Blocked   depends_on PROJ-2" in text
    assert "Commits   abc1234" in text
    # A non-gating relation is listed under its own kind, never reported as a blocker.
    assert "relates_to PROJ-9" in text
    assert "depends_on PROJ-9" not in text


def test_detail_accepts_a_lowercase_ticket_id(tmp_path):
    write_store(tmp_path, [("PROJ-1", "the feature", "OPEN")])
    store = tickets.load_store(tmp_path)
    assert "PROJ-1" in "\n".join(tickets.render_detail(store, "proj-1", tmp_path))


def test_graph_marks_a_blocker_and_names_its_state(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "the feature", "OPEN"), ("PROJ-2", "the blocker", "OPEN")],
        index={
            "tickets": {"PROJ-1": {"relations": {"depends_on": ["PROJ-2", "PROJ-404"]}}}
        },
    )
    store = tickets.load_store(tmp_path)
    text = "\n".join(tickets.render_graph(store))
    assert "depends_on PROJ-2  (open - gates this)" in text
    # An unknown blocker still gates, and says it is unknown rather than silently vanishing.
    assert "depends_on PROJ-404  (missing - gates this)" in text


def test_a_ticket_that_exists_only_in_the_index_is_still_loaded(tmp_path):
    """The index is a source of tickets, not merely of metadata for tickets found on disk.

    A ticket recorded in `index.json` with no matching markdown file must still appear -- otherwise
    a store whose markdown has not been written yet reads as empty, and `exists` stays False, which
    the CLI renders as "no ticket store here" rather than as the one open ticket it has.
    """
    directory = tmp_path / tickets.TICKETS_REL
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.json").write_text(
        json.dumps(
            {"tickets": {"PROJ-9": {"status": "in_progress", "title": "index only"}}}
        ),
        encoding="utf-8",
    )
    store = tickets.load_store(tmp_path)
    assert store.exists, "an index-only store exists"
    assert "PROJ-9" in store.tickets
    assert store.tickets["PROJ-9"].status == "IN_PROGRESS", "status is upper-cased"
    assert store.tickets["PROJ-9"].title == "index only"


# --- parser and index tolerance ------------------------------------------------------------------
# The store reads two hand-editable files. Both are written by humans, so the interesting cases are
# the shapes a human plausibly produces: a field the template does not show, a relation given as a
# bare string rather than a list, and an index entry that is not an object at all.


def test_design_field_is_parsed_and_shown_in_detail(tmp_path):
    directory = tmp_path / tickets.TICKETS_REL
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "PROJ-1-slug.md").write_text(
        "# PROJ-1: the feature\n\n"
        "- **Status:** OPEN\n"
        "- **Design:** docs/design/thing.md          (visual - screens & states)\n",
        encoding="utf-8",
    )
    store = tickets.load_store(tmp_path)
    # The trailing parenthetical annotation is an editor's note, not part of the path.
    assert store.tickets["PROJ-1"].design == "docs/design/thing.md"
    assert "Design    docs/design/thing.md" in "\n".join(
        tickets.render_detail(store, "PROJ-1", tmp_path)
    )


def test_a_relation_given_as_a_bare_string_is_accepted(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "t", "OPEN"), ("PROJ-2", "t", "OPEN")],
        index={"tickets": {"PROJ-1": {"relations": {"depends_on": "PROJ-2"}}}},
    )
    store = tickets.load_store(tmp_path)
    assert store.tickets["PROJ-1"].related("depends_on") == ["PROJ-2"]
    assert store.is_blocked(store.tickets["PROJ-1"]), "a string edge still gates"


def test_an_index_without_the_tickets_envelope_is_read_as_flat(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "t", "OPEN")],
        index={"PROJ-1": {"commits": ["abc1234"]}, "schema": 1},
    )
    store = tickets.load_store(tmp_path)
    # The flat fallback keeps object entries and drops the scalar `schema` key rather than
    # treating it as a ticket.
    assert store.tickets["PROJ-1"].commits == ["abc1234"]
    assert "schema" not in store.tickets


def test_a_non_object_index_entry_is_skipped_not_loaded(tmp_path):
    write_store(
        tmp_path,
        [("PROJ-1", "t", "OPEN")],
        index={"tickets": {"PROJ-1": {"commits": ["abc"]}, "PROJ-2": "not an object"}},
    )
    store = tickets.load_store(tmp_path)
    assert "PROJ-2" not in store.tickets


def test_a_ticket_with_no_branch_shares_telemetry_with_nobody(tmp_path):
    directory = tmp_path / tickets.TICKETS_REL
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "PROJ-1-slug.md").write_text(
        "# PROJ-1: no branch\n\n- **Status:** OPEN\n", encoding="utf-8"
    )
    store = tickets.load_store(tmp_path)
    assert store.branch_sharers(store.tickets["PROJ-1"]) == []
