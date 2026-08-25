import pytest

from estop_audit.events import parse_event
from estop_audit.sequences import (
    classify_pause,
    pair_stops,
    partition_runs,
    split_episodes,
)

from .conftest import ev


def events(*raws):
    return [parse_event(raw) for raw in raws]


def only_run(raws):
    runs = partition_runs(events(*raws))
    assert len(runs) == 1
    return runs[0]


# --- pause classification ---------------------------------------------------

def test_estop_pause_is_classified_safety():
    assert classify_pause(parse_event(ev(0, "run.paused", reason="estop"))) == "safety"


def test_material_reload_pause_is_classified_operational():
    event = parse_event(ev(0, "run.paused", reason="material_reload"))
    assert classify_pause(event) == "operational"


def test_an_unknown_pause_reason_is_unclassified_never_operational():
    event = parse_event(ev(0, "run.paused", reason="tool_change"))
    assert classify_pause(event) == "unclassified"


def test_a_missing_pause_reason_is_unclassified():
    assert classify_pause(parse_event(ev(0, "run.paused"))) == "unclassified"


def test_a_dict_pause_reason_is_unclassified_not_a_crash():
    # reason is a payload field; parse_event deliberately does not type-check
    # it. A dict reason must not reach PAUSE_CLASSIFICATION.get() as a key --
    # dicts are unhashable, and that would raise a TypeError that kills every
    # subsequent stop_records() call on an append-only store.
    event = parse_event(ev(0, "run.paused", reason={"x": 1}))
    assert classify_pause(event) == "unclassified"


def test_a_list_pause_reason_is_unclassified_not_a_crash():
    event = parse_event(ev(0, "run.paused", reason=["estop"]))
    assert classify_pause(event) == "unclassified"


def test_an_int_pause_reason_is_unclassified_not_a_crash():
    event = parse_event(ev(0, "run.paused", reason=1))
    assert classify_pause(event) == "unclassified"


def test_the_reason_guard_is_not_a_blanket_return_estop_and_material_reload_still_classify():
    # Counterexample to the fixes above: the non-string guard must not have
    # swallowed the real classification logic.
    assert classify_pause(parse_event(ev(0, "run.paused", reason="estop"))) == "safety"
    assert (
        classify_pause(parse_event(ev(0, "run.paused", reason="material_reload")))
        == "operational"
    )


# --- partitioning -----------------------------------------------------------

def test_partition_key_is_cell_and_run_not_run_alone():
    runs = partition_runs(events(
        ev(0, "controller.booted", cell="CELL-01", run=None),
        ev(0, "controller.booted", cell="CELL-02", run=None),
    ))
    assert {r.scope for r in runs} == {("CELL-01", None), ("CELL-02", None)}


def test_partitioning_sorts_by_timestamp_regardless_of_arrival_order():
    run = only_run([ev(20, "panel.completed", panelId="B"),
                    ev(0, "panel.started", panelId="A")])
    assert [e.raw["panelId"] for e in run.events] == ["A", "B"]


def test_a_run_without_run_completed_is_truncated():
    assert only_run([ev(0, "run.started")]).truncated is True


def test_a_run_with_run_completed_is_not_truncated():
    run = only_run([ev(0, "run.started"), ev(10, "run.completed")])
    assert run.completed is True
    assert run.truncated is False


# --- episode splitting ------------------------------------------------------

def test_run_resumed_closes_an_episode():
    run = only_run([ev(0, "stop.requested"), ev(1, "motion.halted"),
                    ev(10, "run.resumed"), ev(20, "stop.requested")])
    episodes = split_episodes(run)
    assert len(episodes) == 2
    assert episodes[0][1].type == "run.resumed"
    assert episodes[1][1] is None


# --- pairing ----------------------------------------------------------------

def test_a_simple_pair_is_matched():
    run = only_run([ev(33, "stop.requested", source="operator_estop"),
                    ev(34, "motion.halted", axesStopped=["j1"]),
                    ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "matched"
    assert sequence.evidence_status == "complete"
    assert sequence.co_satisfied_with == ()
    assert sequence.episode_closed_by == "run.resumed"


def test_two_sequential_stops_produce_two_independent_matches():
    run = only_run([ev(0, "stop.requested"), ev(1, "motion.halted"),
                    ev(10, "run.resumed"),
                    ev(20, "stop.requested"), ev(22, "motion.halted"),
                    ev(30, "run.resumed")])
    first, second = pair_stops(run)
    assert first.outcome == second.outcome == "matched"
    assert (first.halt.ts - first.request.ts).total_seconds() == 1
    assert (second.halt.ts - second.request.ts).total_seconds() == 2
    assert first.co_satisfied_with == second.co_satisfied_with == ()


def test_one_halt_satisfies_every_outstanding_request_fan_out():
    run = only_run([ev(0, "stop.requested", source="operator_estop"),
                    ev(1, "stop.requested", source="light_curtain"),
                    ev(2, "motion.halted"),
                    ev(10, "run.resumed")])
    sequences = pair_stops(run)
    assert len(sequences) == 2
    assert {s.outcome for s in sequences} == {"matched"}
    assert {s.halt.key for s in sequences} == {sequences[0].halt.key}
    # each names the other, and neither is falsely reported unmatched
    assert sequences[0].co_satisfied_with == (sequences[1].request.key,)
    assert sequences[1].co_satisfied_with == (sequences[0].request.key,)
    # the earliest demand yields the largest, most conservative delta
    deltas = [(s.halt.ts - s.request.ts).total_seconds() for s in sequences]
    assert deltas == [2, 1]


def test_the_inversion_guard_a_failed_stop_never_pairs_with_a_later_halt():
    # An unbounded FIFO implementation fails this test, which is why it exists:
    # it would pair R1 with the distant halt, reporting the FAILED stop as
    # matched and the SUCCESSFUL stop as no_halt_recorded -- both wrong, in the
    # worst available direction.
    run = only_run([
        ev(0, "stop.requested", source="operator_estop"),   # never answered
        ev(120, "run.resumed"),                             # episode closes
        ev(6000, "stop.requested", source="operator_estop"),
        ev(6001, "motion.halted"),
        ev(6060, "run.resumed"),
    ])
    failed, succeeded = pair_stops(run)
    assert failed.outcome == "no_halt_recorded"
    assert failed.evidence_status == "complete"
    assert failed.episode_closed_by == "run.resumed"
    assert succeeded.outcome == "matched"
    assert (succeeded.halt.ts - succeeded.request.ts).total_seconds() == 1


def test_a_halt_in_a_fresh_episode_starts_from_an_empty_queue():
    run = only_run([ev(0, "stop.requested"), ev(10, "run.resumed"),
                    ev(20, "motion.halted"), ev(30, "run.resumed")])
    unanswered, orphan = pair_stops(run)
    assert unanswered.outcome == "no_halt_recorded"
    assert orphan.outcome == "orphan_halt"
    assert orphan.request is None


def test_a_halt_with_no_preceding_request_is_an_orphan():
    run = only_run([ev(0, "motion.halted", axesStopped=["j1"]), ev(10, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "orphan_halt"
    assert sequence.evidence_status == "complete"
    assert sequence.anchor.type == "motion.halted"


def test_a_request_open_at_stream_end_is_truncated_not_a_finding():
    run = only_run([ev(0, "run.started"), ev(33, "stop.requested")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "no_halt_recorded"
    assert sequence.evidence_status == "truncated"
    assert sequence.episode_closed_by == "stream_end"


def test_a_request_open_at_an_observed_close_is_complete_not_truncated():
    run = only_run([ev(33, "stop.requested"), ev(60, "run.completed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "no_halt_recorded"
    assert sequence.evidence_status == "complete"
    assert sequence.episode_closed_by == "run.completed"


def test_a_matched_record_is_complete_even_when_the_stream_ends_after_it():
    # A halt observed is a halt observed. No later data can unsay it.
    run = only_run([ev(33, "stop.requested"), ev(34, "motion.halted")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "matched"
    assert sequence.evidence_status == "complete"
    assert sequence.episode_closed_by == "stream_end"


def test_a_same_second_pair_is_flagged_ordering_ambiguous():
    run = only_run([ev(33, "stop.requested"), ev(33, "motion.halted"),
                    ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.ordering_confidence == "ambiguous"
    assert any("share timestamp" in note for note in sequence.notes)


def test_a_halt_never_crosses_a_run_boundary():
    runs = partition_runs(events(
        ev(0, "stop.requested", run="RUN-A"),
        ev(1, "motion.halted", run="RUN-B"),
    ))
    by_run = {run.run_id: pair_stops(run) for run in runs}
    assert by_run["RUN-A"][0].outcome == "no_halt_recorded"
    assert by_run["RUN-B"][0].outcome == "orphan_halt"


def test_a_same_second_pair_is_matched_regardless_of_arrival_order():
    # Identical events, arrival order swapped. Whole-second timestamps cannot
    # order them, so the outcome must not depend on which line came first. Before
    # this was fixed, the reversed order produced orphan_halt + no_halt_recorded,
    # both claiming "unambiguous" -- a fabricated safety finding asserting more
    # confidence than the correct answer.
    forward = only_run([ev(33, "stop.requested"), ev(33, "motion.halted"),
                        ev(60, "run.resumed")])
    backward = only_run([ev(33, "motion.halted"), ev(33, "stop.requested"),
                         ev(60, "run.resumed")])
    for run in (forward, backward):
        [sequence] = pair_stops(run)
        assert sequence.outcome == "matched"
        assert sequence.ordering_confidence == "ambiguous"


def test_a_halt_sharing_a_second_with_its_episode_close_is_not_orphaned():
    run = only_run([ev(33, "stop.requested"), ev(60, "run.resumed"),
                    ev(60, "motion.halted")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "matched"
    assert sequence.ordering_confidence == "ambiguous"
    assert any("episode close" in note for note in sequence.notes)


def test_ambiguity_notes_name_the_tied_events():
    run = only_run([ev(33, "stop.requested"), ev(33, "motion.halted"),
                    ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    joined = " ".join(sequence.notes)
    assert sequence.request.key in joined
    assert sequence.halt.key in joined


def test_fan_out_across_three_requests_names_all_the_others():
    run = only_run([ev(0, "stop.requested", source="operator_estop"),
                    ev(1, "stop.requested", source="light_curtain"),
                    ev(2, "stop.requested", source="remote"),
                    ev(3, "motion.halted"),
                    ev(10, "run.resumed")])
    sequences = pair_stops(run)
    assert len(sequences) == 3
    for sequence in sequences:
        assert len(sequence.co_satisfied_with) == 2
        assert sequence.request.key not in sequence.co_satisfied_with


def test_every_record_names_the_event_that_closed_its_episode():
    run = only_run([ev(0, "stop.requested"), ev(1, "motion.halted"),
                    ev(10, "run.resumed")])
    [sequence] = pair_stops(run)
    closer = next(e for e in run.events if e.type == "run.resumed")
    assert sequence.episode_closed_by_event_key == closer.key
    assert sequence.episode_events  # Task 5 builds its context window from these


def test_a_request_anchored_record_anchors_on_the_request():
    run = only_run([ev(33, "stop.requested"), ev(34, "motion.halted"),
                    ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.anchor is sequence.request


def test_run_completed_mid_run_closes_an_episode_and_a_second_one_follows():
    run = only_run([ev(0, "stop.requested"), ev(5, "run.completed"),
                    ev(20, "stop.requested"), ev(21, "motion.halted")])
    first, second = pair_stops(run)
    assert first.outcome == "no_halt_recorded"
    assert first.episode_closed_by == "run.completed"
    assert first.evidence_status == "complete"
    assert second.outcome == "matched"
    assert second.episode_closed_by == "stream_end"


def test_run_scope_distinguishes_in_run_from_outside_run():
    assert only_run([ev(0, "run.started")]).run_scope == "in_run"
    outside = partition_runs(events(ev(0, "controller.booted", run=None)))[0]
    assert outside.run_scope == "outside_run"


def test_classify_pause_refuses_a_non_pause_event():
    with pytest.raises(ValueError):
        classify_pause(parse_event(ev(0, "run.resumed")))


def test_a_request_tied_with_its_episode_closer_is_carried_forward_not_failed():
    # Unorderable: the demand may have been raised just before the resume and gone
    # unanswered, or just after it and belong to what follows. Publishing the first
    # reading would fabricate a "the cell did not stop" finding on a tiebreak.
    for raws in (
        [ev(60, "run.resumed"), ev(60, "stop.requested"), ev(61, "motion.halted")],
        [ev(60, "stop.requested"), ev(60, "run.resumed"), ev(61, "motion.halted")],
    ):
        [sequence] = pair_stops(only_run(raws))
        assert sequence.outcome == "matched"
        assert sequence.ordering_confidence == "ambiguous"
        assert any("carried forward" in note for note in sequence.notes)


def test_a_carried_request_that_is_never_answered_still_discloses_the_tie():
    run = only_run([ev(60, "run.resumed"), ev(60, "stop.requested")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "no_halt_recorded"
    assert sequence.evidence_status == "truncated"
    assert sequence.ordering_confidence == "ambiguous"


def test_an_orphan_halt_produced_by_a_same_second_tie_is_not_called_unambiguous():
    run = only_run([ev(10, "stop.requested"), ev(10, "motion.halted"),
                    ev(10, "stop.requested"), ev(10, "motion.halted"),
                    ev(60, "run.resumed")])
    sequences = pair_stops(run)
    orphans = [s for s in sequences if s.outcome == "orphan_halt"]
    assert orphans, "expected the second halt in the tied group to be an orphan"
    for orphan in orphans:
        assert orphan.ordering_confidence == "ambiguous"
        assert any("not determinable" in note for note in orphan.notes)


def test_an_orphan_halt_with_no_tie_remains_unambiguous():
    run = only_run([ev(0, "motion.halted"), ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "orphan_halt"
    assert sequence.ordering_confidence == "unambiguous"


def test_a_request_tied_with_both_a_halt_and_the_closer_stays_and_matches():
    # A halt in the same second CAN answer the request, so carrying the request
    # forward would tear apart a pairing the data supports and republish it as a
    # failure. Every arrival order of the three tied events must agree.
    orders = [
        [ev(10, "stop.requested"), ev(10, "motion.halted"), ev(10, "run.resumed")],
        [ev(10, "run.resumed"), ev(10, "stop.requested"), ev(10, "motion.halted")],
        [ev(10, "motion.halted"), ev(10, "run.resumed"), ev(10, "stop.requested")],
    ]
    for raws in orders:
        [sequence] = pair_stops(only_run(raws))
        assert sequence.outcome == "matched"
        assert sequence.ordering_confidence == "ambiguous"


def test_two_requests_and_two_halts_tied_with_the_closer_are_not_failures():
    # The worst-direction case: two demands and two halts recorded in the same
    # second must never publish as two "the cell did not stop" findings.
    run = only_run([ev(10, "stop.requested"), ev(10, "stop.requested"),
                    ev(10, "motion.halted"), ev(10, "motion.halted"),
                    ev(10, "run.resumed")])
    sequences = pair_stops(run)
    assert sorted(s.outcome for s in sequences) == [
        "matched", "matched", "orphan_halt"
    ]
    assert all(s.ordering_confidence == "ambiguous" for s in sequences)


def test_two_tied_orphan_halts_with_no_demand_stay_unambiguous():
    # Nothing was outstanding for either halt to take, so their records are
    # identical under either ordering. Flagging them would dilute the signal, and
    # the note would name demands the first note has just said do not exist.
    run = only_run([ev(10, "motion.halted"), ev(10, "motion.halted"),
                    ev(60, "run.resumed")])
    sequences = pair_stops(run)
    assert len(sequences) == 2
    assert all(s.outcome == "orphan_halt" for s in sequences)
    assert all(s.ordering_confidence == "unambiguous" for s in sequences)


def test_two_tied_halts_competing_for_a_demand_disclose_the_tie():
    # Here a demand WAS available, so which halt matched and which was orphaned
    # is decided by arrival order. The orphan must say so.
    run = only_run([ev(5, "stop.requested"), ev(10, "motion.halted"),
                    ev(10, "motion.halted"), ev(60, "run.resumed")])
    orphans = [s for s in pair_stops(run) if s.outcome == "orphan_halt"]
    assert orphans
    assert all(s.ordering_confidence == "ambiguous" for s in orphans)


def test_an_orphan_whose_existence_rests_on_an_earlier_tie_says_so():
    # The demands this halt might have taken were consumed by a pairing that
    # itself rested on a same-second tie. Under the other reading this halt is
    # matched and the other one is the orphan -- so this adverse record exists
    # only by coin toss, and must not present itself as certain.
    run = only_run([ev(10, "motion.halted"), ev(10, "stop.requested"),
                    ev(20, "motion.halted"), ev(60, "run.resumed")])
    sequences = pair_stops(run)
    orphan = next(s for s in sequences if s.outcome == "orphan_halt")
    assert orphan.ordering_confidence == "ambiguous"
    assert any("earlier pairing" in note for note in orphan.notes)


def test_two_tied_episode_closers_flip_content_unless_flagged_ambiguous():
    # stop.requested / motion.halted, then run.resumed and run.completed
    # sharing a second. Arrival order alone decides whether episode_closed_by
    # reads run.resumed or run.completed -- same record_id, different content
    # -- so it must never be reported unambiguous either way.
    for raws in (
        [ev(33, "stop.requested"), ev(34, "motion.halted"),
         ev(60, "run.resumed"), ev(60, "run.completed")],
        [ev(33, "stop.requested"), ev(34, "motion.halted"),
         ev(60, "run.completed"), ev(60, "run.resumed")],
    ):
        [sequence] = pair_stops(only_run(raws))
        assert sequence.ordering_confidence == "ambiguous"
        assert sequence.episode_closed_by in ("run.resumed", "run.completed")
        joined = " ".join(sequence.notes)
        assert "not determinable" in joined
        assert "closing events" in joined


def test_a_single_episode_closer_still_reports_unambiguous():
    # Counterexample to the fix above: the flag must not be hardcoded true.
    run = only_run([ev(33, "stop.requested"), ev(34, "motion.halted"),
                    ev(60, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.ordering_confidence == "unambiguous"


def test_an_orphan_halt_tied_with_its_episode_closer_is_flagged_ambiguous():
    # The matched path already discloses this exact tie. Omitting it here would
    # mean the service discloses ties only when the resulting record reads well.
    run = only_run([ev(10, "motion.halted"), ev(10, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "orphan_halt"
    assert sequence.ordering_confidence == "ambiguous"
    assert any("not determinable" in note for note in sequence.notes)
