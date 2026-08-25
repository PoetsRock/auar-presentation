"""Interval arithmetic that carries its own uncertainty.

Whole-second timestamps cannot support a point measurement, so nothing here
returns one unaccompanied. Every interval is an open bound plus the resolution
that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import Event

CLOCK_AUTHORITY = "cell_wall_clock_unverified"
"""``ts`` is presumed cell wall-clock with no monotonic reference. An NTP step or
a controller reboot can move it backwards and today that is undetectable
(docs/firmware-event-schema-v4.2.md lines 47-50, point 4 'No clock authority'). Every interval computed from
``ts`` inherits this caveat and says so."""


def _fmt(value: float) -> str:
    return f"{value:g}"


@dataclass(frozen=True)
class Bound:
    """An open interval known to contain the true value."""

    nominal_seconds: float
    lower_seconds_exclusive: float
    upper_seconds_exclusive: float
    source_resolution_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "nominal_seconds": self.nominal_seconds,
            "lower_bound_seconds_exclusive": self.lower_seconds_exclusive,
            "upper_bound_seconds_exclusive": self.upper_seconds_exclusive,
            "source_resolution_seconds": self.source_resolution_seconds,
        }


@dataclass(frozen=True)
class ResponseTime:
    """A :class:`Bound` plus the fields that make it quotable to an inspector.

    Deliberately a distinct type from :class:`Bound` so that a bare interval --
    a stoppage duration, say -- cannot be serialised into the ``response_time``
    slot of an audit record without its method, clock caveat, and claim.
    """

    bound: Bound
    method: str
    clock_authority: str
    causal_order_established: bool
    defensible_claim: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.bound.as_dict(),
            "method": self.method,
            "clock_authority": self.clock_authority,
            "causal_order_established": self.causal_order_established,
            "defensible_claim": self.defensible_claim,
        }


def interval_bound(earlier: Event, later: Event) -> Bound:
    """Bound the true interval between two quantised timestamps.

    Let ``d`` be the observed difference and ``r_e``/``r_l`` the two events'
    timestamp resolutions.

    * Under **truncation** the true value lies in ``(d - r_e, d + r_l)``.
    * Under **rounding** it lies in ``(d - h, d + h)`` where ``h = (r_e + r_l)/2``.

    We do not know which convention the controller uses, so we take the union --
    the bound that is correct under either. When both resolutions are equal (every
    case in today's data, ``r = 1 s``) the two conventions coincide and this
    reduces to ``(d - r, d + r)``.
    """
    delta = (later.ts - earlier.ts).total_seconds()
    r_earlier = earlier.ts_resolution_seconds
    r_later = later.ts_resolution_seconds
    half = (r_earlier + r_later) / 2
    return Bound(
        nominal_seconds=delta,
        lower_seconds_exclusive=delta - max(r_earlier, half),
        upper_seconds_exclusive=delta + max(r_later, half),
        source_resolution_seconds=max(r_earlier, r_later),
    )


def response_time(request: Event, halt: Event) -> ResponseTime:
    """Stop response time for a matched request/halt pair."""
    bound = interval_bound(request, halt)
    causal_order_established = bound.lower_seconds_exclusive >= 0

    if causal_order_established:
        claim = f"stop response < {_fmt(bound.upper_seconds_exclusive)} s"
    else:
        claim = (
            f"stop response not established: the two events lie within "
            f"{_fmt(bound.source_resolution_seconds)} s of one another, so the halt "
            f"cannot be shown to follow the request at this timestamp resolution"
        )

    method = (
        "derived_from_whole_second_controller_wall_clock"
        if bound.source_resolution_seconds == 1.0
        else "derived_from_sub_second_controller_wall_clock"
    )

    return ResponseTime(
        bound=bound,
        method=method,
        clock_authority=CLOCK_AUTHORITY,
        causal_order_established=causal_order_established,
        defensible_claim=claim,
    )
