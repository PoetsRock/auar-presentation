"""Plain-text rendering of an audit record, for a human inspector.

This module exists for one reason: to make the measurement's limits unskippable.
The uncertainty language below is **computed from the record's bound fields**, not
read from a pre-baked string, so there is no rendering path that emits a
controller-derived interval without also emitting what constrains it.

Per-axis amendment figures are a distinct case: the amendment schema carries no
bound, resolution, or method, because those numbers come from the rig, not this
service. Rather than inventing a bound this service cannot verify, the per-axis
block states plainly that the figure is unaccompanied by one -- see
``_per_axis_block``.
"""

from __future__ import annotations

import textwrap
from typing import Any

WIDTH = 78
LABEL_WIDTH = 13
_RULE = "=" * WIDTH


def _fmt(value: float) -> str:
    return f"{value:g}"


def _wrap_text(text: str, prefix: str = "  ") -> list[str]:
    """Wrap text to page width with a prefix, handling multi-line wrapping."""
    lines = []
    continuation = " " * len(prefix)
    # Same two arguments as _field, and for the same reason: NOTES is rendered
    # through this function, and event keys appear there. A 64-hex identifier
    # must never be split mid-token.
    wrapped = textwrap.wrap(
        text, width=WIDTH - len(prefix), break_long_words=False, break_on_hyphens=False
    ) or [""]
    lines.append(prefix + wrapped[0])
    for line in wrapped[1:]:
        lines.append(continuation + line)
    return lines


def _field(label: str, value: Any) -> str:
    """One ``label : value`` line, wrapped to the page width.

    The page declares a width and draws rules that wide; a value that runs past
    it breaks the frame on the printed sheet an inspector is handed. Long values
    are real here -- the per-axis reason and expected source both exceed the
    width on the sample data -- so they wrap under a hanging indent rather than
    being truncated. Nothing on this page may be shortened to fit.
    """
    prefix = f"  {label:<{LABEL_WIDTH}}: "
    text = f"{prefix}{value}"
    if len(text) <= WIDTH:
        return text
    continuation = " " * len(prefix)
    # break_long_words=False: event keys and chain hashes are identifiers, and a
    # 64-hex token split across a line break reads as corruption to an inspector
    # rather than as a wrap. A token too long for the column overflows the width
    # instead -- the lesser of the two wrongs on an evidence document.
    wrapped = textwrap.wrap(
        str(value),
        width=WIDTH - len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    return "\n".join([prefix + wrapped[0]] + [continuation + w for w in wrapped[1:]])


def _response_time_block(record: dict[str, Any]) -> list[str]:
    lines = ["STOP RESPONSE"]
    measured = record.get("response_time")

    if measured is None:
        if record.get("outcome") == "orphan_halt":
            # A halt WAS recorded -- it is printed under CONTEXT on this very
            # page. What is missing is a stop demand to attribute it to, so
            # there is no interval to measure. Falling through to the
            # "not evidenced to have stopped" wording would put a false claim in
            # front of an inspector, contradicted by the page's own CONTEXT
            # block, which is precisely the harm this module exists to prevent.
            lines.append("  NOT APPLICABLE - no stop demand was recorded for this halt.")
            lines += _wrap_text("A motion.halted was observed (see CONTEXT below), but no stop.requested could be attributed to it, so there is no interval to measure. This is NOT a finding that the cell failed to stop; it is a halt whose cause is unrecorded.")
        elif record.get("evidence_status") != "complete":
            lines.append("  Not evidenced - stream incomplete.")
            lines += _wrap_text("No motion.halted was recorded for this stop demand before the ingested stream ended. This is absence of evidence, not evidence that the cell failed to stop.")
        else:
            closed_by = record.get("episode", {}).get("closed_by", "the episode close")
            lines.append("  NOT EVIDENCED.")
            lines += _wrap_text(f"The stop episode closed on {closed_by} with no motion.halted recorded. On this evidence the cell is not evidenced to have stopped in response to this demand.")
        return lines

    lower = measured["lower_bound_seconds_exclusive"]
    upper = measured["upper_bound_seconds_exclusive"]
    resolution = measured["source_resolution_seconds"]
    resolution_words = (
        "whole-second" if resolution == 1.0 else f"{_fmt(resolution)} s"
    )

    lines.append(_field("Measured", f"{_fmt(measured['nominal_seconds'])} s (nominal)"))
    lines.append(
        _field(
            "Bound",
            f"greater than {_fmt(lower)} s and less than {_fmt(upper)} s",
        )
    )
    lines.append(
        _field("Resolution", f"source timestamps are {resolution_words} ({_fmt(resolution)} s)")
    )
    lines.append(_field("Claim", measured["defensible_claim"]))
    if not measured["causal_order_established"]:
        lines.append(
            "                 The halt cannot be shown to follow the request at this"
        )
        lines.append(
            "                 resolution; the bound spans zero."
        )
    lines.append(_field("Method", measured["method"]))
    lines += [
        _field("Clock", "cell wall-clock, unverified"),
        "                 There is no monotonic reference in this event stream, so a",
        "                 clock step would be undetectable and this interval inherits",
        "                 that caveat.",
    ]
    return lines


def _per_axis_block(record: dict[str, Any]) -> list[str]:
    per_axis = record.get("per_axis", {})
    # axesStopped is a motion.halted payload field and is not type-checked by
    # parse_event (see sequences.classify_pause for why the guard belongs at
    # the point of use). str() on each element lets a non-string axis label
    # render as itself rather than crash the page -- this block only affects
    # rendering of the one affected record, not stop_records() for the store.
    axes = ", ".join(str(a) for a in per_axis.get("axes_reported_stopped", [])) or "none reported"
    lines = ["PER-AXIS RESPONSE"]

    if per_axis.get("status") == "supplied_by_amendment":
        lines.append(_field("Status", "supplied by amendment (see AMENDMENTS below)"))
        for measurement in per_axis.get("measurements", []):
            axis = measurement.get("axis", "?")
            delta = measurement.get("delta_seconds")
            value = "not supplied" if delta is None else f"{delta} s"
            lines.append(_field(f"  {axis}", value))
        # The amendment schema carries no bound, resolution, or method -- unlike
        # every controller-derived interval on this page, this number is not
        # accompanied by anything that constrains it. Saying so plainly is the
        # only honest option; inventing a bound this service cannot verify
        # would be worse than the asymmetry it replaces.
        lines += _wrap_text(
            "These figures are supplied by their source without an uncertainty "
            "bound. This service does not compute or verify one for them.",
            prefix="  ",
        )
    else:
        lines.append(_field("Status", "unavailable from this source"))
        lines.append(_field("Reason", per_axis.get("reason", "")))
    lines.append(_field("Axes stopped", axes))
    lines.append(_field("Expected", per_axis.get("expected_source", "")))
    return lines


def _context_block(record: dict[str, Any]) -> list[str]:
    context = record.get("context", {})
    lines = ["CONTEXT"]

    request = record.get("stop_request")
    if request:
        lines.append(_field("Stop source", request.get("source", "unknown")))
        lines.append(_field("Panel", request.get("panel_id", "-")))
        lines.append(_field("Requested", request["ts"]))
    halt = record.get("motion_halt")
    if halt:
        lines.append(_field("Halted", halt["ts"]))

    for engaged in context.get("interlock_engaged", []):
        lines.append(_field("Interlock on", f"{engaged['ts']}  zone={engaged.get('zone')}"))
    for released in context.get("interlock_released", []):
        lines.append(
            _field(
                "Interlock off",
                f"{released['ts']}  zone={released.get('zone')}  "
                f"operator={released.get('operator')}",
            )
        )

    pause = context.get("pause")
    if pause:
        label = pause.get("classification", "unclassified").upper()
        lines.append(
            _field("Pause", f"{pause['ts']}  reason={pause.get('reason')}  [{label}]")
        )
    resume = context.get("resume")
    if resume:
        lines.append(
            _field("Resume", f"{resume['ts']}  mode={resume.get('resume_mode')}")
        )

    duration = context.get("stoppage_duration")
    if duration:
        lines.append(
            _field(
                "Stoppage",
                f"{_fmt(duration['nominal_seconds'])} s "
                f"(between {_fmt(duration['lower_bound_seconds_exclusive'])} s and "
                f"{_fmt(duration['upper_bound_seconds_exclusive'])} s)",
            )
        )

    lines.append(_field("Episode", f"closed by {record.get('episode', {}).get('closed_by')}"))

    candidates = context.get("cross_run_halt_candidates", [])
    for candidate in candidates:
        lines.append(
            _field(
                "Cross-run",
                f"a motion.halted exists in run {candidate.get('run_id')} at "
                f"{candidate.get('ts')} - NOT counted as evidence for this record",
            )
        )
    total = context.get("cross_run_halt_candidates_total", len(candidates))
    if total > len(candidates):
        lines.append(
            _field("Cross-run", f"showing {len(candidates)} of {total} candidates")
        )
    return lines


def render_text(record: dict[str, Any]) -> str:
    """Render one audit record as a plain-text page."""
    co_satisfied = record.get("episode", {}).get("co_satisfied_with", [])
    run_label = record.get("run_id") or "(outside any run)"
    if record.get("run_truncated"):
        run_label += "  [run stream truncated - no run.completed observed]"

    lines = [
        _RULE,
        f"E-STOP AUDIT RECORD{' ' * 24}record format {record.get('record_version')}",
        _RULE,
        _field("Record ID", record.get("record_id")),
        _field("Cell", record.get("cell_id")),
        _field("Run", run_label),
        _field("Anchor", record.get("anchor_ts")),
        _field("Outcome", record.get("outcome")),
        _field("Evidence", record.get("evidence_status")),
        "",
    ]

    lines += _response_time_block(record) + [""]
    lines += _per_axis_block(record) + [""]
    lines += _context_block(record) + [""]

    if co_satisfied:
        lines += [
            "CONCURRENT DEMANDS",
            f"  This motion.halted also answered {len(co_satisfied)} other outstanding",
            "  stop demand(s). Each has its own record, measured from its own request",
            "  timestamp. These are not independent halts.",
            "",
        ]

    amendments = record.get("amendments", [])
    if amendments:
        lines.append("AMENDMENTS")
        for amendment in amendments:
            lines.append(
                _field(
                    "Attached",
                    f"{amendment.get('ts')}  source={amendment.get('source')}  "
                    f"attested_by={amendment.get('attested_by')}",
                )
            )
        lines.append("")

    notes = record.get("confidence", {}).get("notes", [])
    if notes:
        lines.append("NOTES")
        for note in notes:
            lines += _wrap_text(note, prefix="  - ")
        lines.append("")

    lines.append(_RULE)
    return "\n".join(lines)
