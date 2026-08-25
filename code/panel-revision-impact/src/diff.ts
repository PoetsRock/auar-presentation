/**
 * Set-based diff of two whole builds, keyed by `panelId`.
 *
 * Nothing here knows or cares how many revisions separate the two documents.
 * A gap of one and a gap of five are the same code path, because "previous" is
 * a parameter rather than state stored on a panel.
 */

import { COMPARED_FIELDS } from './model.js';
import type {
  BuildModel,
  ChangeKind,
  ComparedField,
  Opening,
  Panel,
} from './model.js';

export interface PanelDiff {
  readonly panelId: string;
  readonly kind: ChangeKind;
  readonly previous: Panel | null;
  readonly next: Panel | null;
  readonly changedFields: readonly ComparedField[];
  /** The panel as it stands in the revision where it last appears. */
  readonly current: Panel;
}

/**
 * Openings are compared as a set, not a sequence: re-ordering the array without
 * changing any opening is not a design change. Sorting on (x, w, h) gives a
 * canonical order for that comparison.
 */
function canonicalOpenings(openings: readonly Opening[]): Opening[] {
  return [...openings].sort((a, b) => a.x - b.x || a.w - b.w || a.h - b.h);
}

function openingsEqual(a: readonly Opening[], b: readonly Opening[]): boolean {
  if (a.length !== b.length) return false;
  const left = canonicalOpenings(a);
  const right = canonicalOpenings(b);
  return left.every((o, i) => {
    const other = right[i];
    return other !== undefined && o.x === other.x && o.w === other.w && o.h === other.h;
  });
}

function fieldChanged(field: ComparedField, a: Panel, b: Panel): boolean {
  if (field === 'openings') return !openingsEqual(a.openings, b.openings);
  return a[field] !== b[field];
}

/** Compared fields that differ, in `COMPARED_FIELDS` order. */
export function changedFields(a: Panel, b: Panel): ComparedField[] {
  return COMPARED_FIELDS.filter((field) => fieldChanged(field, a, b));
}

function byPanelId(panels: readonly Panel[]): Map<string, Panel> {
  const index = new Map<string, Panel>();
  for (const panel of panels) {
    if (index.has(panel.panelId)) {
      throw new Error(`Duplicate panelId in build: ${panel.panelId}`);
    }
    index.set(panel.panelId, panel);
  }
  return index;
}

/**
 * Diff every panel across both revisions. Output is sorted by `panelId` so the
 * result is byte-stable and can be attached to a change record.
 */
export function diffPanels(
  previous: BuildModel,
  next: BuildModel,
): PanelDiff[] {
  const before = byPanelId(previous.panels);
  const after = byPanelId(next.panels);

  const allIds = [...new Set([...before.keys(), ...after.keys()])].sort();

  return allIds.map((panelId): PanelDiff => {
    const prev = before.get(panelId) ?? null;
    const nxt = after.get(panelId) ?? null;

    if (prev === null && nxt !== null) {
      return {
        panelId,
        kind: 'added',
        previous: null,
        next: nxt,
        changedFields: [],
        current: nxt,
      };
    }

    if (prev !== null && nxt === null) {
      return {
        panelId,
        kind: 'removed',
        previous: prev,
        next: null,
        changedFields: [],
        current: prev,
      };
    }

    // Both present: `allIds` is built from the two key sets, so this is total.
    /* c8 ignore next */
    if (prev === null || nxt === null) throw new Error('unreachable');

    const fields = changedFields(prev, nxt);
    return {
      panelId,
      kind: fields.length === 0 ? 'unchanged' : 'modified',
      previous: prev,
      next: nxt,
      changedFields: fields,
      current: nxt,
    };
  });
}
