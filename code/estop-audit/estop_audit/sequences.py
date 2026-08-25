"""Partition the event stream into runs, split runs into stop episodes, and pair
each stop request with the halt that answered it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, NamedTuple

from .events import Event, iso_z

PAUSE_CLASSIFICATION: dict[str, str] = {
    "estop": "safety",
    "material_reload": "operational",
}
"""``run.paused`` is overloaded: one event type carries both a safety stop and a
routine material reload. An inspector's audit log must distinguish them
(docs/firmware-event-schema-v4.2.md lines 51-54, point 5 'run.paused is overloaded').

Adding a firmware reason is a one-line change here. Anything absent from this
table is ``unclassified`` -- never ``operational``. An unrecognised pause reason
is a question for a human; quietly filing it as routine is precisely the failure
inspection action a2 exists to prevent.
"""

EPISODE_CLOSING_TYPES: tuple[str, ...] = ("run.resumed", "run.completed")

TIE_RELEVANT_TYPES: tuple[str, ...] = (
    "stop.requested",
    "motion.halted",
) + EPISODE_CLOSING_TYPES
"""Event types whose presence in a timestamp group makes another event's record
rest on a tie. Closers count: a halt tied with the ``run.resumed`` that ended its
episode has its episode membership asserted by the record (``episode_closed_by``,
``episode_events``) on evidence the timestamps cannot supply."""


def classify_pause(event: Event) -> str:
    """Safety vs routine for a ``run.paused`` event.

    Exposed at module level, not buried inside record assembly, so the mapping
    can be tested directly against a pause that belongs to no stop sequence --
    which is exactly what the sample's ``material_reload`` pause is.

    Raises on any other event type. Answering silently for, say, a ``run.resumed``
    that happened to carry a ``reason`` field would classify it as a safety event.

    ``reason`` is a payload field and is deliberately not type-checked by
    ``parse_event`` -- rejecting the whole event over one malformed field would
    discard genuine safety evidence. But a dict or list ``reason`` cannot be
    looked up in ``PAUSE_CLASSIFICATION`` (dicts and lists are unhashable), and
    this function is the point of use, so it guards here rather than upstream.
    The guard is also exactly right on the merits, not just defensive: this
    module's rule is that an unrecognised pause reason is a question for a
    human and must never be filed as routine, and a structured ``reason`` is
    the most unrecognised a reason can be.
    """
    if event.type != "run.paused":
        raise ValueError(
            f"classify_pause expects a run.paused event, got {event.type!r}"
        )
    reason = event.raw.get("reason")
    if not isinstance(reason, str):
        return "unclassified"
    return PAUSE_CLASSIFICATION.get(reason, "unclassified")


@dataclass(frozen=True)
class RunView:
    """One ``(cell_id, run_id)`` partition, sorted into analysis order."""

    scope: tuple[str, str | None]
    cell_id: str
    run_id: str | None
    events: tuple[Event, ...]
    completed: bool
    truncated: bool

    @property
    def run_scope(self) -> str:
        return "in_run" if self.run_id is not None else "outside_run"


@dataclass(frozen=True)
class StopSequence:
    """One stop demand and whatever answered it, or failed to."""

    request: Event | None            # None only for an orphan halt
    halt: Event | None               # None for an unmatched request
    outcome: str                     # matched | no_halt_recorded | orphan_halt
    evidence_status: str             # complete | truncated
    co_satisfied_with: tuple[str, ...]
    episode_closed_by: str           # run.resumed | run.completed | stream_end
    episode_closed_by_event_key: str | None
    ordering_confidence: str         # unambiguous | ambiguous
    notes: tuple[str, ...]
    episode_events: tuple[Event, ...] = field(default=(), compare=False, repr=False)

    @property
    def anchor(self) -> Event:
        """The event a record is filed under: the request, or the orphan halt."""
        anchor = self.request or self.halt
        assert anchor is not None, "a stop sequence must have a request or a halt"
        return anchor


def partition_runs(events: Iterable[Event]) -> list[RunView]:
    """Group events by ``(cell_id, run_id)`` and sort each group into analysis order.

    The partition key is the **pair**, not ``run_id`` alone. ``runId`` may legitimately
    be null (docs/firmware-event-schema-v4.2.md line 70, "null for events outside a
    run"); keying on it alone would collect every out-of-run event, across all cells and
    all time, into a single bucket -- reintroducing unbounded pairing lookahead through
    the back door.

    Sorting is stable on ``(ts, arrival_ordinal)``: whole-second timestamps make
    same-second events unorderable, so arrival order breaks the tie and any pairing that
    depends on such a tie is flagged downstream rather than silently trusted.
    """
    numbered: dict[tuple[str, str | None], list[tuple[int, Event]]] = {}
    for ordinal, event in enumerate(events):
        numbered.setdefault(event.scope, []).append((ordinal, event))

    runs = []
    for scope, items in numbered.items():
        items.sort(key=lambda pair: (pair[1].ts, pair[0]))
        ordered = tuple(event for _, event in items)
        completed = any(event.type == "run.completed" for event in ordered)
        runs.append(
            RunView(
                scope=scope,
                cell_id=scope[0],
                run_id=scope[1],
                events=ordered,
                completed=completed,
                truncated=not completed,
            )
        )
    runs.sort(key=lambda run: (run.cell_id, run.run_id or ""))
    return runs


def _group_by_ts(events: Iterable[Event]) -> list[tuple[datetime, list[Event]]]:
    """Group consecutive events that share a timestamp.

    Whole-second timestamps make events within one second unorderable, so the
    order they happen to arrive in must never decide an outcome. Grouping is how
    that rule is enforced rather than merely intended: everything in a group is
    treated as simultaneous, and the analysis sort has already placed groups in
    timestamp order.
    """
    groups: list[tuple[datetime, list[Event]]] = []
    for event in events:
        if groups and groups[-1][0] == event.ts:
            groups[-1][1].append(event)
        else:
            groups.append((event.ts, [event]))
    return groups


class Episode(NamedTuple):
    """One stop episode: its events, what closed it, and what was carried in.

    A ``NamedTuple`` so that ``episode[0]`` / ``episode[1]`` keep working for
    callers written against the earlier two-tuple shape. ``tied_closer_keys``
    is appended last, after ``carried_request_keys``, specifically so that
    positional access into the first two fields is unaffected.
    """

    events: tuple[Event, ...]
    closer: Event | None
    carried_request_keys: frozenset[str]
    tied_closer_keys: frozenset[str] = frozenset()


def split_episodes(run: RunView) -> list[Episode]:
    """Split a run into stop episodes, each with the event that closed it.

    An episode is closed by ``run.resumed`` or ``run.completed``. A trailing episode
    with no closer is closed by the end of the ingested stream and reports ``None``.

    The split falls at a *timestamp group* boundary, not an event boundary. A halt
    sharing a second with the resume that closes its episode is unorderable against
    it, so it stays inside the episode it might belong to rather than being orphaned
    into the next one by an arrival-order accident.

    **A ``stop.requested`` tied with the closer is carried into the NEXT episode --
    but only when no ``motion.halted`` shares that same second.** If one does, the
    request stays, because a halt in its own second can answer it and fan-out will
    do so. Carrying it out regardless would tear apart a pairing the data supports
    and republish it as a failure. Its key is reported in ``carried_request_keys``
    so the pairing can disclose the tie. The two readings are "the demand was
    raised just before the cell resumed and went unanswered" and "the demand was
    raised just after the resume and belongs to what follows", and at whole-second
    resolution nothing distinguishes them. Keeping it here would publish the first
    reading as fact -- a fabricated *the cell did not stop* finding, decided by a
    tiebreak. Carrying it forward lets a halt in the next episode answer it, and
    if none does it is still reported unanswered, only now with the ambiguity on
    the record.
    """
    episodes: list[Episode] = []
    current: list[Event] = []
    carried_in: frozenset[str] = frozenset()

    for _ts, group in _group_by_ts(run.events):
        closers = [e for e in group if e.type in EPISODE_CLOSING_TYPES]
        closer = closers[0] if closers else None
        if closer is None:
            current.extend(group)
            continue

        # Two closers sharing a second (e.g. run.resumed and run.completed) are
        # unorderable: arrival order alone would decide which one the record
        # says closed the episode, silently flipping record content between
        # two orderings that read as equally unambiguous. Name both so the
        # pairing layer can flag the record instead.
        tied_closers = (
            frozenset(e.key for e in closers) if len(closers) > 1 else frozenset()
        )

        if any(e.type == "motion.halted" for e in group):
            # A halt in this same second can answer the tied requests, and
            # fan-out will pair it with every request outstanding when it
            # arrives. Carrying them out would tear apart a pairing the data
            # actually supports and republish it as failures -- the exact
            # worst-direction outcome this module exists to prevent.
            carry_forward: list[Event] = []
            current.extend(group)
        else:
            carry_forward = [e for e in group if e.type == "stop.requested"]
            current.extend(e for e in group if e.type != "stop.requested")

        episodes.append(Episode(tuple(current), closer, carried_in, tied_closers))
        current = list(carry_forward)
        carried_in = frozenset(e.key for e in carry_forward)

    if current:
        episodes.append(Episode(tuple(current), None, carried_in))
    return episodes


def pair_stops(run: RunView) -> list[StopSequence]:
    """Pair stop requests with halts, fanning out within bounded stop episodes.

    Two rules, and the second is what makes the first safe.

    **1. A halt satisfies every request outstanding when it arrives.** It is not
    *consumed* by one of them.

    "Which request did this halt answer?" has no single correct answer when more than
    one demand was outstanding -- physically the halt answered all of them. The
    alternatives were considered and each fails in a specific way:

    * *FIFO* picks the earliest and reports the others as unmatched, fabricating a
      safety finding against stops that in fact worked.
    * *LIFO* picks the latest, which reports the shortest delta -- the flattering bias,
      and the wrong one to build into a safety record.
    * *Refusing to pair when ambiguous* yields zero measurements on a cell with
      redundant triggers (light curtain **and** operator button), failing inspection
      action a3 rather than satisfying it.

    Fan-out asserts only what is observable: N demands, one halt, N deltas -- with the
    earliest demand yielding the largest and therefore most conservative number. Every
    affected record discloses the others via ``co_satisfied_with``.

    **2. A stop episode is closed by ``run.resumed``, ``run.completed``, or the end of
    the ingested stream -- whichever comes first.** A request still open at closure is
    ``no_halt_recorded`` and can never be paired afterwards.

    Without this boundary, pairing inverts the very finding it exists to produce. Given
    a run where one stop fails and a later, unrelated stop succeeds::

        07:15:33  stop.requested   R1
           --     (no halt -- THIS IS THE FINDING)
        07:17:33  run.resumed          <- closes R1's episode
        09:00:00  stop.requested   R2
        09:00:01  motion.halted    H

    unbounded lookahead pairs R1 with H and reports the **failed** stop as matched with
    a 1h44m response time, while reporting the **successful** stop as
    ``no_halt_recorded``. Both records are wrong, in the worst available direction, on
    the one record an inspector cares most about. The episode boundary is what stops
    it: R1 closes at the resume and can never see H.

    **The boundary only helps where a closing event actually intervenes.** Delete the
    ``run.resumed`` row above and both requests sit in one episode, so fan-out attaches
    R1 to H and reports a 1h44m "stop response" without complaint. That is not
    hypothetical -- it is exactly what happens if firmware can pause without ever
    resuming, and it is why the open question below is load-bearing rather than a
    nicety.

    A fixed time window would also fix this, but requires a constant we would be
    inventing -- and "why 30 seconds?" has no good answer at an inspection. The episode
    boundary is derived from an event the controller already emits, needs no constant,
    stays stable when FM-5 reads 24h of events off the same store, and is explainable in
    one sentence: *the cell started running again, so that stop was over.*

    Open with Chris (week 1): is ``run.resumed`` guaranteed after every ``run.paused``?
    If not, this needs a deliberately generous time-window backstop, recorded per record
    so the policy is visible rather than hidden in code.
    """
    sequences: list[StopSequence] = []
    for episode in split_episodes(run):
        sequences.extend(_pair_episode(episode))
    return sequences


def _pair_episode(episode: Episode) -> list[StopSequence]:
    episode_events, closer, carried_request_keys, tied_closer_keys = episode
    closed_by = closer.type if closer is not None else "stream_end"
    closed_key = closer.key if closer is not None else None

    tied_closer_note: str | None = None
    if tied_closer_keys:
        tied_closer_note = (
            f"this episode's close is tied between {len(tied_closer_keys)} "
            f"closing events ({', '.join(sorted(tied_closer_keys))}); which of "
            f"them ended the episode is not determinable at this resolution"
        )

    def build(**overrides: Any) -> StopSequence:
        base: dict[str, Any] = {
            "request": None,
            "halt": None,
            "co_satisfied_with": (),
            "episode_closed_by": closed_by,
            "episode_closed_by_event_key": closed_key,
            "ordering_confidence": "unambiguous",
            "notes": (),
            "episode_events": episode_events,
        }
        base.update(overrides)
        if tied_closer_note is not None:
            # Two episode closers tied in the same second mean arrival order
            # alone decided which of them this record says closed the
            # episode -- the same record, different content, both readings
            # claiming "unambiguous". Every record built for this episode
            # must disclose that, not just the ones that happen to mention
            # the closer directly.
            base["ordering_confidence"] = "ambiguous"
            base["notes"] = tuple(base["notes"]) + (tied_closer_note,)
        return StopSequence(**base)

    def carried_note(request: Event) -> str | None:
        if request.key not in carried_request_keys:
            return None
        return (
            f"stop.requested {request.key} shares its timestamp with the event that "
            f"closed the preceding episode; which episode it belongs to is not "
            f"determinable at {request.ts_resolution_seconds:g}s resolution. It was "
            f"carried forward rather than reported as a failed stop on a tiebreak"
        )

    sequences: list[StopSequence] = []
    open_requests: list[Event] = []
    episode_rests_on_a_tie = False

    for _ts, group in _group_by_ts(episode_events):
        # Every request in the group is admitted before any halt in it is
        # considered. Within one second nothing distinguishes a request that
        # arrived before its halt from one that arrived after, so a halt here must
        # be able to answer a request here. Process events one at a time instead
        # and swapping two lines of the input file turns a working stop into a
        # fabricated "the cell did not stop" finding paired with an unexplained
        # orphan halt -- and one that claims to be unambiguous. A fast cell makes
        # this MORE likely, not less: a sub-second stop response lands both events
        # in the same second.
        group_requests = [e for e in group if e.type == "stop.requested"]
        # Could a halt in this group have taken a demand at all? If not, two halts
        # tied here are not competing for anything: their records are identical
        # under either ordering, and flagging them would dilute the signal until
        # an inspector cannot tell a genuinely uncertain record from a certain one.
        demand_available = bool(group_requests) or bool(open_requests)
        open_requests.extend(group_requests)

        for event in group:
            if event.type != "motion.halted":
                continue

            if not open_requests:
                notes = [
                    "no stop.requested was outstanding in this episode when the "
                    "halt arrived; this halt cannot be attributed to a recorded "
                    "demand"
                ]
                ordering = "unambiguous"
                # An orphan produced by a tie is not an orphan we are sure about:
                # another halt in this same second already consumed the demands,
                # and which halt answered which is not knowable at this resolution.
                # Scan the whole group, not just what precedes this halt, and
                # exclude by identity rather than key: two byte-identical halts
                # in one second share an event_key, and excluding by value makes
                # each erase the other from the tie set -- so both would report
                # "unambiguous" about a tie they are themselves part of.
                #
                # Closers are in TIE_RELEVANT_TYPES deliberately. The matched path
                # already flags a halt tied with its closer as ambiguous; omitting
                # it here would disclose the same physical tie on a record that
                # reads well and hide it on one that reads badly. This record also
                # asserts episode membership the tie cannot support.
                tied = [
                    other
                    for other in group
                    if other is not event
                    and other.type in TIE_RELEVANT_TYPES
                    and (other.type != "motion.halted" or demand_available)
                ]
                if tied:
                    ordering = "ambiguous"
                    notes.append(
                        f"this motion.halted shares timestamp {iso_z(event.ts)} "
                        f"with {len(tied)} other stop-sequence event(s) "
                        f"({', '.join(e.key for e in tied)}); which halt answered "
                        f"which demand is not determinable at "
                        f"{event.ts_resolution_seconds:g}s resolution"
                    )
                elif episode_rests_on_a_tie:
                    # This halt found nothing outstanding -- but the demands were
                    # consumed by a pairing that itself rested on a tie. Under the
                    # other reading one of them was still open when this halt
                    # arrived, and this halt is not an orphan at all. Its very
                    # existence as an adverse record depends on a coin toss.
                    ordering = "ambiguous"
                    notes.append(
                        "an earlier pairing in this episode rested on a "
                        "same-second tie, so which demands were still available "
                        "to this halt is not determinable; under the alternative "
                        "reading this halt may not be unattributable at all"
                    )
                sequences.append(
                    build(
                        halt=event,
                        outcome="orphan_halt",
                        evidence_status="complete",
                        ordering_confidence=ordering,
                        notes=tuple(notes),
                    )
                )
                continue

            outstanding = list(open_requests)
            open_requests = []
            for index, request in enumerate(outstanding):
                # Exclude by position, not by key value: two requests could share
                # an event_key (the content-collision hole in events.event_key),
                # and excluding by value would make each erase the other.
                others = tuple(
                    other.key
                    for position, other in enumerate(outstanding)
                    if position != index
                )
                notes = []
                ordering = "unambiguous"

                if request.ts == event.ts:
                    ordering = "ambiguous"
                    notes.append(
                        f"stop.requested {request.key} and motion.halted "
                        f"{event.key} share timestamp {iso_z(event.ts)}; their "
                        f"order is not determinable at "
                        f"{event.ts_resolution_seconds:g}s resolution, so this "
                        f"pairing rests on simultaneity rather than observed order"
                    )
                if closer is not None and closer.ts == event.ts:
                    ordering = "ambiguous"
                    notes.append(
                        f"motion.halted {event.key} and the {closer.type} that "
                        f"closed this episode ({closer.key}) share timestamp "
                        f"{iso_z(event.ts)}; whether the halt preceded the episode "
                        f"close is not determinable at this resolution"
                    )
                carried = carried_note(request)
                if carried is not None:
                    ordering = "ambiguous"
                    notes.append(carried)
                if others:
                    notes.append(
                        f"this motion.halted also answered {len(others)} other "
                        f"outstanding stop demand(s); see co_satisfied_with"
                    )

                sequences.append(
                    build(
                        request=request,
                        halt=event,
                        outcome="matched",
                        evidence_status="complete",
                        co_satisfied_with=others,
                        ordering_confidence=ordering,
                        notes=tuple(notes),
                    )
                )
                if ordering == "ambiguous":
                    episode_rests_on_a_tie = True

    # Anything still open when the episode closed was never answered.
    for request in open_requests:
        if closer is not None:
            evidence, note = (
                "complete",
                f"request was still open when the episode closed on {closed_by}; "
                f"the episode demonstrably ended without a recorded halt",
            )
        else:
            evidence, note = (
                "truncated",
                "request was still open when the ingested stream ended; this is "
                "absence of evidence, not evidence that the cell failed to stop",
            )
        notes = [note]
        ordering = "unambiguous"
        carried = carried_note(request)
        if carried is not None:
            ordering = "ambiguous"
            notes.append(carried)
        sequences.append(
            build(
                request=request,
                halt=None,
                outcome="no_halt_recorded",
                evidence_status=evidence,
                ordering_confidence=ordering,
                notes=tuple(notes),
            )
        )

    return sequences
