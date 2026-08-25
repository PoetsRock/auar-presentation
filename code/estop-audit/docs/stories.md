# Revised user stories — AUAR October demo

**Owner:** Software Engineering Lead
**Last updated:** 21 Aug 2026 (week 1)
**Status:** Proposed. Needs sign-off from Robin (Product) and Chris (Robotics).

---

## Why these differ from the hand-over

Robin's Notion briefs were written before anyone had run the fixture data
(`build-r3.json`, `build-r4.json`, `cell-events.jsonl`). Reading that data
changed three things: what is **valuable**, what is **safe**, and what is
**buildable at all**.

Every change below traces to specific evidence in that data. None of it is
preference, and each one is falsifiable — if the evidence is wrong, reverse
the change.

---

## Change log

| # | Change | Story | Rationale (short) |
|---|---|---|---|
| C1 | **Added** | PR-6 Impact and cost assessment | The money is in classification, not detection |
| C2 | **Superseded** | PR-2 (status of each panel) | Absorbed into PR-6; status alone is not decidable |
| C3 | **Promoted** | PR-5 Should → Must, inside PR-6 | Cost is the value case, not a nice-to-have |
| C4 | **Descoped** | "Indirect effects" as designed | Adjacency rule flags 13 of 20 panels |
| C5 | **Replaced** | Indirect effects → geometric consistency | Catches 1 real defect instead of 13 false ones |
| C6 | **Blocked** | FM-4 Buffer and reconcile | Not buildable on the current event schema |
| C7 | **Reduced** | FM-2 Run progress | `cycleSeconds` does not reconcile; use panel counts |
| C8 | **Constrained** | FM-3 Remote stop | Needs a wait-state UI or it looks broken on stage |
| C9 | **Assigned** | Inspection a3 | Had no owner; Lead takes it |
| C10 | **Challenged** | Inspection a4 | May already be satisfied by existing event fields |

---

## Evidence base: what r3 → r4 actually contains

Seven of twenty panels changed. All on level 1. Their recoverability differs
completely, and that difference is the whole feature.

| Panel | Change | Status | Class | Cost |
|---|---|---|---|---|
| EW-L1-N1 | opening x 1200→1800 | **installed** | `escalate` | TBC — blocks approval |
| EW-L1-E1 | opening x 1800→2400 | manufactured | `remake` | £180 |
| EW-L1-W1 | width 4800→4200, weight 192→168 | manufactured | `remake` | £180 |
| IW-L1-01 | height 2700→2750, **weight unchanged** | manufactured | `remake` + suspect | £180 |
| FC-01 | span 4800→4200, weight 218→196 | manufactured | `remake` | £180 |
| EW-L1-N2 | opening x 600→900 | planned | `requeue` | £0 |
| FC-02 | span 4800→4200, weight 218→196 | planned | `requeue` | £0 |

Three findings fall out of this table that no story in the hand-over covers:

1. **A changed panel is already installed.** EW-L1-N1's window moved 600mm in a
   panel that is in a building. Product's open question ("how far back can we
   revise once a panel is installed?") is unanswered and the flow has no gate
   for it. This is the only genuine safety and quality risk in the feature.
2. **Two changed panels cost nothing.** EW-L1-N2 and FC-02 are `planned` — they
   need re-queueing, not re-making. A tool that presents all seven as equally
   "affected" reproduces the exact £430-per-build waste it exists to prevent.
3. **Derived fields go stale.** IW-L1-01's height changed 2700→2750 but
   `weightKg` stayed at 85, while every other resized panel had its weight
   recalculated (192→168, 218→196). Someone edited by hand. Every downstream
   cost and handling figure for that panel is wrong. Nobody asked for this
   check; it falls out of the diff for free.

**Correct classification:** £720 of re-makes, two free re-queues, one
escalation. **Alex's adjacency rule** would flag all thirteen level-1 panels —
£2,340 if acted on, against a baseline where only ~12% of panels are currently
wasted. The tool would be worse than the status quo.

---

## Panel Revisions — revised story set

### PR-1 — See which panels a design change affects — **Must** *(unchanged)*

As a production manager I want to see which panels a design change affects, so
that I only re-make what's needed.

### PR-6 — Impact and cost assessment — **Must** *(NEW — supersedes PR-2, absorbs PR-5)*

> **As a** production manager
> **I want** every affected panel classified by what can still be recovered and
> what it costs, before I approve a re-issue
> **So that** I only re-make what is genuinely unrecoverable, and I can put a
> number in front of the client.

**Acceptance criteria**

1. Every panel is assigned exactly one class: `no_action`, `requeue`,
   `remake`, `recall`, `escalate`.
2. Class is a function of `(changed, status)` **only** — never of adjacency.
3. Each class carries a cost: `requeue` £0, `remake` £180,
   `recall` £180 + logistics (**TBC — Robin**), `escalate` no automatic cost.
4. Total cost of the change is shown **before** approval, not after.
5. **No panel with status `installed` can be auto-re-issued.** It routes to
   `escalate` and blocks approval until explicitly acknowledged by an engineer.
6. Panels whose geometry changed but whose derived fields did not are flagged
   as suspect data and excluded from the cost total.
7. Output is deterministic and diffable, so it can be attached to the change
   record — which answers Product's audit-trail question at near-zero cost.

**Note on AC5.** This is the criterion to defend hardest. It is the difference
between a tool that speeds up replanning and a tool that lets someone re-issue
a wall that is already standing.

### PR-3 — Approve a re-issue, factory queue updates — **Must** *(unchanged)*

### PR-4 — Site foreman told a panel is superseded — **Must** *(unchanged)*

Note: this is the only story that protects against the EW-L1-N1 case reaching
site. It should not be cut even though it is the least visible on stage.

### PR-7 — Geometric consistency check — **Should** *(replaces "indirect effects")*

> **As a** production manager
> **I want** to be told when an unchanged panel no longer fits a changed one
> **So that** I catch knock-on defects without reviewing the whole level.

**Evidence.** EW-L1-W1 shrank 4800→4200 and both cassettes spanning it followed
(FC-01, FC-02). But **EW-L2-W1 is still 4800** — a level-2 wall that no longer
stacks on the level-1 wall beneath it. Adjacency flags thirteen panels and
buries this. A stacking-alignment check flags exactly one, and it is real.

**Cut line:** if week 6 is tight, this is the first thing to go. PR-1 and PR-6
are the demo.

---

## Fleet Monitor — revised story set

### FM-1 — See every cell and what it's running — **Must** *(unchanged)*

Open question for the CTO: we have **one** cell. A "fleet monitor" showing one
tile is a weak demo of a fifty-cell operating model. Options: demo one real
cell plus clearly-labelled simulated cells, or reframe the demo as
"cell monitor, built to scale." Do not fake this silently — the customer is
buying the operating model, and a discovered fake costs more than a small demo.

### FM-2 — Run progress and expected finish — **Must** *(reduced)*

**Change.** Alex estimated 2 weeks for a run-progress estimator. Do not build
an estimator. `cycleSeconds` in the event stream does not reconcile with
wall-clock elapsed time — EW-L1-N1 reports 388s against 376s elapsed, EW-L1-E1
reports 624s against 550s. The field is undefined and cannot be built on.

**Instead:** derive progress from `panel.completed` count against `panelCount`
on `run.started` (present in the sample, value 20). Expected finish =
elapsed ÷ completed × remaining. Reliable fields only, and a fraction of the
estimate.

**Follow-up for Chris:** what is `cycleSeconds` actually measuring? If it is
authoritative and the wall-clock gap is an artefact of the sample, revisit.

### FM-3 — Stop a run remotely — **Must** *(constrained)*

**Decision taken:** remote stop is a **graceful end-of-panel halt**. It is
explicitly **not** a safety function. Physical e-stop remains local and
unchanged. Rationale: a safety-rated stop over a link we already know drops is
not defensible, and it would drag the whole feature into the safety case.

**New acceptance criterion.** Mean panel cycle is ~388s. Pressing "Stop" and
seeing nothing happen for up to six and a half minutes looks like a broken
product in front of a customer. The UI must show a committed wait state:
*"Stop requested — halting after current panel, ~4 min remaining"* with a live
countdown and the panel it is finishing.

**Question for Chris.** The March stream shows the cell already stopping
mid-panel on e-stop and resuming with `resumeMode: "from_panel_start"`. So
mid-panel stop is not unrecoverable — it costs one panel. Is "stop now" genuinely
unscoped, or just unrequested? Not needed for the demo either way; worth
knowing before we tell the customer it is impossible.

### FM-4 — Keep running and catch up after a dropout — **Must** *(BLOCKED)*

**Not buildable on the current event schema.** See
`docs/firmware-event-schema-v4.2.md`. Requires `eventId`, `seq`, `bootId`,
millisecond timestamps and an acknowledgement protocol, none of which exist
today and none of which are in the v4.2 scope Chris has described.

**This is the highest-urgency item in the pack**, because the fix has to land
in firmware v4.2, v4.2 work starts when boards arrive in week 3, and there is
no v4.3 before the demo. If the schema is not agreed before week 3, this story
does not ship this year.

### FM-5 — Last 24h of events for a cell — **Should** *(keep — nearly free)*

The e-stop audit store built for inspection action 2 already persists the event
stream. This story is mostly a read endpoint over it. Cheap; keep unless the
week 7 picture is dire.

---

## Site inspection actions — ownership resolved

The inspection chain is the **critical path to an unsupervised demo**, not a
side item. Sequence: a2 → a3 → a5 → a7, where a7 is a 10-working-day external
lead time. That is 24 working days of pure sequence with no slack.

| # | Action | Owner (was) | Owner (now) | Note |
|---|---|---|---|---|
| 2 | E-stop events logged and retrievable | Software | **Lead** | Build slice 1. Starts week 1. |
| 3 | Stop response time measured per cell | *Not agreed* | **Lead** + Chris's rig | Was unowned. See below. |
| 4 | Operator sign-in recorded per run | Software | **Challenge first** | May be near-done already |
| 5 | Cell re-test | Robotics | Robotics | Blocked on a2 + a3 |
| 7 | Inspector return visit | External | External | **Book provisionally in week 1** |

### a3 — the measurement problem

Action 3 requires stop response time recorded **per axis**. The current event
stream cannot express that:

- Timestamps are whole-second resolution. The sample's
  `stop.requested` → `motion.halted` delta is exactly 1s. You can report
  "≤2s" and nothing better.
- `motion.halted` carries `axesStopped: ["j1"..."j6"]` — six axes, one event,
  one timestamp. There is no per-axis delta to compute.

**Resolution:** measurement comes from Chris's rig with external
instrumentation, not from the controller event stream. Robotics' own plan
already implies this ("Rig support for inspection action 3, cell has to be
stopped for the measurement"). The software side of a3 defines the record
format and the audit log; the rig supplies the numbers. **This must be
confirmed with Chris in week 1** — if a3 instead depends on v4.2 firmware
timing, the chain cannot complete before 12 Oct and the demo cannot be
unsupervised.

### a4 — challenge before building

`run.started` already carries `operator: "op-114"`, and `interlock.released`
carries an operator id. a4 may be largely satisfied by data we already emit.
Verify before spending the estimated 3 days. It is also the only inspection
action that does **not** block unsupervised running, so it is the safest cut in
the pack.

---

## Open questions, with owners

| Q | Ask | Owner | Needed by |
|---|---|---|---|
| Q1 | Logistics cost of recalling an in-transit panel | Robin | Week 2 |
| Q2 | Can an installed panel ever be revised, and who signs it off? | Robin | Week 2 |
| Q3 | Does a3 depend on v4.2 firmware, or only the rig? | Chris | **Week 1** |
| Q4 | Will v4.2 carry `eventId` / `seq` / ms timestamps? | Chris | **Week 1** |
| Q5 | Does deploying v4.2 after the cell re-test invalidate the re-test? | Chris | **Week 1** |
| Q6 | One real cell or simulated fleet for the demo? | CTO | Week 2 |
| Q7 | What is `cycleSeconds` measuring? | Chris | Week 3 |
