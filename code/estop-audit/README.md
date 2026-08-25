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

- **That every event that parsed, and was not a within-batch content collision, was
  persisted in the order it was accepted, and that no part of the stored log has
  been altered or reordered in place.** The store is append-only and hash-chained;
  `verify_chain()` re-walks the file and reports the first line that fails, along
  with the record count and head hash. This is narrower than "every event we
  received": `ingest_lines` drops malformed lines and within-batch content
  collisions, and counts both on the `IngestReport` it returns. That report is an
  in-memory object, never persisted — the durable store carries no trace of what
  was dropped, only of what it accepted.
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
- **Same-second ordering, where it decides a pairing or an attribution.** Source
  timestamps are whole-second, so two events in the same second are unorderable.
  Where a pairing or an attribution rests on such a tie, the record carries
  `ordering_confidence: "ambiguous"` with a note naming the tied events, and
  `causal_order_established: false` means the halt cannot be shown to have followed
  the request at all — this is the single largest body of work in this branch.
- **That a fan-out halt would have answered each demand individually.** Fan-out
  asserts only that one halt answered every request outstanding when it arrived; it
  is not proof that each of those demands, faced alone, would have been honoured.
- **A plausibility bound on a pairing inside an episode that never closes.** An
  unanswered request in such an episode can be paired with a halt arbitrarily later,
  producing a large delta that is flagged ambiguous but not flagged *implausible*.
  Bounding it needs a plausibility constant this service does not invent — that is
  the robotics lead's decision.
- **That the stream itself was complete, from `evidence_status: "complete"`.** That
  field means no more data could change *this* record's outcome; it does not mean
  the stream was complete, since a gap is unobservable without a sequence number.
- **That the single-writer guard stops a determined writer.** It is a file-size
  check, not a lock. It catches the realistic in-process mistake — two instances
  writing the same path — not a determined, well-timed concurrent race.
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

## Why the code is shaped this way

Condensed from `docs/build-log.md`, which records 54 decisions with what each
costs if wrong. These are the ones that would look arbitrary otherwise.

**A halt satisfies every outstanding stop demand, not one of them.** When more
than one demand is open, "which request did this halt answer?" has no correct
answer — physically it answered all of them. FIFO would report the others as
unmatched, fabricating a safety finding against stops that worked. LIFO would
report the shortest delta, which is the flattering bias and the wrong one to
build into a safety record. Refusing to pair at all yields zero measurements on
a cell with redundant triggers. Fan-out asserts only what is observable: N
demands, one halt, N deltas, the earliest yielding the most conservative number,
each record naming the others in `co_satisfied_with`.

**Pairing lookahead is bounded by a stop episode, not a time window.** Without a
bound, a stop that failed pairs with some later unrelated halt — reporting the
*failed* stop as matched and the *successful* one as `no_halt_recorded`, both
wrong in the worst available direction. A time window would fix it but needs a
constant we would be inventing, and "why 30 seconds?" has no good answer at an
inspection. `run.resumed` is an event the controller already emits, and it is
explainable in one sentence: the cell started running again, so that stop was
over. See Open questions — this rests on that event being guaranteed.

**Same-second events are grouped and treated as simultaneous, never ordered.**
Whole-second timestamps make events within one second genuinely unorderable, so
arrival order must not decide an outcome. Before this was enforced, swapping two
adjacent lines of an input file flipped a `matched` record into a fabricated
"the cell did not stop" finding — which also claimed to be unambiguous. A *fast*
cell makes that more likely, not less: a sub-second stop response puts request
and halt in the same second. Any record whose content would differ under an
alternative ordering carries `ordering_confidence: "ambiguous"` and a note
naming the tied events. Records that would be identical either way stay
`unambiguous`, deliberately — a flag on everything tells an inspector nothing.

**Bounds take the union of two quantisation conventions.** We do not know whether
the controller truncates or rounds to the second, so the interval is the one
correct under either. `Δ = 0` is not clamped: two events in the same second bound
the delta at `(−1 s, +1 s)` and set `causal_order_established: false`, because the
halt cannot be shown to have followed the request at all.

**`ResponseTime` is a distinct type from `Bound`** so a bare interval — a stoppage
duration, say — cannot occupy a record's `response_time` slot without its method,
clock caveat, and claim. The renderer computes its uncertainty wording *from* the
record's bound fields rather than reading a stored string, so no rendering path
can emit a controller-derived time without emitting what constrains it.

**Identity is a content hash, and collisions are counted rather than hidden.**
The source has no `eventId`. Hashing the full event including `ts` survives the
real trap in the data (`nailing.started` legitimately appears twice for one
panel), but two genuinely distinct events sharing every field and the same whole
second are indistinguishable. `IngestReport.content_collisions` counts that case
so a possible silent drop is a number on a report.

**`verify_chain()` reports `records` and `head_hash`** because the chain cannot
detect tail truncation — deleting records off the end leaves a shorter chain that
verifies perfectly. Those two values are what a verifier holding an independently
recorded anchor compares against. The gap does not close; it becomes someone's
explicit responsibility.

**Payload fields are guarded where they are used, not rejected at parse.**
Envelope fields (`cellId`, `event`, `runId`) are type-checked and a bad one makes
the line malformed. Payload fields are open by design, so a structured
`run.paused` reason degrades to `unclassified` rather than discarding an
otherwise-valid safety event. Unknown never becomes `operational`: an
unrecognised pause reason is a question for a human.

### Four decisions that were reversed

Recorded because the reversals are more informative than the conclusions.

| Was | Became | Why |
|---|---|---|
| A halt tied with its episode closer can stay `unambiguous` — the outcome is stable either way | Flag it | The module already flagged outcome-stable ties elsewhere, so the effect was that the same tie was disclosed when a record read *well* and hidden when it read *badly* |
| Two closers sharing a second is a cosmetic wobble | Merge-blocking, fixed | `episode.closed_by` is record content and is printed on the inspector's page; two ingests of identical events gave the same `record_id` with different content and no flag |
| Silent truncation of the cross-run candidate list is a test gap | A behaviour defect, fixed | A slice whose premise is *surface the near-miss without using it* must not withhold part of the near-miss silently |
| The tied-halts gap is "attribution only, no numbers move" | `axes_stopped` moves | In a safety audit, which axes are recorded as having stopped is the payload, not attribution |

## Known gaps that ship

Each was consciously deferred with a recorded ruling; none is load-bearing, and
all were reviewed. Full reasoning in `docs/build-log.md`.

- **Same-second tie assessment is not uniform across all three sites.** The
  matched path compares pairwise rather than scanning its timestamp group, so
  with two halts in one second it can name one of them — and therefore *its*
  `axes_stopped` — and report `unambiguous`, while the companion orphan record in
  the same run does disclose the tie. The measured delta is invariant. The fix is
  a rewrite using "would this record's content differ under an alternative
  ordering of its group?" as one predicate at all three sites; it was declined on
  the final fix round rather than shipped unverified.
- **`episode_rests_on_a_tie` never resets**, so every later demand-less orphan in
  an episode inherits ambiguity when at most one could actually flip. Over-
  disclosure on an adverse record, which is the right side to err on.
- **No plausibility bound on a large delta.** In an episode that never closes, an
  unanswered request can pair with a halt arbitrarily later. It is flagged
  ambiguous but not flagged *implausible*; bounding it needs a constant that is
  the robotics lead's call.
- **No integrity statement on the rendered page.** `verify_chain()`'s verdict,
  `records` and `head_hash` are available from the service but do not appear on
  the artefact handed to an inspector.
- **`query_events` and iteration raise on a structurally damaged store** where
  `verify_chain()` returns a verdict. An inspector calling retrieval first gets a
  traceback rather than a precise `broken_at_seq`.

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

Design: `docs/design.md`. Implementation plan: `docs/implementation-plan.md`.
Full decision record: `docs/build-log.md`.
