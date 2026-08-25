from datetime import datetime, timezone

from estop_audit.events import parse_event
from estop_audit.records import (
    AMENDMENT_EVENT_TYPE,
    attach_per_axis_measurement,
    build_record,
    collect_amendments,
    record_id_for,
)
from estop_audit.sequences import pair_stops, partition_runs
from estop_audit.store import AppendOnlyAuditStore

from .conftest import ev

AXES = ["j1", "j2", "j3", "j4", "j5", "j6"]

SAMPLE_SHAPED = [
    ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1", axisInMotion=True),
    ev(34, "motion.halted", panelId="EW-L1-E1", axesStopped=AXES),
    ev(35, "interlock.engaged", zone="assembly_table"),
    ev(37, "run.paused", reason="estop"),
    ev(277, "interlock.released", zone="assembly_table", operator="op-114"),
    ev(295, "run.resumed", resumeMode="from_panel_start", panelId="EW-L1-E1"),
]


def records_from(raws):
    runs = partition_runs([parse_event(raw) for raw in raws])
    built = []
    for run in runs:
        for sequence in pair_stops(run):
            built.append(build_record(sequence, run, all_runs=runs))
    return built


def test_a_matched_record_carries_the_bound_not_a_bare_number():
    [record] = records_from(SAMPLE_SHAPED)
    assert record["outcome"] == "matched"
    assert record["response_time"]["nominal_seconds"] == 1.0
    assert record["response_time"]["upper_bound_seconds_exclusive"] == 2.0
    assert record["response_time"]["defensible_claim"] == "stop response < 2 s"


def test_a_matched_record_reports_per_axis_as_unavailable_with_the_axes_listed():
    [record] = records_from(SAMPLE_SHAPED)
    assert record["per_axis"]["status"] == "unavailable_from_source"
    assert record["per_axis"]["axes_reported_stopped"] == AXES
    assert record["per_axis"]["measurements"] == []


def test_a_matched_record_classifies_the_estop_pause_as_safety():
    [record] = records_from(SAMPLE_SHAPED)
    assert record["context"]["pause"]["classification"] == "safety"
    assert record["context"]["resume"]["resume_mode"] == "from_panel_start"


def test_stoppage_duration_is_bounded_like_every_other_interval():
    [record] = records_from(SAMPLE_SHAPED)
    duration = record["context"]["stoppage_duration"]
    assert duration["nominal_seconds"] == 258.0
    assert duration["lower_bound_seconds_exclusive"] == 257.0
    assert duration["upper_bound_seconds_exclusive"] == 259.0


def test_interlock_events_are_gathered_into_context():
    [record] = records_from(SAMPLE_SHAPED)
    assert record["context"]["interlock_engaged"][0]["zone"] == "assembly_table"
    assert record["context"]["interlock_released"][0]["operator"] == "op-114"


def test_a_truncated_run_is_mirrored_on_the_record():
    [record] = records_from(SAMPLE_SHAPED)
    assert record["run_truncated"] is True
    assert record["evidence_status"] == "complete"
    assert record["episode"]["closed_by"] == "run.resumed"


def test_an_unmatched_request_has_no_response_time():
    [record] = records_from([ev(33, "stop.requested"), ev(60, "run.completed")])
    assert record["outcome"] == "no_halt_recorded"
    assert record["response_time"] is None
    assert record["motion_halt"] is None


def test_a_cross_run_halt_is_surfaced_as_context_and_refused_as_evidence():
    records = records_from([
        ev(33, "stop.requested", run="RUN-A"),
        ev(60, "run.completed", run="RUN-A"),
        ev(34, "motion.halted", run="RUN-B", axesStopped=AXES),
    ])
    unmatched = next(r for r in records if r["outcome"] == "no_halt_recorded")
    [candidate] = unmatched["context"]["cross_run_halt_candidates"]
    assert candidate["run_id"] == "RUN-B"
    assert candidate["not_counted_as_evidence"] is True


def test_cross_run_candidates_disclose_their_pre_truncation_total():
    # _MAX_CROSS_RUN_CANDIDATES caps the list at 3. Five qualifying halts must
    # still be countable: the list is cut for readability, but the cut must be
    # visible, not silent -- an inspector shown 3 of 8 must not conclude those
    # are all of them.
    raws = [ev(33, "stop.requested", run="RUN-A"), ev(60, "run.completed", run="RUN-A")]
    for offset, run in enumerate(["RUN-B", "RUN-C", "RUN-D", "RUN-E", "RUN-F"]):
        raws.append(ev(34 + offset, "motion.halted", run=run, axesStopped=AXES))
    records = records_from(raws)
    unmatched = next(r for r in records if r["outcome"] == "no_halt_recorded")
    context = unmatched["context"]
    assert context["cross_run_halt_candidates_total"] == 5
    assert len(context["cross_run_halt_candidates"]) == 3


def test_record_ids_namespace_requests_and_orphan_halts_apart():
    records = records_from([ev(33, "stop.requested"), ev(60, "run.completed")])
    orphans = records_from([ev(33, "motion.halted", axesStopped=AXES),
                            ev(60, "run.completed")])
    assert ":req:" in records[0]["record_id"]
    assert ":halt:" in orphans[0]["record_id"]


def test_a_null_run_id_renders_in_the_record_id_and_the_run_scope():
    [record] = records_from([ev(33, "stop.requested", run=None)])
    assert record["run_scope"] == "outside_run"
    assert ":-:" in record["record_id"]


def test_fan_out_is_disclosed_on_the_record():
    records = records_from([
        ev(0, "stop.requested", source="operator_estop"),
        ev(1, "stop.requested", source="light_curtain"),
        ev(2, "motion.halted", axesStopped=AXES),
        ev(10, "run.resumed"),
    ])
    assert len(records) == 2
    assert all(len(r["episode"]["co_satisfied_with"]) == 1 for r in records)


def test_an_amendment_is_appended_to_the_store_never_a_mutation(tmp_path, clock):
    store = AppendOnlyAuditStore(tmp_path / "events.jsonl", clock=clock)
    for raw in SAMPLE_SHAPED:
        store.append(raw)

    runs = partition_runs([r.event for r in store])
    [sequence] = pair_stops(runs[0])
    record_id = record_id_for(sequence, runs[0])

    before = len(list(store))
    attach_per_axis_measurement(
        store,
        record_id=record_id,
        cell_id="CELL-01",
        run_id="RUN-A",
        measurements=[{"axis": "j1", "delta_seconds": 0.041}],
        source="rig",
        attested_by="chris",
        measured_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert len(list(store)) == before + 1
    assert store.verify_chain().ok is True
    assert list(store)[-1].event.type == AMENDMENT_EVENT_TYPE


def test_a_same_second_tie_reaches_the_record_as_ambiguous():
    # The pairing layer spent five review rounds getting same-second tie
    # disclosures right. If this layer drops or rewords them, all of that work
    # becomes invisible to the inspector -- so it is pinned here, not assumed.
    [record] = records_from([
        ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1"),
        ev(33, "motion.halted", panelId="EW-L1-E1", axesStopped=AXES),
        ev(295, "run.resumed", resumeMode="from_panel_start"),
    ])
    assert record["confidence"]["ordering"] == "ambiguous"
    notes = record["confidence"]["notes"]
    assert notes, "the tie note must survive into the record"
    assert any("not determinable" in note for note in notes)
    # and the measurement must refuse to assert an order it cannot establish
    assert record["response_time"]["causal_order_established"] is False


def test_the_per_axis_reason_and_expected_source_are_on_the_record():
    # Part of the inspector-facing contract: the record must say WHY per-axis is
    # unavailable and where the numbers would come from, not merely omit them.
    [record] = records_from(SAMPLE_SHAPED)
    assert "single timestamp" in record["per_axis"]["reason"]
    assert "rig" in record["per_axis"]["expected_source"]


def test_an_attached_measurement_is_folded_into_the_record(tmp_path, clock):
    store = AppendOnlyAuditStore(tmp_path / "events.jsonl", clock=clock)
    for raw in SAMPLE_SHAPED:
        store.append(raw)
    runs = partition_runs([r.event for r in store])
    [sequence] = pair_stops(runs[0])
    record_id = record_id_for(sequence, runs[0])
    attach_per_axis_measurement(
        store,
        record_id=record_id,
        cell_id="CELL-01",
        run_id="RUN-A",
        measurements=[{"axis": "j1", "delta_seconds": 0.041}],
        source="rig",
        attested_by="chris",
        measured_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
    )

    events = [r.event for r in store]
    runs = partition_runs(events)
    amendments = collect_amendments(events)
    stop_run = next(run for run in runs if run.run_id == "RUN-A")
    [sequence] = [s for s in pair_stops(stop_run) if s.outcome == "matched"]
    record = build_record(sequence, stop_run, all_runs=runs, amendments=amendments)

    assert record["per_axis"]["status"] == "supplied_by_amendment"
    assert record["per_axis"]["measurements"][0]["axis"] == "j1"
    assert record["amendments"][0]["source"] == "rig"
    assert record["amendments"][0]["attested_by"] == "chris"


def test_an_amendment_with_a_dict_record_id_is_skipped_a_valid_one_still_folds_in():
    # recordId is a payload field, not type-checked by parse_event. A dict
    # recordId would be used as a dict key via indexed.setdefault below and
    # raise a TypeError -- unrecoverable on an append-only store. It must be
    # skipped exactly as a missing (None) recordId already is, and it must
    # not cost the valid amendment alongside it in the same stream.
    events = [
        parse_event(
            ev(
                40,
                AMENDMENT_EVENT_TYPE,
                recordId={"oops": 1},
                source="rig",
                attestedBy="chris",
                measurements=[{"axis": "j1", "delta_seconds": 0.041}],
            )
        ),
        parse_event(
            ev(
                41,
                AMENDMENT_EVENT_TYPE,
                recordId="CELL-01:RUN-A:req:abcdef123456",
                source="rig",
                attestedBy="chris",
                measurements=[{"axis": "j2", "delta_seconds": 0.05}],
            )
        ),
    ]

    amendments = collect_amendments(events)

    assert amendments == {
        "CELL-01:RUN-A:req:abcdef123456": [
            {
                "ts": "2026-03-11T07:15:41Z",
                "source": "rig",
                "attested_by": "chris",
                "measurements": [{"axis": "j2", "delta_seconds": 0.05}],
                "event_key": events[1].key,
            }
        ]
    }
