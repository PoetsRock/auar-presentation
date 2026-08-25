# Claude Code prompts — build slices

Two independent sessions. Run them separately; they share no code.

Before either: `cd /Users/poetsrock/code/auar && git init` if you haven't.

---

## Slice 1 — E-stop audit and stop-response measurement (Python)

> **Context.** You are building inspection actions a2 and a3 for a timber-frame
> robotics company. An external safety inspector must accept the output. a2 is
> "emergency stop events logged and retrievable"; a3 is "stop response time
> measured and recorded per cell." This is on the critical path to an
> unsupervised customer demo — it is the first thing being built and everything
> else waits on it.
>
> **Input.** `cell-events.jsonl` in the repo root: newline-delimited JSON from a
> March trial run. 29 events, one cell, one run, containing exactly one e-stop
> sequence. Read it before writing anything and let the real shape drive the
> design.
>
> **Build.** A Python service (3.11+, stdlib plus pytest; no frameworks) that:
> 1. Ingests the stream and persists events to an append-only audit store.
> 2. Identifies stop sequences: pairs each `stop.requested` with the
>    `motion.halted` that follows it, within the same `runId`.
> 3. Records the delta, the axes reported stopped, the stop source, and the
>    surrounding context (`interlock.engaged`, `run.paused`, `run.resumed`).
> 4. Emits an audit record an inspector would accept, and a retrieval interface
>    to query stop events by cell and time range.
>
> **Constraints that matter more than features.**
> - Timestamps are **whole-second resolution**. The one delta in the sample is
>   exactly 1s. Do not report false precision — surface the measurement's
>   resolution limit in the record itself. This is the honest answer and it is
>   the point of the exercise.
> - `motion.halted` carries `axesStopped: ["j1".."j6"]` — six axes, one event,
>   one timestamp. **Per-axis deltas are not derivable.** Record what is
>   knowable, mark per-axis as unavailable from this source, and structure the
>   record so rig-supplied per-axis numbers can be attached later.
> - `run.paused` is overloaded: `reason: "estop"` and `reason: "material_reload"`
>   share an event type. The audit log must distinguish safety from routine.
> - Ingestion must be **idempotent**. Re-ingesting the same file must not
>   duplicate records. Note in code where a real `eventId` would go — see
>   `firmware-event-schema-v4.2.md`.
>
> **Edge cases to handle explicitly, with tests:**
> a `stop.requested` with no following `motion.halted`; two stops in one run;
> a `motion.halted` with no preceding request; events arriving out of order;
> a truncated stream (the sample ends mid-run, with no `run.completed`);
> a `stop.requested` whose `motion.halted` belongs to a different `runId`.
>
> **Deliver.** Working code, pytest suite covering the above, and a short README
> stating what the service can and cannot prove today and what changes when
> firmware v4.2 lands. Keep scope tight — no web layer, no database, no CLI
> beyond what the tests need. Correctness and honesty about limits over surface
> area.

---

## Slice 2 — Panel revision impact and cost classification (TypeScript)

> **Context.** When a building design changes mid-build, the production manager
> must work out which prefabricated panels are affected and what to do about
> each. Today she rebuilds the schedule by hand and, in doubt, re-makes more than
> needed — about 12% of panels on a changed build, ~£180 each. This tool tells
> her what genuinely needs re-making and what it costs, **before** she approves.
>
> **Input.** `build-r3.json` and `build-r4.json` in the repo root: two revisions
> of the same 20-panel build. Read both before designing anything.
>
> **Build.** A TypeScript library (Node 20+, vitest; no framework, no UI) that
> exposes a pure function over two whole builds:
> ```ts
> classifyRevision(previous: BuildModel, next: BuildModel): RevisionImpact
> ```
>
> **Design constraints — these are decisions already taken, not suggestions:**
> - **Pure function over two complete builds.** Do not store previous state
>   inside panels, and do not mutate any schema. The input is two documents. This
>   deliberately demonstrates that a `previousSpec` field is unnecessary — the
>   design must work without one, and must handle diffing revisions that are more
>   than one step apart.
> - **Classification is a function of `(changed, status)` only. Never adjacency.**
>   Classes: `no_action`, `requeue`, `remake`, `recall`, `escalate`.
>   Costs: `requeue` £0, `remake` £180, `recall` £180 + logistics (unknown — model
>   it as an explicit unknown, do not invent a number), `escalate` no auto cost.
> - **No panel with status `installed` may be auto-re-issued.** It routes to
>   `escalate` and blocks approval. This is the safety criterion; make it
>   structurally impossible to bypass, not merely a flag someone can ignore.
> - **Flag suspect data, but do not adjust cost for it.** A panel whose geometry
>   changed but whose derived fields did not has been hand-edited. Raise an
>   independent `suspect_data` flag; it is a data-quality signal, not a cost
>   adjustment. Exclude a panel from the cost total **only when the suspect field
>   feeds its own cost calculation** — `remake` is flat £180 and never reads
>   `weightKg`, so a suspect panel still contributes. `recall`, where logistics
>   may scale with weight, is where exclusion applies. IW-L1-01 therefore classes
>   `remake`, contributes £180, and carries the flag. Total stays £720.
> - **Deterministic, serialisable output**, attachable to a change record.
>
> **Also implement, separately and clearly marked as `Should`:** a geometric
> consistency check that flags an *unchanged* panel no longer consistent with a
> changed one — specifically walls on level 2 that no longer stack on the level-1
> wall beneath them. Keep it independent of classification so it can be removed
> without touching the core.
>
> **Verify against the fixtures.** Seven of twenty panels changed, all on level 1.
> Four are `manufactured` (£720 of re-makes), two are `planned` (£0 — re-queue
> only), one is `installed` and must escalate. One changed panel has a stale
> `weightKg`. One unchanged level-2 wall no longer stacks. Write these as tests.
> **Do not hardcode the expected panel IDs into the logic** — the tests assert
> them; the logic must derive them.
>
> **Edge cases with tests:** panels added in the new revision; panels removed;
> revisions more than one step apart; identical revisions; empty builds; a panel
> whose only change is `status`; floating-point-free integer geometry.
>
> **Deliver.** Library, vitest suite, and a README stating why classification
> excludes adjacency and what the cost model assumes. No UI, no persistence.
