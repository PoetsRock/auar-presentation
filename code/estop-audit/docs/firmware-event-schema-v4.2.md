# Firmware v4.2 — controller event schema contract

**Owner:** Software Engineering Lead
**Audience:** Chris (Robotics Lead)
**Status:** Draft for agreement. **Needed before firmware work starts, week 3.**

---

## Why this document exists

It is the artefact missing from the hand-over. Three separate blockers turn out
to be the same problem — nobody has written down what the controller must
*emit*, only what it must *do*:

| Blocker | Needs from the event schema |
|---|---|
| FM-4 buffer and reconcile | Idempotency key, gap detection, ordering authority |
| Inspection a2 e-stop audit | Tamper-evident ordering, safety-class retention |
| Inspection a3 stop timing | Per-axis halt events, sub-second resolution |

v4.2 is scoped today as "expose run events, accept remote stop." That is a
behaviour spec with no data contract. Boards arrive week 3, firmware follows,
and **there is no v4.3 before 12 October** — so anything not agreed now is not
in the demo.

---

## What is wrong with the stream today

Evidence from `cell-events.jsonl` (March trials, 29 events):

**1. No unique event identifier.** `nailing.started` for `EW-L1-E1` appears
twice — 07:14:51 and 07:20:05 — differing only in `ts`. Both are legitimate;
the second follows an e-stop and a `from_panel_start` resume. Any dedupe on
content or on `(runId, panelId, event)` silently drops a real event. Exactly-once
delivery is impossible without a stable key.

**2. No sequence number.** A gap is undetectable. Receiving events at 07:10 then
07:40 is indistinguishable from a quiet cell and a thirty-minute outage. The
story asks for "no gaps"; today you cannot even observe one.

**3. Whole-second timestamps.** The stop sequence runs
`stop.requested` 07:15:33 → `motion.halted` 07:15:34 → `interlock.engaged`
07:15:35 — consecutive seconds. Any two events landing in the same second are
unorderable, and a3's measurement is capped at 1s granularity.

**4. No clock authority.** `ts` is presumably cell wall-clock. An NTP step or a
controller reboot mid-outage can move timestamps backwards. Ordering a
reconciled buffer by `ts` is unsafe.

**5. `run.paused` is overloaded.** `reason: "estop"` and
`reason: "material_reload"` share one event type. An inspector's audit log must
distinguish a safety event from a routine pause, and the Fleet Monitor must not
alarm on a material reload.

---

## Required envelope

Every event, every type:

```jsonc
{
  "eventId":     "01J8X4...",        // ULID/UUIDv7. Stable across retransmit.
  "seq":         1247,               // Monotonic per (cellId, bootId). Never reused.
  "bootId":      "b-2026-03-11-01",  // New value on every controller restart.
  "ts":          "2026-03-11T07:15:33.412Z",  // UTC, millisecond resolution.
  "monotonicUs": 8143412337,         // Since boot. AUTHORITATIVE for ordering.
  "cellId":      "CELL-01",
  "runId":       "RUN-2026-03-11-A", // null for events outside a run
  "class":       "safety",           // safety | operational | telemetry
  "event":       "motion.halted",
  // ...type-specific payload unchanged
}
```

**Why each field earns its place**

- `eventId` — server-side idempotency. Dedupe on this and only this.
- `seq` — gap detection. Server tracks highest contiguous seq per
  `(cellId, bootId)` and requests replay of anything missing.
- `bootId` — distinguishes a legitimate `seq` reset after reboot from a gap.
  Without it, every restart looks like data loss.
- `ts` at ms — human-readable, and enough resolution for a2's audit log.
- `monotonicUs` — immune to clock steps. Ordering and all interval arithmetic
  use this, never `ts`. This is what makes a3's timing defensible **if** the
  measurement ever moves from the rig to the controller.
- `class` — drives buffer overflow policy and UI alarm behaviour.

## Required for inspection action 3

`motion.halted` must emit **per axis**, not as an array:

```jsonc
{ "event": "axis.halted", "axis": "j1", "requestEventId": "01J8X4...",
  "monotonicUs": 8143412337, "deltaUs": 41200 }
```

Each axis halt references the `stop.requested` that caused it. This makes the
delta computable rather than inferred, and gives the inspector a per-axis record.

**If v4.2 cannot do this, say so in week 1** and a3's measurement stays on the
rig permanently. That is an acceptable answer. An unanswered question is not.

---

## Required protocol

Exactly-once is not achievable at the transport layer. It is achieved as
**at-least-once delivery plus idempotent receive**:

1. Controller writes each event to durable local storage **before** attempting
   transmission. Survives power loss, not just link loss.
2. Controller transmits batches. Server replies with the highest **contiguous**
   `seq` it has durably persisted, per `(cellId, bootId)`.
3. Controller retains everything above that watermark; frees below it. Nothing
   is deleted on send — only on acknowledgement.
4. Server dedupes on `eventId` at write. Replays are free.
5. Server detects gaps by `seq` continuity and requests a replay range.
6. A `bootId` change is a discontinuity marker, not a gap.

### Buffer sizing

Measured from the sample: 29 events across ~26 minutes covering 3 panels, or
roughly **1.1 events/minute**. A 20-panel run is ~2h10m and ~145 events. At
that rate, 24 hours of buffer is on the order of tens of kilobytes.

This is genuinely good news: **the buffer is cheap once the schema is right.**
The difficulty in FM-4 was never volume — it was that the schema made
correctness impossible. Fix the envelope and this becomes a small piece of work.

*Caveat:* the sample emits one `nailing.progress` per panel. If real firmware
emits progress at 1Hz, the rate is ~100× higher and sizing needs redoing.
Confirm with Chris.

### Overflow policy

The buffer must never silently drop a safety event. If retention is exhausted:

| Class | Examples | Policy |
|---|---|---|
| `safety` | `stop.*`, `axis.halted`, `interlock.*` | **Never dropped.** Halt the run before dropping. |
| `operational` | `run.*`, `panel.*`, `nailing.started/completed` | Retain; drop only after telemetry |
| `telemetry` | `nailing.progress` | Drop oldest first |

This matters more than it looks. If the link drops during an e-stop and the
buffer later overflows, the safety evidence for inspection action 2 is gone —
and a2 exists precisely because *"right now we can't prove the cell stopped
when it should have."* Losing it to a buffer policy would be the same failure
with extra steps.

---

## Consequence for the UI

Reconciliation delivers **old events after new ones**. The Fleet Monitor must
separate two concepts that the current design conflates:

- **Current state** — derived from the highest `seq` seen. Never rewinds.
- **Event log** — append-only, ordered by `monotonicUs`, backfilled on
  reconnect.

Without this split, a cell that reconnects after a three-hour outage will
appear to jump backwards to a three-hour-old state on the supervisor's screen.
That is a worse failure than showing nothing, because it looks correct.

---

## What we need from Chris, and when

| Ask | Needed by | If the answer is no |
|---|---|---|
| Confirm envelope fields land in v4.2 | **End of week 1** | FM-4 is cut from the demo; say so now, not in week 6 |
| Confirm `axis.halted` per-axis events | **End of week 1** | a3 measurement stays on the rig permanently |
| Confirm real `nailing.progress` rate | Week 2 | Re-size the buffer |
| Confirm `run.paused` reason taxonomy | Week 2 | Audit log has to infer safety events; weaker for the inspector |

The envelope is a change to the event emitter, not to control logic. The claim
worth testing with Chris is that it is small **relative to v4.2 as a whole** —
but it has to be in v4.2, because there is no later.

---

## Position

FM-4 stays in the plan as *blocked*, not as *cut*, until Chris answers. If the
envelope lands, it is a small piece of work on a cheap buffer. If it does not,
we cut FM-4 in week 1 with a written reason, and the demo runs on a connection
we do not drop.

What we do not do is let Jo start three weeks of telemetry work against a
schema that cannot satisfy the story it exists to serve.
