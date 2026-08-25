/**
 * SHOULD — geometric consistency check (PR-7).
 *
 * Flags an UNCHANGED panel that is no longer consistent with a CHANGED one:
 * specifically a wall on level N that no longer stacks on the walls of level
 * N-1 beneath it.
 *
 * This module is deliberately independent of classification:
 *   - it imports nothing from ../classify, ../cost, ../diff or ../suspect;
 *   - it is not re-exported from ../index.ts;
 *   - its findings never enter RevisionImpact or the cost total.
 * Deleting this directory removes the feature and breaks nothing else. That
 * separation is the point: adjacency reasoning is useful for spotting knock-on
 * defects and must never be allowed to price a panel.
 *
 * Integer millimetres throughout.
 */

import type { BuildModel, Panel, Zone } from '../model.js';

const WALL_TYPES: readonly Panel['type'][] = ['external_wall', 'internal_wall'];

interface Interval {
  readonly panelId: string;
  readonly start: number;
  readonly end: number;
}

export interface StackingViolation {
  /** The level-N wall that is no longer supported. */
  readonly panelId: string;
  readonly level: number;
  readonly zone: Zone;
  /** Stretches of this wall with nothing beneath them, in mm along the zone. */
  readonly unsupported: readonly { readonly from: number; readonly to: number }[];
  /** The level N-1 walls that do support it, if any. */
  readonly supportedBy: readonly string[];
  /** Which changed panels below caused this, where the diff explains it. */
  readonly attributedTo: readonly string[];
}

export interface StackingReport {
  /** Violations present in `next` that were not present in `previous`. */
  readonly introduced: readonly StackingViolation[];
  /** Violations present in both revisions — pre-existing, not caused here. */
  readonly preExisting: readonly StackingViolation[];
}

/**
 * Walls in a zone are laid end-to-end from x=0 in panelId order.
 *
 * The build model carries no panel origin, so absolute position is not
 * knowable from this data. Ordering by panelId is a documented assumption of
 * this check, not a fact derived from the schema — see README. It is
 * deterministic, which is what makes the result diffable.
 */
function layout(panels: readonly Panel[], level: number, zone: Zone): Interval[] {
  const walls = panels
    .filter(
      (p) => p.level === level && p.zone === zone && WALL_TYPES.includes(p.type),
    )
    .sort((a, b) => a.panelId.localeCompare(b.panelId));

  let cursor = 0;
  return walls.map((wall) => {
    const interval = { panelId: wall.panelId, start: cursor, end: cursor + wall.width };
    cursor += wall.width;
    return interval;
  });
}

/** Stretches of `span` not covered by any interval in `support`. */
function uncovered(
  span: Interval,
  support: readonly Interval[],
): { from: number; to: number }[] {
  const merged = [...support]
    .sort((a, b) => a.start - b.start)
    .reduce<{ start: number; end: number }[]>((acc, interval) => {
      const last = acc[acc.length - 1];
      if (last !== undefined && interval.start <= last.end) {
        last.end = Math.max(last.end, interval.end);
      } else {
        acc.push({ start: interval.start, end: interval.end });
      }
      return acc;
    }, []);

  const gaps: { from: number; to: number }[] = [];
  let cursor = span.start;

  for (const block of merged) {
    if (block.end <= cursor) continue;
    if (block.start > cursor) {
      gaps.push({ from: cursor, to: Math.min(block.start, span.end) });
    }
    cursor = Math.max(cursor, block.end);
    if (cursor >= span.end) break;
  }

  if (cursor < span.end) gaps.push({ from: cursor, to: span.end });

  return gaps.filter((gap) => gap.to > gap.from);
}

function violationsIn(build: BuildModel): StackingViolation[] {
  const levels = [...new Set(build.panels.map((p) => p.level))].sort((a, b) => a - b);
  const violations: StackingViolation[] = [];

  for (const level of levels) {
    if (!levels.includes(level - 1)) continue;

    const zones = [
      ...new Set(
        build.panels
          .filter((p) => p.level === level && WALL_TYPES.includes(p.type))
          .map((p) => p.zone),
      ),
    ].sort();

    for (const zone of zones) {
      const above = layout(build.panels, level, zone);
      const below = layout(build.panels, level - 1, zone);

      for (const wall of above) {
        const gaps = uncovered(wall, below);
        if (gaps.length === 0) continue;
        violations.push({
          panelId: wall.panelId,
          level,
          zone,
          unsupported: gaps,
          supportedBy: below.map((b) => b.panelId),
          attributedTo: [],
        });
      }
    }
  }

  return violations.sort((a, b) => a.panelId.localeCompare(b.panelId));
}

function key(v: StackingViolation): string {
  return `${v.panelId}|${v.unsupported.map((g) => `${g.from}-${g.to}`).join(',')}`;
}

/**
 * Compare stacking consistency across two revisions.
 *
 * Reporting only what the revision INTRODUCED is what makes this actionable:
 * a design that was already odd in r3 is not this change's problem.
 */
export function checkStacking(
  previous: BuildModel,
  next: BuildModel,
): StackingReport {
  const before = violationsIn(previous);
  const beforeKeys = new Set(before.map(key));
  const beforePanels = new Map(previous.panels.map((p) => [p.panelId, p]));

  const introduced: StackingViolation[] = [];
  const preExisting: StackingViolation[] = [];

  for (const violation of violationsIn(next)) {
    if (beforeKeys.has(key(violation))) {
      preExisting.push(violation);
      continue;
    }
    // Attribute the new violation to whichever supporting panels changed width.
    const attributedTo = violation.supportedBy.filter((panelId) => {
      const was = beforePanels.get(panelId);
      const now = next.panels.find((p) => p.panelId === panelId);
      return was === undefined || now === undefined || was.width !== now.width;
    });
    introduced.push({ ...violation, attributedTo });
  }

  return { introduced, preExisting };
}
