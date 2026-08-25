import json
from datetime import datetime, timezone

from estop_audit.service import EstopAuditService
from estop_audit.store import AppendOnlyAuditStore

from .conftest import at, ev

AXES = ["j1", "j2", "j3", "j4", "j5", "j6"]


def service(tmp_path, clock):
    return EstopAuditService(AppendOnlyAuditStore(tmp_path / "events.jsonl", clock=clock))


def lines_for(raws):
    return [json.dumps(raw) for raw in raws]


def test_ingest_counts_what_it_appended(tmp_path, clock):
    report = service(tmp_path, clock).ingest_lines(lines_for([ev(0, "run.started")]))
    assert report.lines_read == 1
    assert report.events_appended == 1
    assert report.duplicates_skipped == 0
    assert report.content_collisions == 0


def test_re_ingesting_the_same_stream_appends_nothing(tmp_path, clock):
    svc = service(tmp_path, clock)
    raws = [ev(0, "run.started"), ev(1, "panel.started", panelId="P1")]
    svc.ingest_lines(lines_for(raws))
    second = svc.ingest_lines(lines_for(raws))
    assert second.events_appended == 0
    assert second.duplicates_skipped == 2
    assert second.content_collisions == 0


def test_a_repeat_within_one_batch_is_a_collision_not_a_duplicate(tmp_path, clock):
    # Distinguishing these two is the whole point: a duplicate across calls is
    # re-ingest working; a repeat inside one batch may be a distinct event that
    # the content-hash key cannot see. It is counted, not hidden.
    raw = ev(0, "run.started")
    report = service(tmp_path, clock).ingest_lines(lines_for([raw, raw]))
    assert report.events_appended == 1
    assert report.content_collisions == 1
    assert report.duplicates_skipped == 0


def test_a_malformed_line_is_reported_and_does_not_cost_the_rest(tmp_path, clock):
    report = service(tmp_path, clock).ingest_lines(
        [json.dumps(ev(0, "run.started")), "{not json", json.dumps(ev(1, "run.paused"))]
    )
    assert report.events_appended == 2
    assert len(report.malformed) == 1
    assert report.malformed[0][0] == 2


def test_a_non_string_cell_id_is_reported_malformed_and_never_reaches_the_store(tmp_path, clock):
    # A non-string cellId becomes a dict key downstream (Event.scope,
    # partition_runs) and would poison the append-only chain forever if it
    # were ever persisted -- there is no way to remove it afterwards. It must
    # be caught here, before the store ever sees it.
    svc = service(tmp_path, clock)
    good = json.dumps(ev(0, "run.started"))
    bad = json.dumps({"ts": "2026-03-11T07:15:00Z", "cellId": {"oops": 1}, "event": "run.started"})
    report = svc.ingest_lines([good, bad])
    assert report.events_appended == 1
    assert len(report.malformed) == 1
    assert report.malformed[0][0] == 2
    assert len(svc.query_events()) == 1


def test_blank_lines_are_ignored_silently(tmp_path, clock):
    report = service(tmp_path, clock).ingest_lines(
        ["", json.dumps(ev(0, "run.started")), "   ", ""]
    )
    assert report.lines_read == 1
    assert report.malformed == []


def test_stop_records_filter_by_cell(tmp_path, clock):
    svc = service(tmp_path, clock)
    svc.ingest_lines(lines_for([
        ev(0, "stop.requested", cell="CELL-01"),
        ev(1, "motion.halted", cell="CELL-01", axesStopped=AXES),
        ev(0, "stop.requested", cell="CELL-02"),
        ev(1, "motion.halted", cell="CELL-02", axesStopped=AXES),
    ]))
    assert [r["cell_id"] for r in svc.stop_records(cell_id="CELL-02")] == ["CELL-02"]


def test_stop_records_filter_on_the_anchor_so_a_sequence_is_never_split(tmp_path, clock):
    svc = service(tmp_path, clock)
    svc.ingest_lines(lines_for([
        ev(33, "stop.requested"),
        ev(34, "motion.halted", axesStopped=AXES),
        ev(60, "run.resumed"),
    ]))

    def parsed(literal):
        return datetime.fromisoformat(literal).astimezone(timezone.utc)

    # A window that ends between the request and the halt still yields the whole record.
    assert len(svc.stop_records(start=parsed(at(0)), end=parsed(at(34)))) == 1
    # A window starting after the request excludes it entirely.
    assert svc.stop_records(start=parsed(at(34))) == []


def test_stop_records_are_ordered_by_anchor(tmp_path, clock):
    svc = service(tmp_path, clock)
    svc.ingest_lines(lines_for([
        ev(100, "stop.requested"), ev(101, "motion.halted", axesStopped=AXES),
        ev(110, "run.resumed"),
        ev(0, "stop.requested"), ev(1, "motion.halted", axesStopped=AXES),
        ev(10, "run.resumed"),
    ]))
    anchors = [r["anchor_ts"] for r in svc.stop_records()]
    assert anchors == sorted(anchors)


def test_query_events_exposes_the_raw_store_for_a2_retrieval(tmp_path, clock):
    svc = service(tmp_path, clock)
    svc.ingest_lines(lines_for([ev(0, "run.started"), ev(1, "panel.started", panelId="P1")]))
    assert len(svc.query_events(cell_id="CELL-01")) == 2


def test_ingest_file_reads_from_disk(tmp_path, clock):
    source = tmp_path / "stream.jsonl"
    source.write_text("\n".join(lines_for([ev(0, "run.started")])) + "\n")
    assert service(tmp_path, clock).ingest_file(source).events_appended == 1


def test_a_dict_pause_reason_is_appended_and_stop_records_does_not_raise(tmp_path, clock):
    # The primary e-stop path: run.paused with reason="estop" is what a real
    # e-stop emits. reason is a payload field, deliberately not type-checked
    # by parse_event -- rejecting the whole event over one malformed field
    # would discard genuine safety evidence for a legitimate stop sequence.
    # But an unguarded reason lookup would use it as a dict key downstream
    # (classify_pause -> PAUSE_CLASSIFICATION.get), raising a TypeError that
    # would kill every subsequent stop_records() call on this append-only
    # store. This must not happen: the event is appended, the chain stays
    # intact, and stop_records() returns the record with the pause
    # classified unclassified rather than raising.
    svc = service(tmp_path, clock)
    report = svc.ingest_lines(lines_for([
        ev(33, "stop.requested"),
        ev(34, "motion.halted", axesStopped=AXES),
        ev(37, "run.paused", reason={"x": 1}),
    ]))
    assert report.events_appended == 3
    assert report.malformed == []
    assert svc.verify_chain().ok

    [record] = svc.stop_records()
    assert record["outcome"] == "matched"
    assert record["context"]["pause"]["classification"] == "unclassified"
