# EOD response to the CTO

**Channel:** #software-leadership · reply to CTO, Mon 09:14
**Sent:** Mon 18 Aug, week 1
**Purpose:** answers the question actually asked — *"what's landing when, who's
on what, anything at risk."*

> **Note on what is deliberately absent.** The estimation calibration
> (`05-estimation-calibration.md`) is not in this message. Telling the CTO in
> week 1 that his engineers estimate 40–120% light is true, will get back to
> Alex and Jo, and buys a fight before the standing to win it exists. It belongs
> in the delivery plan as the reasoning behind the cuts, not in a Slack message
> that might get forwarded.

---

Morning — plan as promised.

Short version: both features demo on 12 Oct. What's actually at risk isn't the
features, it's *unsupervised*.

**The site inspection is the critical path.** The chain is a2 → a3 → a5 →
inspector, and the inspector is a 10-working-day external lead time. That's 24
working days of pure sequence with no slack. If we don't submit to the inspector
by **Fri 19 Sep**, the cell isn't signed off for unsupervised running by the
12th. It fits, but only if a2 starts today — so I've started it.

**One question could still break it.** Does deploying firmware v4.2 to the cell
*after* the re-test invalidate the re-test? Nobody's asked. If yes, re-test slips
to week 7, sign-off lands week 9, and unsupervised is gone. Asking Chris today,
will come back to you either way.

**Who's on what**
• Me — e-stop logging + stop response time (a2/a3). a3 had no owner, so I've
taken it. Also writing the v4.2 event schema contract, which is the missing
piece behind three separate blockers.
• Alex — panel diff + impact/cost classification
• Sam — revision review screen + fleet dashboard. Need a breakdown from him and
updated mocks from Robin first.
• Jo — telemetry, gated on the schema contract landing before boards arrive wk 3.

**What I'm cutting**
• Build model migration cutover → Q4. Jo's away wks 4–5; 3 weeks of work doesn't
fit in 2.8 weeks of capacity. Replacing it with a read-only adapter so nothing
else is blocked.
• Indirect-effects logic as designed. On real data it flags 13 of 20 panels —
worse than the status quo it's meant to fix. Replacing with a targeted
consistency check.
• Operator sign-in (a4). Doesn't block unsupervised, and we may already emit the
data.

**What I've added:** cost classification before approval. On the r3→r4 build,
4 panels genuinely need re-making and 2 just need re-queueing at zero cost. That
gap is where the £430/build actually is — the current stories would show all 6
as equally "affected."

**One decision I need from you, by end of week 2:** we have one cell. A fleet
monitor showing one tile is a thin demo of a fifty-cell operating model. Either
we show simulated cells clearly labelled as simulated, or we reframe it as "cell
monitor, built to scale." I don't want to fake it quietly — that costs more if
the customer notices.

**Fallback if the chain slips:** supervised demo, someone beside the cell,
everything else unchanged. Trigger is a condition, not a date — see
`01-delivery-plan.md`. Flagging it now rather than in week six.

---

## Why this framing and not another

The CTO asked three things in a specific order. The reply answers them in that
order rather than reordering his question to make a point. The critical-path
finding still lands in the second paragraph; it does not need the opening slot,
and taking it costs goodwill on day one.

"I've started it" is a claim about day one, and it has to be true. a2 genuinely
must start immediately — see the critical path — which is why it is build
slice 1.
