# Estimation calibration

**Owner:** Software Engineering Lead
**Status:** Working note. Feeds the cuts in `01-delivery-plan.md`.
**Circulation:** internal to planning. Not for the CTO in week 1 — see
`00-cto-response.md`.

---

## The multipliers

Derived from `Delivery backlog history`, twelve workstreams over two quarters.
Ratio of actual to estimate:

| Discipline | Non-hardware | Hardware-dependent | Sample |
|---|---|---|---|
| Solver (Alex) | **1.55×** | **2.18×** | 4 workstreams |
| Platform (Jo) | 1.51× | 2.10× | 5 workstreams |
| Frontend (Sam) | **1.14×** | 1.60× | 3 workstreams |
| **All** | **1.42×** | **2.04×** | 12 workstreams |

Global figures check out against totals rather than averaged ratios: non-hardware
17.5 estimated → 24.8 actual (1.417); hardware-dependent 10.5 → 21.4 (2.038).
The two methods agreeing is mild evidence the bias is systematic rather than
noise.

## What this actually says

**Hardware dependency roughly doubles the overrun**, consistently, across every
discipline. That is the single most useful number in the pack, and it is why
Fleet Monitor carries more schedule risk than Panel Revisions regardless of how
the individual items are estimated.

**The bias is not uniform across people.** Alex is the least accurate estimator
on the team; Sam is the most accurate — when Sam estimates at all. This inverts
the obvious reading of the hand-over. Alex wrote the most detailed plan and Sam
wrote "few weeks of work," so Alex *looks* more rigorous. On the evidence, Alex's
numbers need challenging and Sam's need extracting.

**Sample sizes are small.** Three to five workstreams per discipline. These are
planning multipliers, not laws. They are used here to size risk and justify cuts,
not to performance-manage anyone.

---

## Two kinds of low confidence

The hand-over contains one Low-confidence estimate — Alex's indirect effects,
2 weeks — and the reason he gives matters more than the label:

> *"If moving one window can cascade through a whole level, this is a much bigger
> problem than 2 weeks and I can't estimate it until I've tried."*

That is not a wide estimate. It is **two estimates and no way to tell which one
applies**. The distinction changes the remedy completely:

| | Wide uncertainty | Bimodal uncertainty |
|---|---|---|
| Sounds like | "2 weeks, maybe 3" | "2 weeks, or 8, depending" |
| Shape | One distribution, long tail | Two distributions, unknown which |
| Remedy | Pad, or decompose further | **Timeboxed spike on the deciding fact** |
| Why padding fails | — | Any single number is wrong in *both* worlds |

Padding a bimodal estimate produces a number that is too high if the good branch
holds and far too low if the bad one does. It is the worst available answer.

**The correct move is to name the deciding fact and go and resolve it.** Here the
deciding fact was: *do design changes cascade?*

**And it was already answered by data sitting in the hand-over.** In r3 → r4,
seven panels changed, all directly, none by cascade. The single genuine knock-on
effect — EW-L2-W1 no longer stacking on the shrunk EW-L1-W1 — is found by a
structural rule, not by propagation. Alex's spike was reading two JSON files.

The estimate was not low-confidence because the work was hard. It was
low-confidence because nobody had looked at the fixtures.

## The Mediums are worse than the Low

Alex's Low at least carries a stated reason. The two Mediums carry none, and one
of them contradicts its own design note. The technical design describes the diff
as *"hash the geometry, compare hashes, linear over panels."* That is days of
work. The estimate is four weeks.

So either the four weeks includes work that is not described anywhere — schema
changes, the status join, the re-issue pipeline — or it is padding. **The gap
between the estimate and the design is the thing to probe, not the number.**
Asking "why four weeks?" invites defensiveness. Asking "what's in the four weeks
that isn't in the design note?" invites decomposition.

---

## Definition of ready

Seven checks. Every one traces to a specific failure in *this* hand-over, which
is the only reason to trust them. Generic hygiene checklists get ignored; ones
with receipts get used.

| # | Check | Caught here |
|---|---|---|
| 1 | Does the output the story requires **exist in the data we have**? | a3 needs per-axis stop deltas. The stream emits six axes in one event with one timestamp. |
| 2 | Is the acceptance criterion **measurable at the resolution the data provides**? | Stop response time, against whole-second timestamps. Best available answer is "≤2s". |
| 3 | Has anyone **run the story against real fixture data**? | Adjacency-based indirect effects flags 13 of 20 panels. Nobody ran it. |
| 4 | Does any estimate **assume a schema another team is deleting**? | Alex plans 6 weeks on `PanelSpec`; Jo deletes `PanelSpec` in week 3. |
| 5 | Does the estimate **decompose into items of ≤3 days**? | Alex's 4-week Medium; Sam's "few weeks of work". |
| 6 | If confidence is Low, is it **wide or bimodal** — and if bimodal, what is the spike? | Indirect effects. See above. |
| 7 | Does the story depend on a **hardware milestone**, and is that milestone's slip modelled downstream? | Everything in Fleet Monitor depends on boards landing in week 3. |

Check 4 is the one most likely to be skipped, because it requires reading someone
else's plan. It is also the one that would have caught the largest single piece
of waste in the hand-over.

## What this does not tell you

- **It does not tell you the estimates are dishonest.** A systematic 1.4×
  suggests a shared definition of "done" that excludes integration, review, and
  the last 10%. That is a process artefact, not a character flaw, and the fix is
  to change what gets counted rather than to ask people to try harder.
- **It does not survive scope changes.** The multipliers describe how this team
  estimates work of the kind it has done before. Panel Revisions is new
  territory; the multiplier is a starting point, not a forecast.
- **It does not replace decomposition.** A calibrated bad estimate is still a bad
  estimate. Applying 1.55× to a number nobody can break down produces a
  confident-looking guess, which is worse than an admitted one.
