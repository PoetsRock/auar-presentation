from datetime import datetime, timezone

import pytest

from estop_audit.events import (
    Event,
    MalformedEventError,
    canonical_json,
    event_key,
    iso_z,
    parse_event,
    parse_line,
    parse_ts,
    ts_resolution_seconds,
)


def test_canonical_json_is_key_order_independent():
    a = {"b": 2, "a": 1}
    b = {"a": 1, "b": 2}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_has_no_incidental_whitespace():
    assert canonical_json({"a": 1, "b": 2}) == b'{"a":1,"b":2}'


def test_event_key_is_stable_and_prefixed():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": "stop.requested"}
    key = event_key(raw)
    assert key.startswith("sha256:")
    assert len(key) == len("sha256:") + 64
    assert key == event_key(dict(reversed(list(raw.items()))))


def test_event_key_distinguishes_the_two_legitimate_nailing_started_events():
    # docs/firmware-event-schema-v4.2.md lines 38-44: nailing.started for EW-L1-E1
    # appears twice, either side of an e-stop resume. Both are real. A key that
    # collapses them silently drops a genuine event.
    first = {"ts": "2026-03-11T07:14:51Z", "cellId": "CELL-01", "runId": "RUN-A",
             "event": "nailing.started", "panelId": "EW-L1-E1", "pattern": "std-300"}
    second = dict(first, ts="2026-03-11T07:20:05Z")
    assert event_key(first) != event_key(second)


@pytest.mark.parametrize(
    "literal,expected",
    [
        ("2026-03-11T07:15:33Z", 1.0),
        ("2026-03-11T07:15:33.412Z", 0.001),
        ("2026-03-11T07:15:33.412337Z", 0.000001),
    ],
)
def test_ts_resolution_is_read_from_the_literal(literal, expected):
    assert ts_resolution_seconds(literal) == pytest.approx(expected)


def test_parse_ts_normalises_to_utc():
    assert parse_ts("2026-03-11T08:15:33+01:00") == datetime(
        2026, 3, 11, 7, 15, 33, tzinfo=timezone.utc
    )


def test_parse_ts_rejects_a_naive_timestamp():
    with pytest.raises(MalformedEventError):
        parse_ts("2026-03-11T07:15:33")


def test_iso_z_round_trips_with_a_z_suffix():
    assert iso_z(datetime(2026, 3, 11, 7, 15, 33, tzinfo=timezone.utc)) == "2026-03-11T07:15:33Z"


def test_parse_event_populates_the_normalised_fields():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "runId": "RUN-A",
           "event": "stop.requested", "source": "operator_estop"}
    event = parse_event(raw)
    assert isinstance(event, Event)
    assert event.cell_id == "CELL-01"
    assert event.run_id == "RUN-A"
    assert event.type == "stop.requested"
    assert event.ts_resolution_seconds == 1.0
    assert event.scope == ("CELL-01", "RUN-A")
    assert event.raw is raw


def test_parse_event_allows_a_null_run_id():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "runId": None,
           "event": "controller.booted"}
    assert parse_event(raw).scope == ("CELL-01", None)


@pytest.mark.parametrize("missing", ["ts", "cellId", "event"])
def test_parse_event_rejects_a_missing_required_field(missing):
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": "run.started"}
    del raw[missing]
    with pytest.raises(MalformedEventError):
        parse_event(raw)


@pytest.mark.parametrize("bad_value", [{"oops": 1}, [1, 2], 7])
def test_parse_event_rejects_a_non_string_cell_id(bad_value):
    # cellId becomes a dict key downstream (Event.scope, partition_runs) and a
    # sort key in stop_records. A non-string admitted here poisons the
    # append-only chain forever, so it must be rejected at parse time.
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": bad_value, "event": "run.started"}
    with pytest.raises(MalformedEventError):
        parse_event(raw)


@pytest.mark.parametrize("bad_value", [{"oops": 1}, [1, 2], 7])
def test_parse_event_rejects_a_non_string_event_type(bad_value):
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": bad_value}
    with pytest.raises(MalformedEventError):
        parse_event(raw)


@pytest.mark.parametrize("bad_value", [{"oops": 1}, [1, 2], 7])
def test_parse_event_rejects_a_non_string_run_id(bad_value):
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": "run.started",
           "runId": bad_value}
    with pytest.raises(MalformedEventError):
        parse_event(raw)


def test_parse_event_still_allows_a_null_run_id_after_type_checks():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "runId": None,
           "event": "controller.booted"}
    assert parse_event(raw).run_id is None


def test_parse_line_rejects_invalid_json():
    with pytest.raises(MalformedEventError):
        parse_line("{not json")


def test_events_are_hashable_despite_carrying_a_raw_dict():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": "run.started"}
    assert len({parse_event(raw), parse_event(dict(raw))}) == 1
