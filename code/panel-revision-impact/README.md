# Panel revision impact and cost classification

Given two revisions of the same build, this library reports which prefabricated
panels a design change genuinely affects, what to do about each, and what it
costs — **before** the production manager approves a re-issue.

```ts
import { classifyRevision, reissueQueue } from './src/index.js';

const impact = classifyRevision(buildR3, buildR4);

impact.cost.formatted;    // '£720.00'
impact.approval.blocked;  // true — EW-L1-N1 is installed
reissueQueue(impact);     // { approved: false, blockedBy: [...] }
```

```
npm install
npm run demo       # human-readable report on build-r3.json -> build-r4.json
npm run demo:json  # the same result as a serialisable change record
npm test           # vitest
npm run type-check
```

Node 20+. No framework, no UI, no persistence.

`demo.ts` is a thin script over the library, not part of it — it reads the two
revisions and prints what `classifyRevision` returns. It takes an optional pair
of file paths, so any two revisions can be compared:

```
npx vite-node demo.ts build-r3.json build-r4.json
```

---

## Why classification excludes adjacency

The obvious way to answer "what does this change affect?" is to follow the
building: this wall moved, so the panels touching it are affected, and the
panels touching those. On the r3→r4 fixture that approach flags **thirteen of
twenty panels**. The production manager is then in exactly the position she is
in today — holding a list too long to trust, re-making more than she needs.

Adjacency answers the wrong question. What a panel costs depends on **how far
through manufacture it already is**, not on where it sits in the building. A
planned panel costs nothing to change no matter how many neighbours it has. An
installed one is a site visit whether it is in the middle of a wall or on the
end. So the class is a function of `(changeKind, status)` and nothing else, and
the result is seven panels rather than thirteen — each one genuinely requiring a
decision.

This is enforced structurally, not by convention. `classify.ts` imports no
geometry, no zone, no level, and no other panel. It is handed two scalars. There
is no adjacency to consult because none is in scope.

**Adjacency is not useless — it is a different question.** "Which panels are now
geometrically inconsistent?" is real and valuable, and it is answered separately
in `src/should/stacking.ts`. Keeping the two apart is deliberate: a knock-on
geometric defect should never quietly become a line on an invoice.

### The classification matrix

|              | `planned` | `manufactured` | `in_transit` | `installed` |
|--------------|-----------|----------------|--------------|-------------|
| `unchanged`  | no_action | no_action      | no_action    | no_action   |
| `modified`   | requeue   | remake         | recall       | **escalate**|
| `added`      | requeue   | remake         | recall       | **escalate**|
| `removed`    | no_action | **escalate**   | **escalate** | **escalate**|

`added` shares the `modified` row: a panel new to this revision is work the
factory has not been told about, which is the same situation as a panel whose
spec moved.

`removed` is its own row, and this is an interpretation rather than something
the brief specified. There is nothing to re-issue for a deleted panel, so the
question becomes whether material has been committed. If none has, deleting a
`planned` panel costs nothing and needs nobody — `no_action`. If some has, a
physical panel exists that nobody wants, and its disposition (scrap, re-use,
credit) is a human decision with a cost this tool cannot know — `escalate`.

## Installed panels cannot be auto-re-issued

This is the safety criterion, and it is enforced in two independent ways that
are both compile-time, not runtime flags anyone can ignore.

**1. There is no field to read.** `Classification` is a discriminated union in
which the `escalate` variant has no `reissue` member. Reading a re-issue action
requires narrowing away from `escalate` first, and `classifyPanel` returns
`escalate` for every `installed` panel regardless of change kind.

```
error TS2339: Property 'reissue' does not exist on type 'Classification'.
```

**2. There is no list to iterate.** `reissueQueue()` is the only way to obtain
instructions, and while any panel escalates it returns
`{ approved: false, blockedBy }` — not an empty array, not a filtered array.
A partial re-issue cannot be started and then regretted.

`RevisionImpact.approval` is likewise derived from the presence of escalations.
There is no settable boolean.

## What the cost model assumes

**Money is integer pence.** £180 is `18000`. No floating-point arithmetic
touches a monetary value anywhere, including formatting.

| Class      | Cost           | Reads |
|------------|----------------|-------|
| `no_action`| £0             | — |
| `requeue`  | £0             | — |
| `remake`   | £180 flat      | — |
| `recall`   | £180 + logistics (**unknown**) | `weightKg` |
| `escalate` | no automatic cost | — |

Assumptions, stated so they can be challenged:

- **£180 is flat per re-made panel**, independent of size, type and complexity.
  A 6m roof panel and a 1.8m internal wall cost the same to re-make. This is the
  figure the business already uses; it is almost certainly an average.
- **Recall logistics is unknown and is not guessed.** It is modelled as an
  explicit `unknowns` entry, and any total containing one reports
  `complete: false`. A recall's true cost is £180 *plus something*, and the
  output says so rather than quietly implying the something is zero.
- **Escalation has no automatic cost.** Not "£0" — no automatic cost. The figure
  exists but only an engineer can produce it.
- **Removed panels are never charged.** Nothing was re-made.

### Suspect data is a data-quality signal, not a cost adjustment

A panel whose geometry changed but whose derived fields did not has been
hand-edited, and its downstream figures are wrong. It is flagged in
`impact.suspectData` and on the panel itself.

It is **excluded from the cost total only when the suspect field feeds that
panel's own cost calculation.** Each cost rule declares the panel fields its
price reads, and exclusion is the intersection of the panel's suspect fields
with its class's declared dependencies:

- `remake` is flat £180 and reads nothing, so a stale `weightKg` cannot affect
  it. The record is untrustworthy; the cost is not. The panel still contributes.
- `recall` reads `weightKg`, because logistics may scale with weight. A stale
  weight there does corrupt the figure, so the panel is withheld and the total
  reports itself incomplete.

On the fixtures this matters concretely: `IW-L1-01` has a stale `weightKg` and
classes `remake`. Excluding it would report **£540 against a true £720** — an
understatement at exactly the moment the tool exists to prevent one. It carries
the flag and contributes its £180.

No panel id and no class name appears in the exclusion test; the rule is
derived.

### Detecting a stale derived field

The naive rule — "geometry changed but `weightKg` did not" — is wrong on this
data. Three of the seven changed panels only move an opening sideways, and a
window at a different `x` uses the same timber and weighs the same.

So the comparison is against **material quantity**: face area less opening area,
plus span. Opening *position* is not part of it; opening *size* is. All integer
mm and mm². On the fixtures this flags exactly one panel, correctly.

## The `Should` — geometric consistency check

`src/should/stacking.ts`. Flags an *unchanged* panel no longer consistent with a
*changed* one: a wall on level N that no longer stacks on the walls of level N-1
beneath it.

On the fixtures, `EW-L1-W1` narrowed 4800→4200 while `EW-L2-W1` stayed at 4800.
One flag, and it is real. Adjacency would have buried it among thirteen.

It is **structurally separable**: it imports nothing from `classify`, `cost`,
`diff` or `suspect`; it is not re-exported from `index.ts`; and its findings
never enter `RevisionImpact` or the cost total. Deleting the `should/` directory
removes the feature and breaks nothing else.

The check reports `introduced` violations separately from `preExisting` ones. A
design that was already odd in r3 is not this revision's problem.

## Limits — what this cannot tell you

Worth knowing before the output is attached to a change record.

- **Panels have no origin coordinate.** The schema carries `width` but no `x`,
  so the stacking check lays walls end-to-end from zero in `panelId` order. That
  is a documented modelling assumption, not a fact derived from the data. It is
  deterministic, which is what makes the result diffable. Real panel origins
  would make it authoritative.
- **A wrong derived value is undetectable.** There is no density model, so the
  library can tell that `weightKg` *did not move when it should have*, but not
  that it moved *to the wrong number*.
- **The exclusion path is specified but unobserved.** No panel in r3→r4 changes
  while `in_transit`, so no panel classes `recall`, so the AC6 exclusion never
  fires on the real fixtures. It is covered by synthetic tests instead.
- **Removed-panel handling is an interpretation**, as described above.
- **Recall logistics is genuinely open** and blocks a complete figure for any
  recall.

## Output shape

`RevisionImpact` is a plain object of scalars, arrays and string literals —
`JSON.stringify`-able, byte-stable across runs, with panels sorted by `panelId`.
Called twice on the same inputs it produces identical bytes, so it can be
attached to a change record and diffed against the next one.

The function is pure: it reads no clock, no filesystem and no global state, and
mutates neither argument.

## Layout

```
src/
  model.ts               types; re-exports the canonical build.interface.ts unchanged
  diff.ts                set-based panel diff, revision-gap agnostic
  classify.ts            the (changeKind, status) matrix — no geometry in scope
  suspect.ts             material-quantity comparison for stale derived fields
  cost.ts                cost rules, field dependencies, totalling
  classifyRevision.ts    orchestration, approval gate, reissueQueue
  should/stacking.ts     Should — independent, deletable
tests/                   66 tests
```

### On `previousSpec`

The build-model types in `src/model.ts` are re-exported from the repository's
canonical `build.interface.ts`, **unmodified**. No field was added to `Panel`,
in particular no `previousSpec`, because the previous revision is a *parameter*
of `classifyRevision`, not state carried on a panel.

Two consequences fall out for free. Diffing revisions more than one step apart
is the same code path as adjacent ones — nothing counts steps. And a panel
cannot hold a stale copy of its own history, because it holds none.
