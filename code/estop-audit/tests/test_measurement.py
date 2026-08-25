import pytest

from estop_audit.events import parse_event
from estop_audit.measurement import interval_bound, response_time

from .conftest import ev


def event(offset, event_type, **payload):
    return parse_event(ev(offset, event_type, **payload))


def sub_second_event(literal, event_type):
    return parse_event({"ts": literal, "cellId": "CELL-01", "runId": "RUN-A",
                        "event": event_type})


def test_a_one_second_delta_bounds_to_zero_and_two():
    bound = interval_bound(event(33, "stop.requested"), event(34, "motion.halted"))
    assert bound.nominal_seconds == 1.0
    assert bound.lower_seconds_exclusive == 0.0
    assert bound.upper_seconds_exclusive == 2.0
    assert bound.source_resolution_seconds == 1.0


def test_a_same_second_delta_cannot_prove_the_halt_followed_the_request():
    bound = interval_bound(event(33, "stop.requested"), event(33, "motion.halted"))
    assert bound.nominal_seconds == 0.0
    assert bound.lower_seconds_exclusive == -1.0
    assert bound.upper_seconds_exclusive == 1.0


def test_millisecond_timestamps_narrow_the_bound_with_no_code_change():
    bound = interval_bound(
        sub_second_event("2026-03-11T07:15:33.412Z", "stop.requested"),
        sub_second_event("2026-03-11T07:15:33.453Z", "motion.halted"),
    )
    assert bound.nominal_seconds == pytest.approx(0.041)
    assert bound.upper_seconds_exclusive == pytest.approx(0.042)
    assert bound.lower_seconds_exclusive == pytest.approx(0.040)


def test_mixed_resolutions_take_the_conservative_union_of_both_conventions():
    # A 1 s request and a 1 ms halt. Truncation implies (d-1, d+0.001);
    # rounding implies (d-0.5005, d+0.5005). We must cover both.
    bound = interval_bound(
        sub_second_event("2026-03-11T07:15:33Z", "stop.requested"),
        sub_second_event("2026-03-11T07:15:34.000Z", "motion.halted"),
    )
    assert bound.lower_seconds_exclusive == pytest.approx(0.0)
    assert bound.upper_seconds_exclusive == pytest.approx(1.5005)


def test_response_time_states_the_defensible_claim_not_the_nominal():
    measured = response_time(event(33, "stop.requested"), event(34, "motion.halted"))
    assert measured.causal_order_established is True
    assert measured.defensible_claim == "stop response < 2 s"
    assert "1 s" != measured.defensible_claim


def test_response_time_refuses_to_assert_ordering_it_cannot_establish():
    measured = response_time(event(33, "stop.requested"), event(33, "motion.halted"))
    assert measured.causal_order_established is False
    assert "not established" in measured.defensible_claim


def test_response_time_carries_the_clock_caveat():
    measured = response_time(event(33, "stop.requested"), event(34, "motion.halted"))
    assert measured.clock_authority == "cell_wall_clock_unverified"
    assert measured.method == "derived_from_whole_second_controller_wall_clock"


def test_response_time_as_dict_always_carries_the_bound():
    payload = response_time(
        event(33, "stop.requested"), event(34, "motion.halted")
    ).as_dict()
    for required in (
        "nominal_seconds",
        "lower_bound_seconds_exclusive",
        "upper_bound_seconds_exclusive",
        "source_resolution_seconds",
        "method",
        "clock_authority",
        "causal_order_established",
        "defensible_claim",
    ):
        assert required in payload
