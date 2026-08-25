/**
 * Suspect data: geometry moved but a field derived from it did not.
 *
 * The naive rule — "any geometry field changed but weightKg did not" — is
 * wrong on this data. Three of the seven changed panels in r3→r4 only move an
 * opening sideways. A window at a different x uses the same timber and weighs
 * the same, so an unchanged weight there is correct, not stale.
 *
 * So the comparison is against MATERIAL QUANTITY, not against raw geometry:
 * the amount of stuff in the panel. Opening position is not part of it;
 * opening SIZE is.
 *
 * All arithmetic is integer (mm and mm²). No floats, no tolerances.
 */

import type { ComparedField, Panel, SuspectFlag } from './model.js';

interface MaterialQuantity {
  /** Face area less openings, in mm². Integer. */
  readonly netAreaMm2: number;
  /** Structural span in mm, or null for non-spanning panels. */
  readonly spanMm: number | null;
}

export function materialQuantity(panel: Panel): MaterialQuantity {
  const openingArea = panel.openings.reduce((sum, o) => sum + o.w * o.h, 0);
  return {
    netAreaMm2: panel.width * panel.height - openingArea,
    spanMm: panel.span,
  };
}

function quantityChanged(a: Panel, b: Panel): boolean {
  const before = materialQuantity(a);
  const after = materialQuantity(b);
  return (
    before.netAreaMm2 !== after.netAreaMm2 || before.spanMm !== after.spanMm
  );
}

/**
 * Fields whose value is computed from material quantity, and so must move when
 * material quantity moves. `weightKg` is the only such field in the current
 * schema; the list is here so a future derived field is a one-line addition.
 */
const DERIVED_FROM_MATERIAL_QUANTITY: readonly ComparedField[] = ['weightKg'];

/** Human-readable summary of what moved, naming only the dimensions that did. */
function describeQuantityChange(previous: Panel, next: Panel): string {
  const before = materialQuantity(previous);
  const after = materialQuantity(next);
  const parts: string[] = [];

  if (before.netAreaMm2 !== after.netAreaMm2) {
    parts.push(`net area ${before.netAreaMm2}mm² → ${after.netAreaMm2}mm²`);
  }
  if (before.spanMm !== after.spanMm) {
    parts.push(`span ${String(before.spanMm)}mm → ${String(after.spanMm)}mm`);
  }

  return `material quantity changed (${parts.join(', ')})`;
}

/**
 * Flag a modified panel whose material quantity changed while a derived field
 * stood still. Returns an empty array for added, removed, or unchanged panels:
 * with only one revision of a panel there is no derived value to contradict.
 */
export function detectSuspectData(
  previous: Panel | null,
  next: Panel | null,
): SuspectFlag[] {
  if (previous === null || next === null) return [];
  if (!quantityChanged(previous, next)) return [];

  return DERIVED_FROM_MATERIAL_QUANTITY.filter(
    (field) => previous[field] === next[field],
  ).map((field) => ({
    panelId: next.panelId,
    field,
    reason: 'derived_field_stale' as const,
    detail: `${describeQuantityChange(previous, next)} but ${field} is unchanged at ${String(next[field])}`,
  }));
}
