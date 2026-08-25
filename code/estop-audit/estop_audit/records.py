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
        # recordId is a payload field, not type-checked by parse_event -- see
        # sequences.classify_pause for why the guard belongs here instead. A
        # non-string recordId (None included) can never key indexed.setdefault
        # below, so it is skipped exactly as a missing recordId already was.
        if not isinstance(record_id, str):
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

    cross_run_candidates, cross_run_total = _cross_run_candidates(sequence, run, all_runs)
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
        "cross_run_halt_candidates": cross_run_candidates,
        "cross_run_halt_candidates_total": cross_run_total,
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
) -> tuple[list[dict[str, Any]], int]:
    """Halts on the same cell, in a *different* run, that a request might look like it
    should have paired with.

    Surfaced so the inspector can pull the thread; flagged so we do not pull it for
    them. Pairing across runs with a caveat was rejected: it invents evidence, and a
    ``runId`` bug in firmware would silently manufacture response times.

    Returns the (truncated) list alongside the pre-truncation total, so a caller can
    disclose that the list was cut rather than let an inspector conclude a short list
    is the whole picture.
    """
    if sequence.request is None or sequence.outcome != "no_halt_recorded":
        return [], 0

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
    return candidates[:_MAX_CROSS_RUN_CANDIDATES], len(candidates)


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
