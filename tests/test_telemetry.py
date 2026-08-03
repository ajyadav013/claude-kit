"""telemetry: transcript aggregation is deduplicated, cache-aware, and never raises on bad input."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from claude_kit import telemetry


def _record(
    request_id: str,
    *,
    branch: str = "feat/x",
    out: int = 100,
    inp: int = 10,
    cache_read: int = 1000,
    cache_write: int = 5,
    model: str = "claude-opus-4-8",
    agent: str | None = None,
    timestamp: str = "2026-07-27T10:00:00.000Z",
) -> dict:
    record: dict = {
        "requestId": request_id,
        "gitBranch": branch,
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }
    if agent:
        record["agentName"] = agent
    return record


def _transcript(tmp_path: Path, records: list[dict], name: str = "s.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_repeated_request_id_counted_once(tmp_path):
    """Regression: streaming rewrites the same usage block, so summing raw records over-counts.

    Measured 3.3x on a real session (622 usage records, 219 distinct requests). Dedupe by
    ``requestId`` is a correctness rule, not an optimisation — this pins it.
    """
    # One logical request written five times, as a streaming response does.
    records = [_record("req-1", out=500) for _ in range(5)]
    result = telemetry.scan([_transcript(tmp_path, records)])

    assert result["feat/x"].requests == 1
    assert result["feat/x"].output_tokens == 500, (
        "repeated usage blocks must not accumulate"
    )


def test_distinct_requests_accumulate(tmp_path):
    records = [_record(f"req-{i}", out=100, inp=10) for i in range(4)]
    entry = telemetry.scan([_transcript(tmp_path, records)])["feat/x"]

    assert entry.requests == 4
    assert entry.output_tokens == 400
    assert entry.input_tokens == 40
    assert entry.total_tokens == 440


def test_dedupe_spans_multiple_files(tmp_path):
    """The same request appearing in two transcripts is still one request."""
    a = _transcript(tmp_path, [_record("shared", out=70)], "a.jsonl")
    b = _transcript(tmp_path, [_record("shared", out=70)], "b.jsonl")

    entry = telemetry.scan([a, b])["feat/x"]
    assert entry.requests == 1
    assert entry.output_tokens == 70


def test_cache_counters_are_separate_from_input(tmp_path):
    """Cache reads dwarf fresh input (46.6M vs 58k observed), so they must not be folded in."""
    entry = telemetry.scan(
        [
            _transcript(
                tmp_path, [_record("r", inp=8, cache_read=90_000, cache_write=700)]
            )
        ]
    )["feat/x"]

    assert entry.input_tokens == 8
    assert entry.cache_read == 90_000
    assert entry.cache_write == 700
    assert entry.total_tokens == 8 + 100, (
        "total is fresh input + output, cache excluded"
    )


def test_records_grouped_by_branch(tmp_path):
    records = [
        _record("a", branch="feat/one", out=10),
        _record("b", branch="feat/two", out=20),
        _record("c", branch="", out=30),
    ]
    result = telemetry.scan([_transcript(tmp_path, records)])

    assert result["feat/one"].output_tokens == 10
    assert result["feat/two"].output_tokens == 20
    assert result[""].output_tokens == 30, (
        "records with no branch group under the empty key"
    )


def test_branch_filter_restricts_the_scan(tmp_path):
    records = [_record("a", branch="feat/one"), _record("b", branch="feat/two")]
    result = telemetry.scan([_transcript(tmp_path, records)], branch="feat/one")

    assert list(result) == ["feat/one"]


def test_usage_without_request_id_is_not_a_request(tmp_path):
    """Synthetic records (hook output, local errors) carry usage but no requestId — and no tokens."""
    synthetic = {
        "gitBranch": "feat/x",
        "message": {"model": telemetry.SYNTHETIC_MODEL, "usage": {"output_tokens": 0}},
    }
    result = telemetry.scan([_transcript(tmp_path, [synthetic, _record("real")])])

    assert result["feat/x"].requests == 1, "only the real request counts"
    assert telemetry.SYNTHETIC_MODEL not in result["feat/x"].models


def test_models_and_agents_are_collected_without_duplicates(tmp_path):
    records = [
        _record("a", model="claude-opus-4-8", agent="developer"),
        _record("b", model="claude-opus-4-8", agent="developer"),
        _record("c", model="claude-sonnet-4-6", agent="tester"),
    ]
    entry = telemetry.scan([_transcript(tmp_path, records)])["feat/x"]

    assert entry.models == ["claude-opus-4-8", "claude-sonnet-4-6"]
    assert entry.agents == ["developer", "tester"]


def test_elapsed_spans_first_to_last_record(tmp_path):
    records = [
        _record("a", timestamp="2026-07-27T10:00:00.000Z"),
        _record("b", timestamp="2026-07-27T10:30:00.000Z"),
    ]
    entry = telemetry.scan([_transcript(tmp_path, records)])["feat/x"]

    assert entry.elapsed_seconds == 1800.0


def test_malformed_lines_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                "not json at all",
                json.dumps(_record("good", out=42)),
                "{unclosed",
                "",
                json.dumps(["a list, not an object"]),
            ]
        ),
        encoding="utf-8",
    )
    entry = telemetry.scan([path])["feat/x"]
    assert entry.requests == 1 and entry.output_tokens == 42


def test_missing_file_yields_no_telemetry(tmp_path):
    assert telemetry.scan([tmp_path / "absent.jsonl"]) == {}


def test_non_numeric_usage_contributes_zero(tmp_path):
    record = {
        "requestId": "r",
        "gitBranch": "feat/x",
        "message": {"usage": {"output_tokens": "many", "input_tokens": True}},
    }
    entry = telemetry.scan([_transcript(tmp_path, [record])])["feat/x"]
    # bool is an int subclass — it must not silently count as 1.
    assert entry.output_tokens == 0 and entry.input_tokens == 0


def test_parse_timestamp_accepts_z_suffix():
    """``fromisoformat`` only accepts ``Z`` from 3.11; the kit supports 3.9, so it is normalised."""
    parsed = telemetry.parse_timestamp("2026-07-27T10:00:00.000Z")
    assert parsed == datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)


def test_parse_timestamp_rejects_junk():
    assert telemetry.parse_timestamp("yesterday") is None
    assert telemetry.parse_timestamp(None) is None
    assert telemetry.parse_timestamp("") is None


def test_naive_timestamp_is_treated_as_utc():
    parsed = telemetry.parse_timestamp("2026-07-27T10:00:00")
    assert parsed is not None and parsed.tzinfo is timezone.utc


def test_empty_telemetry_reports_empty():
    entry = telemetry.Telemetry()
    assert entry.empty
    assert entry.elapsed_seconds is None
    assert entry.to_dict()["requests"] == 0


def test_transcript_dir_matches_by_recorded_cwd(tmp_path):
    """The slug is a guess; the recorded ``cwd`` is what confirms it."""
    project = tmp_path / "myproject"
    project.mkdir()
    projects_root = tmp_path / "projects"
    (projects_root / "an-unguessable-name").mkdir(parents=True)
    (projects_root / "an-unguessable-name" / "s.jsonl").write_text(
        json.dumps({"cwd": str(project.resolve())}) + "\n", encoding="utf-8"
    )

    found = telemetry.transcript_dir(project, projects_root)
    assert found is not None and found.name == "an-unguessable-name"


def test_transcript_dir_rejects_a_directory_for_another_project(tmp_path):
    project = tmp_path / "mine"
    project.mkdir()
    projects_root = tmp_path / "projects"
    (projects_root / "theirs").mkdir(parents=True)
    (projects_root / "theirs" / "s.jsonl").write_text(
        json.dumps({"cwd": "/somewhere/else"}) + "\n", encoding="utf-8"
    )

    assert telemetry.transcript_dir(project, projects_root) is None


def test_collect_without_transcripts_is_empty_not_an_error(tmp_path):
    """A project that has never been opened in Claude Code still renders — with no figures."""
    assert telemetry.collect(tmp_path, tmp_path / "no-such-projects-root") == {}


def test_human_tokens_scales():
    assert telemetry.human_tokens(None) == "-"
    assert telemetry.human_tokens(999) == "999"
    assert telemetry.human_tokens(281_000) == "281.0k"
    assert telemetry.human_tokens(46_600_000) == "46.6M"


def test_human_duration_scales():
    assert telemetry.human_duration(None) == "-"
    assert telemetry.human_duration(45) == "45s"
    assert telemetry.human_duration(48 * 60) == "48m"
    assert telemetry.human_duration(72 * 60) == "1h12m"
    assert telemetry.human_duration(51 * 3600) == "2d3h"


def test_agent_name_is_collected_from_non_usage_records(tmp_path):
    """`agentName` marks a subagent turn and can arrive on a record that carries no usage block.

    Reading it only from usage records left the AGENT column structurally unfillable — across every
    transcript on this machine the two fields never co-occurred.
    """
    records = [
        {"gitBranch": "feat/x", "agentName": "senior-backend-dev"},
        _record("r", branch="feat/x", out=50),
    ]
    entry = telemetry.scan([_transcript(tmp_path, records)])["feat/x"]

    assert entry.agents == ["senior-backend-dev"]
    assert entry.requests == 1 and entry.output_tokens == 50


def test_agent_is_credited_only_to_the_branch_its_own_record_names(tmp_path):
    """Transcripts interleave branches and agents; inferring across a file smears them."""
    records = [
        {"gitBranch": "feat/one", "agentName": "tester"},
        {"gitBranch": "feat/two", "agentName": "developer"},
        _record("a", branch="feat/one"),
        _record("b", branch="feat/two"),
    ]
    result = telemetry.scan([_transcript(tmp_path, records)])

    assert result["feat/one"].agents == ["tester"]
    assert result["feat/two"].agents == ["developer"]


def test_agent_only_entry_is_not_treated_as_empty(tmp_path):
    """A named lane with no billed turn yet should still render its agent, not a dash."""
    records = [{"gitBranch": "feat/x", "agentName": "unit-tester"}]
    entry = telemetry.scan([_transcript(tmp_path, records)])["feat/x"]

    assert not entry.empty
    assert entry.requests == 0 and entry.agents == ["unit-tester"]


# --- transcript-directory resolution: the slug fast path and its guards -------------------------


def test_transcript_dir_takes_the_slug_fast_path_when_it_matches(tmp_path):
    """The slug guess is used directly when its transcripts confirm the cwd — no directory scan."""
    project = tmp_path / "myproject"
    project.mkdir()
    projects_root = tmp_path / "projects"
    slug = telemetry.slugify_project(project.resolve())
    (projects_root / slug).mkdir(parents=True)
    (projects_root / slug / "s.jsonl").write_text(
        json.dumps({"cwd": str(project.resolve())}) + "\n", encoding="utf-8"
    )

    found = telemetry.transcript_dir(project, projects_root)
    assert found is not None and found.name == slug


def test_collect_aggregates_from_a_resolved_transcript_dir(tmp_path):
    project = tmp_path / "myproject"
    project.mkdir()
    projects_root = tmp_path / "projects"
    slug = telemetry.slugify_project(project.resolve())
    (projects_root / slug).mkdir(parents=True)
    (projects_root / slug / "s.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"cwd": str(project.resolve())}),
                json.dumps(_record("req-1", branch="feat/telemetry")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    by_branch = telemetry.collect(project, projects_root)
    assert by_branch["feat/telemetry"].requests == 1


def test_read_cwd_stops_after_the_scan_budget(tmp_path):
    """A huge transcript must not be read end to end just to find a cwd that isn't near the top."""
    path = tmp_path / "s.jsonl"
    filler = [json.dumps({"type": "noise", "i": i}) for i in range(200)]
    filler.append(json.dumps({"cwd": "/late/and/ignored"}))
    path.write_text("\n".join(filler) + "\n", encoding="utf-8")

    assert telemetry._read_cwd(path) is None


def test_read_cwd_skips_unparseable_and_non_string_entries(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                "{ not json",
                json.dumps(["a", "list", "not", "an", "object"]),
                json.dumps({"cwd": 7}),
                json.dumps({"cwd": ""}),
                json.dumps({"cwd": "/the/real/one"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert telemetry._read_cwd(path) == "/the/real/one"


def test_dir_matches_keeps_looking_past_transcripts_with_no_cwd(tmp_path):
    """A transcript that records no cwd is uninformative, not a rejection of the directory."""
    project = tmp_path / "mine"
    project.mkdir()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    silent = candidate / "a.jsonl"
    silent.write_text(json.dumps({"type": "noise"}) + "\n", encoding="utf-8")
    speaking = candidate / "b.jsonl"
    speaking.write_text(
        json.dumps({"cwd": str(project.resolve())}) + "\n", encoding="utf-8"
    )
    os.utime(silent, (2, 2))  # newest first → the silent one is examined first
    os.utime(speaking, (1, 1))

    assert telemetry._dir_matches(candidate, project.resolve())


def test_scan_skips_records_whose_message_is_not_an_object(tmp_path):
    """A non-mapping `message` must be skipped, not crash the scan (F-034).

    `record.get("message", {})` guards the key being absent and not its holding the wrong type, so
    a line like {"message": 3} used to raise AttributeError out of a read-only reporting command --
    in a module whose contract for this file is to skip anything unreadable.
    """
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"message": 3, "gitBranch": "feat/x"}),
                json.dumps({"message": "a string", "gitBranch": "feat/x"}),
                json.dumps({"message": [1, 2], "gitBranch": "feat/x"}),
                json.dumps(_record("req-1", branch="feat/x")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    by_branch = telemetry.scan([path])

    # the one well-formed record still lands, and the three malformed ones are simply not counted
    assert by_branch["feat/x"].requests == 1
