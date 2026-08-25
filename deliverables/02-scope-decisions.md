# Scope decisions

**Owner:** Software Engineering Lead
**Status:** Taken in week 1. Reversible on stated evidence.

---

## How to read this

The brief asks *why* more than *what*. Each decision below records what was
decided, whose stated position it overrides, what it costs, and **what evidence
would reverse it**. A decision that nothing could reverse is a preference wearing
a suit.

---

## Part 1 — Decisions that override a stated position

### D1 — The build model migration cutover moves to Q4

**Overrides:** Jo. *"One cutover. All the read paths move in a single PR… Merge
end of week 3 and we're on `BuildModel` everywhere."*

**Why.** Jo has **2.8 weeks of capacity** before the week-3 target — week 2 has a
bank holiday — against **4.5 calibrated weeks** of work, and is then away for
weeks 4 and 5. The cutover cannot land in week 3. On Jo's own capacity it lands
around week 7, and a single-PR cutover landing in week 7 with seven weeks of new
code sitting on top is *precisely* the "exponentially more complex" outcome Jo
warns against. The calendar causes it, not the delay.

**Instead.** A read-only `PanelSpec → BuildModel` adapter, ~2 days, deleted at
cutover. All new code reads `BuildModel` only, so the migration surface stops
growing today.

**Cost.** Jo is right that half-migrated is worse than either end. We accept that
state for eight weeks, deliberately, in exchange for removing the largest
schedule dependency in the plan.

**Reverses if.** Jo's weeks 4–5 absence changes, or the week-1 read-path
inventory shows the remaining work is under ~1.5 weeks.

### D2 — `PanelSpec` is frozen. No `revision`, no `previousSpec`.

**Overrides:** Alex. *"I'll add `revision` and `previousSpec` to `PanelSpec` so
we can diff without standing up a separate store."*

**Why.** This is not a small convenience — it changes the shape of the problem.
It creates a second source of revision truth competing with
`BuildModel.revision` / `supersedes`; it supports diffing only **one step back**,
while the fixtures show chains (r4 supersedes 3, supersedes 2); and it makes the
diff's input contract "a panel carrying its own history," which means the logic
gets **rewritten** at cutover rather than re-pointed.

**Instead.** `diff(previous, next)` — a pure function over two whole builds. The
fixtures are already two complete documents; that is the natural shape.

**Cost.** Two builds in memory rather than one panel. 5.9 KiB for 20 panels.

**Reverses if.** Builds turn out too large to load whole. Nothing suggests this.

**Settled by.** Build slice 2. If the pure function works, the argument is over.

### D3 — Adjacency-based indirect effects is replaced

**Overrides:** Alex. *"Any panel sharing an edge with a changed panel gets
flagged for review. Deliberately conservative: I'd rather over-flag than miss
one. On a typical change this will flag most of a level, but that's the safe
direction to be wrong in."*

**Why.** Run against the fixtures, the rule flags **13 of 20 panels** — every
panel on level 1 — where 7 actually changed. The feature exists because ~12% of
panels are currently re-made unnecessarily. A tool that flags 65% is worse than
the status quo, and its realistic fate is to be ignored, which is the worst
outcome available: it looks like the feature shipped.

**The reasoning error is worth naming.** "I'd rather over-flag than miss one" is
correct for a safety system and wrong for a cost-reduction tool. Here,
over-flagging *is* the failure mode the feature was funded to prevent.

**Instead.** PR-7 geometric consistency. On the fixtures it flags exactly one
panel, and it is real: EW-L2-W1 is still 4800 wide while EW-L1-W1 beneath it
shrank to 4200, so a level-2 wall no longer stacks on the level-1 wall below.
Adjacency finds this too — buried among twelve false positives.

**Cost.** We will miss knock-on effects that are not geometric.

**Reverses if.** Robin or Alex can show design changes routinely propagate
through non-geometric relationships. Worth asking; not assumed.

### D4 — Run-progress estimation is replaced by panel-count derivation

**Overrides:** Alex, 2 weeks at Medium confidence.

**Why.** `cycleSeconds` does not reconcile with wall-clock elapsed time —
EW-L1-N1 reports 388s against 376s, EW-L1-E1 reports 624s against 550s, and the
discrepancies are not even consistent. The field is undefined. An estimator built
on it inherits the undefinedness and hides it behind a confident number.

**Instead.** `panel.completed` count against `panelCount` from `run.started`
(present in the sample, value 20). Expected finish = elapsed ÷ completed ×
remaining. Reliable fields only.

**Cost.** A cruder estimate. Adequate for a supervisor planning a day, which is
what the story actually asks for.

**Reverses if.** Chris confirms `cycleSeconds` is authoritative and the
wall-clock gap is a sample artefact (Q7).

### D5 — PR-2 is superseded; PR-5 is promoted to Must

**Overrides:** Robin's priorities.

**Why.** PR-2 gives the production manager each panel's status. Status alone is
not decidable — knowing a panel is `manufactured` does not tell her whether to
re-make it. PR-5, the only story that surfaces money, was marked *Should*. The
business case for the entire feature is a money number. Shipping the mechanism
without the number reproduces the situation she is in today, with a nicer list.

**Instead.** PR-6 absorbs both: classification plus cost, before approval.

**Reverses if.** Robin has context suggesting the manager already knows the cost
model well enough to decide from status alone.

---

## Part 2 — Decisions filling a gap nobody owned

### D6 — Installed panels escalate. They are never auto-re-issued.

**Fills.** Robin's open question — *"How far back can we revise once a panel is
installed?"* — which was asked and never answered, and for which the flow has no
gate.

**Why it can't wait for an answer.** EW-L1-N1 in the fixtures has a window moved
600mm in a panel that is standing in a building. Without a gate, the tool's
happy path re-issues it. The cheapest safe assumption is a hard block requiring
explicit engineer acknowledgement.

**Reverses if.** Robin defines a revision policy for installed panels. Until
then the block stands, and it is PR-6's most defensible acceptance criterion.

### D7 — The Lead owns inspection actions a2 and a3

**Fills.** a3's owner column reads *"Not agreed"*, with the note *"The
measurement is a software job but it needs our rig. Someone should pick it up."*

**Why the Lead.** It is unowned, it is on the critical path, it sits across the
software/robotics boundary where a lead should be, and taking it converts an
open question into work in progress on day one. It is also build slice 1.

### D8 — Remote stop is a graceful end-of-panel halt, not a safety function

**Fills.** Robin's open question, plus Chris's *"assume end-of-panel unless
someone tells us otherwise."*

**Why explicit.** A safety-rated stop delivered over a link we already know drops
is not defensible, and asserting one would pull Fleet Monitor into the safety
case. Physical e-stop stays local and unchanged.

**What the data adds.** The March stream shows the cell already stopping
mid-panel on e-stop and resuming `from_panel_start`. Mid-panel stop is therefore
not unrecoverable — it costs one panel. So end-of-panel is a **product choice**,
not a hardware limitation, and we should stop describing it as impossible.

**Consequence.** Mean cycle is ~388s, so "Stop" can appear to do nothing for six
minutes. FM-3 gains an acceptance criterion: a committed wait state with a live
countdown. Without it the demo looks broken on stage.

### D9 — The firmware event schema contract is a week-1 Lead deliverable

**Fills.** The artefact missing from the hand-over. v4.2 is specced as behaviour
— "expose run events, accept remote stop" — with no data contract.

**Why now.** Boards land week 3, firmware follows, and there is no v4.3 before
12 October. Anything not agreed now is not in the demo.

**Honest scope.** It fully solves FM-4, improves a2, and only partly addresses
a3 — per-axis timing needs a new event type, and the measurement should stay on
the rig regardless. One document, three blockers, three different resolutions.

---

## Part 3 — Decisions about what not to build

### D10 — Build slice selection: options 5 and 2

| Option | Verdict | Reason |
|---|---|---|
| **5 — E-stop logging + response time** | **Taken** | On the critical path, unowned, unblocks robotics → re-test → inspector. Nothing else can start without it. |
| **2 — Panel diff** | **Taken, extended** | Extended into classification and cost. Also settles D2 in code. |
| 1 — Revision review screen | Rejected | Sam's work. Taking it doesn't unblock Sam, it does Sam's job. |
| 3 — Compatibility layer | Obtained free | Slice 2's adapter *is* the compatibility layer. |
| 4 — Telemetry buffer | Rejected | Unbuildable as specified. The right deliverable is the schema contract, which we wrote instead. |
| 6 — Run-state machine | Closest runner-up | Its central question — what a remote stop does to a half-made panel — is **already answered by the sample stream**: the cell stops mid-panel and resumes `from_panel_start`. Its output would be a document, and we already have one as a Lead deliverable. |

### D11 — No estimation tooling or eval harness this quarter

**Considered.** A reusable skill plus evals to flag stories that are
under-specified or undeliverable as written — automating the seven checks.

**Why not now.** It is not from the plan, ships nothing on 12 October, and
unblocks nobody. Spending a new lead's first week on process tooling while the
team is ~49% over-committed is the wrong signal and the wrong priority.

**Instead.** The multipliers table and the seven-check definition of ready in
`05-estimation-calibration.md`. Same insight, one page, zero build cost, usable
by the team on Monday.

**Revisit.** Q4, once there is evidence the checklist gets used and skipped in
predictable places.

### D12 — FM-4 stays *blocked*, not *cut*

The distinction is deliberate. Cutting it in week 1 without asking Chris would
discard a story that might cost two days once the envelope is right. Leaving it
"in progress" would let Jo spend three weeks against a schema that cannot satisfy
it. **Blocked** names the gate and the date: if Chris cannot commit the envelope
to v4.2 by end of week 1, it is cut, in writing, with a reason.

---

## Deferred to Q4

| Item | Why deferred | Prerequisite |
|---|---|---|
| `BuildModel` migration cutover | D1 | Read-path inventory; adapter as regression suite |
| a4 operator sign-in | Doesn't block unsupervised; may already be satisfied by `run.started.operator` | Verification, ~half a day |
| Mid-panel remote stop | Unscoped by robotics; not needed for the demo | Chris's answer on whether it is genuinely unscoped or merely unrequested |
| Moving a3 measurement from rig to controller | Needs `axis.halted` in firmware | v4.3 |
| Estimation tooling | D11 | Evidence the manual checklist is used |
