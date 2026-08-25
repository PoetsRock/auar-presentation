# Critical path — Plan A, with the Plan B tail

Source: [`diagrams/critical-path.mmd`](diagrams/critical-path.mmd)

GitHub renders the block below directly. To regenerate elsewhere:
`npx @mermaid-js/mermaid-cli -i deliverables/diagrams/critical-path.mmd -o critical-path.svg`

---

```mermaid
gantt
    title Plan A - two chains converge on the cell re-test (Plan B tail at bottom)
    dateFormat YYYY-MM-DD
    axisFormat %-d %b
    excludes weekends

    section Software chain
    a2 E-stop logging - Lead 4d           :crit, a2, 2026-08-18, 2026-08-26
    a3 Stop response - Lead + rig 5d      :crit, a3, 2026-08-27, 2026-09-03
    Float - 9 working days of reserve     :active, fl, 2026-09-04, 2026-09-15

    section Firmware chain BINDING
    Boards arrive                         :milestone, b0, 2026-09-01, 0d
    v4.2a stop path only - 1.0w           :crit, f1, 2026-09-01, 2026-09-07
    Bench validation reduced - 0.5w       :crit, f2, 2026-09-08, 2026-09-10
    Deploy to cell + smoke - 0.5w         :crit, f3, 2026-09-11, 2026-09-15

    section The gate
    a5 Cell re-test on final config - 5d  :crit, a5, 2026-09-16, 2026-09-22
    SUBMIT - THE WALL Wed 23 Sep          :crit, w1, 2026-09-23, 1d
    a7 Inspector return - EXTERNAL 10wd   :crit, a7, 2026-09-24, 2026-10-07
    Sign-off Wed 7 Oct                    :milestone, sg, 2026-10-07, 0d

    section Panel Revisions
    Diff + classification - slice 2       :done, p1, 2026-08-18, 2026-08-24
    Integration - Alex                    :p2, 2026-08-25, 2026-09-18
    Review screen - Sam                   :p3, 2026-08-25, 2026-09-11
    PR-7 consistency - CUT LINE           :p4, 2026-09-07, 2026-09-18

    section Fleet Monitor
    Telemetry vs schema contract - Jo     :m1, 2026-08-18, 2026-09-07
    Dashboard + stop wait state - Sam     :m2, 2026-09-14, 2026-09-28
    v4.2b telemetry - after sign-off      :m3, 2026-09-29, 2026-10-09

    section Calendar and demo
    Jo away                               :done, c1, 2026-09-08, 2026-09-21
    Offsite Thu-Fri                       :done, c2, 2026-09-24, 2026-09-25
    Rehearsals                            :r1, 2026-09-29, 2026-10-09
    Code freeze Wed 7 Oct                 :crit, g4, 2026-10-07, 1d
    DEMO unsupervised Mon 12 Oct          :crit, g5, 2026-10-12, 1d

    section If split fails PLAN B
    v4.2 full envelope - no split         :pb1, 2026-09-01, 2026-09-22
    Bench validation 1.0w                 :pb2, 2026-09-23, 2026-09-29
    Deploy to cell                        :pb3, 2026-09-30, 2026-10-02
    DEMO supervised Mon 12 Oct            :pb4, 2026-10-12, 1d
    a5 Cell re-test 5d                    :pb5, 2026-10-13, 2026-10-19
    a7 Inspector - EXTERNAL 10wd          :pb6, 2026-10-20, 2026-11-02
    Unsupervised sign-off Mon 2 Nov       :milestone, pb7, 2026-11-02, 0d
```

---

## How to read it

**Two chains, one gate.** The software chain (a2 → a3) and the firmware chain
(boards → v4.2a → bench → deploy) run independently and both feed the cell
re-test. Neither was traced end to end in the hand-over.

**The firmware chain is binding.** It clears 15 Sep; the software chain clears
3 Sep. The nine working days between them are drawn as float, and that float is
the plan's only reserve on this path. It is not spare capacity to fill.

**The wall.** `SUBMIT` sits on Wed 23 Sep. The arithmetic deadline is Fri 25 Sep
— ten working days back from Fri 9 Oct — but Thu 24 and Fri 25 are the week-6
offsite, so the last day anyone can actually submit is the Wednesday. Plan A has
**no slack** between a5 finishing and the wall.

**The offsite falls inside the inspector window.** Harmless, because a7 is
external work. It is drawn because it is the reason the wall moved.

**Plan B is not a delay.** It starts from the same boards date and differs only
in ordering: firmware runs whole instead of split, so the re-test happens after
the demo rather than before it. Both plans demo on 12 October. What moves is the
certificate — from 7 Oct to ~2 Nov.

## What this diagram does not show

- **Robotics resource contention.** One spare controller, one live cell, Chris
  at 0.8 FTE. Bench validation (8–10 Sep) and a5 (16–22 Sep) do not collide on
  these dates, but Plan B's bench (23–29 Sep) sits closer to other cell work.
  This needs a proper robotics swimlane before it can be relied on.
- **FM-4.** Cut under Plan A — the envelope ships in v4.2b, after sign-off.
  Buildable under Plan B. Its absence from Plan A's rows is the point.
- **The two-clocks contrast.** An earlier version put features and permission
  side by side as two tracks, which made the asymmetry more legible. Six sections
  cost that. If a presentation opener is wanted, a stripped four-bar version —
  features vs permission, Plan A vs Plan B — belongs in a separate frame.

## Calendar note

Weeks run Tue → Mon in 2026. The hand-over's day-names are wrong for 2026; its
dates are right. Bank holiday is Mon 31 Aug, inside week 2. Demo is Mon 12 Oct.
See the note at the top of `01-delivery-plan.md`.
