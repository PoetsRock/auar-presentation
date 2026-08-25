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
With no ``seq`` in the source (deliverables/firmware-event-schema-v4.2.md lines 38-40,
point 2 'No sequence number') a gap is unobservable -- a quiet cell and a
thirty-minute outage look identical. Events lost to a controller buffer overflow
never arrive here, and no property of this file can reveal them.

**Single writer.** One live instance per path. Two would each hold a stale chain
head and fork the file into a state that append-only semantics forbid repairing,
so :meth:`append` refuses rather than corrupting the evidence. This guard is a
file-size check, not a lock: it catches the realistic in-process mistake of two
instances in the same process or a restarted process racing its predecessor,
not a determined, well-timed concurrent writer.
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
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, UnicodeDecodeError, OSError) as exc:
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
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, OSError) as exc:
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
