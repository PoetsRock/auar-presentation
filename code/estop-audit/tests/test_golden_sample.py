"""End-to-end assertions against the real March 2026 trial stream.

Everything asserted here is a claim we would make to an external inspector.
"""

import json
from pathlib import Path

import pytest

from estop_audit.events import parse_event
from estop_audit.sequences import classify_pause
from estop_audit.service import EstopAuditService
from estop_audit.store import AppendOnlyAuditStore

SAMPLE = Path(__file__).resolve().parents[1] / "cell-events.jsonl"


@pytest.fixture
def ingested(tmp_path, clock):
    service = EstopAuditService(AppendOnlyAuditStore(tmp_path / "audit.jsonl", clock=clock))
    report = service.ingest_file(SAMPLE)
    return service, report


def test_the_whole_sample_ingests_cleanly(ingested):
    _, report = ingested
    assert report.lines_read == 29
    assert report.events_appended == 29
    assert report.malformed == []
    assert report.content_collisions == 0


def test_re_ingesting_the_sample_is_a_no_op(ingested, tmp_path):
    service, _ = ingested
    before = service.verify_chain()
    second = service.ingest_file(SAMPLE)
    assert second.events_appended == 0
    assert second.duplicates_skipped == 29
    assert before.ok and service.verify_chain().ok


def test_the_sample_contains_exactly_one_stop_sequence(ingested):
    service, _ = ingested
    records = service.stop_records()
    assert len(records) == 1


def test_the_stop_sequence_is_matched_and_bounded_under_two_seconds(ingested):
    service, _ = ingested
    [record] = service.stop_records()
    assert record["cell_id"] == "CELL-01"
    assert record["run_id"] == "RUN-2026-03-11-A"
    assert record["outcome"] == "matched"
    assert record["stop_request"]["source"] == "operator_estop"
    assert record["stop_request"]["ts"] == "2026-03-11T07:15:33Z"
    assert record["motion_halt"]["ts"] == "2026-03-11T07:15:34Z"

    measured = record["response_time"]
    assert measured["nominal_seconds"] == 1.0
    assert measured["lower_bound_seconds_exclusive"] == 0.0
    assert measured["upper_bound_seconds_exclusive"] == 2.0
    assert measured["source_resolution_seconds"] == 1.0
    assert measured["causal_order_established"] is True
    assert measured["defensible_claim"] == "stop response < 2 s"


def test_per_axis_is_unavailable_with_all_six_axes_recorded(ingested):
    service, _ = ingested
    [record] = service.stop_records()
    assert record["per_axis"]["status"] == "unavailable_from_source"
    assert record["per_axis"]["axes_reported_stopped"] == [
        "j1", "j2", "j3", "j4", "j5", "j6"
    ]


def test_the_run_is_truncated_but_the_stop_episode_is_fully_evidenced(ingested):
    # These come apart, and the sample is the proof: no run.completed anywhere,
    # yet the stop episode closed cleanly on an observed run.resumed at 07:19:55.
    service, _ = ingested
    [record] = service.stop_records()
    assert record["run_truncated"] is True
    assert record["evidence_status"] == "complete"
    assert record["episode"]["closed_by"] == "run.resumed"
    assert record["episode"]["co_satisfied_with"] == []


def test_the_estop_pause_is_safety_and_the_reload_pause_is_not(ingested):
    service, _ = ingested
    [record] = service.stop_records()
    assert record["context"]["pause"]["reason"] == "estop"
    assert record["context"]["pause"]["classification"] == "safety"

    pauses = [
        parse_event(json.loads(line))
        for line in SAMPLE.read_text().splitlines()
        if line.strip() and json.loads(line)["event"] == "run.paused"
    ]
    assert [classify_pause(pause) for pause in pauses] == ["safety", "operational"]


def test_the_routine_reload_pause_produces_no_stop_record(ingested):
    service, _ = ingested
    anchors = [record["anchor_ts"] for record in service.stop_records()]
    assert "2026-03-11T07:22:48Z" not in anchors


def test_the_surrounding_context_is_captured(ingested):
    service, _ = ingested
    [record] = service.stop_records()
    context = record["context"]
    assert context["interlock_engaged"][0]["ts"] == "2026-03-11T07:15:35Z"
    assert context["interlock_released"][0]["operator"] == "op-114"
    assert context["resume"]["resume_mode"] == "from_panel_start"
    assert context["stoppage_duration"]["nominal_seconds"] == 258.0
    assert context["stoppage_duration"]["upper_bound_seconds_exclusive"] == 259.0


def test_the_rendered_page_states_the_limit_not_the_nominal(ingested):
    service, _ = ingested
    [record] = service.stop_records()
    page = service.render(record)
    assert "stop response < 2 s" in page
    assert "unavailable from this source" in page
    assert "[SAFETY]" in page


def test_the_audit_store_verifies_after_a_full_ingest(ingested):
    service, _ = ingested
    assert service.verify_chain().ok is True
