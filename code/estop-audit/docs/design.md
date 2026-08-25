# E-stop audit and stop-response measurement — design

**Date:** 2026-08-25
**Slice:** 1 (inspection actions a2 + a3)
**Owner:** Software Engineering Lead
**Status:** Approved for implementation

---

## 1. Purpose

Two site-inspection actions, one service:

- **a2 — "Emergency stop events logged and retrievable."** Persist the controller
  event stream to an append-only, tamper-evident audit store, and expose retrieval
  by cell and time range.
- **a3 — "Stop response time measured and recorded per cell."** Pair each
  `stop.requested` with the `motion.halted` that answers it, compute the delta
  *with its uncertainty*, and emit a record an external inspector will accept.

a2 → a3 → a5 → a7 is 24 working days of pure sequence with no slack
(`docs/stories.md:199-209`). This is the first thing built and everything else waits
on it.

**The governing constraint is honesty, not coverage.** The source data cannot support
a per-axis sub-second measurement. The deliverable is a record that says so precisely,
in a form the inspector can act on — not a number that looks better than the evidence.

## 2. Scope

**In:** ingest, append-only hash-chained store, idempotent receive, stop-sequence
pairing, resolution-aware measurement, audit record, plain-text inspector rendering,
retrieval by cell + time range, pytest suite.

**Out (explicitly):** web layer, database, CLI beyond test needs, live controller
transport, buffer/reconcile (FM-4 — blocked on firmware), Fleet Monitor UI.

**Runtime:** Python 3.11+, standard library only. `pytest` for tests.

## 3. Input

`cell-events.jsonl` — 29 newline-delimited JSON objects, one cell (`CELL-01`), one run
(`RUN-2026-03-11-A`), March 2026 trial. Contains exactly one e-stop sequence.

`cell-events.json` and `cell-events.ndjson` are byte-identical copies of the same file
(verified by MD5). The service ingests one path. No format detection is built for a
distinction that does not exist.

Relevant shape:

| Event | Carries |
|---|---|
| `stop.requested` | `source: "operator_estop"`, `panelId`, `axisInMotion` |
| `motion.halted` | `axesStopped: ["j1".."j6"]` — six axes, **one** timestamp |
| `interlock.engaged` / `.released` | `zone`, `operator` (on release) |
| `run.paused` | `reason: "estop"` **or** `reason: "material_reload"` — overloaded |
| `run.resumed` | `resumeMode`, `panelId` (absent on the routine resume) |

The sample run has no `run.completed`. The stream is truncated mid-run.

Known deficiencies of the source, from `docs/firmware-event-schema-v4.2.md`:
no `eventId`, no `seq`, no `bootId`, whole-second `ts`, no clock authority,
overloaded `run.paused`.

## 4. Architecture

An event-sourced pipeline: **ingest appends; everything else is recomputed from the
log on read.** Nothing derived is persisted, so no derived value can drift from the
evidence that produced it. At ~145 events per run, recomputation cost is irrelevant.

Two orderings are kept deliberately apart — the same split
`docs/firmware-event-schema-v4.2.md:159-161` ("Consequence for the UI": current state vs event log) requires of the Fleet Monitor:

| | Ordering | Meaning |
|---|---|---|
| **Audit store** | arrival order, append-only, never rewritten | *receipt* — what we were told, and when |
| **Analysis** | stable sort on `(ts, arrival_ordinal)`, partitioned by `runId` | *inference* — what happened |

Out-of-order arrival is therefore the normal case, absorbed by the analysis sort, while
the store still shows plainly that an event arrived late.

```
cell-events.jsonl
      │
      ▼
  events.py      parse → normalise → canonical hash (event_key)
      │
      ▼
  store.py       append-only JSONL, hash-chained, idempotent on event_key
      │
      ├──────────────► query(cell_id, start, end)          [a2 retrieval]
      ▼
  sequences.py   partition by (cellId, runId) → stable ts sort → fan-out pairing
                 within stop episodes bounded by run.resumed / run.completed
      │
      ▼
  measurement.py Δ + open-interval bound from per-event ts resolution
      │
      ▼
  records.py     audit record + amendment folding (per-axis seam)
      │
      ├──────────────► stop_records(cell_id, start, end)   [a3 records]
      ▼
  report.py      plain-text inspector rendering
```

`service.py` is a thin facade over the above. Module boundaries are chosen so each file
answers one question and can be tested without the others.

## 5. Module contracts

### 5.1 `estop_audit/events.py`

```python
def canonical_json(obj: dict) -> bytes
    # sorted keys, no whitespace, UTF-8, ensure_ascii=False

def event_key(raw: dict) -> str
    # "sha256:<64 hex>" over canonical_json(raw)

@dataclass(frozen=True)
class Event:
    key: str                      # event_key(raw)
    ts: datetime                  # timezone-aware UTC
    ts_resolution_seconds: float  # derived from the literal: 1.0 if no fraction
    cell_id: str
    run_id: str | None
    type: str                     # the "event" field
    raw: dict                     # untouched original

def parse_event(raw: dict) -> Event          # raises MalformedEventError
def parse_line(line: str) -> Event           # raises MalformedEventError
```

`ts_resolution_seconds` is read from the timestamp *literal*: `...:33Z` → `1.0`,
`...:33.412Z` → `0.001`. This makes the measurement code forward-compatible with
firmware v4.2 millisecond timestamps without today pretending to have them.

**Fields are type-checked, not merely present.** `cellId` and `event` must be strings
and `runId` must be a string or null; anything else raises `MalformedEventError` and is
reported by ingest rather than persisted. This is not defensive programming — a
non-string `cellId` passes straight into `partition_runs`, which uses it as a dict key,
so a single such event hash-chained into the append-only store raises
`TypeError: unhashable type` from **every** subsequent `stop_records()` call, for every
cell, in a file the design forbids repairing. The guarantee in §5.9 — one bad line must
not cost the surrounding safety evidence — depends on this check.

Required fields: `ts`, `cellId`, `event`. `runId` may be absent (null for events
outside a run, per the v4.2 envelope). Anything else is payload.

### 5.2 `estop_audit/store.py` — append-only, hash-chained

Stored line envelope:

```jsonc
{
  "seq": 0,                        // position in the store, monotonic, never reused
  "ingested_at": "2026-08-25T...Z",// arrival time (injected clock; fixed in tests)
  "event_key": "sha256:...",       // idempotency key
  "prev_hash": "sha256:...",       // previous line's record_hash; genesis = 64 zeros
  "record_hash": "sha256:...",     // over prev_hash + canonical(line minus record_hash)
  "event": { ... }                 // the original object, unmodified
}
```

```python
class AppendOnlyAuditStore:
    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now)
    def append(self, raw: dict) -> AppendResult   # idempotent on event_key
    def __iter__(self) -> Iterator[StoredRecord]  # arrival order
    def query(self, *, cell_id: str | None = None,
              start: datetime | None = None,
              end: datetime | None = None) -> list[StoredRecord]
    def verify_chain(self) -> ChainVerification
```

Supporting types, all frozen dataclasses in this module:

```python
class AppendResult:      appended: bool; seq: int | None; event_key: str
class StoredRecord:      seq: int; ingested_at: datetime; event_key: str
                         prev_hash: str; record_hash: str; event: Event
class ChainVerification: ok: bool; broken_at_seq: int | None; reason: str | None
```

- `query` time range is **half-open `[start, end)`**, filtering on event `ts`.
  Stated explicitly because an inspector will ask about boundaries.
- `verify_chain()` re-walks the file recomputing hashes; returns
  `ChainVerification(ok: bool, broken_at_seq: int | None, reason: str | None)`.
  Any edit, deletion, or reordering downstream of a line breaks the chain there.
- The clock is injectable so golden tests produce byte-stable files.

**What the chain proves and does not prove** — stated in the code docstring, in
`ChainVerification`, and in the README. Three separate limits, and conflating them
would overstate the deliverable to an inspector:

1. **Interior alterations are detected.** Edit, delete, or reorder any line that is
   not at the tail, and the walk fails at that line.
2. **Tail truncation is NOT detected.** Dropping records off the end leaves a shorter
   chain that verifies perfectly. This is the likeliest real tampering — removing what
   follows an e-stop. `ChainVerification` therefore carries `records` and `head_hash`
   so a verifier holding an independently recorded anchor can catch it. Without an
   anchor, `ok=True` means *internally consistent*, not *complete*.
3. **The chain is unkeyed, so it is not a signature.** Anyone with write access can
   recompute the whole chain from genesis and produce a verifying forgery. Closing
   this needs a keyed digest and therefore key management, which §1 deliberately
   excludes from slice 1.

And separately from all three: it proves nothing about events that never reached us.
The buffer-overflow hole
(`docs/firmware-event-schema-v4.2.md:138-144` (overflow policy: safety events never dropped)) is outside this boundary.

`verify_chain()` returns a verdict in every case — damaged, empty, or absent file
included — never a traceback. An inspector handed a corrupted file must get an
answer, not a stack trace. `broken_at_seq` is the walk position, never a value read
out of the file, so a tampered record cannot misdirect where the break is reported.

### 5.3 Idempotency without `eventId`

The key is the SHA-256 of the full canonical event, `ts` included.

This survives the trap documented at `docs/firmware-event-schema-v4.2.md:32-36` (point 1, 'No unique event identifier'):
`nailing.started` for `EW-L1-E1` legitimately appears twice (07:14:51 and 07:20:05,
either side of the e-stop resume). The two differ in `ts`, hash differently, and both
persist. Deduping on `(runId, panelId, event)` would have dropped one.

Re-ingesting the same file is a no-op.

**The residual hole, made observable rather than silent.** Two *genuinely distinct*
events identical in every field including their whole-second `ts` are indistinguishable
and the second would be dropped. `IngestReport` therefore separates:

- `duplicates_skipped` — key already in the store from an **earlier** ingest call.
  Expected; this is re-ingest working.
- `content_collisions` — key repeated **within a single** ingest call. Suspicious:
  either a retransmit inside one batch, or a distinct event we cannot see.

A collapse becomes a number on a report instead of an absence nobody notices.
`# TODO(firmware-v4.2): replace synthetic key with eventId` sits on that line, citing
`docs/firmware-event-schema-v4.2.md` §"Required envelope".

### 5.4 `estop_audit/sequences.py`

```python
@dataclass(frozen=True)
class RunView:
    scope: tuple[str, str | None]   # (cell_id, run_id) -- the partition key
    cell_id: str
    run_id: str | None              # None for events emitted outside a run
    events: tuple[Event, ...]       # stable-sorted (ts, arrival_ordinal)
    completed: bool                 # a run.completed event was seen
    truncated: bool                 # not completed

def partition_runs(events: Iterable[Event]) -> list[RunView]
def pair_stops(run: RunView) -> list[StopSequence]
def classify_pause(event: Event) -> str          # see 5.7

@dataclass(frozen=True)
class StopSequence:
    request: Event | None        # None only for an orphan halt
    halt: Event | None           # None for an unmatched request
    outcome: str                 # matched | no_halt_recorded | orphan_halt
    evidence_status: str         # complete | truncated  (see "Two axes" below)
    co_satisfied_with: tuple[str, ...]   # event_keys of other requests the same
                                         # halt answered; empty when sole
    episode_closed_by: str | None        # event_key of the run.resumed / run.completed
                                         # that closed the episode, if any
    ordering_confidence: str
    notes: tuple[str, ...]       # human-readable reasons behind any flag
```

`classify_pause` is exposed on the module (not buried inside record assembly) so the
safety-vs-routine mapping can be tested directly against a `run.paused` event that
belongs to no stop sequence -- which is exactly the case the sample's
`material_reload` pause presents.

**Partition key is `(cell_id, run_id)`, not `run_id` alone.** `runId` may legitimately
be null (`docs/firmware-event-schema-v4.2.md:70` -- "null for events outside a run").
Partitioning on `run_id` alone would collect every out-of-run event across all cells and
all time into one bucket, which reintroduces unbounded lookahead through the back door.
Records built from a null-run partition carry `run_scope: "outside_run"`.

#### Pairing: fan-out within a stop episode

Two rules, and the second is what makes the first safe.

**1. A halt satisfies every request open at the moment it arrives.** It is not
*consumed* by one of them. Each open request produces its own record, with its own delta
measured from its own timestamp, and each record names the others via
`co_satisfied_with`.

**2. A stop episode is closed by `run.resumed`, by `run.completed`, or by the end of the
ingested stream -- whichever comes first.** A request still open when its episode closes
is `no_halt_recorded` and can **never** be paired afterwards. A halt in a later episode
starts from an empty request queue.

**Why fan-out rather than FIFO or LIFO** -- this reasoning belongs in the code as a
module docstring on `pair_stops`, not only here:

> "Which request did this halt answer?" is a question with no single correct answer when
> more than one stop demand was outstanding. Physically the halt answered all of them.
> FIFO picks the earliest and reports the others as unmatched -- fabricating a safety
> finding against stops that worked. LIFO picks the latest, which reports the shortest
> delta and is the flattering bias to build into a safety record. Refusing to pair at all
> yields zero measurements on a cell with redundant triggers (light curtain *and* operator
> button), failing a3 rather than satisfying it. Fan-out asserts only what is observable:
> N demands, one halt, N deltas -- the earliest demand yielding the largest and therefore
> most conservative number.

**Why an episode boundary rather than a time window.** Without a boundary, FIFO pairing
inverts the finding it exists to produce. Given a run where a stop fails and a later,
unrelated stop succeeds:

| Time | Event |
|---|---|
| 07:15:33 | `stop.requested` R1 |
| -- | *(no halt -- **this is the finding**)* |
| 07:17:33 | `run.resumed` — closes R1's episode |
| 09:00:00 | `stop.requested` R2 |
| 09:00:01 | `motion.halted` H |

The `run.resumed` row is load-bearing and must survive any retelling of this
example. Without a closing event between R1 and R2, both requests sit in one
episode, fan-out attaches R1 to H, and the failed stop is reported as matched with
a 1h44m response time — the very outcome the boundary exists to prevent. The
boundary helps only where a closer actually intervenes.

unbounded FIFO pairs R1 -> H and reports the **failed** stop as matched with a 1h44m
response time, while reporting the **successful** stop as `no_halt_recorded`. Both
records are wrong, in the worst available direction.

A fixed time window fixes this but requires a constant we would be inventing; the first
question at the inspection is "why 30 seconds?" and there is no good answer. The episode
boundary is derived from an event the controller already emits (`run.resumed` at 07:19:55
in the sample), needs no constant, is stable when FM-5 reads 24h of events off the same
store, and is explainable in one sentence: *the cell started running again, so that stop
was over.*

**Open question raised by this choice**, to go to Chris alongside the pause-taxonomy ask
already logged at `docs/firmware-event-schema-v4.2.md:176`: **is `run.resumed` guaranteed
to follow every `run.paused`?** If yes, the boundary is airtight. If no, we add a
deliberately generous time-window backstop, recorded in each record as
`pairing_window_seconds` so the policy is visible rather than hidden in code. Both
answers are workable; the unanswered version is not.

#### Two axes: what we saw, and how much it proves

`outcome` records the observation. `evidence_status` records how much can be concluded
from it. They are separate fields because they extend independently -- when firmware
v4.2 lands `seq` and ingest gaps become detectable, `evidence_status` grows a
`gap_detected` value without touching `outcome`, and consumers switching on `outcome` do
not break.

| `outcome` | Condition |
|---|---|
| `matched` | request satisfied by a halt in the same episode |
| `no_halt_recorded` | request open when its episode closed |
| `orphan_halt` | halt arriving with no open request in that episode |

`evidence_status` answers one question: **could more data change this outcome?**

| `evidence_status` | Condition | Inspector meaning |
|---|---|---|
| `complete` | every event the outcome depends on was observed | the record is as good as the source allows |
| `truncated` | the outcome is `no_halt_recorded` **and** the episode closed only because the ingested stream ended | absence of evidence, **not** evidence of absence |

Concretely: `matched` and `orphan_halt` are always `complete` -- the halt was observed,
and no later data can unsay it. `no_halt_recorded` is `complete` when the episode closed
on an observed `run.resumed` or `run.completed` (the episode demonstrably ended without a
halt) and `truncated` only when the data simply ran out.

**`evidence_status` is scoped to the episode, not the run.** These come apart, and the
sample is the proof: `RUN-2026-03-11-A` has no `run.completed` and is truncated, yet its
stop episode closed cleanly on an observed `run.resumed` at 07:19:55. That record is
`evidence_status: "complete"` on a `run_truncated: true` run, and both statements are
true. Collapsing the two would weaken a fully-evidenced record for no reason.

The pair `no_halt_recorded` + `truncated` is the load-bearing one: it means the request
was still open when the data ran out. Treating that as a safety finding would manufacture
a defect out of a file that merely stops.

**Guard against the single-field consumer.** A consumer reading only `outcome` sees a
truncated stream as a hard finding. `report.py` (5.8) therefore renders
`no_halt_recorded` + `evidence_status != "complete"` as *"not evidenced -- stream
incomplete"*, never as *"the cell did not stop"*. The inspector-facing surface cannot
make this mistake even if a future programmatic consumer does.

#### Cross-`(cell_id, run_id)` requests

A `stop.requested` in `RUN-A` is never satisfied by a halt in `RUN-B`, and never by a
halt on another cell. The record notes any cross-scope halt candidate under
`context.cross_run_halt_candidates`, each flagged `"not_counted_as_evidence": true`.

Pairing across scopes with a caveat was considered and rejected: it invents evidence, and
it would let a `runId` bug in firmware silently manufacture response times. Surfacing the
near-miss without using it hands the inspector the thread to pull without us pulling it
for them.

#### Simultaneity: same-second events are grouped, never ordered

Events sharing a timestamp are **unorderable** at whole-second resolution, so arrival
order must never decide an outcome. Pairing therefore walks *timestamp groups*, not
individual events: within a group every `stop.requested` is admitted before any
`motion.halted` in that group is considered, and an episode closes at the end of the
group containing its closer rather than at the closer itself.

Without this, swapping two adjacent lines of an input file flips a `matched` record
into an `orphan_halt` plus a `no_halt_recorded` — a fabricated "the cell did not stop"
finding that reports `ordering_confidence: "unambiguous"`, asserting more confidence
than the correct answer. A *fast* cell makes this more likely, not less: a sub-second
stop response puts request and halt in the same whole second. Every downstream
mitigation misses it — `causal_order_established` applies only to pairs that were
matched, and the renderer's softening fires only on `evidence_status != "complete"`.

#### Confidence flags

- `ordering_confidence: "ambiguous"` when a pairing rests on a same-second tie —
  request and halt sharing a second, a halt sharing a second with the event that closed
  its episode, or **two episode closers sharing a second with each other**. `notes`
  names the tied events by `event_key`.

  The last case is easy to mistake for cosmetic and is not. `episode.closed_by` is
  record content and is printed on the inspector's page, so two ingests of the same
  events in different arrival order would otherwise produce the same `record_id` with
  different content and no flag — undetectable as a difference, which is worse than a
  visible disagreement.
- `co_satisfied_with` non-empty is itself the disclosure that more than one demand was
  outstanding. No separate "ambiguous pairing" flag is needed under fan-out, because
  fan-out does not make an arbitrary choice to disclose -- it reports all of them.

### 5.5 `estop_audit/measurement.py`

```python
@dataclass(frozen=True)
class Bound:
    nominal_seconds: float
    lower_seconds_exclusive: float
    upper_seconds_exclusive: float
    source_resolution_seconds: float

def interval_bound(earlier: Event, later: Event) -> Bound
def response_time(request: Event, halt: Event) -> ResponseTime
```

`ResponseTime` is a `Bound` plus the four honesty fields that make it quotable:
`method`, `clock_authority`, `causal_order_established`, and `defensible_claim`.
It is a distinct type from `Bound` precisely so that a bare interval -- a stoppage
duration, say -- can never be serialised into the `response_time` slot of a record.

Let `Δ = later.ts − earlier.ts` in seconds, `r_e` and `r_l` the two events'
`ts_resolution_seconds`.

- Under **truncation**, true value ∈ `(Δ − r_e, Δ + r_l)`.
- Under **rounding**, true value ∈ `(Δ − h, Δ + h)` where `h = (r_e + r_l) / 2`.

We do not know which convention the controller uses, so we take the **union** — the
conservative bound that is correct under either:

```
lower = Δ − max(r_e, h)
upper = Δ + max(r_l, h)
```

When both resolutions are equal (every case in today's data, `r = 1 s`) the two
conventions coincide and this reduces to `(Δ − r, Δ + r)`.

**For the sample:** `Δ = 1 s`, `r = 1 s` → `(0 s, 2 s)` → defensible claim
**"stop response < 2 s"**, which is exactly what `docs/stories.md:216-218` says is the
most that can honestly be reported.

**`Δ = 0` is handled, not special-cased away.** Two events in the same second bound the
delta at `(−1 s, +1 s)`: we could not establish that the halt even *followed* the
request. The record then carries `causal_order_established: false`. This is a real
possibility on this data and must not silently render as "0 s response time".

`interval_bound` is reused for the stoppage duration (`run.paused` → `run.resumed`), so
the downtime figure carries the same honesty as the response time.

Every `ResponseTime` carries:

```jsonc
{
  "nominal_seconds": 1,
  "lower_bound_seconds_exclusive": 0,
  "upper_bound_seconds_exclusive": 2,
  "source_resolution_seconds": 1,
  "method": "derived_from_whole_second_controller_wall_clock",
  "clock_authority": "cell_wall_clock_unverified",
  "causal_order_established": true,
  "defensible_claim": "stop response < 2 s"
}
```

`clock_authority` is not decoration. Per `docs/firmware-event-schema-v4.2.md:47-50` (point 4, 'No clock authority'),
`ts` is presumed cell wall-clock with no monotonic reference; an NTP step or controller
reboot can move it backwards, and today that is undetectable. All interval arithmetic
here inherits that caveat and says so.

### 5.6 `estop_audit/records.py` — the audit record

```python
def build_record(seq: StopSequence, run: RunView, all_runs: list[RunView]) -> dict
def fold_amendments(record: dict, amendments: list[dict]) -> dict
def attach_per_axis_measurement(store, *, record_id: str,
                                measurements: list[dict],
                                source: str, attested_by: str,
                                measured_at: datetime) -> dict
```

Record shape:

```jsonc
{
  "record_version": "1.0",
  "record_type": "stop_sequence",
  "record_id": "CELL-01:RUN-2026-03-11-A:req:<request_key first 12 hex>",
  "cell_id": "CELL-01",
  "run_id": "RUN-2026-03-11-A",
  "anchor_ts": "2026-03-11T07:15:33Z",     // request ts; halt ts for an orphan
  "run_scope": "in_run",                   // in_run | outside_run

  "outcome": "matched",                    // matched | no_halt_recorded | orphan_halt
  "evidence_status": "complete",           // complete | truncated -- scoped to the
                                           // EPISODE, not the run
  "run_truncated": true,                   // convenience mirror of the run's state

  "episode": {
    "closed_by_event_key": "sha256:...",   // the run.resumed / run.completed, or null
    "closed_by": "run.resumed",            // run.resumed | run.completed | stream_end
    "co_satisfied_with": []                // event_keys of other requests the same
                                           // halt answered; empty when this was the
                                           // sole outstanding demand
  },

  "stop_request": {
    "ts": "2026-03-11T07:15:33Z", "source": "operator_estop",
    "panel_id": "EW-L1-E1", "axis_in_motion": true, "event_key": "sha256:..."
  },
  "motion_halt": {
    "ts": "2026-03-11T07:15:34Z",
    "axes_reported_stopped": ["j1","j2","j3","j4","j5","j6"],
    "event_key": "sha256:..."
  },

  "response_time": { ...as §5.5... },

  "per_axis": {
    "status": "unavailable_from_source",
    "reason": "motion.halted reports six axes under one timestamp; no per-axis delta is derivable",
    "axes_reported_stopped": ["j1","j2","j3","j4","j5","j6"],
    "measurements": [],
    "expected_source": "external rig instrumentation, or firmware v4.2 axis.halted events"
  },

  "context": {
    "interlock_engaged": [{"ts": "...", "zone": "assembly_table"}],
    "interlock_released": [{"ts": "...", "zone": "assembly_table", "operator": "op-114"}],
    "pause":  {"ts": "...", "reason": "estop", "classification": "safety"},
    "resume": {"ts": "...", "resume_mode": "from_panel_start", "panel_id": "EW-L1-E1"},
    "stoppage_duration": { ...Bound... },
    "cross_run_halt_candidates": [],
    "cross_run_halt_candidates_total": 0    // pre-truncation count; the list is
                                            // capped, and the page says so when the
                                            // total exceeds what is shown
  },

  "confidence": {
    "ordering": "unambiguous",
    "notes": []
  },

  "amendments": []
}
```

**Context window.** For a matched or unmatched request, context is gathered from the
request `ts` forward to the corresponding `run.resumed` (or end of run), within the same
`runId`: `interlock.engaged`, `interlock.released`, the `run.paused` and `run.resumed`
that bracket the stop.

**Per-axis seam.** `attach_per_axis_measurement` **appends an amendment event to the
store**; it never mutates the original record. The append-only property stays literally
true, and the inspector can see when the rig data arrived, from whom, and that it is
`source: "rig"` rather than `source: "controller"`. `build_record` folds amendments in
at read time. Records are addressed by `record_id`, which is derived from an event
content hash and is therefore stable across re-ingests.

**`record_id` for a record with no request.** An `orphan_halt` has no `stop.requested`
to derive from, so it is addressed on the halt instead:
`"<cell_id>:<run_id>:halt:<halt_key first 12 hex>"`. The `req:` / `halt:` segment keeps
the two namespaces from ever colliding, and makes the anchor visible in the identifier
itself. `run_id` is rendered `"-"` when null.

### 5.7 `run.paused` disambiguation

| `reason` | `classification` |
|---|---|
| `estop` | `safety` |
| `material_reload` | `operational` |
| anything else / absent | `unclassified` |

**Unknown never defaults to `operational`.** An unrecognised pause reason is a question
for a human; quietly filing it as routine is precisely the failure a2 exists to prevent,
and it is the open question already logged for Chris
(`docs/firmware-event-schema-v4.2.md:176`).

The mapping is a single module-level table so that adding a firmware reason is a
one-line change with an obvious test.

### 5.8 `estop_audit/report.py`

```python
def render_text(record: dict) -> str
```

Plain-text, paper-shaped, one stop sequence per page-equivalent.

**The uncertainty language is computed from the record's bound fields inside the
renderer**, not read from a pre-baked string. No rendering path can produce a response
time without also producing its limits. This is the reason a renderer exists at all.

Every rendered page states, in words: the measured nominal, the bound, the source
resolution, the clock caveat, and that per-axis figures are unavailable from this source.

**The `evidence_status` guard lives here.** `outcome: "no_halt_recorded"` with
`evidence_status != "complete"` renders as *"not evidenced -- stream incomplete"*, never
as *"the cell did not stop"*. A programmatic consumer reading `outcome` alone can make
that mistake; the inspector-facing surface must not. Where a record has a non-empty
`episode.co_satisfied_with`, the rendering says so in words -- *"this halt also answered
N other stop demands"* -- so a fanned-out record is never mistaken for N independent
halts.

### 5.9 `estop_audit/service.py`

```python
class EstopAuditService:
    def __init__(self, store: AppendOnlyAuditStore)
    def ingest_file(self, path: Path) -> IngestReport
    def ingest_lines(self, lines: Iterable[str]) -> IngestReport
    def query_events(self, *, cell_id=None, start=None, end=None) -> list[StoredRecord]
    def stop_records(self, *, cell_id=None, start=None, end=None) -> list[dict]
    def render(self, record: dict) -> str
```

`IngestReport`: `lines_read`, `events_appended`, `duplicates_skipped`,
`content_collisions`, `malformed` (list of `(line_number, reason)`).

Malformed lines are **skipped and reported**, never fatal — one bad line must not cost
the surrounding safety evidence. Blank lines are ignored silently.

`stop_records` filters on `anchor_ts` so a stop sequence is wholly in range or wholly
out — never split across a boundary.

## 6. File layout

```
estop_audit/
  __init__.py
  events.py
  store.py
  sequences.py
  measurement.py
  records.py
  report.py
  service.py
tests/
  test_events.py
  test_store.py
  test_sequences.py
  test_measurement.py
  test_records.py
  test_report.py
  test_service.py
  test_golden_sample.py
  conftest.py
README.md
```

## 7. Testing

pytest, stdlib only. Edge-case fixtures are **hand-built**, not carved out of the
sample, so each case is readable in isolation and does not depend on the trial file
staying as it is. `conftest.py` provides a builder for synthetic event streams and a
fixed clock.

Required cases, all from the brief:

| Case | Asserts |
|---|---|
| `stop.requested` with no following `motion.halted`, run completed | `no_halt_recorded` + `evidence_status: "complete"` |
| same, run truncated | `no_halt_recorded` + `evidence_status: "truncated"`; renders as "not evidenced", **not** as a safety finding |
| two stops in one run, sequential | two `matched` records, correct deltas, `co_satisfied_with` empty on both |
| `motion.halted` with no preceding request | `orphan_halt`, anchored on halt ts |
| events arriving out of order | analysis result identical to in-order; store order differs |
| truncated stream (no `run.completed`) | `run_truncated: true` on every record in the run -- but an episode that closed on an observed `run.resumed` still reports `evidence_status: "complete"`. Run truncation and episode truncation are **not** the same thing. |
| request whose halt is in a different `runId` | request `no_halt_recorded`; halt is `orphan_halt`; cross-scope candidate listed and flagged `not_counted_as_evidence` |

Cases arising from the fan-out and episode-boundary rules (5.4):

| Case | Asserts |
|---|---|
| **The inversion guard** -- R1 unanswered, episode closes, later R2 + halt | R1 `no_halt_recorded`; R2 `matched` at its true 1 s delta. **A pre-boundary FIFO implementation fails this test**, which is why it exists. |
| Two requests open when one halt arrives (fan-out) | two `matched` records referencing the same halt; deltas measured from each request; `co_satisfied_with` names the other on both |
| Request open at `run.resumed` | `no_halt_recorded`, `episode.closed_by: "run.resumed"`, and a halt after the resume does **not** retro-pair |
| Halt arriving in a fresh episode | pairs only with requests raised after the boundary; request queue starts empty |
| Request open at end of stream | `episode.closed_by: "stream_end"`, `evidence_status: "truncated"` |
| Null `runId` events | partitioned per `(cell_id, None)`, `run_scope: "outside_run"`; two cells' out-of-run events never share a partition |

Plus:

- **Idempotency:** ingest the sample twice → 29 events, second report shows
  `duplicates_skipped: 29`, `events_appended: 0`; file byte-identical.
- **Content collision visibility:** a batch containing a repeated identical event
  reports `content_collisions: 1`.
- **Tamper detection:** mutate a byte in the middle of the store file →
  `verify_chain().ok is False` and `broken_at_seq` names the right line.
- **Measurement:** `Δ=1, r=1` → `(0, 2)`; `Δ=0` → `(−1, 1)` with
  `causal_order_established: False`; mixed resolutions take the conservative union.
- **`run.paused` classification:** `estop` → safety, `material_reload` → operational,
  unknown → `unclassified`.
- **Renderer:** no rendered output contains a response time without its bound; a
  `no_halt_recorded` + `truncated` record renders as "not evidenced -- stream
  incomplete", never as "the cell did not stop"; a record with non-empty
  `co_satisfied_with` says so in words.
- **Golden test over `cell-events.jsonl`:** exactly one `matched` stop sequence,
  `CELL-01` / `RUN-2026-03-11-A`, nominal 1 s, bound `(0, 2)`, per-axis
  `unavailable_from_source` with six axes listed, `run_truncated: true` **but**
  `evidence_status: "complete"` (the episode closed on the observed `run.resumed` at
  07:19:55), `episode.closed_by: "run.resumed"`, `co_satisfied_with` empty, and the routine
  `material_reload` pause classified `operational` and **excluded** from stop records.

## 8. README requirements

The README must state, plainly and without hedging:

**What the service can prove today**
- That every event we received was persisted, in the order received, and has not been
  altered since (hash chain).
- That a `stop.requested` at 07:15:33 was followed by a `motion.halted` at 07:15:34 on
  `CELL-01` / `RUN-2026-03-11-A`, and the stop response was **under 2 seconds**.
- That the stop was a safety event, distinguished from the routine `material_reload`
  pause later in the same run.
- That re-ingesting the same stream does not duplicate records.

**What it cannot prove today**
- Any response time tighter than a 2-second bound. The source is whole-second.
- Any **per-axis** figure. Six axes share one `motion.halted` timestamp.
- That the stream was **complete**. With no `seq`, a gap is unobservable — a quiet cell
  and a 30-minute outage look identical (`docs/firmware-event-schema-v4.2.md:38-40` (point 2, 'No sequence number')).
- That timestamps were not moved by a clock step. There is no monotonic reference.
- That two distinct events sharing every field and the same whole second were both
  retained. The report counts the suspicion; it cannot resolve it.

**What changes when firmware v4.2 lands**

| v4.2 field | Unlocks | Code seam |
|---|---|---|
| `eventId` | true idempotency; the content-hash key retires | `events.event_key` |
| `seq` + `bootId` | gap detection; completeness becomes provable | new; out of slice 1 |
| ms `ts` | bound narrows automatically — `ts_resolution_seconds` already reads the literal | none |
| `monotonicUs` | interval arithmetic immune to clock steps; `clock_authority` upgrades | `measurement` |
| `axis.halted` per axis | per-axis deltas become **derived** rather than attached | `records.per_axis` |
| `class` | safety/operational classification comes from the source | `sequences` pause table |

The README must also record the **open question this design raises**: is `run.resumed`
guaranteed to follow every `run.paused`? The stop-episode boundary (5.4) rests on it. If
the answer is no, a generous time-window backstop is added and recorded per record as
`pairing_window_seconds`. This goes to Chris in week 1 alongside the pause-taxonomy ask
already logged at `docs/firmware-event-schema-v4.2.md:176`.

The README must also record the standing position from `docs/stories.md:222-229`: if
v4.2 cannot emit per-axis halts, a3's measurement stays on Chris's rig permanently, and
this service's job is the record format and the audit log — the rig supplies the
numbers. Both answers are acceptable; an unanswered question is not.

## 9. Known limitations, carried in code

Each of these gets a docstring at the point where it bites, citing this spec:

1. Content-hash idempotency can collapse two distinct same-second events.
   Counted as `content_collisions`, not silently dropped.
2. Stream completeness is unprovable without `seq`.
3. Wall-clock timestamps have no authority; intervals inherit that.
4. Whole-second resolution caps every measurement at a ±1 s bound.
5. Per-axis deltas are not derivable from `motion.halted`.
6. The hash chain detects interior alterations only. Tail truncation still verifies,
   and an unkeyed chain is not a signature — see 5.2. It also says nothing about
   events that never arrived.
10. One live store instance per path. A second concurrent writer is refused rather
    than allowed to fork the chain, but the guard is a size check, not a lock: it
    catches the realistic in-process mistake, not a determined race.
7. Fan-out pairing asserts that a halt answered every outstanding demand. That is the
   observable claim, but it is not proof that each demand individually would have been
   honoured. `co_satisfied_with` discloses it on every affected record.
8. The stop-episode boundary depends on `run.resumed` being emitted. If firmware can
   pause without ever resuming, an episode closes only at stream end -- and an
   unanswered request then fans out onto whatever halt eventually arrives, producing a
   `matched` record with an arbitrarily large delta. The same is true of a request
   carried across an episode boundary because it shared a second with the closer: it
   can be answered by a halt arbitrarily far into the next episode. Both records carry
   `ordering_confidence: "ambiguous"` and a note, but nothing flags an implausible
   response time as implausible -- `co_satisfied_with` discloses that another demand
   was outstanding, not that the number is absurd. Bounding it needs a plausibility
   constant, which is Chris's call rather than ours. Open with Chris; see 8.
9. `evidence_status` covers stream truncation only. Ingest **gaps** are undetectable
   without `seq`, so a record can read `complete` over a stream that silently lost
   events. This is limitation 2 seen from the record's side, and the reason
   `evidence_status` is an extensible field rather than a boolean.
