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
