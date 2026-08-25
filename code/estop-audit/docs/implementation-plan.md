# E-stop Audit and Stop-Response Measurement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that persists controller events to a tamper-evident append-only store, pairs each e-stop request with the halt that answered it, and emits an audit record that reports the stop response time *with its uncertainty bound* rather than a false-precision number.

**Architecture:** Event-sourced pipeline. Ingest appends to a hash-chained JSONL store; everything derived (run partitioning, stop pairing, measurement, records, rendering) is recomputed from the log on read, so no derived value can drift from the evidence that produced it. Pairing is fan-out within stop episodes bounded by `run.resumed` / `run.completed` / stream end.

**Tech Stack:** Python 3.11+, standard library only (`json`, `hashlib`, `dataclasses`, `datetime`, `pathlib`, `re`). `pytest` for tests. No web layer, no database, no CLI.

**Spec:** `docs/superpowers/specs/2026-08-25-estop-audit-design.md` — read it before starting. This plan implements it; where the plan and spec disagree, the spec is right and the plan is a bug.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.11+.** `datetime.fromisoformat` must handle a trailing `Z`; that is 3.11 behaviour.
- **Standard library only** in `estop_audit/`. `pytest` is a test-time dependency and must not be imported by package code.
- **No network, no database, no CLI.** Out of scope for slice 1.
- **The audit store is append-only.** Nothing in this codebase may rewrite or delete a line of the store file. Corrections are appended as amendments.
- **No measurement may be serialised or rendered without its uncertainty bound.** This is the point of the exercise, not a nicety.
- **Whole-second source resolution.** The only defensible claim from the sample data is `stop response < 2 s`. Never emit `1 s` unqualified.
- **`unclassified` is the default for unknown `run.paused` reasons.** Never default an unknown reason to `operational`.
- **Hash format:** chain hashes are bare 64-char lowercase hex. Event keys are prefixed `sha256:`. The two namespaces are deliberately distinct.
- **Timestamp serialisation:** always `iso_z()` — UTC, `Z` suffix, never `+00:00`.
- **Sample data:** `cell-events.jsonl` in the repo root. `cell-events.json` and `cell-events.ndjson` are byte-identical copies; ignore them.

---

## File Structure

| File | Responsibility |
|---|---|
| `estop_audit/__init__.py` | Package marker; re-exports the public facade only |
| `estop_audit/events.py` | Parse and normalise raw events; canonical serialisation; content-hash identity; timestamp resolution |
| `estop_audit/store.py` | Hash-chained append-only JSONL store; idempotent append; retrieval by cell and time range; chain verification |
| `estop_audit/measurement.py` | Resolution-aware interval arithmetic; `Bound` and `ResponseTime` |
| `estop_audit/sequences.py` | Partition into runs; split into stop episodes; fan-out pairing; pause classification |
| `estop_audit/records.py` | Assemble the audit record; per-axis amendment seam |
| `estop_audit/report.py` | Plain-text inspector rendering; the place uncertainty language is enforced |
| `estop_audit/service.py` | Thin facade: ingest, query, stop records, render |
| `tests/conftest.py` | Synthetic event-stream builder and a fixed clock |
| `tests/test_*.py` | One test module per source module, plus `test_golden_sample.py` |
| `README.md` | What the service can and cannot prove; what changes when firmware v4.2 lands |

Dependency direction is strictly one-way: `events` → `store` → `measurement` → `sequences` → `records` → `report` → `service`. No module imports one below it in that list.

---

## Task 1: Package scaffolding and event identity

**Files:**
- Create: `estop_audit/__init__.py`
- Create: `estop_audit/events.py`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MalformedEventError`, `GENESIS_HASH: str`, `canonical_json(obj: dict) -> bytes`, `sha256_hex(data: bytes) -> str`, `event_key(raw: dict) -> str`, `ts_resolution_seconds(literal: str) -> float`, `parse_ts(literal: str) -> datetime`, `iso_z(dt: datetime) -> str`, `Event` (frozen dataclass: `key`, `ts`, `ts_resolution_seconds`, `cell_id`, `run_id`, `type`, `raw`; property `scope -> tuple[str, str | None]`), `parse_event(raw: dict) -> Event`, `parse_line(line: str) -> Event`.

- [ ] **Step 1: Create the project skeleton**

```bash
mkdir -p estop_audit tests
touch estop_audit/__init__.py tests/__init__.py
```

Write `pyproject.toml`:

```toml
[project]
name = "estop-audit"
version = "0.1.0"
description = "E-stop audit and stop-response measurement for inspection actions a2/a3"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7.4"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing tests**

Write `tests/test_events.py`:

```python
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
    # docs/firmware-event-schema-v4.2.md lines 32-36, point 1 'No unique event identifier': nailing.started for EW-L1-E1
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


def test_parse_line_rejects_invalid_json():
    with pytest.raises(MalformedEventError):
        parse_line("{not json")


def test_events_are_hashable_despite_carrying_a_raw_dict():
    raw = {"ts": "2026-03-11T07:15:33Z", "cellId": "CELL-01", "event": "run.started"}
    assert len({parse_event(raw), parse_event(dict(raw))}) == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.events'`

- [ ] **Step 4: Write the implementation**

Write `estop_audit/events.py`:

```python
"""Parsing, normalisation, and identity for controller events.

The controller stream carries no ``eventId``. Identity here is therefore
synthesised from the event's full content -- see :func:`event_key` for what
that costs us and how the cost is made visible rather than hidden.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

GENESIS_HASH = "0" * 64
"""``prev_hash`` of the first record in an audit store. Bare hex, no prefix."""


class MalformedEventError(ValueError):
    """A line or object could not be read as a controller event."""


def canonical_json(obj: Mapping[str, Any]) -> bytes:
    """Serialise deterministically: sorted keys, no incidental whitespace, UTF-8."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def event_key(raw: Mapping[str, Any]) -> str:
    """Synthetic idempotency key: SHA-256 over the full canonical event.

    Includes ``ts``, which is what makes it safe against the trap documented in
    docs/firmware-event-schema-v4.2.md lines 32-36, point 1 'No unique event identifier': ``nailing.started`` for
    ``EW-L1-E1`` legitimately appears twice, either side of an e-stop resume.
    Deduping on ``(runId, panelId, event)`` would silently drop one of them.

    The residual hole: two *genuinely distinct* events sharing every field
    including their whole-second ``ts`` are indistinguishable here, and the
    second would be dropped. ``IngestReport.content_collisions`` counts that
    case so a collapse is an observable number rather than an absence nobody
    notices.

    TODO(firmware-v4.2): replace with the ``eventId`` field from the required
    envelope in docs/firmware-event-schema-v4.2.md. Dedupe on that and only that.
    """
    return "sha256:" + sha256_hex(canonical_json(raw))


_TS_FRACTION = re.compile(r"\.(\d+)")


def ts_resolution_seconds(literal: str) -> float:
    """Resolution implied by a timestamp *literal*, in seconds.

    Read from the string rather than assumed, so that firmware v4.2's
    millisecond timestamps narrow every measurement bound automatically with no
    code change -- and so that today's whole-second stream is not quietly
    treated as if it were more precise than it is.
    """
    match = _TS_FRACTION.search(literal)
    if match is None:
        return 1.0
    return 10.0 ** (-len(match.group(1)))


def parse_ts(literal: str) -> datetime:
    """Parse an ISO-8601 timestamp to a timezone-aware UTC ``datetime``."""
    if not isinstance(literal, str):
        raise MalformedEventError(f"ts must be a string, got {type(literal).__name__}")
    try:
        parsed = datetime.fromisoformat(literal)
    except ValueError as exc:
        raise MalformedEventError(f"unparseable ts: {literal!r}") from exc
    if parsed.tzinfo is None:
        raise MalformedEventError(f"ts must carry a timezone: {literal!r}")
    return parsed.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    """Serialise a UTC datetime with a ``Z`` suffix, never ``+00:00``."""
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Event:
    """A controller event, normalised. ``raw`` is never mutated."""

    key: str
    ts: datetime
    ts_resolution_seconds: float
    cell_id: str
    run_id: str | None
    type: str
    raw: Mapping[str, Any] = field(compare=False, repr=False)

    @property
    def scope(self) -> tuple[str, str | None]:
        """Partition key. ``run_id`` alone is not enough -- it may be null."""
        return (self.cell_id, self.run_id)


_REQUIRED_FIELDS = ("ts", "cellId", "event")


def parse_event(raw: Mapping[str, Any]) -> Event:
    if not isinstance(raw, dict):
        raise MalformedEventError("event must be a JSON object")
    for name in _REQUIRED_FIELDS:
        if name not in raw:
            raise MalformedEventError(f"missing required field: {name}")
    literal = raw["ts"]
    return Event(
        key=event_key(raw),
        ts=parse_ts(literal),
        ts_resolution_seconds=ts_resolution_seconds(literal),
        cell_id=raw["cellId"],
        run_id=raw.get("runId"),
        type=raw["event"],
        raw=raw,
    )


def parse_line(line: str) -> Event:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MalformedEventError(f"invalid JSON: {exc}") from exc
    return parse_event(raw)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS — 17 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml estop_audit/__init__.py estop_audit/events.py tests/__init__.py tests/test_events.py
git commit -m "feat: event parsing, canonical serialisation, and content-hash identity"
```

---

## Task 2: Hash-chained append-only audit store

**Files:**
- Create: `estop_audit/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: from `estop_audit.events` — `Event`, `GENESIS_HASH`, `canonical_json`, `event_key`, `iso_z`, `parse_event`, `parse_ts` (reads `ingested_at` back), `sha256_hex`.
- Produces: `AuditStoreError`, `ConcurrentWriterError`, `AppendResult(appended: bool, seq: int | None, event_key: str)`, `StoredRecord(seq: int, ingested_at: datetime, event_key: str, prev_hash: str, record_hash: str, event: Event)`, `ChainVerification(ok: bool, broken_at_seq: int | None, reason: str | None, records: int, head_hash: str)`, `AppendOnlyAuditStore(path, clock=...)` with `.append(raw) -> AppendResult`, `.__iter__() -> Iterator[StoredRecord]`, `.query(*, cell_id=None, start=None, end=None) -> list[StoredRecord]`, `.verify_chain() -> ChainVerification`.

- [ ] **Step 1: Write the shared test fixtures**

Write `tests/conftest.py` — used by this and every later task:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Write `tests/test_store.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from estop_audit.events import GENESIS_HASH
from estop_audit.store import (
    AppendOnlyAuditStore,
    AuditStoreError,
    ConcurrentWriterError,
)

from .conftest import at, ev


def test_append_returns_the_assigned_seq(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    result = store.append(ev(0, "run.started"))
    assert result.appended is True
    assert result.seq == 0


def test_append_is_idempotent_on_event_key(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    raw = ev(0, "run.started")
    assert store.append(raw).appended is True
    second = store.append(dict(raw))
    assert second.appended is False
    assert second.seq is None
    assert len(list(store)) == 1


def test_the_first_record_chains_from_the_genesis_hash(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    assert list(store)[0].prev_hash == GENESIS_HASH


def test_each_record_chains_to_its_predecessor(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    first, second = list(store)
    assert second.prev_hash == first.record_hash


def test_a_clean_store_verifies(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    assert store.verify_chain().ok is True


def test_editing_a_line_breaks_the_chain_at_that_line(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    store.append(ev(2, "panel.completed", panelId="P1"))

    lines = store_path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["event"]["panelId"] = "P-FORGED"
    lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    store_path.write_text("\n".join(lines) + "\n")

    verification = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.broken_at_seq == 1
    assert verification.reason


def test_deleting_a_line_breaks_the_chain(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    store.append(ev(2, "panel.completed", panelId="P1"))

    lines = store_path.read_text().splitlines()
    store_path.write_text("\n".join([lines[0], lines[2]]) + "\n")

    assert AppendOnlyAuditStore(store_path, clock=clock).verify_chain().ok is False


def test_a_reopened_store_resumes_the_chain_and_the_seq(store_path, clock):
    first = AppendOnlyAuditStore(store_path, clock=clock)
    first.append(ev(0, "run.started"))

    reopened = AppendOnlyAuditStore(store_path, clock=clock)
    assert reopened.append(ev(1, "panel.started", panelId="P1")).seq == 1
    assert reopened.verify_chain().ok is True
    assert reopened.append(ev(0, "run.started")).appended is False


def test_query_filters_by_cell(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started", cell="CELL-01"))
    store.append(ev(0, "run.started", cell="CELL-02"))
    assert [r.event.cell_id for r in store.query(cell_id="CELL-02")] == ["CELL-02"]


def test_query_time_range_is_half_open(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    for offset in (0, 10, 20):
        store.append(ev(offset, "panel.started", panelId=f"P{offset}"))

    def parsed(literal):
        return datetime.fromisoformat(literal).astimezone(timezone.utc)

    found = store.query(start=parsed(at(0)), end=parsed(at(20)))
    assert [r.event.raw["panelId"] for r in found] == ["P0", "P10"]


def test_iteration_preserves_arrival_order_not_timestamp_order(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(20, "panel.completed", panelId="LATE"))
    store.append(ev(0, "panel.started", panelId="EARLY"))
    assert [r.event.raw["panelId"] for r in store] == ["LATE", "EARLY"]


def test_an_absent_store_does_not_verify_and_is_not_created(tmp_path, clock):
    path = tmp_path / "never" / "written.jsonl"
    verification = AppendOnlyAuditStore(path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.records == 0
    assert "no evidence" in verification.reason
    assert not path.exists()  # opening evidence must not create it


def test_an_empty_store_does_not_verify(store_path, clock):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.touch()
    verification = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.records == 0
    assert "empty" in verification.reason


def test_verification_reports_the_record_count_and_head(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    verification = store.verify_chain()
    assert verification.ok is True
    assert verification.records == 2
    assert verification.head_hash == list(store)[-1].record_hash


def test_tail_truncation_verifies_and_is_caught_only_by_the_anchor(store_path, clock):
    # The honest limit. Dropping records off the END leaves an internally
    # consistent chain: seqs still contiguous, hashes still match. Only an
    # independently recorded (records, head_hash) anchor reveals it. This test
    # exists to pin that limitation down, not to assert the store is sound.
    store = AppendOnlyAuditStore(store_path, clock=clock)
    for offset in range(3):
        store.append(ev(offset, "panel.started", panelId=f"P{offset}"))
    anchor = store.verify_chain()

    lines = store_path.read_text().splitlines()
    store_path.write_text("\n".join(lines[:2]) + "\n")

    truncated = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert truncated.ok is True  # the file alone cannot tell
    assert anchor.records == 3
    assert truncated.records == 2  # the anchor can
    assert truncated.head_hash != anchor.head_hash


def test_a_structurally_damaged_file_yields_a_verdict_not_a_traceback(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    lines = store_path.read_text().splitlines()
    store_path.write_text(lines[0] + "\n{ this is not json\n")

    verification = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.broken_at_seq == 1


def test_appending_onto_a_damaged_store_is_refused(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store_path.write_text(store_path.read_text() + "{ not json\n")
    with pytest.raises(AuditStoreError):
        AppendOnlyAuditStore(store_path, clock=clock).append(ev(1, "run.paused"))


def test_broken_at_seq_reports_the_walk_position_not_the_file_value(store_path, clock):
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store.append(ev(1, "panel.started", panelId="P1"))
    lines = store_path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["seq"] = 9999
    lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    store_path.write_text("\n".join(lines) + "\n")

    verification = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.broken_at_seq == 1


def test_a_byte_corrupt_file_yields_a_verdict_not_a_traceback(store_path, clock):
    # Same requirement as the malformed-JSON case, one exception class over: an
    # inspector handed a byte-damaged evidence file must get a verdict.
    store = AppendOnlyAuditStore(store_path, clock=clock)
    store.append(ev(0, "run.started"))
    store_path.write_bytes(store_path.read_bytes() + b"\xff\xfe not utf-8\n")

    verification = AppendOnlyAuditStore(store_path, clock=clock).verify_chain()
    assert verification.ok is False
    assert verification.reason
    assert verification.records == 1  # the verified prefix, not the whole file


def test_a_second_live_instance_cannot_fork_the_chain(store_path, clock):
    first = AppendOnlyAuditStore(store_path, clock=clock)
    first.append(ev(0, "run.started"))
    second = AppendOnlyAuditStore(store_path, clock=clock)
    second.append(ev(1, "panel.started", panelId="P1"))
    with pytest.raises(ConcurrentWriterError):
        first.append(ev(2, "panel.completed", panelId="P1"))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.store'`

- [ ] **Step 4: Write the implementation**

Write `estop_audit/store.py`:

```python
"""Append-only, hash-chained audit store.

Two properties matter, and they are different things:

* **Append-only** -- nothing here ever rewrites or deletes a line. Corrections
  arrive as new records (see ``records.attach_per_axis_measurement``).
* **Hash-chained** -- each line's hash covers the previous line's hash, so any
  alteration *in the interior of the file* is detectable by re-walking it.

**What the chain proves, stated precisely.** Re-walking detects any partial or
localised alteration: edit a line and its own hash stops matching; delete or
reorder an interior line and the next line's ``prev_hash`` no longer matches.

**What it does not prove, and this is the important part.** The chain is
*unkeyed*. Anyone who can write the file can recompute the whole chain from
``GENESIS_HASH`` forward and produce a fabricated log that verifies perfectly.
``ok=True`` therefore means "internally consistent", never "authentic".

**Tail truncation is the specific gap.** Deleting records from the END leaves a
shorter chain that still verifies: seqs stay contiguous from zero, every
``prev_hash`` still matches, every ``record_hash`` still recomputes. This is the
most likely real-world tampering -- dropping the records after an e-stop -- and
the file alone cannot reveal it. That is why :class:`ChainVerification` reports
``records`` and ``head_hash``: a verifier who recorded those independently (a
witness log, a countersigned handover, a value written down at shift end)
detects truncation by comparing them. Without such an anchor, completeness is
not established.

**And what it says nothing about at all:** events that never reached this file.
With no ``seq`` in the source (docs/firmware-event-schema-v4.2.md lines 38-40,
point 2 'No sequence number') a gap is unobservable -- a quiet cell and a
thirty-minute outage look identical. Events lost to a controller buffer overflow
never arrive here, and no property of this file can reveal them.

**Single writer.** One live instance per path. Two would each hold a stale chain
head and fork the file into a state that append-only semantics forbid repairing,
so :meth:`append` refuses rather than corrupting the evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .events import (
    GENESIS_HASH,
    Event,
    canonical_json,
    event_key,
    iso_z,
    parse_event,
    parse_ts,
    sha256_hex,
)


class AuditStoreError(RuntimeError):
    """The audit store cannot be used safely."""


class ConcurrentWriterError(AuditStoreError):
    """The file changed underneath us; another writer holds this store open."""


@dataclass(frozen=True)
class AppendResult:
    appended: bool
    seq: int | None
    event_key: str


@dataclass(frozen=True)
class StoredRecord:
    seq: int
    ingested_at: datetime
    event_key: str
    prev_hash: str
    record_hash: str
    event: Event


@dataclass(frozen=True)
class ChainVerification:
    """Outcome of re-walking the store.

    ``records`` and ``head_hash`` exist so completeness can be checked against an
    independently recorded anchor. The file alone cannot detect tail truncation;
    these two values are what makes it detectable by someone who wrote them down.

    **They mean different things by verdict.** On ``ok=True`` they describe the
    whole file and are the completeness anchor. On a failure verdict they describe
    the verified *prefix* only -- how many records were sound before the break, and
    the chain head at that point. Comparing a failed verdict's ``records`` against
    an anchor is a category error; check ``ok`` first.
    """

    ok: bool
    broken_at_seq: int | None = None
    reason: str | None = None
    records: int = 0
    head_hash: str = GENESIS_HASH


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _body_hash(body: Mapping[str, Any]) -> str:
    """Hash of a record body, which already contains ``prev_hash``.

    Chaining is therefore implicit: change any earlier line and every later
    ``record_hash`` stops matching.
    """
    return sha256_hex(canonical_json(body))


class AppendOnlyAuditStore:
    """A JSONL file of stored records, one per line, in arrival order."""

    def __init__(self, path: Path | str, clock: Callable[[], datetime] = _utc_now):
        self._path = Path(path)
        self._clock = clock
        self._keys: set[str] = set()
        self._last_hash = GENESIS_HASH
        self._next_seq = 0
        self._size = 0
        self._load_error: str | None = None
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        """Read existing records to resume the chain head and the seq counter.

        Never raises. An inspector handed a damaged file must still be able to
        call :meth:`verify_chain` and receive a verdict rather than a traceback,
        so a load failure is recorded and surfaces only when someone tries to
        append onto a chain we cannot trust.
        """
        if not self._path.exists():
            return
        self._size = self._path.stat().st_size
        try:
            for line in self._raw_lines():
                self._keys.add(line["event_key"])
                self._last_hash = line["record_hash"]
                self._next_seq = line["seq"] + 1
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            AttributeError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            self._load_error = f"audit store at {self._path} could not be read: {exc}"

    def _raw_lines(self) -> Iterator[dict[str, Any]]:
        """Yield stored records as raw dicts, one per line, in file order.

        Read as bytes and decoded per line, deliberately. Text-mode iteration
        decodes in buffered chunks, so one corrupt byte anywhere in the buffer
        fails the whole read before even the earlier, valid lines are yielded --
        and ``verify_chain`` would then report a verified prefix of zero on a
        file whose opening records are perfectly sound. Decoding per line lets
        the prefix survive right up to the damage, which is what makes
        ``ChainVerification.records`` meaningful on a failure verdict.

        A decode failure propagates to the callers, which catch it: ``_load``
        records it, ``verify_chain`` turns it into a verdict.
        """
        if not self._path.exists():
            return
        with self._path.open("rb") as handle:
            for line_bytes in handle:
                line = line_bytes.decode("utf-8")
                if line.strip():
                    yield json.loads(line)

    def _assert_sole_writer(self) -> None:
        current = self._path.stat().st_size if self._path.exists() else 0
        if current != self._size:
            raise ConcurrentWriterError(
                f"{self._path} changed size from {self._size} to {current} since "
                "this store last read it; another writer holds it open. Appending "
                "now would fork the chain into a file that append-only semantics "
                "forbid repairing."
            )

    def append(self, raw: Mapping[str, Any]) -> AppendResult:
        """Persist one event. Idempotent on ``event_key``."""
        if self._load_error is not None:
            raise AuditStoreError(self._load_error)

        key = event_key(raw)
        if key in self._keys:
            return AppendResult(appended=False, seq=None, event_key=key)

        parse_event(raw)  # validate before anything is written
        self._assert_sole_writer()

        body = {
            "seq": self._next_seq,
            "ingested_at": iso_z(self._clock()),
            "event_key": key,
            "prev_hash": self._last_hash,
            "event": dict(raw),
        }
        record = dict(body, record_hash=_body_hash(body))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record).decode("utf-8") + "\n")

        self._keys.add(key)
        self._last_hash = record["record_hash"]
        self._next_seq += 1
        self._size = self._path.stat().st_size
        return AppendResult(appended=True, seq=body["seq"], event_key=key)

    def __iter__(self) -> Iterator[StoredRecord]:
        """Stored records in **arrival** order -- the receipt, not the timeline."""
        for line in self._raw_lines():
            yield StoredRecord(
                seq=line["seq"],
                ingested_at=parse_ts(line["ingested_at"]),
                event_key=line["event_key"],
                prev_hash=line["prev_hash"],
                record_hash=line["record_hash"],
                event=parse_event(line["event"]),
            )

    def query(
        self,
        *,
        cell_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[StoredRecord]:
        """Retrieve by cell and time range. The range is half-open: ``[start, end)``.

        Stated explicitly because an inspector will ask about boundaries.
        """
        found = []
        for record in self:
            if cell_id is not None and record.event.cell_id != cell_id:
                continue
            if start is not None and record.event.ts < start:
                continue
            if end is not None and record.event.ts >= end:
                continue
            found.append(record)
        return found

    def verify_chain(self) -> ChainVerification:
        """Re-walk the file recomputing every hash.

        Returns a verdict in every case, including a damaged or absent file --
        never a traceback. ``broken_at_seq`` is the position in the walk, not a
        value read out of the file, so a tampered record cannot misdirect it.
        """
        if not self._path.exists():
            return ChainVerification(
                False,
                None,
                f"no audit store at {self._path}: there is no evidence here to verify",
            )

        expected_prev = GENESIS_HASH
        position = 0
        try:
            for line in self._raw_lines():
                if not isinstance(line, dict):
                    return ChainVerification(
                        False, position, "record is not a JSON object",
                        position, expected_prev,
                    )
                if line.get("seq") != position:
                    return ChainVerification(
                        False, position,
                        f"expected seq {position}, found {line.get('seq')!r}",
                        position, expected_prev,
                    )
                if line.get("prev_hash") != expected_prev:
                    return ChainVerification(
                        False, position,
                        "prev_hash does not match the preceding record",
                        position, expected_prev,
                    )
                body = {k: v for k, v in line.items() if k != "record_hash"}
                if _body_hash(body) != line.get("record_hash"):
                    return ChainVerification(
                        False, position,
                        "record_hash does not match the record contents",
                        position, expected_prev,
                    )
                expected_prev = line["record_hash"]
                position += 1
        except (
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            return ChainVerification(
                False, position, f"record could not be parsed: {exc}",
                position, expected_prev,
            )

        if position == 0:
            return ChainVerification(
                False,
                None,
                f"audit store at {self._path} is empty: there is no evidence here "
                "to verify",
            )
        return ChainVerification(True, None, None, position, expected_prev)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS — 20 passed

- [ ] **Step 6: Commit**

```bash
git add estop_audit/store.py tests/conftest.py tests/test_store.py
git commit -m "feat: hash-chained append-only audit store with idempotent receive"
```

---

## Task 3: Resolution-aware measurement

**Files:**
- Create: `estop_audit/measurement.py`
- Test: `tests/test_measurement.py`

**Interfaces:**
- Consumes: from `estop_audit.events` — `Event`, `parse_event`.
- Produces: `Bound(nominal_seconds, lower_seconds_exclusive, upper_seconds_exclusive, source_resolution_seconds)` with `.as_dict()`, `ResponseTime(bound, method, clock_authority, causal_order_established, defensible_claim)` with `.as_dict()` (flattened), `interval_bound(earlier: Event, later: Event) -> Bound`, `response_time(request: Event, halt: Event) -> ResponseTime`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_measurement.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_measurement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.measurement'`

- [ ] **Step 3: Write the implementation**

Write `estop_audit/measurement.py`:

```python
"""Interval arithmetic that carries its own uncertainty.

Whole-second timestamps cannot support a point measurement, so nothing here
returns one unaccompanied. Every interval is an open bound plus the resolution
that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import Event

CLOCK_AUTHORITY = "cell_wall_clock_unverified"
"""``ts`` is presumed cell wall-clock with no monotonic reference. An NTP step or
a controller reboot can move it backwards and today that is undetectable
(docs/firmware-event-schema-v4.2.md lines 47-50, point 4 'No clock authority'). Every interval computed from
``ts`` inherits this caveat and says so."""


def _fmt(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class Bound:
    """An open interval known to contain the true value."""

    nominal_seconds: float
    lower_seconds_exclusive: float
    upper_seconds_exclusive: float
    source_resolution_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "nominal_seconds": self.nominal_seconds,
            "lower_bound_seconds_exclusive": self.lower_seconds_exclusive,
            "upper_bound_seconds_exclusive": self.upper_seconds_exclusive,
            "source_resolution_seconds": self.source_resolution_seconds,
        }


@dataclass(frozen=True)
class ResponseTime:
    """A :class:`Bound` plus the fields that make it quotable to an inspector.

    Deliberately a distinct type from :class:`Bound` so that a bare interval --
    a stoppage duration, say -- cannot be serialised into the ``response_time``
    slot of an audit record without its method, clock caveat, and claim.
    """

    bound: Bound
    method: str
    clock_authority: str
    causal_order_established: bool
    defensible_claim: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.bound.as_dict(),
            "method": self.method,
            "clock_authority": self.clock_authority,
            "causal_order_established": self.causal_order_established,
            "defensible_claim": self.defensible_claim,
        }


def interval_bound(earlier: Event, later: Event) -> Bound:
    """Bound the true interval between two quantised timestamps.

    Let ``d`` be the observed difference and ``r_e``/``r_l`` the two events'
    timestamp resolutions.

    * Under **truncation** the true value lies in ``(d - r_e, d + r_l)``.
    * Under **rounding** it lies in ``(d - h, d + h)`` where ``h = (r_e + r_l)/2``.

    We do not know which convention the controller uses, so we take the union --
    the bound that is correct under either. When both resolutions are equal (every
    case in today's data, ``r = 1 s``) the two conventions coincide and this
    reduces to ``(d - r, d + r)``.
    """
    delta = (later.ts - earlier.ts).total_seconds()
    r_earlier = earlier.ts_resolution_seconds
    r_later = later.ts_resolution_seconds
    half = (r_earlier + r_later) / 2
    return Bound(
        nominal_seconds=delta,
        lower_seconds_exclusive=delta - max(r_earlier, half),
        upper_seconds_exclusive=delta + max(r_later, half),
        source_resolution_seconds=max(r_earlier, r_later),
    )


def response_time(request: Event, halt: Event) -> ResponseTime:
    """Stop response time for a matched request/halt pair."""
    bound = interval_bound(request, halt)
    causal_order_established = bound.lower_seconds_exclusive >= 0

    if causal_order_established:
        claim = f"stop response < {_fmt(bound.upper_seconds_exclusive)} s"
    else:
        claim = (
            f"stop response not established: the two events lie within "
            f"{_fmt(bound.source_resolution_seconds)} s of one another, so the halt "
            f"cannot be shown to follow the request at this timestamp resolution"
        )

    method = (
        "derived_from_whole_second_controller_wall_clock"
        if bound.source_resolution_seconds == 1.0
        else "derived_from_sub_second_controller_wall_clock"
    )

    return ResponseTime(
        bound=bound,
        method=method,
        clock_authority=CLOCK_AUTHORITY,
        causal_order_established=causal_order_established,
        defensible_claim=claim,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_measurement.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add estop_audit/measurement.py tests/test_measurement.py
git commit -m "feat: resolution-aware interval bounds and stop response time"
```

---

## Task 4: Run partitioning, stop episodes, and fan-out pairing

This is the core of the service. The module docstring on `pair_stops` is a **required deliverable**, not decoration — without it the natural instinct of the next maintainer is to simplify fan-out back to a `pop(0)` loop and silently reintroduce the inversion described below.

**Files:**
- Create: `estop_audit/sequences.py`
- Test: `tests/test_sequences.py`

**Interfaces:**
- Consumes: from `estop_audit.events` — `Event`, `iso_z`.
- Produces: `PAUSE_CLASSIFICATION: dict[str, str]`, `EPISODE_CLOSING_TYPES: tuple[str, ...]`, `classify_pause(event: Event) -> str`, `RunView(scope, cell_id, run_id, events, completed, truncated)`, `StopSequence(request, halt, outcome, evidence_status, co_satisfied_with, episode_closed_by, episode_closed_by_event_key, ordering_confidence, notes, episode_events)` with property `.anchor -> Event`, `partition_runs(events: Iterable[Event]) -> list[RunView]`, `Episode(events, closer, carried_request_keys)` (a `NamedTuple`, so index access still works), `split_episodes(run: RunView) -> list[Episode]`, `pair_stops(run: RunView) -> list[StopSequence]`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_sequences.py`:

```python
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


def test_an_orphan_halt_tied_with_its_episode_closer_is_flagged_ambiguous():
    # The matched path already discloses this exact tie. Omitting it here would
    # mean the service discloses ties only when the resulting record reads well.
    run = only_run([ev(10, "motion.halted"), ev(10, "run.resumed")])
    [sequence] = pair_stops(run)
    assert sequence.outcome == "orphan_halt"
    assert sequence.ordering_confidence == "ambiguous"
    assert any("not determinable" in note for note in sequence.notes)


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sequences.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.sequences'`

- [ ] **Step 3: Write the implementation**

Write `estop_audit/sequences.py`:

```python
"""Partition the event stream into runs, split runs into stop episodes, and pair
each stop request with the halt that answered it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, NamedTuple

from .events import Event, iso_z

PAUSE_CLASSIFICATION: dict[str, str] = {
    "estop": "safety",
    "material_reload": "operational",
}
"""``run.paused`` is overloaded: one event type carries both a safety stop and a
routine material reload. An inspector's audit log must distinguish them
(docs/firmware-event-schema-v4.2.md lines 51-54, point 5 'run.paused is overloaded').

Adding a firmware reason is a one-line change here. Anything absent from this
table is ``unclassified`` -- never ``operational``. An unrecognised pause reason
is a question for a human; quietly filing it as routine is precisely the failure
inspection action a2 exists to prevent.
"""

EPISODE_CLOSING_TYPES: tuple[str, ...] = ("run.resumed", "run.completed")

TIE_RELEVANT_TYPES: tuple[str, ...] = (
    "stop.requested",
    "motion.halted",
) + EPISODE_CLOSING_TYPES
"""Event types whose presence in a timestamp group makes another event's record
rest on a tie. Closers count: a halt tied with the ``run.resumed`` that ended its
episode has its episode membership asserted by the record (``episode_closed_by``,
``episode_events``) on evidence the timestamps cannot supply."""


def classify_pause(event: Event) -> str:
    """Safety vs routine for a ``run.paused`` event.

    Exposed at module level, not buried inside record assembly, so the mapping
    can be tested directly against a pause that belongs to no stop sequence --
    which is exactly what the sample's ``material_reload`` pause is.

    Raises on any other event type. Answering silently for, say, a ``run.resumed``
    that happened to carry a ``reason`` field would classify it as a safety event.
    """
    if event.type != "run.paused":
        raise ValueError(
            f"classify_pause expects a run.paused event, got {event.type!r}"
        )
    return PAUSE_CLASSIFICATION.get(event.raw.get("reason"), "unclassified")


@dataclass(frozen=True)
class RunView:
    """One ``(cell_id, run_id)`` partition, sorted into analysis order."""

    scope: tuple[str, str | None]
    cell_id: str
    run_id: str | None
    events: tuple[Event, ...]
    completed: bool
    truncated: bool

    @property
    def run_scope(self) -> str:
        return "in_run" if self.run_id is not None else "outside_run"


@dataclass(frozen=True)
class StopSequence:
    """One stop demand and whatever answered it, or failed to."""

    request: Event | None            # None only for an orphan halt
    halt: Event | None               # None for an unmatched request
    outcome: str                     # matched | no_halt_recorded | orphan_halt
    evidence_status: str             # complete | truncated
    co_satisfied_with: tuple[str, ...]
    episode_closed_by: str           # run.resumed | run.completed | stream_end
    episode_closed_by_event_key: str | None
    ordering_confidence: str         # unambiguous | ambiguous
    notes: tuple[str, ...]
    episode_events: tuple[Event, ...] = field(default=(), compare=False, repr=False)

    @property
    def anchor(self) -> Event:
        """The event a record is filed under: the request, or the orphan halt."""
        anchor = self.request or self.halt
        assert anchor is not None, "a stop sequence must have a request or a halt"
        return anchor


def partition_runs(events: Iterable[Event]) -> list[RunView]:
    """Group events by ``(cell_id, run_id)`` and sort each group into analysis order.

    The partition key is the **pair**, not ``run_id`` alone. ``runId`` may legitimately
    be null (docs/firmware-event-schema-v4.2.md line 70, "null for events outside a
    run"); keying on it alone would collect every out-of-run event, across all cells and
    all time, into a single bucket -- reintroducing unbounded pairing lookahead through
    the back door.

    Sorting is stable on ``(ts, arrival_ordinal)``: whole-second timestamps make
    same-second events unorderable, so arrival order breaks the tie and any pairing that
    depends on such a tie is flagged downstream rather than silently trusted.
    """
    numbered: dict[tuple[str, str | None], list[tuple[int, Event]]] = {}
    for ordinal, event in enumerate(events):
        numbered.setdefault(event.scope, []).append((ordinal, event))

    runs = []
    for scope, items in numbered.items():
        items.sort(key=lambda pair: (pair[1].ts, pair[0]))
        ordered = tuple(event for _, event in items)
        completed = any(event.type == "run.completed" for event in ordered)
        runs.append(
            RunView(
                scope=scope,
                cell_id=scope[0],
                run_id=scope[1],
                events=ordered,
                completed=completed,
                truncated=not completed,
            )
        )
    runs.sort(key=lambda run: (run.cell_id, run.run_id or ""))
    return runs


def _group_by_ts(events: Iterable[Event]) -> list[tuple[datetime, list[Event]]]:
    """Group consecutive events that share a timestamp.

    Whole-second timestamps make events within one second unorderable, so the
    order they happen to arrive in must never decide an outcome. Grouping is how
    that rule is enforced rather than merely intended: everything in a group is
    treated as simultaneous, and the analysis sort has already placed groups in
    timestamp order.
    """
    groups: list[tuple[datetime, list[Event]]] = []
    for event in events:
        if groups and groups[-1][0] == event.ts:
            groups[-1][1].append(event)
        else:
            groups.append((event.ts, [event]))
    return groups


class Episode(NamedTuple):
    """One stop episode: its events, what closed it, and what was carried in.

    A ``NamedTuple`` so that ``episode[0]`` / ``episode[1]`` keep working for
    callers written against the earlier two-tuple shape.
    """

    events: tuple[Event, ...]
    closer: Event | None
    carried_request_keys: frozenset[str]


def split_episodes(run: RunView) -> list[Episode]:
    """Split a run into stop episodes, each with the event that closed it.

    An episode is closed by ``run.resumed`` or ``run.completed``. A trailing episode
    with no closer is closed by the end of the ingested stream and reports ``None``.

    The split falls at a *timestamp group* boundary, not an event boundary. A halt
    sharing a second with the resume that closes its episode is unorderable against
    it, so it stays inside the episode it might belong to rather than being orphaned
    into the next one by an arrival-order accident.

    **A ``stop.requested`` tied with the closer is carried into the NEXT
    episode -- but only when no ``motion.halted`` shares that same second.** If
    one does, the
    request stays, because a halt in its own second can answer it and fan-out will
    do so. Carrying it out regardless would tear apart a pairing the data supports
    and republish it as a failure. Its key is reported in ``carried_request_keys``
    so the pairing can disclose the tie. The two readings are "the demand was raised just before the cell
    resumed and went unanswered" and "the demand was raised just after the resume
    and belongs to what follows", and at whole-second resolution nothing
    distinguishes them. Keeping it here would publish the first reading as fact --
    a fabricated *the cell did not stop* finding, decided by a tiebreak. Carrying it
    forward lets a halt in the next episode answer it, and if none does it is still
    reported unanswered, only now with the ambiguity on the record.
    """
    episodes: list[Episode] = []
    current: list[Event] = []
    carried_in: frozenset[str] = frozenset()

    for _ts, group in _group_by_ts(run.events):
        closer = next((e for e in group if e.type in EPISODE_CLOSING_TYPES), None)
        if closer is None:
            current.extend(group)
            continue

        if any(e.type == "motion.halted" for e in group):
            # A halt in this same second can answer the tied requests, and
            # fan-out will pair it with every request outstanding when it
            # arrives. Carrying them out would tear apart a pairing the data
            # actually supports and republish it as failures -- the exact
            # worst-direction outcome this module exists to prevent.
            carry_forward: list[Event] = []
            current.extend(group)
        else:
            carry_forward = [e for e in group if e.type == "stop.requested"]
            current.extend(e for e in group if e.type != "stop.requested")

        episodes.append(Episode(tuple(current), closer, carried_in))
        current = list(carry_forward)
        carried_in = frozenset(e.key for e in carry_forward)

    if current:
        episodes.append(Episode(tuple(current), None, carried_in))
    return episodes


def pair_stops(run: RunView) -> list[StopSequence]:
    """Pair stop requests with halts, fanning out within bounded stop episodes.

    Two rules, and the second is what makes the first safe.

    **1. A halt satisfies every request outstanding when it arrives.** It is not
    *consumed* by one of them.

    "Which request did this halt answer?" has no single correct answer when more than
    one demand was outstanding -- physically the halt answered all of them. The
    alternatives were considered and each fails in a specific way:

    * *FIFO* picks the earliest and reports the others as unmatched, fabricating a
      safety finding against stops that in fact worked.
    * *LIFO* picks the latest, which reports the shortest delta -- the flattering bias,
      and the wrong one to build into a safety record.
    * *Refusing to pair when ambiguous* yields zero measurements on a cell with
      redundant triggers (light curtain **and** operator button), failing inspection
      action a3 rather than satisfying it.

    Fan-out asserts only what is observable: N demands, one halt, N deltas -- with the
    earliest demand yielding the largest and therefore most conservative number. Every
    affected record discloses the others via ``co_satisfied_with``.

    **2. A stop episode is closed by ``run.resumed``, ``run.completed``, or the end of
    the ingested stream -- whichever comes first.** A request still open at closure is
    ``no_halt_recorded`` and can never be paired afterwards.

    Without this boundary, pairing inverts the very finding it exists to produce. Given
    a run where one stop fails and a later, unrelated stop succeeds::

        07:15:33  stop.requested   R1
           --     (no halt -- THIS IS THE FINDING)
        07:17:33  run.resumed          <- closes R1's episode
        09:00:00  stop.requested   R2
        09:00:01  motion.halted    H

    unbounded lookahead pairs R1 with H and reports the **failed** stop as matched with
    a 1h44m response time, while reporting the **successful** stop as
    ``no_halt_recorded``. Both records are wrong, in the worst available direction, on
    the one record an inspector cares most about. The episode boundary is what stops
    it: R1 closes at the resume and can never see H.

    **The boundary only helps where a closing event actually intervenes.** Delete the
    ``run.resumed`` row above and both requests sit in one episode, so fan-out attaches
    R1 to H and reports a 1h44m "stop response" without complaint. That is not
    hypothetical -- it is exactly what happens if firmware can pause without ever
    resuming, and it is why the open question below is load-bearing rather than a
    nicety.

    A fixed time window would also fix this, but requires a constant we would be
    inventing -- and "why 30 seconds?" has no good answer at an inspection. The episode
    boundary is derived from an event the controller already emits, needs no constant,
    stays stable when FM-5 reads 24h of events off the same store, and is explainable in
    one sentence: *the cell started running again, so that stop was over.*

    Open with Chris (week 1): is ``run.resumed`` guaranteed after every ``run.paused``?
    If not, this needs a deliberately generous time-window backstop, recorded per record
    so the policy is visible rather than hidden in code.
    """
    sequences: list[StopSequence] = []
    for episode in split_episodes(run):
        sequences.extend(_pair_episode(episode))
    return sequences


def _pair_episode(episode: Episode) -> list[StopSequence]:
    episode_events, closer, carried_request_keys = episode
    closed_by = closer.type if closer is not None else "stream_end"
    closed_key = closer.key if closer is not None else None

    def build(**overrides: Any) -> StopSequence:
        base: dict[str, Any] = {
            "request": None,
            "halt": None,
            "co_satisfied_with": (),
            "episode_closed_by": closed_by,
            "episode_closed_by_event_key": closed_key,
            "ordering_confidence": "unambiguous",
            "notes": (),
            "episode_events": episode_events,
        }
        base.update(overrides)
        return StopSequence(**base)

    def carried_note(request: Event) -> str | None:
        if request.key not in carried_request_keys:
            return None
        return (
            f"stop.requested {request.key} shares its timestamp with the event that "
            f"closed the preceding episode; which episode it belongs to is not "
            f"determinable at {request.ts_resolution_seconds:g}s resolution. It was "
            f"carried forward rather than reported as a failed stop on a tiebreak"
        )

    sequences: list[StopSequence] = []
    open_requests: list[Event] = []
    episode_rests_on_a_tie = False

    for _ts, group in _group_by_ts(episode_events):
        # Every request in the group is admitted before any halt in it is
        # considered. Within one second nothing distinguishes a request that
        # arrived before its halt from one that arrived after, so a halt here must
        # be able to answer a request here. Process events one at a time instead
        # and swapping two lines of the input file turns a working stop into a
        # fabricated "the cell did not stop" finding paired with an unexplained
        # orphan halt -- and one that claims to be unambiguous. A fast cell makes
        # this MORE likely, not less: a sub-second stop response lands both events
        # in the same second.
        group_requests = [e for e in group if e.type == "stop.requested"]
        # Could a halt in this group have taken a demand at all? If not, two halts
        # tied here are not competing for anything: their records are identical
        # under either ordering, and flagging them would dilute the signal until
        # an inspector cannot tell a genuinely uncertain record from a certain one.
        demand_available = bool(group_requests) or bool(open_requests)
        open_requests.extend(group_requests)

        for event in group:
            if event.type != "motion.halted":
                continue

            if not open_requests:
                notes = [
                    "no stop.requested was outstanding in this episode when the "
                    "halt arrived; this halt cannot be attributed to a recorded "
                    "demand"
                ]
                ordering = "unambiguous"
                # An orphan produced by a tie is not an orphan we are sure about:
                # another halt in this same second already consumed the demands,
                # and which halt answered which is not knowable at this resolution.
                # Scan the whole group, not just what precedes this halt, and
                # exclude by identity rather than key: two byte-identical halts
                # in one second share an event_key, and excluding by value makes
                # each erase the other from the tie set -- so both would report
                # "unambiguous" about a tie they are themselves part of.
                #
                # Closers are in TIE_RELEVANT_TYPES deliberately. The matched path
                # already flags a halt tied with its closer as ambiguous; omitting
                # it here would disclose the same physical tie on a record that
                # reads well and hide it on one that reads badly. This record also
                # asserts episode membership the tie cannot support.
                tied = [
                    other
                    for other in group
                    if other is not event
                    and other.type in TIE_RELEVANT_TYPES
                    and (other.type != "motion.halted" or demand_available)
                ]
                if tied:
                    ordering = "ambiguous"
                    notes.append(
                        f"this motion.halted shares timestamp {iso_z(event.ts)} "
                        f"with {len(tied)} other stop-sequence event(s) "
                        f"({', '.join(e.key for e in tied)}); which halt answered "
                        f"which demand is not determinable at "
                        f"{event.ts_resolution_seconds:g}s resolution"
                    )
                elif episode_rests_on_a_tie:
                    # This halt found nothing outstanding -- but the demands were
                    # consumed by a pairing that itself rested on a tie. Under the
                    # other reading one of them was still open when this halt
                    # arrived, and this halt is not an orphan at all. Its very
                    # existence as an adverse record depends on a coin toss.
                    ordering = "ambiguous"
                    notes.append(
                        "an earlier pairing in this episode rested on a "
                        "same-second tie, so which demands were still available "
                        "to this halt is not determinable; under the alternative "
                        "reading this halt may not be unattributable at all"
                    )
                sequences.append(
                    build(
                        halt=event,
                        outcome="orphan_halt",
                        evidence_status="complete",
                        ordering_confidence=ordering,
                        notes=tuple(notes),
                    )
                )
                continue

            outstanding = list(open_requests)
            open_requests = []
            for index, request in enumerate(outstanding):
                # Exclude by position, not by key value: two requests could share
                # an event_key (the content-collision hole in events.event_key),
                # and excluding by value would make each erase the other.
                others = tuple(
                    other.key
                    for position, other in enumerate(outstanding)
                    if position != index
                )
                notes = []
                ordering = "unambiguous"

                if request.ts == event.ts:
                    ordering = "ambiguous"
                    notes.append(
                        f"stop.requested {request.key} and motion.halted "
                        f"{event.key} share timestamp {iso_z(event.ts)}; their "
                        f"order is not determinable at "
                        f"{event.ts_resolution_seconds:g}s resolution, so this "
                        f"pairing rests on simultaneity rather than observed order"
                    )
                if closer is not None and closer.ts == event.ts:
                    ordering = "ambiguous"
                    notes.append(
                        f"motion.halted {event.key} and the {closer.type} that "
                        f"closed this episode ({closer.key}) share timestamp "
                        f"{iso_z(event.ts)}; whether the halt preceded the episode "
                        f"close is not determinable at this resolution"
                    )
                carried = carried_note(request)
                if carried is not None:
                    ordering = "ambiguous"
                    notes.append(carried)
                if others:
                    notes.append(
                        f"this motion.halted also answered {len(others)} other "
                        f"outstanding stop demand(s); see co_satisfied_with"
                    )

                sequences.append(
                    build(
                        request=request,
                        halt=event,
                        outcome="matched",
                        evidence_status="complete",
                        co_satisfied_with=others,
                        ordering_confidence=ordering,
                        notes=tuple(notes),
                    )
                )
                if ordering == "ambiguous":
                    episode_rests_on_a_tie = True

    # Anything still open when the episode closed was never answered.
    for request in open_requests:
        if closer is not None:
            evidence, note = (
                "complete",
                f"request was still open when the episode closed on {closed_by}; "
                f"the episode demonstrably ended without a recorded halt",
            )
        else:
            evidence, note = (
                "truncated",
                "request was still open when the ingested stream ended; this is "
                "absence of evidence, not evidence that the cell failed to stop",
            )
        notes = [note]
        ordering = "unambiguous"
        carried = carried_note(request)
        if carried is not None:
            ordering = "ambiguous"
            notes.append(carried)
        sequences.append(
            build(
                request=request,
                halt=None,
                outcome="no_halt_recorded",
                evidence_status=evidence,
                ordering_confidence=ordering,
                notes=tuple(notes),
            )
        )

    return sequences
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sequences.py -v`
Expected: PASS — 39 passed

- [ ] **Step 5: Run the whole suite to check nothing regressed**

Run: `python -m pytest -v`
Expected: PASS — 84 passed (17 events + 20 store + 8 measurement + 39 sequences)

- [ ] **Step 6: Commit**

```bash
git add estop_audit/sequences.py tests/test_sequences.py
git commit -m "feat: fan-out stop pairing within bounded stop episodes

A halt satisfies every outstanding demand rather than being consumed by
one, and lookahead is bounded by run.resumed/run.completed/stream end.
Unbounded FIFO would report a failed stop as matched against a later
unrelated halt while reporting the working stop as no_halt_recorded."
```

---

## Task 5: Audit record assembly and the per-axis amendment seam

**Files:**
- Create: `estop_audit/records.py`
- Test: `tests/test_records.py`

**Interfaces:**
- Consumes: from `estop_audit.events` — `Event`, `iso_z`; from `estop_audit.measurement` — `interval_bound`, `response_time`; from `estop_audit.sequences` — `RunView`, `StopSequence`, `classify_pause`. `attach_per_axis_measurement` takes its store **structurally** (anything with `.append(raw)`) rather than importing `AppendOnlyAuditStore`, which keeps the dependency chain one-way: `records` must not import `store`.
- Produces: `AMENDMENT_EVENT_TYPE: str`, `RECORD_VERSION: str`, `record_id_for(sequence: StopSequence, run: RunView) -> str`, `collect_amendments(events: Iterable[Event]) -> dict[str, list[dict]]`, `attach_per_axis_measurement(store, *, record_id, cell_id, measurements, source, attested_by, measured_at, run_id=None) -> AppendResult`, `build_record(sequence: StopSequence, run: RunView, *, all_runs: list[RunView], amendments: dict[str, list[dict]] | None = None) -> dict`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_records.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_records.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.records'`

- [ ] **Step 3: Write the implementation**

Write `estop_audit/records.py`:

```python
"""Assemble the audit record an inspector reads, and the seam that lets rig-supplied
per-axis numbers arrive later without anything being rewritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .events import Event, iso_z
from .measurement import interval_bound, response_time
from .sequences import RunView, StopSequence, classify_pause

RECORD_VERSION = "1.0"
AMENDMENT_EVENT_TYPE = "audit.amendment.per_axis"

PER_AXIS_UNAVAILABLE_REASON = (
    "motion.halted reports every axis under a single timestamp; no per-axis delta "
    "is derivable from this source"
)
PER_AXIS_EXPECTED_SOURCE = (
    "external rig instrumentation, or firmware v4.2 axis.halted events "
    "(docs/firmware-event-schema-v4.2.md, 'Required for inspection action 3')"
)

_MAX_CROSS_RUN_CANDIDATES = 3


def _short(key: str) -> str:
    return key.removeprefix("sha256:")[:12]


def record_id_for(sequence: StopSequence, run: RunView) -> str:
    """Stable identity for a record, derived from event content.

    The ``req:`` / ``halt:`` segment keeps the two namespaces from colliding and makes
    the record's anchor visible in the identifier itself. An orphan halt has no request
    to derive from, so it is addressed on its halt.
    """
    anchor_kind = "req" if sequence.request is not None else "halt"
    return f"{run.cell_id}:{run.run_id or '-'}:{anchor_kind}:{_short(sequence.anchor.key)}"


def collect_amendments(events: Iterable[Event]) -> dict[str, list[dict[str, Any]]]:
    """Index amendment events by the ``record_id`` they amend."""
    indexed: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.type != AMENDMENT_EVENT_TYPE:
            continue
        record_id = event.raw.get("recordId")
        if record_id is None:
            continue
        indexed.setdefault(record_id, []).append(
            {
                "ts": iso_z(event.ts),
                "source": event.raw.get("source"),
                "attested_by": event.raw.get("attestedBy"),
                "measurements": event.raw.get("measurements", []),
                "event_key": event.key,
            }
        )
    for entries in indexed.values():
        entries.sort(key=lambda entry: entry["ts"])
    return indexed


def attach_per_axis_measurement(
    store: Any,
    *,
    record_id: str,
    cell_id: str,
    measurements: list[dict[str, Any]],
    source: str,
    attested_by: str,
    measured_at: datetime,
    run_id: str | None = None,
) -> Any:
    """Attach rig-supplied per-axis numbers by **appending** an amendment.

    The original record is never mutated -- it is recomputed from the log, and the
    amendment is part of that log. The audit store's append-only property therefore
    stays literally true, and the inspector can see when the per-axis data arrived, who
    attested it, and that its source was the rig rather than the controller.
    """
    return store.append(
        {
            "ts": iso_z(measured_at),
            "cellId": cell_id,
            "runId": run_id,
            "event": AMENDMENT_EVENT_TYPE,
            "recordId": record_id,
            "source": source,
            "attestedBy": attested_by,
            "measurements": measurements,
        }
    )


def _event_summary(event: Event, *fields: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"ts": iso_z(event.ts)}
    for name in fields:
        summary[_snake(name)] = event.raw.get(name)
    summary["event_key"] = event.key
    return summary


def _snake(camel: str) -> str:
    out: list[str] = []
    for char in camel:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)


def _build_context(
    sequence: StopSequence, run: RunView, all_runs: list[RunView]
) -> dict[str, Any]:
    anchor_ts = sequence.anchor.ts
    window = [event for event in sequence.episode_events if event.ts >= anchor_ts]

    pause = next((e for e in window if e.type == "run.paused"), None)
    resume = next((e for e in window if e.type == "run.resumed"), None)

    context: dict[str, Any] = {
        "interlock_engaged": [
            _event_summary(e, "zone") for e in window if e.type == "interlock.engaged"
        ],
        "interlock_released": [
            _event_summary(e, "zone", "operator")
            for e in window
            if e.type == "interlock.released"
        ],
        "pause": None,
        "resume": None,
        "stoppage_duration": None,
        "cross_run_halt_candidates": _cross_run_candidates(sequence, run, all_runs),
    }

    if pause is not None:
        context["pause"] = {
            "ts": iso_z(pause.ts),
            "reason": pause.raw.get("reason"),
            "classification": classify_pause(pause),
            "event_key": pause.key,
        }
    if resume is not None:
        context["resume"] = _event_summary(resume, "resumeMode", "panelId")
    if pause is not None and resume is not None:
        context["stoppage_duration"] = interval_bound(pause, resume).as_dict()

    return context


def _cross_run_candidates(
    sequence: StopSequence, run: RunView, all_runs: list[RunView]
) -> list[dict[str, Any]]:
    """Halts on the same cell, in a *different* run, that a request might look like it
    should have paired with.

    Surfaced so the inspector can pull the thread; flagged so we do not pull it for
    them. Pairing across runs with a caveat was rejected: it invents evidence, and a
    ``runId`` bug in firmware would silently manufacture response times.
    """
    if sequence.request is None or sequence.outcome != "no_halt_recorded":
        return []

    candidates = []
    for other in all_runs:
        if other.scope == run.scope or other.cell_id != run.cell_id:
            continue
        for event in other.events:
            if event.type == "motion.halted" and event.ts >= sequence.request.ts:
                candidates.append(
                    {
                        "run_id": other.run_id,
                        "ts": iso_z(event.ts),
                        "event_key": event.key,
                        "not_counted_as_evidence": True,
                        "reason": "a halt in a different run is not evidence that "
                        "this request was answered",
                    }
                )
    candidates.sort(key=lambda candidate: candidate["ts"])
    return candidates[:_MAX_CROSS_RUN_CANDIDATES]


def _build_per_axis(
    sequence: StopSequence, amendments: list[dict[str, Any]]
) -> dict[str, Any]:
    axes = []
    if sequence.halt is not None:
        axes = list(sequence.halt.raw.get("axesStopped", []))

    measurements: list[dict[str, Any]] = []
    for amendment in amendments:
        measurements.extend(amendment.get("measurements", []))

    return {
        "status": "supplied_by_amendment" if measurements else "unavailable_from_source",
        "reason": PER_AXIS_UNAVAILABLE_REASON,
        "axes_reported_stopped": axes,
        "measurements": measurements,
        "expected_source": PER_AXIS_EXPECTED_SOURCE,
    }


def build_record(
    sequence: StopSequence,
    run: RunView,
    *,
    all_runs: list[RunView],
    amendments: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Assemble one audit record. Pure: no I/O, no caching, recomputed on every read."""
    record_id = record_id_for(sequence, run)
    own_amendments = (amendments or {}).get(record_id, [])

    record: dict[str, Any] = {
        "record_version": RECORD_VERSION,
        "record_type": "stop_sequence",
        "record_id": record_id,
        "cell_id": run.cell_id,
        "run_id": run.run_id,
        "run_scope": run.run_scope,
        "anchor_ts": iso_z(sequence.anchor.ts),
        "outcome": sequence.outcome,
        "evidence_status": sequence.evidence_status,
        "run_truncated": run.truncated,
        "episode": {
            "closed_by": sequence.episode_closed_by,
            "closed_by_event_key": sequence.episode_closed_by_event_key,
            "co_satisfied_with": list(sequence.co_satisfied_with),
        },
        "stop_request": None,
        "motion_halt": None,
        "response_time": None,
        "per_axis": _build_per_axis(sequence, own_amendments),
        "context": _build_context(sequence, run, all_runs),
        "confidence": {
            "ordering": sequence.ordering_confidence,
            "notes": list(sequence.notes),
        },
        "amendments": own_amendments,
    }

    if sequence.request is not None:
        record["stop_request"] = _event_summary(
            sequence.request, "source", "panelId", "axisInMotion"
        )
    if sequence.halt is not None:
        record["motion_halt"] = _event_summary(sequence.halt, "panelId", "axesStopped")
    if sequence.request is not None and sequence.halt is not None:
        record["response_time"] = response_time(sequence.request, sequence.halt).as_dict()

    return record
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_records.py -v`
Expected: PASS — 15 passed

- [ ] **Step 5: Commit**

```bash
git add estop_audit/records.py tests/test_records.py
git commit -m "feat: audit record assembly with an append-only per-axis amendment seam"
```

---

## Task 6: Plain-text inspector rendering

The renderer exists to make the uncertainty language unskippable. It computes its wording from the record's bound fields rather than reading a pre-baked string, so no rendering path can emit a response time without its limits.

**Files:**
- Create: `estop_audit/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: nothing from other package modules — `render_text` takes a plain record dict, which keeps it trivially testable against hand-written records.
- Produces: `render_text(record: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_report.py`:

```python
from estop_audit.events import parse_event
from estop_audit.records import build_record
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.report'`

- [ ] **Step 3: Write the implementation**

Write `estop_audit/report.py`:

```python
"""Plain-text rendering of an audit record, for a human inspector.

This module exists for one reason: to make the measurement's limits unskippable.
The uncertainty language below is **computed from the record's bound fields**, not
read from a pre-baked string, so there is no rendering path that emits a response
time without also emitting what constrains it.
"""

from __future__ import annotations

import textwrap
from typing import Any

WIDTH = 78
LABEL_WIDTH = 13
_RULE = "=" * WIDTH


def _fmt(value: float) -> str:
    return f"{value:g}"


def _field(label: str, value: Any) -> str:
    """One ``label : value`` line, wrapped to the page width.

    The page declares a width and draws rules that wide; a value that runs past
    it breaks the frame on the printed sheet an inspector is handed. Long values
    are real here -- the per-axis reason and expected source both exceed the
    width on the sample data -- so they wrap under a hanging indent rather than
    being truncated. Nothing on this page may be shortened to fit.
    """
    prefix = f"  {label:<{LABEL_WIDTH}}: "
    text = f"{prefix}{value}"
    if len(text) <= WIDTH:
        return text
    continuation = " " * len(prefix)
    # break_long_words=False: event keys and chain hashes are identifiers, and a
    # 64-hex token split across a line break reads as corruption to an inspector
    # rather than as a wrap. A token too long for the column overflows the width
    # instead -- the lesser of the two wrongs on an evidence document.
    wrapped = textwrap.wrap(
        str(value),
        width=WIDTH - len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    return "\n".join([prefix + wrapped[0]] + [continuation + w for w in wrapped[1:]])


def _response_time_block(record: dict[str, Any]) -> list[str]:
    lines = ["STOP RESPONSE"]
    measured = record.get("response_time")

    if measured is None:
        if record.get("outcome") == "orphan_halt":
            # A halt WAS recorded -- it is printed under CONTEXT on this very
            # page. What is missing is a stop demand to attribute it to, so
            # there is no interval to measure. Falling through to the
            # "not evidenced to have stopped" wording would put a false claim in
            # front of an inspector, contradicted by the page's own CONTEXT
            # block, which is precisely the harm this module exists to prevent.
            lines += [
                "  NOT APPLICABLE - no stop demand was recorded for this halt.",
                "  A motion.halted was observed (see CONTEXT below), but no",
                "  stop.requested could be attributed to it, so there is no",
                "  interval to measure. This is NOT a finding that the cell",
                "  failed to stop; it is a halt whose cause is unrecorded.",
            ]
        elif record.get("evidence_status") != "complete":
            lines += [
                "  Not evidenced - stream incomplete.",
                "  No motion.halted was recorded for this stop demand before the",
                "  ingested stream ended. This is absence of evidence, not evidence",
                "  that the cell failed to stop.",
            ]
        else:
            closed_by = record.get("episode", {}).get("closed_by", "the episode close")
            lines += [
                "  NOT EVIDENCED.",
                f"  The stop episode closed on {closed_by} with no motion.halted",
                "  recorded. On this evidence the cell is not evidenced to have",
                "  stopped in response to this demand.",
            ]
        return lines

    lower = measured["lower_bound_seconds_exclusive"]
    upper = measured["upper_bound_seconds_exclusive"]
    resolution = measured["source_resolution_seconds"]
    resolution_words = (
        "whole-second" if resolution == 1.0 else f"{_fmt(resolution)} s"
    )

    lines.append(_field("Measured", f"{_fmt(measured['nominal_seconds'])} s (nominal)"))
    lines.append(
        _field(
            "Bound",
            f"greater than {_fmt(lower)} s and less than {_fmt(upper)} s",
        )
    )
    lines.append(
        _field("Resolution", f"source timestamps are {resolution_words} ({_fmt(resolution)} s)")
    )
    lines.append(_field("Claim", measured["defensible_claim"]))
    if not measured["causal_order_established"]:
        lines.append(
            "                 The halt cannot be shown to follow the request at this"
        )
        lines.append(
            "                 resolution; the bound spans zero."
        )
    lines.append(_field("Method", measured["method"]))
    lines += [
        _field("Clock", "cell wall-clock, unverified"),
        "                 There is no monotonic reference in this event stream, so a",
        "                 clock step would be undetectable and this interval inherits",
        "                 that caveat.",
    ]
    return lines


def _per_axis_block(record: dict[str, Any]) -> list[str]:
    per_axis = record.get("per_axis", {})
    axes = ", ".join(per_axis.get("axes_reported_stopped", [])) or "none reported"
    lines = ["PER-AXIS RESPONSE"]

    if per_axis.get("status") == "supplied_by_amendment":
        lines.append(_field("Status", "supplied by amendment (see AMENDMENTS below)"))
        for measurement in per_axis.get("measurements", []):
            axis = measurement.get("axis", "?")
            delta = measurement.get("delta_seconds")
            lines.append(_field(f"  {axis}", f"{delta} s"))
    else:
        lines.append(_field("Status", "unavailable from this source"))
    lines.append(_field("Axes stopped", axes))
    lines.append(_field("Reason", per_axis.get("reason", "")))
    lines.append(_field("Expected", per_axis.get("expected_source", "")))
    return lines


def _context_block(record: dict[str, Any]) -> list[str]:
    context = record.get("context", {})
    lines = ["CONTEXT"]

    request = record.get("stop_request")
    if request:
        lines.append(_field("Stop source", request.get("source", "unknown")))
        lines.append(_field("Panel", request.get("panel_id", "-")))
        lines.append(_field("Requested", request["ts"]))
    halt = record.get("motion_halt")
    if halt:
        lines.append(_field("Halted", halt["ts"]))

    for engaged in context.get("interlock_engaged", []):
        lines.append(_field("Interlock on", f"{engaged['ts']}  zone={engaged.get('zone')}"))
    for released in context.get("interlock_released", []):
        lines.append(
            _field(
                "Interlock off",
                f"{released['ts']}  zone={released.get('zone')}  "
                f"operator={released.get('operator')}",
            )
        )

    pause = context.get("pause")
    if pause:
        label = pause.get("classification", "unclassified").upper()
        lines.append(
            _field("Pause", f"{pause['ts']}  reason={pause.get('reason')}  [{label}]")
        )
    resume = context.get("resume")
    if resume:
        lines.append(
            _field("Resume", f"{resume['ts']}  mode={resume.get('resume_mode')}")
        )

    duration = context.get("stoppage_duration")
    if duration:
        lines.append(
            _field(
                "Stoppage",
                f"{_fmt(duration['nominal_seconds'])} s "
                f"(between {_fmt(duration['lower_bound_seconds_exclusive'])} s and "
                f"{_fmt(duration['upper_bound_seconds_exclusive'])} s)",
            )
        )

    lines.append(_field("Episode", f"closed by {record.get('episode', {}).get('closed_by')}"))

    for candidate in context.get("cross_run_halt_candidates", []):
        lines.append(
            _field(
                "Cross-run",
                f"a motion.halted exists in run {candidate.get('run_id')} at "
                f"{candidate.get('ts')} - NOT counted as evidence for this record",
            )
        )
    return lines


def render_text(record: dict[str, Any]) -> str:
    """Render one audit record as a plain-text page."""
    co_satisfied = record.get("episode", {}).get("co_satisfied_with", [])
    run_label = record.get("run_id") or "(outside any run)"
    if record.get("run_truncated"):
        run_label += "  [run stream truncated - no run.completed observed]"

    lines = [
        _RULE,
        f"E-STOP AUDIT RECORD{' ' * 24}record format {record.get('record_version')}",
        _RULE,
        _field("Record ID", record.get("record_id")),
        _field("Cell", record.get("cell_id")),
        _field("Run", run_label),
        _field("Anchor", record.get("anchor_ts")),
        _field("Outcome", record.get("outcome")),
        _field("Evidence", record.get("evidence_status")),
        "",
    ]

    lines += _response_time_block(record) + [""]
    lines += _per_axis_block(record) + [""]
    lines += _context_block(record) + [""]

    if co_satisfied:
        lines += [
            "CONCURRENT DEMANDS",
            f"  This motion.halted also answered {len(co_satisfied)} other outstanding",
            "  stop demand(s). Each has its own record, measured from its own request",
            "  timestamp. These are not independent halts.",
            "",
        ]

    amendments = record.get("amendments", [])
    if amendments:
        lines.append("AMENDMENTS")
        for amendment in amendments:
            lines.append(
                _field(
                    "Attached",
                    f"{amendment.get('ts')}  source={amendment.get('source')}  "
                    f"attested_by={amendment.get('attested_by')}",
                )
            )
        lines.append("")

    notes = record.get("confidence", {}).get("notes", [])
    if notes:
        lines.append("NOTES")
        lines += [f"  - {note}" for note in notes]
        lines.append("")

    lines.append(_RULE)
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add estop_audit/report.py tests/test_report.py
git commit -m "feat: plain-text inspector rendering that cannot omit the bound"
```

---

## Task 7: Service facade and ingest reporting

**Files:**
- Create: `estop_audit/service.py`
- Modify: `estop_audit/__init__.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: everything below it in the dependency chain.
- Produces: `IngestReport(lines_read, events_appended, duplicates_skipped, content_collisions, malformed)`, `EstopAuditService(store)` with `.ingest_file(path) -> IngestReport`, `.ingest_lines(lines) -> IngestReport`, `.query_events(*, cell_id=None, start=None, end=None) -> list[StoredRecord]`, `.stop_records(*, cell_id=None, start=None, end=None) -> list[dict]`, `.render(record) -> str`, `.verify_chain() -> ChainVerification`.

- [ ] **Step 1: Write the failing tests**

Write `tests/test_service.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'estop_audit.service'`

- [ ] **Step 3: Write the implementation**

Write `estop_audit/service.py`:

```python
"""Thin facade over the pipeline. Holds no derived state of its own."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .events import MalformedEventError, event_key, parse_event
from .records import build_record, collect_amendments
from .report import render_text
from .sequences import pair_stops, partition_runs
from .store import AppendOnlyAuditStore, ChainVerification, StoredRecord


@dataclass
class IngestReport:
    """What one ingest call did, including what it could not be sure about."""

    lines_read: int = 0
    events_appended: int = 0
    duplicates_skipped: int = 0
    content_collisions: int = 0
    malformed: list[tuple[int, str]] = field(default_factory=list)


class EstopAuditService:
    def __init__(self, store: AppendOnlyAuditStore):
        self._store = store

    # --- ingest ------------------------------------------------------------

    def ingest_file(self, path: Path | str) -> IngestReport:
        with Path(path).open("r", encoding="utf-8") as handle:
            return self.ingest_lines(handle)

    def ingest_lines(self, lines: Iterable[str]) -> IngestReport:
        """Ingest newline-delimited JSON events.

        ``duplicates_skipped`` and ``content_collisions`` are counted separately and
        deliberately. A key already in the store from an **earlier** call is expected --
        that is re-ingest working. A key repeated **within one batch** is suspicious:
        either a retransmit inside the batch, or two genuinely distinct events that the
        content-hash key cannot tell apart (see ``events.event_key``). Counting the
        second case turns a silent drop into a number on a report.
        """
        report = IngestReport()
        seen_this_call: set[str] = set()

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            report.lines_read += 1

            try:
                raw = json.loads(line)
                parse_event(raw)
            except (json.JSONDecodeError, MalformedEventError) as exc:
                report.malformed.append((line_number, str(exc)))
                continue

            key = event_key(raw)
            if key in seen_this_call:
                report.content_collisions += 1
                continue
            seen_this_call.add(key)

            if self._store.append(raw).appended:
                report.events_appended += 1
            else:
                report.duplicates_skipped += 1

        return report

    # --- retrieval ---------------------------------------------------------

    def query_events(
        self,
        *,
        cell_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[StoredRecord]:
        """Inspection action a2: e-stop events logged and retrievable.

        The time range is half-open: ``[start, end)``.
        """
        return self._store.query(cell_id=cell_id, start=start, end=end)

    def stop_records(
        self,
        *,
        cell_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Inspection action a3: stop response recorded per cell.

        Recomputed from the log on every call -- nothing derived is cached, so no
        record can drift from the evidence that produced it.

        Filtering is on ``anchor_ts``, so a stop sequence is wholly in range or wholly
        out. A window that happens to fall between a request and its halt still returns
        the complete record rather than half of one.
        """
        events = [record.event for record in self._store]
        runs = partition_runs(events)
        amendments = collect_amendments(events)

        records = []
        for run in runs:
            if cell_id is not None and run.cell_id != cell_id:
                continue
            for sequence in pair_stops(run):
                anchor = sequence.anchor.ts
                if start is not None and anchor < start:
                    continue
                if end is not None and anchor >= end:
                    continue
                records.append(
                    build_record(sequence, run, all_runs=runs, amendments=amendments)
                )

        records.sort(key=lambda record: (record["anchor_ts"], record["record_id"]))
        return records

    # --- presentation and integrity ---------------------------------------

    def render(self, record: dict[str, Any]) -> str:
        return render_text(record)

    def verify_chain(self) -> ChainVerification:
        return self._store.verify_chain()
```

- [ ] **Step 4: Export the facade**

Write `estop_audit/__init__.py`:

```python
"""E-stop audit and stop-response measurement (inspection actions a2 and a3)."""

from .service import EstopAuditService, IngestReport
from .store import AppendOnlyAuditStore

__all__ = ["EstopAuditService", "IngestReport", "AppendOnlyAuditStore"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_service.py -v`
Expected: PASS — 10 passed

- [ ] **Step 6: Commit**

```bash
git add estop_audit/service.py estop_audit/__init__.py tests/test_service.py
git commit -m "feat: service facade with ingest reporting that counts what it cannot know"
```

---

## Task 8: Golden test over the real trial data, and the README

**Files:**
- Create: `tests/test_golden_sample.py`
- Create: `README.md`
- Test: `tests/test_golden_sample.py`

**Interfaces:**
- Consumes: `EstopAuditService`, `AppendOnlyAuditStore`, `classify_pause`, `parse_event`.
- Produces: nothing consumed by other tasks. This is the end of the chain.

- [ ] **Step 1: Write the failing test**

Write `tests/test_golden_sample.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails, then passes**

Run: `python -m pytest tests/test_golden_sample.py -v`
Expected: PASS if Tasks 1–7 are correct. If any assertion fails, the bug is in the earlier task, not in this test — fix the module, not the expectation. The one exception: if `lines_read` is not 29, check that `cell-events.jsonl` is unmodified.

- [ ] **Step 3: Run the entire suite**

Run: `python -m pytest -v`
Expected: PASS — 132 passed (17 events + 20 store + 8 measurement + 39 sequences + 15 records + 12 report + 10 service + 11 golden)

- [ ] **Step 4: Write the README**

Write `README.md`:

````markdown
# E-stop audit and stop-response measurement

Slice 1 of the site-inspection chain: inspection action **a2** (e-stop events logged
and retrievable) and **a3** (stop response time measured and recorded per cell).

Python 3.11+, standard library only. `pytest` for the tests.

## Usage

```python
from estop_audit import AppendOnlyAuditStore, EstopAuditService

service = EstopAuditService(AppendOnlyAuditStore("audit/events.jsonl"))
report = service.ingest_file("cell-events.jsonl")

for record in service.stop_records(cell_id="CELL-01"):
    print(service.render(record))
```

Run the tests with `python -m pytest`.

## What this service can prove today

- **That every event we received was persisted in the order received, and that no
  part of the stored log has been altered or reordered in place.** The store is
  append-only and hash-chained; `verify_chain()` re-walks the file and reports the
  first line that fails, along with the record count and head hash.
- **That a `stop.requested` at 07:15:33 was followed by a `motion.halted` at
  07:15:34 on `CELL-01` / `RUN-2026-03-11-A`, and the stop response was under two
  seconds.**
- **That the stop was a safety event**, distinguished from the routine
  `material_reload` pause later in the same run.
- **That re-ingesting the same stream does not duplicate records.**

## What this service cannot prove today

- **Any response time tighter than a two-second bound.** Source timestamps are
  whole-second. The observed delta is 1 s; the true value lies somewhere in the open
  interval (0 s, 2 s). That bound holds whether the controller truncates or rounds,
  so it survives not knowing which convention the firmware uses.
- **Any per-axis figure.** `motion.halted` carries `axesStopped: ["j1".."j6"]` — six
  axes under one timestamp. No per-axis delta is derivable. Records mark this
  `unavailable_from_source` and carry a seam for rig-supplied numbers to be attached
  later as amendments.
- **That the stream was complete.** With no sequence number in the source, a gap is
  unobservable: a quiet cell and a thirty-minute outage look identical. The hash
  chain proves the store was not altered; it says nothing about events that never
  arrived.
- **That timestamps were not moved by a clock step.** `ts` is presumed cell
  wall-clock with no monotonic reference. An NTP step or controller reboot can move
  it backwards and today that is undetectable. Every interval inherits the caveat and
  every record says so.
- **That two distinct events sharing every field and the same whole second were both
  retained.** Identity is a content hash, so such a pair is indistinguishable. Ingest
  counts the suspicion as `content_collisions`; it cannot resolve it.
- **That the log is complete at its end.** Deleting records from the *tail* leaves an
  internally consistent chain that still verifies — seqs contiguous, every hash
  matching. This is the likeliest real tampering (dropping what follows an e-stop) and
  the file alone cannot reveal it. `verify_chain()` therefore reports `records` and
  `head_hash`; comparing those against a value recorded independently at the time —
  a witness log, a countersigned handover, a number written down at shift end — is
  what closes the gap. Without that anchor, `ok=True` means *internally consistent*,
  not *complete*.
- **That the log is authentic against someone with write access.** The chain is
  unkeyed, so anyone who can write the file can recompute it from genesis and produce
  a fabricated log that verifies perfectly. The chain detects accidental corruption
  and careless edits; it is not a signature. Adding one means key management, which
  slice 1 deliberately does not have.

## What changes when firmware v4.2 lands

See `docs/firmware-event-schema-v4.2.md`.

| v4.2 field | What it unlocks | Where it lands |
|---|---|---|
| `eventId` | True idempotency; the content-hash key retires and `content_collisions` becomes meaningless | `events.event_key` |
| `seq` + `bootId` | Gap detection; completeness becomes provable rather than assumed | New work, outside slice 1 |
| Millisecond `ts` | The bound narrows automatically — `ts_resolution_seconds` already reads the resolution off the literal, so no code change is needed | None |
| `monotonicUs` | Interval arithmetic immune to clock steps; `clock_authority` upgrades from `cell_wall_clock_unverified` | `measurement` |
| `axis.halted` per axis | Per-axis deltas become **derived** rather than attached by amendment | `records._build_per_axis` |
| `class` | Safety/operational classification comes from the source instead of a local table | `sequences.PAUSE_CLASSIFICATION` |

## Open questions

Both need answers in week 1. An unanswered question is worse than either answer.

1. **Is `run.resumed` guaranteed to follow every `run.paused`?** Stop-episode
   pairing bounds its lookahead on that event. If the answer is no, a deliberately
   generous time-window backstop is added and recorded per record as
   `pairing_window_seconds`, so the policy is visible rather than hidden in code.
2. **Will v4.2 emit per-axis `axis.halted` events?** If not, a3's measurement stays
   on the rig permanently. That is an acceptable answer: the software side of a3 is
   then the record format and the audit log, and the rig supplies the numbers. See
   `docs/stories.md` lines 222–229.

## Scope

Not included, deliberately: web layer, database, CLI, live controller transport,
buffer-and-reconcile (blocked on the firmware schema), Fleet Monitor UI.

Design: `docs/superpowers/specs/2026-08-25-estop-audit-design.md`.
````

- [ ] **Step 5: Verify the README's central claim against the code**

Run:
```bash
python -c "
from estop_audit import AppendOnlyAuditStore, EstopAuditService
import tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp()) / 'audit.jsonl'
svc = EstopAuditService(AppendOnlyAuditStore(tmp))
svc.ingest_file('cell-events.jsonl')
[record] = svc.stop_records()
print(svc.render(record))
print('chain ok:', svc.verify_chain().ok)
"
```
Expected: a rendered audit page containing `stop response < 2 s`, `unavailable from this source`, `[SAFETY]`, and `chain ok: True`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_golden_sample.py README.md
git commit -m "test: golden assertions over the March trial stream, plus README

States what the service can and cannot prove today, and what changes
when firmware v4.2 lands."
```
