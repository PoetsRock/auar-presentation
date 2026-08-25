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
    deliverables/firmware-event-schema-v4.2.md lines 32-36, point 1 'No unique event identifier': ``nailing.started`` for
    ``EW-L1-E1`` legitimately appears twice, either side of an e-stop resume.
    Deduping on ``(runId, panelId, event)`` would silently drop one of them.

    The residual hole: two *genuinely distinct* events sharing every field
    including their whole-second ``ts`` are indistinguishable here, and the
    second would be dropped. ``IngestReport.content_collisions`` counts that
    case so a collapse is an observable number rather than an absence nobody
    notices.

    TODO(firmware-v4.2): replace with the ``eventId`` field from the required
    envelope in deliverables/firmware-event-schema-v4.2.md. Dedupe on that and only that.
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
    # cellId, runId and event become dict keys (Event.scope) and sort keys
    # downstream in sequences.partition_runs. A non-string value there is not
    # merely wrong, it is unrecoverable: this store is append-only, so a
    # poisoned record admitted here can never be removed without destroying
    # the surrounding evidence. Reject it here, before it is ever persisted.
    if not isinstance(raw["cellId"], str):
        raise MalformedEventError(
            f"cellId must be a string, got {type(raw['cellId']).__name__}"
        )
    if not isinstance(raw["event"], str):
        raise MalformedEventError(
            f"event must be a string, got {type(raw['event']).__name__}"
        )
    run_id = raw.get("runId")
    if run_id is not None and not isinstance(run_id, str):
        raise MalformedEventError(
            f"runId must be a string, got {type(run_id).__name__}"
        )
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
