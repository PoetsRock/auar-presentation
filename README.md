# AUAR — Software Engineering Lead task

Delivery plan, two build slices, and the reasoning behind both.

---

## Position

**Both features demo on 12 October. What is at risk is *unsupervised*** — and it
is gated by two chains that nobody in the hand-over traced end to end, both of
which converge on the cell re-test.

The CTO wrote of the site inspection actions: *"I don't think there's much in
there."* There is. It is 24 working days of pure sequence with a 10-working-day
external lead time on the end, and it decides whether the demo can run
unattended. Separately, Chris's email puts firmware on the cell at end of week 5
while his own attached plan puts it at end of week 7.

Two people, two chains, both believed shorter than they are.

---

## If you have ten minutes

1. **[`deliverables/00-cto-response.md`](deliverables/00-cto-response.md)** — the EOD reply the
   CTO actually asked for. One page. *(3 min)*
2. **[`deliverables/04-critical-path-diagram.md`](deliverables/04-critical-path-diagram.md)** —
   the whole schedule argument in one picture. *(2 min)*
3. **[`deliverables/03-demo-date-branch.md`](deliverables/03-demo-date-branch.md)** — the single
   decision the plan hinges on, and what each answer costs. *(5 min)*

That is the plan. Everything else is the working that produced it.

## If you have an hour

| # | Document | What it is | ~ |
|---|---|---|---|
| — | [`deliverables/00-cto-response.md`](deliverables/00-cto-response.md) | The reply, and what it deliberately omits | 3 min |
| 01 | [`deliverables/01-delivery-plan.md`](deliverables/01-delivery-plan.md) | Critical path, capacity, cuts, week-by-week, assumptions, risks | 10 min |
| 02 | [`deliverables/02-scope-decisions.md`](deliverables/02-scope-decisions.md) | Twelve decisions, each with what would reverse it | 8 min |
| 03 | [`deliverables/03-demo-date-branch.md`](deliverables/03-demo-date-branch.md) | Plan A / Plan B and the week-one questions | 6 min |
| 04 | [`deliverables/04-critical-path-diagram.md`](deliverables/04-critical-path-diagram.md) | Schedule diagram, and what it does not show | 2 min |
| 05 | [`deliverables/05-estimation-calibration.md`](deliverables/05-estimation-calibration.md) | Per-discipline multipliers, bimodal vs wide uncertainty, definition of ready | 5 min |
| 06 | [`deliverables/06-b-pass-robotics.md`](deliverables/06-b-pass-robotics.md) | Resource contention pass. Found five things and changed the recommendation | 5 min |
| — | [`deliverables/stories.md`](deliverables/stories.md) | Revised story set, with the fixture evidence for each change | 8 min |
| — | [`deliverables/firmware-event-schema-v4.2.md`](deliverables/firmware-event-schema-v4.2.md) | The artefact missing from the hand-over | 6 min |

**On the volume.** The brief says small and well-reasoned beats large and
half-finished, and this is more documents than that implies. The reason is that
"we ask why more than what" pushed the reasoning into writing rather than into
code. The ten-minute path above is the deliverable; the rest is the working, and
it is separated so it can be ignored.

---

## The build slices

The brief asks for one. There are two, because the second settles an
architectural disagreement in code rather than in a meeting.

### Slice 1 — E-stop audit and stop-response measurement (Python)

Inspection actions **a2 and a3**. Consumes `cell-events.jsonl`, pairs each
`stop.requested` with the `motion.halted` that follows it, and writes an audit
record an inspector would accept.

**Why this one.** a2 is the first link in the chain that gates the unsupervised
demo, and **a3 had no owner** — the hand-over's owner column reads *"Not
agreed."* It sits across the software/robotics boundary, which is where a lead
should be. Taking it converts an open question into work in progress on day one,
which is what the CTO reply claims.

**What it demonstrates deliberately.** The measurement is capped at 1-second
resolution and per-axis deltas are *not derivable* — `motion.halted` carries six
axes in one event with one timestamp. The service records what is knowable,
marks the rest unavailable, and is structured so rig-supplied numbers can attach
later. Reporting false precision to a safety inspector is the failure mode here.

### Slice 2 — Panel revision impact and cost classification (TypeScript)

Stories **PR-1 and PR-6**. `classifyRevision(previous, next)` over
`build-r3.json` and `build-r4.json`.

**Why this one.** The business case for Panel Revisions is a money number, and
no story in the hand-over surfaced money — the only one that did was marked
*Should*. Seven panels change between r3 and r4: four need re-making (£720), two
just need re-queueing (£0), and one is **already installed in a building**. A
tool that presents all seven as equally "affected" reproduces the waste it
exists to prevent.

**What it demonstrates deliberately.** It is a pure function over two whole
builds, with no schema mutation. Alex's plan was to add `revision` and
`previousSpec` to `PanelSpec` — a schema Jo is deleting — which would support
diffing only one step back and would force a rewrite at cutover. If this works
without those fields, that argument is over. See D2 in
[`deliverables/02-scope-decisions.md`](deliverables/02-scope-decisions.md).

---

## What is not here, and why

| Not here | Why |
|---|---|
| **FM-4 telemetry buffer** | Not buildable on the current event schema. The right deliverable was the schema contract, and that is written. |
| **Any UI** | Sam's work. Taking it would not unblock Sam, it would do Sam's job. |
| **Estimation tooling / evals** | Considered and rejected — see D11. Ships nothing on 12 Oct. The insight is a one-page multiplier table instead. |
| **Robotics overrun multipliers** | The 1.42×/2.04× figures come from the *software* backlog. Applying them to robotics' own estimates would not be justified. |
| **Firm answers to Q-A and Q-B** | Only Chris can answer them. The plan branches on them rather than guessing, and the branch closes in week 1. |

---

## Things in the hand-over that do not add up

Raised rather than worked around. Full detail in
[`deliverables/02-scope-decisions.md`](deliverables/02-scope-decisions.md) and
[`deliverables/stories.md`](deliverables/stories.md).

1. **Alex and Jo are building on schemas that delete each other.** Alex plans six
   weeks against `PanelSpec`; Jo deletes `PanelSpec` in week 3.
2. **Jo's migration is arithmetically impossible.** Three weeks of work to land
   end of week 3, with 2.8 weeks of capacity, and away for weeks 4 and 5.
3. **Inspection a3 is undeliverable as written.** It requires per-axis stop
   timing. The stream emits six axes in one event, at whole-second resolution.
4. **Alex's indirect-effects rule flags 13 of 20 panels** on the real fixture,
   against a baseline where 12% are currently wasted. Worse than the status quo.
5. **`cycleSeconds` does not reconcile** with wall-clock elapsed time. Alex's
   two-week run-progress estimator is built on an undefined field.
6. **Three separate blockers are one missing document** — nobody wrote down what
   the controller must *emit*, only what it must *do*.
7. **Sam's plan is not a plan.** *"Few weeks of work. Ping me if you want it
   broken down."* Two of the three user-facing surfaces.
8. **The hand-over's calendar is internally inconsistent.** Its day-names are
   wrong for 2026 while its dates are right; the fixture stream is dated March
   2026. Resolved in favour of the dates — see the note in `01`.

---

## Running the slices

```bash
# Slice 1 — e-stop audit (Python 3.11+, stdlib only)
cd code/estop-audit && uv sync --all-extras && uv run pytest      # 157 tests

# Slice 2 — revision impact (Node 20+)
cd code/panel-revision-impact && npm install && npm test          # 66 tests
npx vite-node demo.ts        # prints the r3 → r4 classification
```

## Repository layout

```
README.md                     you are here
deliverables/                 the plan, the reasoning, the deck
  00 … 06                     read in the order above
  stories.md                  revised story set
  firmware-event-schema-v4.2.md
  claude-code-prompts.md      the specs the slices were built from
  diagrams/*.mmd              diagram sources
  presentation/               the deck
code/
  estop-audit                 slice 1 — Python
  panel-revision-impact       slice 2 — TypeScript
build.interface.ts            shared types for fixtures and event stream
build-r3.json, build-r4.json  two revisions of one build
cell-events.jsonl             sample run, March trials
```

## A note on method

The brief invites the tools you would normally use and asks that any decision be
explainable. AI tooling was used throughout — for reading the hand-over, testing
claims against the fixture data, drafting, and writing both slices. Every number
in these documents was derived from the supplied files rather than estimated, and
the working is shown where it matters.

Two of the findings above came from **drawing the schedule rather than writing
it** — the firmware ordering problem, and the missing bench-validation and deploy
for v4.2b. Both are recorded in `06` with what changed as a result, including a
recommendation that reversed.
