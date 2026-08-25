from datetime import datetime, timedelta, timezone

import pytest

BASE = datetime(2026, 3, 11, 7, 15, 0, tzinfo=timezone.utc)


def at(offset_seconds: int) -> str:
    """Whole-second UTC timestamp literal, ``offset_seconds`` after 07:15:00Z."""
    moment = BASE + timedelta(seconds=offset_seconds)
    return moment.isoformat().replace("+00:00", "Z")


def ev(offset_seconds, event_type, *, cell="CELL-01", run="RUN-A", **payload):
    """Build one raw controller event. ``run=None`` produces an out-of-run event."""
    raw = {"ts": at(offset_seconds), "cellId": cell, "runId": run, "event": event_type}
    raw.update(payload)
    return raw


class FixedClock:
    """Deterministic ingest clock, so store files are byte-stable across runs."""

    def __init__(self, start: datetime = BASE):
        self._now = start

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "audit" / "events.jsonl"
