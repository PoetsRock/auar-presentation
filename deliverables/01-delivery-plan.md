# Delivery plan — October demo

**Owner:** Software Engineering Lead
**Version:** 1.0, week 1 (18 Aug 2026)
**Demo:** Monday 12 October 2026, live cell, unsupervised

> **Calendar note.** The hand-over's day-names are wrong for 2026; its dates are
> right. Week markers fall on Tuesdays (18 Aug, 25 Aug, 1 Sep…). The UK summer
> bank holiday is Mon 31 Aug — still inside week 2, so the capacity deduction is
> unaffected. The demo is Monday 12 Oct, the last day of week 8. Worth confirming
> with the CTO, but the dates are the load-bearing part and they are consistent.

---

## Position

**Both features demo on 12 October. The thing at risk is *unsupervised*, and it
is decided by what has to happen to the cell before an inspector will sign it
off — not by either feature.**

Two chains gate that: the site inspection actions, and the firmware ordering.
The CTO said of the first, *"I don't think there's much in there."* Chris
under-stated the second by a week in his own email. Neither was traced end to
end by anyone, and they converge on a single event: the cell re-test.

Whether 12 October can be unsupervised turns on **two questions to Chris in week
one**. See `03-demo-date-branch.md`. Everything below is written to Plan A; the
Plan B variant is marked where it differs.

> **Current recommendation: Plan B**, revised after the resource pass in
> `06-b-pass-robotics.md`. Plan A costs Fleet Monitor its integration time and
> would demo under-integrated software unsupervised. Plan A becomes the better
> choice only if Chris answers yes to *both* week-one questions.

---

## The critical path

Two independent chains converge on the cell re-test. **Neither was traced in the
hand-over**, and both were under-costed by the person who owned them.

```
  SOFTWARE CHAIN                    FIRMWARE CHAIN
  a2 e-stop logging (4d)            boards arrive (wk 3)
        ↓                                 ↓
  a3 stop response                  v4.2a stop path (1.0w)
  (3d software + 2d rig)                  ↓
        ↓                           bench validation (0.5w)
        ↓                                 ↓
        ↓                           deploy to cell + smoke (0.5w)
        ↓                                 ↓
        └──────────→  a5 cell re-test  ←──┘
                      (5d, robotics, live cell)
                              ↓
                  a7 inspector return visit
                  (10 WORKING DAYS, external)
                              ↓
                   unsupervised running permitted
```

**The firmware chain is binding.** In Plan A it clears around 15 Sep against the
software chain's 3 Sep, so a2 and a3 carry roughly nine working days of float.

That float is not a reason to start them late. a3 needs rig time from Chris, who
is 0.8 FTE and on the commissioning site one day a week, so scheduling it is
harder than doing it. a2 is build slice 1 and starts in week 1 as cheap
insurance, not because it is the binding constraint.

**Two separate under-costings, one gate.** The CTO wrote of the inspection
actions: *"I don't think there's much in there."* There is — 24 working days of
sequence with an external party on the end. And Chris's email says firmware is
*"on the cell end of week 5"*, while his own attached plan
(2.5w + 1.0w + 0.5w from week 3) lands it at the end of week 7. Both chains were
believed shorter than they are, by different people, and they meet at a5.

**Latest possible submission to the inspector: close of Wed 23 Sep.** Ten working
days from Mon 28 Sep lands sign-off on Fri 9 Oct — one working day before the
demo, with zero margin. The arithmetic deadline is Fri 25 Sep, but Thu 24 and
Fri 25 are the week-6 offsite, so **Wed 23 Sep is the real wall**.

**Target submission under Plan A: Wed 23 Sep — the wall exactly.** Once the
firmware chain is admitted, the three days of buffer that appeared to exist
disappear. Plan A has no slack in this chain at all. See
`03-demo-date-branch.md`.

---

## Capacity

Nominal 8 weeks × 3 leads = 24 person-weeks. Actual:

| Person | Nominal | Bank hol (wk2) | Offsite (wk6) | Away | **Available** |
|---|---|---|---|---|---|
| Alex | 8.0 | −0.2 | −0.4 | — | **7.4** |
| Sam | 8.0 | −0.2 | −0.4 | — | **7.4** |
| Jo | 8.0 | −0.2 | −0.4 | −2.0 (wks 4–5) | **5.4** |
| Lead | 8.0 | −0.2 | −0.4 | −50% to leading | **3.7** |
| | | | | **Total** | **23.9** |

Robotics: 2 people, Chris at 0.8 (commissioning site ~1 day/week), minus ~1
day/week live cell support = **~1.6 FTE effective**. Their constraint is not
headcount, it is the **single spare controller** — bench validation and cell work
cannot overlap — and the live cell itself, which a5 and the v4.2 deploy both need.

## Demand, as handed over

Estimates multiplied by their owner's historical bias
(`05-estimation-calibration.md`):

| Owner | Item | Est | ×  | Adjusted |
|---|---|---|---|---|
| Alex | Panel diff | 4.0 | 1.55 | 6.2 |
| Alex | Indirect effects | 2.0 | 1.55 | 3.1 *(bimodal — could be far worse)* |
| Alex | Run-progress estimator | 2.0 | 2.18 | 4.4 |
| Jo | Build model migration | 3.0 | 1.51 | 4.5 |
| Jo | Telemetry | 3.0 | 2.10 | 6.3 |
| Sam | Revision review screen | ~3.0 | 1.14 | 3.4 |
| Sam | Fleet dashboard | ~3.0 | 1.60 | 4.8 |
| Sam | E-stop logging | 0.6 | 1.14 | 0.7 |
| Lead | a2 + a3 + schema contract + adapter | 2.2 | — | 2.2 |
| | | | **Total** | **~35.6** |

**35.6 person-weeks of demand against 23.9 of capacity. Roughly 49% over.**

Sam's two figures are inferred — he gave no breakdown — using the closest
comparable workstreams in the backlog history. Getting real numbers from Sam is a
week-1 action, and until it happens this table's largest uncertainty is his.

---

## What gives, and why

| Cut | Saves | Reason |
|---|---|---|
| **Build model migration cutover → Q4** | 4.5 | Jo has 2.8 weeks of capacity before the week-3 target and needs 4.5. Away weeks 4–5. Replaced by a read-only `PanelSpec → BuildModel` adapter (0.4, Lead). |
| **Indirect effects as designed** | 2.3 | Adjacency flags 13 of 20 panels — worse than the 12% baseline it exists to fix. Replaced by PR-7 geometric consistency (~0.8). |
| **Run-progress estimator** | 3.6 | `cycleSeconds` does not reconcile with wall clock. Derive from `panel.completed` / `panelCount` instead (~0.8). |
| **a4 operator sign-in** | 0.7 | Only inspection action that does *not* block unsupervised. `run.started` may already carry the data. Verify, then cut. |
| **Panel diff core → build slice 2** | ~3.1 | Lead delivers the classifier as a tested pure function in week 1. Alex integrates rather than starts from zero. |

**Revised demand: ~21.4 person-weeks against 23.9 available.**

That is ~10% slack across eight weeks, which is not much. The plan therefore
carries **pre-agreed release valves** rather than relying on finding slack later.

### Release valves, in the order they get pulled

1. **FM-4 buffer and reconcile** — cut in week 1 if Chris cannot commit the event
   envelope to v4.2. Decision is forced by the week-3 boards date, not by us.
2. **PR-7 geometric consistency** — cut at week 6 if integration is tight. This
   is the declared cut line; PR-1 and PR-6 are the demo.
3. **FM-5 last 24h of events** — cut at week 7. Nearly free off a2's audit store,
   so it survives unless the picture is dire.
4. **Fleet dashboard scope** — narrows automatically if the CTO reframes the demo
   away from simulated cells.

## What is added

| Add | Cost | Reason |
|---|---|---|
| **PR-6 impact and cost assessment** | absorbed into diff | The £430/build lives in classification, not detection. Four panels need re-making; two need re-queueing at zero cost. |
| **v4.2 event schema contract** | 0.4 (Lead) | Missing artefact behind three blockers. Must be agreed before boards land in week 3. |
| **`PanelSpec → BuildModel` adapter** | 0.4 (Lead) | Unblocks Alex and Sam without the cutover, and becomes the migration's regression suite in Q4. |

---

## Week by week — Plan A

Weeks run Tue → Mon in 2026. Bank holiday falls Mon 31 Aug, at the end of week 2.

| Wk | Dates | Lead | Alex | Sam | Jo | Robotics |
|---|---|---|---|---|---|---|
| 1 | 18 Aug | **a2 (slice 1)** · schema contract · slice 2 · book inspector · **Q3–Q5 + the split question to Chris** | Read fixtures · drop `previousSpec` · diff integration | **Breakdown** · mock refresh w/ Robin | Publish `BuildModel` types · read-path inventory · telemetry vs contract | **Answer the split question by Fri** · board prep |
| 2 | 25 Aug *(BH Mon 31)* | **a2 closes** · a3 software starts · adapter | Diff + PR-6 integration | Revision review screen | Telemetry ingest + buffer | Board prep · scope v4.2a |
| 3 | 1 Sep | **a3 software closes** · rig measurement w/ Chris | Diff + PR-6 | Revision review screen | Telemetry | **Boards arrive Tue 1st** · v4.2a build |
| 4 | 8 Sep | **a3 closed Thu 3rd** → float · PR-3 approve flow | PR-7 consistency | Screen done → fleet dashboard | *away* | Bench validation (reduced scope) |
| 5 | 15 Sep | Integration · monitor a5 daily | PR-7 | Fleet dashboard *(simulator)* | *away* | **Deploy v4.2a Tue 15th** · **a5 starts Wed 16th** · v4.2b build starts |
| 6 | 22 Sep *(offsite Thu–Fri)* | **Submit to inspector Wed 23rd** | FM-2 progress | Dashboard + stop wait-state *(simulator)* | Telemetry vs simulator | **a5 closes Tue 22nd** · v4.2b build to Fri 25th |
| 7 | 29 Sep | Integration | Hardening | Polish | **First real events ~2 Oct** | **Bench v4.2b 28–30 Sep** · **deploy v4.2b 1–2 Oct** |
| 8 | 6 Oct | **Rehearsals 5–9 Oct · freeze Wed 7th** | Contingency | **Real-cell integration** | **Real-cell integration** | Live cell support |

**Sign-off Wed 7 Oct.** Three working days before the demo.

**Note the shape.** a3 closes Thu 3 Sep and then nothing on the permission chain
moves until the firmware clears on 15 Sep. That gap is real float, and it is
where any software slip gets absorbed. It is also why weeks 4–5 look quiet on the
Lead's row — that is deliberate reserve, not spare capacity to fill.

**Note what the B pass changed.** v4.2b's bench validation and deploy were
missing from this table entirely; they now occupy 28 Sep – 2 Oct. That pushes
rehearsals to 5–9 Oct — **one week, not two** — and it is the same week as Fleet
Monitor's first contact with real cell data. Everything before then runs against
a simulator built from the schema contract. See `06-b-pass-robotics.md`; this is
the strongest argument against Plan A.

### Plan B variant

Identical through week 3. From week 4 the firmware runs whole rather than split,
and the re-test moves after the demo:

| Wk | Robotics | Everyone else |
|---|---|---|
| 4–5 | v4.2 full envelope, no split | unchanged |
| 6 | v4.2 completes ~22 Sep · bench validation | unchanged |
| 7 | Bench closes · deploy to cell ~2 Oct | unchanged |
| 8 | **Demo Mon 12 Oct — supervised** | rehearsals unchanged |
| 9 | **a5 re-test 13–19 Oct** · submit Mon 19th | FM-4 build (envelope now exists) |
| 10–11 | Inspector, 20 Oct – 2 Nov | FM-4 · a3 measurement moves to firmware |
| — | **Unsupervised sign-off ~Mon 2 Nov** | |

Plan B adds roughly two weeks of slack and makes FM-4 buildable. It costs a
supervised demo. Full comparison in `03-demo-date-branch.md`.

### Gates

| Gate | When | If it fails |
|---|---|---|
| **Firmware split question answered** | **End wk 1** | **Plan B. Decided now, not in week 6** |
| Event schema contract agreed with Chris | End wk 1 | FM-4 cut, in writing, with a reason |
| Sam's breakdown + approved mocks | End wk 1 | Sam's two surfaces are unplanned work; escalate |
| Boards arrive | Tue 1 Sep | Firmware slips 1:1. Plan A has no float here — a week's slip forces Plan B |
| v4.2a deployed to cell | Tue 15 Sep | a5 cannot start; Plan A is over |
| a5 submitted to inspector | **Wed 23 Sep** | Fallback condition fires |
| Code freeze | Wed 7 Oct | Demo on unrehearsed code |

## The fallback trigger

Stated as a **condition with a date backstop**, not a date. A date can pass while
the work is 90% done, and abandoning it then would be daft.

> **Condition.** Cell re-test (a5) is not complete and submitted to the inspector.
>
> **Evaluated.** Daily from Mon 14 Sep, jointly by Lead and Chris.
>
> **Backstop.** Close of business **Wed 23 Sep**. Beyond that the arithmetic
> fails regardless of how nearly done a5 is.
>
> **Action.** Switch to Plan B — supervised demo on 12 Oct, unsupervised sign-off
> ~2 Nov. Notify the CTO and the customer-facing team the same day. The demo
> itself is unchanged; the only difference is a person standing beside the cell.

The point of pre-agreeing this is that the switch costs nothing if it is decided
on 23 Sep and costs the demo if it is decided on 9 Oct.

**Two triggers, not one.** The week-1 firmware question is the cheap trigger —
answered before anyone has built anything, and it selects the plan. The 23 Sep
condition is the expensive one, and it only exists because Plan A has no slack.
If the week-1 answer is uncertain, take Plan B: an uncertain Plan A is a Plan B
that arrives five weeks late having burned the optionality.

---

## Assumptions

Each one is written so it can be proved wrong.

| # | Assumption | If wrong |
|---|---|---|
| A1 | a3's measurement comes from Chris's rig, not from v4.2 firmware timing | The chain cannot complete before 12 Oct. Unsupervised is off, full stop. **Highest-severity assumption in the plan.** |
| A2 | Deploying v4.2 after the cell re-test does not invalidate the re-test | Re-test must follow deploy → slips to wk 7 → sign-off wk 9 → unsupervised is off |
| A3 | The event envelope is small relative to v4.2 as a whole | FM-4 is cut in week 1 |
| A4 | Boards clear supplier testing and arrive in week 3 | Firmware slips 1:1. Demo Fleet Monitor on recorded/simulated events |
| A5 | The diff is a pure function over two whole builds; no schema mutation needed | Alex's `previousSpec` approach returns, and the Q4 cutover gets harder |
| A6 | Mocks can be refreshed by Robin inside week 1 | Sam starts on stale mocks or starts late |
| A7 | Installed panels are never auto-re-issued; they escalate | PR-6 AC5 changes and the safety gate needs redesigning |
| A8 | Remote stop is a graceful end-of-panel halt, not a safety function | Feature enters the safety case and does not ship this quarter |
| A9 | One cell is acceptable for the demo, or simulated cells are labelled | Fleet Monitor demo needs rethinking; CTO decision by end wk 2 |
| A10 | Sam's two surfaces are ~6 weeks combined | The largest single unknown in the capacity table |

## Risks

| Risk | Trigger to watch | Mitigation | Owner |
|---|---|---|---|
| Inspection chain slips | a2 not closed by end wk 2 | Fallback condition; a2 is slice 1 and starts day one | Lead |
| Boards slip | Supplier silence by end wk 2 | Chase weekly from wk 1; simulated events as demo fallback | Chris |
| Robotics resource collision | a5 and v4.2 bench work both live in wks 5–6 | One spare controller — sequence explicitly with Chris in wk 1 | Chris |
| Sam's work is unplanned | No breakdown by end wk 1 | Escalate; his surfaces are the visible half of both demos | Lead |
| Jo returns to a changed codebase | wk 6 | Adapter freezes the interface Jo left; read-path inventory done in wk 1 | Jo |
| Demo is a **Monday** | — | Freeze Wed 7 Oct; rehearse Thu 8 and Fri 9. Anything breaking Friday evening sits unattended over the weekend | Lead |
| **v4.2 deploys after the re-test** | Robotics schedule as drawn | See "The v4.2 ordering problem" below. Unresolved | Lead + Chris |
| Alex resists the `previousSpec` decision | wk 1 | Slice 2 settles it in code, not in a meeting | Lead |

## Open questions

Tracked with owners and dates in `stories.md`. The three that gate everything —
Q3 (does a3 need v4.2?), Q4 (envelope in v4.2?), Q5 (does deploy invalidate the
re-test?) — are all for Chris and all needed by end of week 1.
