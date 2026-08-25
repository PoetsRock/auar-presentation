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
