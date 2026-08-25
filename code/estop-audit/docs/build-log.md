# Build log — e-stop audit slice 1 (a2/a3)

Decisions taken during the subagent-driven build, preserved because git
history records what changed and not why it was allowed to ship.

8 tasks, 11 fix rounds, 157 tests. Every `Ruling:` below is a decision made
without asking, with its cost if wrong. Overturn any of them.

# SDD ledger — plan: docs/superpowers/plans/2026-08-25-estop-audit-slice-1.md

Spec: docs/superpowers/specs/2026-08-25-estop-audit-design.md (read; binding authority)
Branch: claude/estop-audit-response-704cc6 (isolated worktree, not main)

## TDD discipline (controller policy for this plan)

Every implementer MUST paste verbatim RED output (test run before implementation,
showing failure) and verbatim GREEN output into its report. The task reviewer is
told a report without RED evidence is not acceptable. Rationale: each task brief
contains both test code and implementation code, so an implementer can otherwise
write both at once and report success without ever proving the test can fail.

## Pre-flight conflict scan

### Cross-task rows (pairs sharing a file or interface)

| Pair | Produced -> consumed | Finding |
|---|---|---|
| T1 -> T2 | Event, GENESIS_HASH, canonical_json, event_key, iso_z, parse_event, parse_ts, sha256_hex | agree |
| T1 -> T3 | Event.ts_resolution_seconds (float) | agree |
| T1 -> T4 | Event, Event.scope, iso_z | agree |
| T1 -> T5 | Event, iso_z | agree |
| T1 -> T7 | MalformedEventError, event_key, parse_event | agree |
| T2 -> T5 | store passed structurally (.append only); records does NOT import store | agree - keeps chain one-way |
| T2 -> T7 | AppendResult.appended, StoredRecord.event, .query, .verify_chain | agree |
| T2 -> T5/T8 | conftest fixtures clock, store_path; tests/conftest.py created in T2 | agree - T1 tests import no fixtures |
| T3 -> T5 | interval_bound().as_dict(), response_time().as_dict() | agree |
| T3 -> T6 | as_dict keys: nominal_seconds, lower/upper_bound_seconds_exclusive, source_resolution_seconds, method, clock_authority, causal_order_established, defensible_claim | agree - all 8 read by report |
| T4 -> T5 | StopSequence.{anchor, episode_events, co_satisfied_with, episode_closed_by, episode_closed_by_event_key, ordering_confidence, notes, outcome, evidence_status}; RunView.run_scope | agree |
| T4 -> T7 | partition_runs, pair_stops | agree |
| T4 -> T8 | classify_pause | agree |
| T5 -> T6 | build_record() dict keys read by render_text | agree - see snake_case row below |
| T5 -> T7 | build_record(seq, run, *, all_runs, amendments), collect_amendments | agree - keyword names match call site |
| T6 -> T7 | render_text(record) | agree |
| T7 -> T8 | EstopAuditService.{ingest_file, stop_records, render, verify_chain} | agree |
| T1 -> T7 | estop_audit/__init__.py created T1, rewritten T7 | agree - sequential, no overlap in staged files |
| T5 -> T6 | _snake() output keys: panelId->panel_id, resumeMode->resume_mode, axesStopped->axes_stopped | agree - report reads panel_id and resume_mode only |

### Per-task self-agreement rows

| Task | Tests specified vs code specified | Finding |
|---|---|---|
| T1 | 17 tests; every symbol asserted is defined in events.py. `event.raw is raw` requires identity preservation - parse_event does not copy | agree |
| T2 | 11 tests; tamper/delete tests depend on verify_chain checking seq, prev_hash, and record_hash - all three implemented | agree |
| T3 | 8 tests; mixed-resolution expectation 1.5005 matches lower=d-max(r_e,h), upper=d+max(r_l,h) | agree |
| T4 | 20 tests; sequence ordering in fan-out and inversion tests matches the emission order of _pair_episode | agree |
| T5 | 13 tests; context window (ts >= anchor within episode_events) yields the asserted pause/resume/interlock entries | agree |
| T6 | 8 tests; every asserted substring is emitted by render_text on the stated branch | agree |
| T7 | 10 tests; content_collisions vs duplicates_skipped split matches ingest_lines control flow | agree |
| T8 | 11 tests; sample yields exactly 1 episode containing a stop (split at 07:19:55 and 07:26:18) | agree |

### Rulings from the scan

Ruling: test fixture lists (SAMPLE_SHAPED in test_records.py, MATCHED in test_report.py)
are near-duplicates and a reviewer may flag the duplication as Minor. They stay
duplicated - each test module must stand alone, and hoisting them to conftest would
couple report tests to record tests and make a change to one silently alter the other.
Cost if wrong: a few lines of duplicated fixture data in two test files.
NOTE: this ruling is NOT passed to reviewers - they are free to raise it and I will
adjudicate in the loop.

Ruling: implementers get the cheapest tier for tasks whose brief contains complete
code (transcription plus testing), escalating on the first report that omits RED
evidence. Cost if wrong: one wasted dispatch and a re-run at a higher tier.

## Progress

Task 1: implemented (commit fbf80fc, 17 passed). RED evidence verified by controller:
  collection-time ModuleNotFoundError for estop_audit.events - the correct failure
  for a module that does not exist yet, not an assertion failure. Review dispatched.
Task 1: complete (commits ae86a88..fbf80fc, review clean - spec OK, quality approved, no findings)

Ruling: the Task 1 reviewer noted the event_key docstring cited firmware-schema
  lines 38-44 for a claim that actually lives at 32-36, and called it non-functional.
  I checked the other six citations rather than accepting that framing: the error was
  systematic (points 1 and 2 transposed; runId-null, overflow-policy and
  pause-taxonomy anchors all wrong). Corrected spec + plan in 62d1ef7 BEFORE
  dispatching Task 2, since Tasks 2, 4, 5 and the README would each have inherited a
  wrong citation. Citations now name the numbered point as well as the line range so
  they degrade gracefully when the source doc is edited.
  Cost if wrong: citations point somewhere slightly off in a doc an inspector may
  follow; no runtime effect.
Ruling: Task 1's shipped docstring still carries the old line numbers. Rather than a
  dedicated dispatch for a one-line comment, I batched the correction into the Task 2
  dispatch (skill sanctions batching small same-shape edits). Cost if wrong: one stale
  citation survives in events.py until the final review catches it.
Task 2: implemented (commits 2bcc745 citation-fix + d0cef8a store; 11 new, 28 total).
  RED evidence verified: collection-time ModuleNotFoundError for estop_audit.store.
  Batched events.py citation correction landed in 2bcc745 as its own commit.
  Review dispatched on the most capable model - this module carries the
  tamper-evidence claim, so chain integrity is worth the reviewer tier.

Task 2 review (opus): spec OK, quality approved, but 1 Critical + 3 Important +
  5 Minor, all against the BRIEF'S DESIGN rather than the implementation. Rulings:

Ruling: Critical "tail truncation verifies clean" - FIX. The reviewer is right and it
  matters more here than in most codebases: dropping the records after an e-stop is
  the likeliest real tampering, and my docstring promised it would be caught. Adding a
  keyed signature was already considered and rejected at design time (no key
  management in slice 1, and the user chose plain hash chain), so the fix is to make
  the limit visible and checkable rather than to close it: ChainVerification now
  reports records + head_hash for comparison against an independently recorded anchor,
  empty/absent files stop returning ok=True, and the docstring/spec/README state the
  limit plainly. Cost if wrong: we ship an honest narrower claim than an inspector
  might want; the alternative was shipping a false broader one.
Ruling: Important "verification unreachable on damaged file" - FIX. An inspector
  handed a corrupt file must get a verdict, not a traceback. _load records the error
  instead of raising; append refuses on a damaged chain; verify_chain always returns.
  Cost if wrong: slightly more code in the load path.
Ruling: Important "docstring overstates what an unkeyed chain proves" - FIX by
  correcting the words, not by adding HMAC. Consistent with the design decision
  already taken. Cost if wrong: none; the narrower claim is the true one.
Ruling: Important "second live instance forks the chain" - FIX with a file-size
  staleness check raising ConcurrentWriterError. Not a lock: it catches the realistic
  in-process mistake, not a determined race, and spec 9 now says so. Cost if wrong:
  a concurrent race could still interleave; single-writer remains an assumption.
Ruling: Minor 5 (broken_at_seq attacker-controlled) and Minor 6 (opening mutates the
  file) - FIX, both one-liners in the same area.
Ruling: Minors 7, 8, 9 (naive-datetime TypeError, hash-before-validate, re-read per
  call) - DEFERRED to the final review. None affects the evidence claim.
Resolved the reviewer's "cannot verify" item myself: ev(..., run=None) sets runId to
  None, parse_event reads it via .get, and Tasks 4 and 5 both rely on exactly that.
  Contract holds; not a gap.
Plan + spec + README corrected in dca9b73; Task 2 brief regenerated. Store tests
  11 -> 19, suite total 28 -> 36, plan grand total 98 -> 106.
Task 2: fix round 1/5 (6 findings addressed per implementer, 0 open; commits
  dca9b73 docs + 5493e0f code; store 19 passed, suite 36 passed). Round-1 RED
  evidence verified by controller: ImportError for AuditStoreError - the new symbols
  did not exist, so the new tests could not have been written after the fix.
  Scoped re-review dispatched (opus - it is verifying a Critical integrity fix).
Task 2: re-review clean - all 6 findings ADDRESSED, no new Critical/Important.
  Two Minor residuals raised:
Ruling: Minor "UnicodeDecodeError/OSError still escape the constructor" - FIX now, not
  defer. It is finding 2's defect one exception class over, and a byte-corrupt
  evidence file is a plausible disk failure; leaving it would mean the fix I just
  shipped only half-works. Folded into 6168bdb with a covering test.
  Cost if wrong: a few lines of exception handling nobody needed.
Ruling: Minor "records/head_hash mean prefix-verified on failure verdicts, whole-file
  on success" - FIX by documenting both meanings on the dataclass. The values are
  genuinely useful on failure; the ambiguity was the defect, not the dual meaning.
  Cost if wrong: none.
Ruling: re-reviewer's TDD caveat (collection-level ImportError does not show which
  assertion each new test would have failed on) - ACCEPTED as sufficient. The symbols
  did not exist, so the tests provably predate the implementation, which is what the
  gate is for. Per-assertion redness would need the tests split across two commits;
  not worth the ceremony. Cost if wrong: slightly weaker evidence for 8 of 20 tests.
Also fixed: plan Task 2 Consumes line omitted parse_ts (doc drift the re-reviewer
  spotted). Added .gitignore - a tool run had left __pycache__ and uv.lock untracked.
  Store tests 19 -> 20, suite 36 -> 37, plan grand total 106 -> 107.
Task 2: complete (commits 62d1ef7..6168bdb, review clean after 1 fix round, 2 minors
  fixed in the same pass, 3 minors deferred to final review: naive-datetime TypeError,
  event_key-before-parse_event, re-read-per-call)
Task 3: implemented (commits 76efea3 batched store fix + 075da58 measurement).
  Four RED/GREEN sections present (one pair per commit); measurement RED is a
  collection-time ModuleNotFoundError. Controller ran the suite independently:
  45 passed.
  DEVIATION NOTED: the implementer went beyond the instructed change in 76efea3,
  switching _raw_lines from text-mode to binary read with per-line decode. It is
  plausibly necessary - text-mode buffering decodes the whole file in one chunk, so
  a UnicodeDecodeError would surface at position 0 and the verified-prefix count
  would be 0 rather than 1 - but it was not asked for, and the new loop contains a
  try/except that catches UnicodeDecodeError only to re-raise it. I did NOT pre-judge
  this for the reviewer; the dispatch points at the deviation and asks for a verdict
  on its merits. Review dispatched (sonnet, with instructions to re-derive the bound
  arithmetic by hand rather than trust the tests).
Task 3 review (sonnet): spec OK. measurement.py APPROVED as-is - reviewer re-derived
  the bound arithmetic by hand and confirmed all four cases including the unclamped
  (-1, 1) for same-second events. Byte-identical transcription verified by diffing the
  brief's code blocks against the commit. One Important finding, in the batched store
  commit rather than Task 3 proper.
Ruling: the implementer's unrequested binary-read redesign of _raw_lines STANDS. The
  reviewer independently reproduced the cause (text-mode iteration decodes in buffered
  chunks and fails the whole read before yielding earlier valid lines), so the narrow
  fix I originally specified could not have satisfied the verified-prefix test. My
  instruction was wrong; the implementer's judgment was better. Plan synced to the
  shipped design in 183ab06 rather than reverting the code.
  Cost if wrong: a slightly unusual read path, now documented in a docstring.
Task 3: fix round 1/5 (1 addressed, 0 open - dead try/except removed, binary-read
  rationale documented; commits 183ab06 docs + b49fa50 code). Controller ran the suite
  independently: 45 passed, byte-corruption test still asserts records == 1.
  Scoped re-review dispatched.
Task 3: re-review clean - finding ADDRESSED, no new breakage. Re-reviewer independently
  reproduced the text-mode buffering claim and confirmed the new docstring is literally
  true, not merely plausible.
Ruling: the re-reviewer's out-of-scope observation - that verify_chain's except tuple
  omits KeyError/AttributeError so a structurally-valid-but-wrong-shape record could
  raise unhandled - is a FALSE POSITIVE, and it contradicts the Task 2 reviewer, which
  had traced the same code and found no KeyError path. I probed it directly rather than
  trusting either: a JSON object missing every field returns
  ok=False "expected seq 0, found None", and a JSON scalar returns ok=False "record is
  not a JSON object". Every field is read via .get() and the one bare subscript is
  reachable only after its .get() comparison succeeded. No change made.
  Cost if wrong: none - a probe, not an argument.
Task 3: complete (commits 6168bdb..b49fa50, review clean after 1 fix round)
Task 4: implemented (commit 5bd9298, 20 new). Controller verified independently:
  65 passed; the required pair_stops rationale docstring landed in full (49 lines,
  all of FIFO/LIFO/refusing-to-pair/co_satisfied_with/run.resumed/"why 30 seconds"/
  inversion present); test_the_inversion_guard is in the suite. RED evidence is a
  collection-time ModuleNotFoundError for estop_audit.sequences.
  Review dispatched (opus) - this is the module that decides safety findings, and its
  failure mode is a confident false record rather than a crash. Reviewer asked to
  verify the docstring is ACCURATE, not merely present, and to judge whether the
  inversion-guard test would genuinely fail against a naive pop(0) implementation.

Task 4 review (opus): spec OK, transcription byte-identical, fan-out and the episode
  boundary both correct and STRUCTURALLY enforced (open_requests is function-local to
  _pair_episode, so cross-episode pairing cannot be reintroduced without deleting the
  split_episodes call). Inversion guard confirmed to genuinely fail a naive pop(0).
  But 1 Critical + 2 Important + 5 Minor. Both headline findings verified by my own
  probe before acting:

Ruling: CRITICAL "same-second tie handled only on the success path" - FIX. Probe
  confirmed: identical events, arrival order swapped, gives matched/ambiguous one way
  and orphan_halt + no_halt_recorded (both "unambiguous", both "complete") the other.
  The wrong answer asserts MORE confidence than the right one, and every downstream
  mitigation is built to miss it. A fast cell makes it likelier, since a sub-second
  response puts both events in one whole second. Fix: pairing now walks timestamp
  GROUPS - every request in a group is admitted before any halt in it is considered,
  and episodes close at group boundaries so a halt sharing a second with its resume is
  not orphaned. Same-second ties now flag ambiguous in both directions.
  Cost if wrong: grouping is slightly more machinery than event-at-a-time iteration.
Ruling: IMPORTANT "the docstring's worked example is refuted by the code" - FIX. Probe
  confirmed: run the example exactly as drawn (no run.resumed between the stops) and
  BOTH requests report matched, the failed one at 6301s. I wrote that example, in the
  spec table as well as the docstring. Added the closing event and stated the caveat
  plainly. Cost if wrong: none; it was simply false.
Ruling: IMPORTANT "no bound or flag on an implausible within-episode delta" - DEFER,
  recorded as spec limitation 8 rather than fixed. Bounding it needs a plausibility
  constant, and inventing one is exactly what the episode-boundary design refused to
  do. It is Chris's call. Cost if wrong: an absurd delta ships unflagged if firmware
  pauses without resuming - now written down instead of implicit.
Ruling: Minors 1-3 (co_satisfied_with excluded by key value not position; notes did not
  name tied events; classify_pause answered for any event type) - FIX, all cheap and
  all in the code being touched anyway.
Ruling: Minor 4 (records not chronological within an episode) - NO CHANGE. service
  .stop_records already sorts by (anchor_ts, record_id). Minor 5 (run_id or "") - NO
  CHANGE, sort-stability only.
Ruling: reviewer noted the report's self-reported line counts were wrong (claimed a
  153-line docstring; actual 49). Code is verbatim-correct, so this is a report
  accuracy lapse, not a defect. No action beyond noting it - I verify counts myself.
Test gaps flagged by the reviewer are all now covered: 9 new tests (20 -> 29), incl.
  the reversed same-second order, the halt/closer tie, N=3 fan-out,
  episode_closed_by_event_key, run_scope, episode_events, request-anchored .anchor,
  and run.completed as a mid-run closer. Suite 65 -> 74, plan total 107 -> 116.
NOTE: commit 76f4df8's message describes both the code and doc fixes, but a failed
  string match meant only the code landed in it; the doc corrections are in c8eadf0.
  Recorded here because the commit message overclaims on its own.
Task 4: fix round 1/5 applied (commit f9cbf8e). Controller verified independently
  rather than trusting the report: 74 passed, 29 collected in test_sequences.py, all
  nine new test functions present by name, and the Critical re-probed directly -
  "request line first", "halt line first", and "halt tied with its episode close" now
  all give matched/ambiguous. The arrival-order dependence is gone.
  NOTE: the implementer's return message claimed "4 new tests" when there are nine;
  its earlier report misstated line counts too. Code correct both times, but its
  self-reported numbers are unreliable - I verify anything numeric myself and told the
  re-reviewer to do the same. Not escalating the model over it: the transcription work
  has been accurate every round, which is what the tier was chosen for.
  Scoped re-review dispatched (opus).
Task 4 re-review round 1 (opus): all 5 original findings ADDRESSED (verified against a
  staged pre-fix copy), corrected docstring confirmed accurate by EXECUTING its worked
  example, all 20 original tests intact (numstat 87 added / 0 deleted). But the fix
  introduced 2 new findings. Both probed and confirmed:
Ruling: NEW CRITICAL (regression) "request tied with its episode closer" - FIX. My
  round-1 doctrine said an event tied with the closer stays in the episode it might
  belong to rather than being orphaned on a tiebreak; I applied it to tied halts and
  not to tied requests. Result: no_halt_recorded + orphan_halt, unambiguous/complete,
  in BOTH arrival orders - grouping froze the wrong branch instead of removing the
  coin flip. Fixed by carrying such a request into the next episode (Episode NamedTuple
  now carries carried_request_keys) with the tie disclosed on whatever outcome results.
  Cost if wrong: a request that truly belonged to the closing episode gets its chance
  to be answered in the next one - flagged ambiguous either way, never silently.
Ruling: NEW IMPORTANT "second halt in a tied group orphaned as unambiguous" - FIX. My
  own requests-first rule manufactured it. Tie-born orphans now flag ambiguous and
  name the tied events; an orphan with no tie stays unambiguous, pinned by a test in
  both directions so nobody blanket-flags every orphan.
Ruling: NEW MINOR "two closers in one group, first by arrival order wins" - DEFER to
  final review. No outcome changes, evidence stays complete; disclosure wobble only.
Ruling: out-of-scope items (bare assert in .anchor stripped under python -O;
  same-second tie comparison ignores ts_resolution_seconds so a sub-second stream with
  0.4s apart literals would read unambiguous) - DEFER to final review. Neither affects
  the whole-second data we actually have.
Task 4: fix round 2/5 (2 addressed, 0 open; commit 417d93f). Controller re-probed all
  eight known tie shapes: every tie now ambiguous, no-tie orphan still unambiguous,
  inversion guard intact. 78 passed. Scoped re-review dispatched.
Task 4 re-review round 2 (opus): both round-2 findings ADDRESSED, but a THIRD
  consecutive same-family Critical - round 2 carried every closer-tied request out
  unconditionally, tearing R+H+C apart and publishing failures where the pre-round-2
  code produced matched. Probed and confirmed (R+R+H+H+C gave TWO fabricated "cell did
  not stop" findings).
Ruling: stop patching shapes, fix the rule. A closer-tied request is carried forward
  ONLY when no motion.halted shares its second. Rounds 1 and 2 each fixed the shape
  they were shown and left its neighbour wrong; the doctrine ("do not let an
  unorderable tie tear apart a pairing the data supports, and do not let one publish a
  failure") was correct all along but never applied in both directions at once.
  Cost if wrong: a request tied with both a halt and the closer stays in the closing
  episode; if it truly belonged to the next one, its delta is measured against a halt
  from the same second either way, so the number is unaffected.
Ruling: Minor "orphan tie scan look-behind and excludes by key value" - FIX. Two
  byte-identical halts share an event_key (Task 1 content-hash identity), so each
  erased the other from the tie set and both claimed unambiguous about a tie they were
  part of. Now a whole-group scan excluding by identity, matching the by-position
  doctrine used for co_satisfied_with three blocks away.
Ruling: Important "a carried request can be answered by a halt arbitrarily far into
  the next episode" - DEFER, folded into spec limitation 8 alongside the existing
  unbounded within-episode delta. Same class, same missing plausibility constant,
  same owner (Chris). Cost if wrong: a large delta ships flagged ambiguous but not
  flagged implausible.
Controller ran an INDEPENDENT exhaustive enumeration this round rather than probing the
  known findings - every multiset over {request, halt, run.resumed, run.completed} of
  size 2-4 at one timestamp, all arrival permutations, crossed with
  with/without a preceding open request and a following halt. Results: 0 shapes where
  the (outcome, confidence) multiset depends on arrival order. 12 shapes where an
  adverse record reports unambiguous while its anchor shares a second with another
  relevant event - analysed each: they are H+closer with no request anywhere (orphan
  either way) and R+R unanswered (no_halt_recorded either way). In both the tie cannot
  change the outcome, so unambiguous is correct and the predicate was over-broad.
Task 4: fix round 3/5 (2 addressed, 0 open; commit ce8ef72). 81 passed.
Task 4 re-review round 3 (opus): both findings ADDRESSED. Its INDEPENDENT enumeration -
  2611 canonical shapes over 1-5 events across up to 3 seconds in every arrival
  permutation, plus 60,000 randomised runs with run.paused added - found 0
  order-dependent outcomes across eight compared record fields, and 0 dropped or
  duplicated requests. It also confirmed all three round-3 tests genuinely fail against
  the pre-fix module, and that plan and source are byte-identical. Round 3 fixed the
  rule, not the shape. One Important remained.
Ruling: I WAS WRONG and reversed myself. I argued a halt tied with its episode closer
  could stay "unambiguous" because the outcome is stable either way. The reviewer
  showed the module already flags ambiguous for outcome-stable ties - the MATCHED path
  discloses this exact halt/closer tie - so my rule was not the module's rule, and the
  effect was that the same physical tie was disclosed when the record read well and
  hidden when it read badly. In a safety audit that asymmetry is the worst direction.
  The orphan record also asserts episode membership (episode_closed_by, episode_events)
  that the tie cannot support. Adopted its sharper test: not "does the tie change the
  outcome" but "is the record's content identical under either ordering". Two
  unanswered requests in one second still read unambiguous under that test, correctly.
  Fixed via a TIE_RELEVANT_TYPES constant that includes the closers, with the reasoning
  attached so nobody trims it back. Cost if wrong: slightly more records carry an
  ambiguity flag than strictly need one.
Ruling: Minor "halts_seen is dead after round 3" - FIX (delete). Minor "105-char
  docstring line" - FIX (rewrap). Minor "carried_in frozenset collapses byte-identical
  carried requests" - NO CHANGE; carried_note tests membership not cardinality, and a
  same-key request necessarily shares the group so it was carried too. Noted so nobody
  starts reading its cardinality.
Task 4: fix round 4/5 (1 addressed, 0 open; commit 2ed6dfb). 82 passed. Controller
  re-ran its own enumeration with a sharper predicate (cross-type tie on the anchor):
  0 records still claiming unambiguous. Scoped re-review dispatched on opus despite the
  small diff - this is the last round before the breaker trips, and the module has
  introduced a new defect in three of four rounds.
Task 4 re-review round 4 (opus): all 3 findings ADDRESSED, no new breakage. Its
  enumeration of 1819 shapes found 0 outcome/content differences vs round 3 - the
  change was purely additive disclosure, all 314 confidence changes tightening, none
  loosening, golden sample byte-identical. But its consistency audit answered "is the
  rule applied everywhere?" with NO: TIE_RELEVANT_TYPES reaches 1 of 3 tie-assessment
  sites. It surfaced 1 Important + 2 Minor under-flags and 1 Minor over-flag, all
  pre-existing, and explicitly left them for adjudication given the round cap.
Ruling: run round 5 (the last) NARROWLY rather than broadly. I prototyped the full
  unified fix - replacing the matched path's pairwise comparisons with a group scan -
  in a scratch copy and ran an order-invariance enumeration against it. My harness
  could not adjudicate it: it does not capture episode_closed_by_event_key, so it
  under-detects content variation, and refining it was becoming its own project. On
  the last round, shipping a broad rewrite of the matched path that I cannot verify is
  exactly the "one more round will converge" trap - and this module has introduced a
  new defect in three of four rounds. So round 5 ships only what I verified in the
  prototype: the Important orphan-inheritance fix and the Minor over-flag narrowing.
  Cost if wrong: two attribution wobbles survive into the final review.
Ruling: PARKED - matched path names one of two tied halts and calls it certain
  (24 shapes). Real, and it contradicts the orphan record in the same run, which does
  disclose the tie. But the measured delta is invariant (both halts share the second),
  so only attribution moves; no outcome and no number changes. Surfaced to the final
  whole-branch review.
Ruling: PARKED - co_satisfied_with can be order-dependent without disclosure
  (27 shapes). Same class, same reasoning: the co-satisfaction list is disclosure, not
  measurement, and no delta or outcome moves.
Task 4: fix round 5/5 dispatched (commit pending). Sequences 37 -> 39, suite 82 -> 84.
Task 4 re-review round 5 (opus): both findings ADDRESSED, no new Critical/Important.
  Regression-probed every Critical from rounds 1-4: all hold. Golden sample byte-
  identical (one matched/unambiguous/complete record, zero notes).
  It MUTATION-TESTED my test reversal: reverting `other is not event` to
  `other.key != event.key` still fails the suite via the new companion test, so the
  guard the deleted test provided moved rather than vanished. It judged the reversal
  reasoned, not loosened, and said so with its own independent argument.
  Two Minor disclosure-only items remain, both declared DEFERRABLE and NOT
  load-bearing by the reviewer:
Ruling: PARKED - the inheritance branch is `elif`, so when an orphan is independently
  tied the "earlier pairing" note is dropped. Confidence is still ambiguous and no
  outcome moves; only the reason given to an inspector is incomplete.
Ruling: PARKED - episode_rests_on_a_tie is a boolean that never resets, so every
  later demand-less orphan inherits when at most one could actually flip. The reviewer
  bounded this precisely and judged over-disclosure the right side to err on versus
  the false-confidence defect it replaced. It is in tension with the signal-dilution
  argument behind the demand_available fix, and it is the same coarseness as the
  already-parked matched-path items: the module models ambiguity as per-record booleans
  rather than asking "could this record differ under an alternative ordering of this
  group". All of these should be adjudicated together as one rewrite at final review,
  not bolted on piecemeal.
  Cost if wrong: some adverse records carry an extra caveat, and one carries a less
  complete explanation. No number and no outcome is affected.
Task 4: complete (commits 5bd9298..9a14f1e, 5 fix rounds, review clean on findings,
  4 parked minors + 5 earlier parked items all routed to the final whole-branch review)
Task 5: implemented (commit cbc070d, 13 new, 97 total). Controller verified
  independently: RED is a collection-time ModuleNotFoundError for estop_audit.records;
  records.py contains zero imports of store (dependency chain stays one-way); and an
  end-to-end probe confirms the honesty chain survives all three modules - a
  same-second tie yields confidence.ordering "ambiguous", its note carried through,
  per_axis "unavailable_from_source", and a defensible_claim of "stop response not
  established: the two events lie within 1 s of one another..." rather than a
  fabricated 0 s. Review dispatched (sonnet) with the ambiguity-survival property as
  its first check: five rounds of Task 4 work become invisible if this module drops or
  rewords a note.
Task 5 review (sonnet): spec OK, quality APPROVED. Byte-for-byte verbatim confirmed by
  diff. All seven properties traced in code: ambiguity copied verbatim into
  confidence.{ordering,notes}; append-only holds (attach_per_axis_measurement only ever
  calls store.append, and the amendment carries source/attested_by/ts while the store
  stamps ingested_at independently, so "when measured" and "when logged" are both
  recoverable); per_axis never overclaims; no hand-built numbers (grep found only the
  version string); classify_pause reachable only from a run.paused-filtered branch;
  cross-run halts context-only; record_id namespaced so req/halt records cannot collide.
Ruling: IMPORTANT "no test exercises the ambiguity pass-through through build_record"
  - FIX, and it is my defect not the implementer's: every fixture in the brief's test
  list uses distinct seconds, so ordering_confidence is "unambiguous" in all 13 tests.
  I had told the reviewer to check that property FIRST and it verified the code is
  right - but a probe is not a regression guard, and this is the exact seam where five
  rounds of Task 4 work could be silently discarded by something that looks like
  formatting. Two tests added to the plan (d284518) and batched into the Task 6
  dispatch rather than spending a full round-trip on one test file. Task 6's reviewer
  will verify them.
  Cost if wrong: one extra commit in Task 6's range.
Ruling: MINOR "per_axis.reason never asserted" - FIX, batched with the above.
Ruling: MINOR "_MAX_CROSS_RUN_CANDIDATES cap and sort order untested" - DEFER to final
  review. Cross-run surfacing is context-only, flagged not_counted_as_evidence, and
  cannot influence an outcome or a measurement.
Task 5: complete (commit cbc070d, review clean, 2 tests batched forward into Task 6)
Task 6: dispatched (report.py, 8 tests + the 2 batched records tests). Suite 97 -> 107.
Task 7: complete (commit c7a8aed, review clean - no Critical/Important). Reviewer
  confirmed the duplicate-vs-collision tests would fail if the counters were swapped,
  in both directions. Two Minors DEFERRED (no blank+malformed interaction test; the
  a2 retrieval test asserts a count only) - both inherited from my brief's test list,
  neither blocks Task 8.
Task 6 review (sonnet): spec FAIL, 1 Critical + 4 Important.
Ruling: CRITICAL "orphan_halt renders a false, self-contradicting page" - FIX.
  Probed and confirmed: an orphan halt printed "the cell is not evidenced to have
  stopped" while the same page showed the halt under CONTEXT. _response_time_block
  branched on evidence_status alone, and an orphan_halt is structurally identical to a
  genuine failure (response_time None, evidence complete) but semantically its
  opposite. This is the exact harm the renderer exists to prevent, for an outcome the
  brief's property list never named. Now branches on outcome first.
  Cost if wrong: none - the previous text was simply false.
Ruling: IMPORTANT "page ignores its own WIDTH=78" - FIX by wrapping under a hanging
  indent, never truncating. Real page had lines of 123/155/128 chars.
Ruling: IMPORTANT two near-vacuous tests - FIX. test_no_page_ever_contains_a_bare_
  nominal asserted "nominal" appears whenever "Measured" does, which the template
  guarantees by construction; the pause test asserted only "SAFETY" so a hardcoded
  label would pass. Both replaced with tests that can fail.
Ruling: my own brief was internally inconsistent - the reviewer proved the phrase
  "not evidenced to have stopped" is NOT contiguous in the brief's string literals,
  so a verbatim transcription would have failed the brief's own test. The implementer
  caught it, fixed it and disclosed it. Plan corrected to match what shipped; the
  implementer was right to deviate.
Ruling: my fix brief said 12 report tests; correct answer is 11 (2 of the changes were
  replacements, not additions). Implementer's count was right, mine was wrong.
  Corrected in the plan. Cost if wrong: none.
Task 6: fix round 1/5 (all addressed per implementer; commit a4a40ca). Controller
  verified: orphan page no longer claims a failure to stop, real page has zero lines
  over 78, old tautological test gone, all 5 specified tests present, 120 passed.
Task 6 re-review (sonnet): all 5 findings ADDRESSED, no new Critical/Important. It
  verified the orphan wording independently, confirmed the other two evidence_status
  branches were not softened while fixing it, checked wrapping preserves full text on
  both the real per-axis fields and a synthetic 172-char value, and confirmed each new
  test would fail against the pre-fix module.
Ruling: MINOR "textwrap break_long_words could split a 64-hex identifier" - FIX now,
  batched into the Task 8 dispatch. Not reachable today (closest value is 75 of 76
  columns) but this is an evidence document, and a hash broken across a line reads as
  corruption rather than as a wrap. break_long_words=False makes an over-long token
  overflow instead, with a test pinning it. Cost if wrong: one line may exceed 78 in
  a future record carrying a longer identifier - visible, not misleading.
Correction to my own dispatch: I described commit c7a8aed as a controller doc commit
  when it was Task 7's implementation. The reviewer caught it. No impact on its
  verdict (c7a8aed touches report.py only via a one-line pass-through) but the
  framing was wrong and is recorded as such.
Task 6: complete (commits a64976a..3f509f8, 1 fix round, review clean, 1 minor fixed
  forward into Task 8)

FINAL WHOLE-BRANCH REVIEW (opus, code-only package - docs/ excluded so the reviewer
  read code rather than 7000 lines of my own design prose):
  Verdict was WOULD NOT MERGE. 2 Critical, 7 Important, 11 Minor.
Ruling: CRITICAL 1 "non-string cellId accepted, chained, then kills stop_records for
  the whole store" - FIX. Probed and confirmed exactly as described: appended=2,
  malformed=[], verify_chain ok=True, then TypeError: unhashable type: 'dict'. Nine
  review rounds missed it because it lives in the SEAM between events.parse_event and
  sequences.partition_runs, and every per-task reviewer worked inside one module. It
  also contradicted the spec's own "one bad line must not cost the surrounding safety
  evidence". Fixed with type validation at parse time.
Ruling: CRITICAL 2 "README overclaims and omits same-second ordering ambiguity" - FIX.
  The service exists to avoid overclaiming and its own README claimed every received
  event was persisted (malformed lines and content collisions are dropped, counted only
  in an in-memory IngestReport) while omitting the largest limitation in the branch.
  Fixed: bullet qualified, five limitation bullets added, store.py docstring caveated.
Ruling: REVERSING MY OWN EARLIER RULING - P7 "two closers in one group". I had parked
  it as "no outcome changes, disclosure wobble only". That was factually wrong and the
  reviewer proved it: episode.closed_by IS record content, it is printed on the
  inspector's page, and two ingests of the same events in different arrival order
  produce the SAME record_id with DIFFERENT content and no flag - worse than a
  differing record because it is undetectable as a difference. Fixed.
Ruling: IMPORTANT "cross-run candidates silently truncated at 3" - FIX. I had deferred
  this as a test gap; the reviewer correctly reclassified it as a behaviour defect. A
  slice whose premise is "surface the near-miss without using it" must not withhold
  part of the near-miss silently.
Ruling: IMPORTANT "per-axis amendment figures render naked" - FIX by narrowing the
  docstring claim and stating on the page that supplied figures carry no bound this
  service computes. Not by inventing a bound the amendment schema does not carry.
Ruling: reviewer's correction to MY FRAMING of the parked tied-halts cluster is
  ACCEPTED. I wrote "only attribution moves; no outcome and no number changes".
  axes_stopped moves, and in a robotics safety audit which axes are recorded as having
  stopped is the payload, not attribution. Re-filed below in those words so it is not
  groomed away.
Ruling: DEFERRED to follow-up, reviewer agreed none are merge-blocking - the four-item
  ambiguity cluster (matched path assesses ties pairwise not by group scan; needs a
  rewrite with "does this record's content differ under an alternative ordering of its
  group" as the predicate at all three tie sites); I5 integrity footer on the rendered
  page carrying verify_chain's verdict, records and head_hash; I7 query/__iter__ raise
  on a damaged file where verify_chain returns a verdict; and the remaining minors.

FIX-WAVE RE-REVIEW (opus): all 8 findings ADDRESSED, no new breakage. It extracted the
  pre-fix tree and ran the 18 new tests against it: 15 fail correctly, 3 pass (2 are
  deliberate counterexamples, 1 was a genuinely inert test). Two items left open.
Ruling: ADJUDICATION beyond the prescribed single fix wave. The re-review found the
  CRITICAL 1 defect class survives through run.paused's `reason` - reached as a dict
  key in classify_pause, on the primary e-stop path, same store-wide unrepairable
  outcome. I swept the class myself and found a THIRD site (collect_amendments uses
  recordId as a dict key) plus a narrower one (report joins axesStopped). The process
  says one wave then adjudicate; I ruled this load-bearing and fixed it, because
  handing over a deliverable that one malformed field permanently disables - in a file
  the design forbids repairing - with only a note attached would be the wrong call.
  Guarded at point of use rather than in parse_event: envelope fields have fixed types,
  payload fields are open by design, and rejecting a whole event over one bad field
  discards real safety evidence. A structured pause reason now reads "unclassified",
  which is the correct answer under the module's own rule, not a workaround.
  Cost if wrong: three guards that degrade to established defaults.
Ruling: the fix wave shipped one INERT regression test (asserted a substring that
  _field wraps, so it passed against the broken implementation). Repaired, and verified
  by un-guarding the code and watching it fail. Recorded because an inert test counted
  as coverage is worse than a missing one.
Ruling: DEFERRED, reviewer-agreed non-blocking - README's two completeness bullets read
  as near-duplicates; the plausibility bullet omits the carried-request half of spec
  limitation 8; tied_closer_keys frozenset can print "tied between 1 closing events"
  when reached directly (unreachable via the service, which dedupes); the per-axis
  no-bound sentence breaks the label column alignment.
FINAL: 157 tests passing. Golden sample unchanged throughout.
