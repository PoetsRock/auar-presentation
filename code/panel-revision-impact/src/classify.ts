/**
 * Classification: a function of (change kind, status) and nothing else.
 *
 * This module imports no geometry, no zone, no level, and no other panel. It is
 * given two scalars and returns a class. Adjacency is not excluded by policy or
 * by review — it is unavailable, because it is never passed in.
 */

import type {
  ChangeKind,
  Classification,
  EscalationReason,
  PanelStatus,
} from './model.js';

/**
 * Statuses at which physical material has been committed: something exists, or
 * is moving, or is standing. Deleting one of these from a revision is a human
 * decision with a cost this tool cannot know.
 */
const MATERIAL_COMMITTED: readonly PanelStatus[] = [
  'manufactured',
  'in_transit',
  'installed',
];

function escalate(reason: EscalationReason): Classification {
  return { class: 'escalate', blocksApproval: true, reason };
}

/**
 * The matrix.
 *
 *                | planned  | manufactured | in_transit | installed
 *   -------------+----------+--------------+------------+-----------
 *   unchanged    | no_action| no_action    | no_action  | no_action
 *   modified     | requeue  | remake       | recall     | escalate
 *   added        | requeue  | remake       | recall     | escalate
 *   removed      | no_action| escalate     | escalate   | escalate
 *
 * `added` shares the `modified` row: a panel new to this revision is work the
 * factory has not been told about, which is the same situation as a panel whose
 * spec moved. `removed` is its own row because there is nothing to re-issue —
 * either no material was ever committed (nothing to recover, no cost), or some
 * was and its disposition is not automatable.
 */
export function classifyPanel(
  kind: ChangeKind,
  status: PanelStatus,
): Classification {
  if (kind === 'unchanged') return { class: 'no_action' };

  if (kind === 'removed') {
    return MATERIAL_COMMITTED.includes(status)
      ? escalate('removed_after_material_committed')
      : { class: 'no_action' };
  }

  // kind is 'modified' or 'added'.
  switch (status) {
    case 'planned':
      return { class: 'requeue', reissue: 'requeue' };
    case 'manufactured':
      return { class: 'remake', reissue: 'remake' };
    case 'in_transit':
      return { class: 'recall', reissue: 'recall' };
    case 'installed':
      // AC5. The returned variant has no `reissue` member, so no caller can
      // obtain a re-issue action for an installed panel — not by ignoring a
      // flag, not by accident. The type system refuses it.
      return escalate('panel_installed');
    default: {
      // Exhaustiveness: a new PanelStatus in build.interface.ts fails to
      // compile here rather than silently falling through to a default class.
      const unhandled: never = status;
      throw new Error(`Unhandled panel status: ${String(unhandled)}`);
    }
  }
}
