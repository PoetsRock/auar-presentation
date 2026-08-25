# Demo date — one decision, two shapes

**Owner:** Software Engineering Lead
**Status:** Branch point. Resolved by one answer from Chris in week 1.

---

## This is not two plans

It is one plan with a gate. Everything before the gate is identical, everything
after it is pre-committed, and the gate closes in week 1 rather than week 6.

## The gate

> **Two questions for Chris, both answered by end of week 1:**
>
> **Q-A.** Can v4.2 be split so that everything touching the **stop path** ships
> first, and everything that is purely **observability** ships after the
> inspector has signed off?
>
> **Q-B.** Can the **run-event stream** ride in the early half without extending
> its build beyond a week?

Q-B was added after the B pass and it matters as much as Q-A. Run events are
observability, so the split rule puts them in the late half — which starves
Fleet Monitor of real cell data until October. They touch no control path, so
including them early does not invalidate the re-test. The only cost is build
time, and the early half has to stay at roughly one week to make the wall.

**So Q-B is really: does adding run events make v4.2a take longer than a week?**
If no, Fleet Monitor gets real data from 15 Sep instead of 2 Oct — three extra
weeks of integration on the feature the demo is for.

**Why this one question decides the whole shape.**

The robotics chain is four weeks of strictly sequential work from the boards
landing: firmware (2.5w) → bench validation on the single spare controller (1.0w)
→ deploy and smoke test (0.5w). Run whole, that puts v4.2 on the cell around
30 September.

But the cell re-test (a5) has to happen on the firmware we intend to demo.
Re-testing on v4.1 and then deploying v4.2 — whose entire purpose is to change
stop behaviour — means demonstrating a configuration the inspector never
examined. So the full-v4.2 ordering pushes the re-test past 12 October and the
inspector sign-off past the demo.

A split fixes it, because the re-test then runs on the **final safety
configuration** and nothing landing afterwards touches the control path:

| Ships before the re-test | Ships after sign-off |
|---|---|
| Remote-stop acceptance | Run-event stream |
| `axis.halted` per-axis instrumentation | Full event envelope (`eventId`, `seq`, `bootId`, `monotonicUs`) |
| Anything altering the stop path | Anything that only observes |

**The rule underneath it:** never change the safety configuration after the
re-test; only add observability. If Chris can hold that line, Plan A is live. If
firmware does not decompose that way — and often it does not — Plan B.

*Note: this stays v4.2 either way. There is no v4.3. The v4.3 problem exists
only because of the 12 October date.*

---

## Plan A — the split works. 12 October, unsupervised.

| Step | Dates |
|---|---|
| Boards arrive | Tue 1 Sep |
| v4.2a — stop path only (1.0w) | 1 – 7 Sep |
| Bench validation, reduced scope (0.5w) | 8 – 10 Sep |
| Deploy to cell + smoke (0.5w) | 11 – 15 Sep |
| a5 cell re-test, on final safety config (5d) | 16 – 22 Sep |
| **Submit to inspector** | **Wed 23 Sep** |
| Inspector return, 10 working days | 24 Sep – 7 Oct |
| Sign-off | Wed 7 Oct |
| Code freeze | Wed 7 Oct |
| **Demo — unsupervised** | **Mon 12 Oct** |
| v4.2b — telemetry and envelope | after sign-off |

**Be honest about what this is.** Submission lands on Wed 23 Sep, which is the
wall exactly. There is no slack in this plan — not one day, anywhere. It also
assumes bench validation halves because the scope halves, which is Chris's
judgement to make, not ours.

**What Plan A costs.**

- **FM-4 is cut.** v4.2a is minimal by construction, so the event envelope ships
  in v4.2b, after sign-off. Buffer-and-reconcile does not make 12 October.
- **a3's measurement stays on the rig permanently.** `axis.halted` is in the
  early split, so per-axis data exists — but there is no time to build a
  controller-side measurement path on top of it.
- **Any slip kills it.** Boards arriving late, bench validation not compressing,
  a5 running long, a single bad smoke test. Each is fatal on its own.

**Fallback if Plan A starts and then slips.** The condition in
`01-delivery-plan.md` still governs: if a5 is not submitted by close of Wed
23 Sep, we switch — and at that point we switch into Plan B's shape, having lost
five weeks of optionality. Which is the argument for deciding in week 1.

---

## Plan B — the split does not work. Two dates, both kept.

| Step | Dates |
|---|---|
| Boards arrive | Tue 1 Sep |
| v4.2 — **full envelope**, no split (3.0w) | 1 – 22 Sep |
| Bench validation (1.0w) | 22 – 29 Sep |
| Deploy to cell + smoke (0.5w) | 29 Sep – 2 Oct |
| Rehearsals | 5 – 9 Oct |
| **Demo — supervised, both features, final firmware** | **Mon 12 Oct** |
| a5 cell re-test (5d) | 13 – 19 Oct |
| Submit to inspector | Mon 19 Oct |
| Inspector return, 10 working days | 20 Oct – 2 Nov |
| **Unsupervised sign-off** | **~Mon 2 Nov** |

The board commitment is kept: both features demo on 12 October, on the firmware
we intend to ship, with nothing faked. What moves is the *certificate*, and it
moves by three weeks to a named date.

**What Plan B buys — and this is the part not to undersell.**

- **FM-4 becomes buildable.** v4.2 carries the full envelope, so buffer-and-
  reconcile is a small piece of work on a cheap buffer rather than a cut story.
- **a3's measurement can move off the rig.** With `axis.halted` and
  `monotonicUs` in firmware, per-axis timing becomes a controller capability
  instead of a permanent manual procedure.
- **The re-test happens once, on the real thing.** No configuration drift
  between what the inspector saw and what runs.
- **Slack exists.** Roughly two weeks of it, against a plan that currently has
  about 10%.

**What Plan B costs.** The customer sees a supervised demo. That is not
cosmetic: the operating model — one supervisor covering several cells — is what
they are buying, and supervision visibly contradicts it. The honest framing is
that they see the machinery working and get a date, with a certificate, for when
it runs unattended.

**If the cell can be shared during week 8**, the re-test could run 5 – 9 Oct
alongside rehearsals and sign-off pulls forward to ~23 Oct. Worth asking; not
assumed here, because rehearsals and a re-test competing for one cell in the
week before a demo is how both go wrong.

---

## The trade-off, stated plainly

| | Plan A | Plan B |
|---|---|---|
| Demo date | 12 Oct | 12 Oct |
| Unsupervised at demo | **Yes** | No |
| Unsupervised sign-off | 7 Oct | ~2 Nov |
| FM-4 buffer and reconcile | **Cut** | **Ships** |
| a3 per-axis measurement | Rig, permanently | Can move to firmware |
| Slack in the plan | **None** | ~2 weeks |
| Re-test on final config | Yes | Yes |
| Fails if | Anything slips at all | Boards slip badly |

**Plan A buys the date and pays with capability.** Plan B buys capability and
slack, and pays three weeks on the certificate.

That is the actual choice, and it is not "fast versus slow." Both demo on
12 October. What differs is whether the customer watches it run unattended, and
whether FM-4 exists this year.

## Recommendation

> **Revised after the B pass** (`06-b-pass-robotics.md`). The original
> recommendation was "take Plan A if the split works." That was made before the
> robotics resources were laid out, and it was wrong in one specific way: Plan A
> also costs Fleet Monitor its integration time.

**Plan B**, unless *both* answers below come back yes.

Plan A's split puts the run-event stream in v4.2b, which by construction ships
after sign-off. The cell therefore emits no real events until ~2 Oct, and Fleet
Monitor's first contact with real cell data is the week of 5 Oct — **one week
before the demo**, on a team whose hardware-integration work historically runs
at 2×.

So Plan A as originally scoped delivers an **unsupervised demo of
under-integrated software**, and the under-integrated half is the feature the
customer came to see. Unsupervised means nobody is standing beside it when it
fails. That combination is worse than either risk on its own, and nobody would
choose it if it were stated out loud — which is the point of stating it.

| Answers | Take |
|---|---|
| Split clean **and** run events fit in v4.2a | **Plan A.** Genuinely good — certificate on 7 Oct and three weeks of real integration. |
| Split clean, run events do **not** fit | **Plan B.** Plan A here buys the certificate and risks the demo. |
| Split not clean | **Plan B.** No choice to make. |

If Plan A is taken, FM-4 is cut in writing during week 1 so nobody spends three
weeks on it.

If Plan B is taken, present it as **two committed dates, not a slip**. The board
committed to a demo on 12 October and that commitment is met in full. What was
never specified in the original ask is that the *certificate* arrives the same
day.

## Three things worth checking before committing

1. **Has the customer been told 12 October, and told it will be unsupervised?**
   Changes what Plan B costs, entirely.
2. **Does the date tie to anything financial** — a contract, a funding
   milestone, a board reporting date? Nothing in the hand-over says so. A board
   commitment with no external dependency is renegotiable in week 1 with
   evidence, and not renegotiable in week 6.
3. **Does the inspector care about firmware version, or only about measured stop
   behaviour?** If the latter, the ordering problem is smaller than it looks and
   the split may not need to be as clean. One phone call.

## What this looks like to the CTO

Not "can we move the date." One line:

> *The 12 October date and "unsupervised" are in tension, and one answer from
> Chris this week decides which we get. Here is what each costs. I need his
> answer by Friday; I will come back to you Monday with one plan, not two.*
