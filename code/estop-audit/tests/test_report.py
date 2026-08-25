from estop_audit.events import parse_event
from estop_audit.records import build_record, record_id_for
from estop_audit.report import render_text
from estop_audit.sequences import pair_stops, partition_runs

from .conftest import ev

AXES = ["j1", "j2", "j3", "j4", "j5", "j6"]


def render_from(raws):
    runs = partition_runs([parse_event(raw) for raw in raws])
    rendered = []
    for run in runs:
        for sequence in pair_stops(run):
            rendered.append(render_text(build_record(sequence, run, all_runs=runs)))
    return rendered


MATCHED = [
    ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1", axisInMotion=True),
    ev(34, "motion.halted", panelId="EW-L1-E1", axesStopped=AXES),
    ev(35, "interlock.engaged", zone="assembly_table"),
    ev(37, "run.paused", reason="estop"),
    ev(277, "interlock.released", zone="assembly_table", operator="op-114"),
    ev(295, "run.resumed", resumeMode="from_panel_start", panelId="EW-L1-E1"),
]


def test_a_response_time_never_renders_without_its_bound():
    [page] = render_from(MATCHED)
    assert "stop response < 2 s" in page
    assert "less than 2 s" in page
    assert "whole-second" in page


def test_the_clock_caveat_is_on_the_page():
    [page] = render_from(MATCHED)
    assert "wall-clock" in page
    assert "undetectable" in page


def test_per_axis_unavailability_is_stated_in_words():
    [page] = render_from(MATCHED)
    assert "unavailable from this source" in page
    assert "j1, j2, j3, j4, j5, j6" in page


def test_a_non_string_axis_label_renders_without_raising():
    # axesStopped is a motion.halted payload field, not type-checked by
    # parse_event. A non-string element must render as itself (via str())
    # rather than crash ", ".join() -- this only affects the one affected
    # record's rendering, not stop_records() for the rest of the store.
    [page] = render_from([
        ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1"),
        ev(34, "motion.halted", panelId="EW-L1-E1", axesStopped=["j1", 2, "j3"]),
    ])
    assert "j1, 2, j3" in page


def test_the_safety_pause_is_labelled_and_the_routine_one_is_not_conflated():
    [page] = render_from(MATCHED)
    assert "[SAFETY]" in page
    # counterexample in the same test: a renderer that hardcoded SAFETY would
    # pass the assertion above, so pin the routine pause too.
    [routine] = render_from([
        ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1"),
        ev(34, "motion.halted", panelId="EW-L1-E1", axesStopped=AXES),
        ev(40, "run.paused", reason="material_reload"),
        ev(295, "run.resumed"),
    ])
    assert "[OPERATIONAL]" in routine
    assert "[SAFETY]" not in routine


def test_a_truncated_unmatched_record_never_says_the_cell_did_not_stop():
    [page] = render_from([ev(0, "run.started"), ev(33, "stop.requested")])
    assert "Not evidenced" in page
    assert "stream incomplete" in page
    assert "did not stop" not in page


def test_a_completed_unmatched_record_does_state_the_finding():
    [page] = render_from([ev(33, "stop.requested"), ev(60, "run.completed")])
    assert "NOT EVIDENCED" in page
    assert "not evidenced to have stopped" in page
    assert "stream incomplete" not in page


def test_fan_out_is_stated_in_words_not_left_to_a_field():
    pages = render_from([
        ev(0, "stop.requested", source="operator_estop"),
        ev(1, "stop.requested", source="light_curtain"),
        ev(2, "motion.halted", axesStopped=AXES),
        ev(10, "run.resumed"),
    ])
    assert all("also answered 1 other" in page for page in pages)


def test_a_measured_number_never_appears_without_what_constrains_it():
    # The earlier version of this test asserted "nominal" appears whenever
    # "Measured" does -- which the template guarantees by construction, so it
    # could not fail. What matters is that the bound, the resolution and the
    # claim accompany the number.
    for page in render_from(MATCHED) + render_from(
        [ev(33, "stop.requested"), ev(60, "run.completed")]
    ):
        if "Measured" not in page:
            continue
        assert "Bound" in page
        assert "Resolution" in page
        assert "Claim" in page
        assert "less than" in page


def test_an_orphan_halt_never_claims_the_cell_did_not_stop():
    # A halt with no attributable demand is not a failure to stop. Rendering it
    # as one would contradict the CONTEXT block on the same page.
    [page] = render_from([ev(0, "run.started"),
                          ev(50, "motion.halted", axesStopped=AXES),
                          ev(90, "run.completed")])
    assert "not evidenced to have stopped" not in page
    assert "NOT APPLICABLE" in page
    assert "no stop demand was recorded" in page
    assert "Halted" in page  # the halt is still on the page


def test_a_same_second_tie_renders_its_uncertainty():
    [page] = render_from([
        ev(33, "stop.requested", source="operator_estop", panelId="EW-L1-E1"),
        ev(33, "motion.halted", panelId="EW-L1-E1", axesStopped=AXES),
        ev(295, "run.resumed"),
    ])
    assert "cannot be shown to follow" in page
    assert "NOTES" in page
    assert "not determinable" in page


def _record_with_amendment(measurements):
    runs = partition_runs([parse_event(r) for r in MATCHED])
    [sequence] = pair_stops(runs[0])
    record_id = record_id_for(sequence, runs[0])
    amendments = {
        record_id: [
            {
                "ts": "2026-04-01T09:00:00Z",
                "source": "rig",
                "attested_by": "chris",
                "measurements": measurements,
                "event_key": "sha256:" + "a" * 64,
            }
        ]
    }
    return build_record(sequence, runs[0], all_runs=runs, amendments=amendments)


def test_per_axis_amendment_figures_are_stated_to_carry_no_uncertainty_bound():
    # The rig-supplied number is the one actually quoted for inspection action
    # a3. Rendering it bare, with no bound, resolution or method, is the wrong
    # asymmetry -- the schema carries none of those, so the page must say so
    # rather than let it read as more certain than a controller-derived one.
    record = _record_with_amendment([{"axis": "j1", "delta_seconds": 0.041}])
    page = render_text(record)
    assert "without an uncertainty bound" in page
    assert "does not compute or verify one" in page


def test_a_measurement_missing_delta_seconds_never_renders_the_word_none():
    record = _record_with_amendment([{"axis": "j2"}])
    page = render_text(record)
    assert "j2" in page
    assert "not supplied" in page
    assert "None s" not in page


def test_the_unavailable_reason_does_not_print_alongside_a_supplied_amendment():
    # "Status: supplied by amendment" followed by a "Reason" label from the
    # unavailable-per-axis explanation contradicts itself on the same page.
    # The prose behind that label gets wrapped across lines by _field, so
    # asserting on a fragment of the prose is inert -- it never appears
    # contiguously in the rendered page either way. Pin the label instead:
    # _field always renders "Reason" as a whole, unwrapped token.
    record = _record_with_amendment([{"axis": "j1", "delta_seconds": 0.041}])
    page = render_text(record)
    assert "supplied by amendment" in page
    per_axis_section = page.split("PER-AXIS RESPONSE", 1)[1].split("CONTEXT", 1)[0]
    assert "Reason" not in per_axis_section


def test_the_page_discloses_when_cross_run_candidates_are_truncated():
    raws = [ev(33, "stop.requested", run="RUN-A"), ev(60, "run.completed", run="RUN-A")]
    for offset, run in enumerate(["RUN-B", "RUN-C", "RUN-D", "RUN-E", "RUN-F"]):
        raws.append(ev(34 + offset, "motion.halted", run=run, axesStopped=AXES))
    pages = render_from(raws)
    [page] = [p for p in pages if "NOT EVIDENCED" in p]
    assert "showing 3 of 5 candidates" in page


def test_a_long_identifier_is_wrapped_whole_never_split():
    # Event keys and chain hashes are identifiers. Splitting one across a line
    # break would read to an inspector as a corrupted value rather than a wrap,
    # so an over-long token overflows the column instead of being broken.
    from estop_audit.report import _field

    key = "sha256:" + "b" * 64
    assert key in _field("Event key", key)


def test_no_rendered_line_exceeds_the_page_width():
    from estop_audit.report import WIDTH

    pages = render_from(MATCHED) + render_from(
        [ev(0, "run.started"), ev(50, "motion.halted", axesStopped=AXES)]
    )
    for page in pages:
        for line in page.splitlines():
            assert len(line) <= WIDTH, f"{len(line)} chars: {line!r}"
