/**
 * Types for revision impact classification.
 *
 * The build-model types are RE-EXPORTED from the repository's canonical
 * `build.interface.ts`, deliberately unmodified. This library adds no field to
 * `Panel` — in particular no `previousSpec` — because the previous revision is
 * an argument to `classifyRevision`, not state carried inside a panel.
 */

export type {
  BuildModel,
  Opening,
  Panel,
  PanelStatus,
  PanelType,
  Zone,
} from '../../../build.interface';

import type { Panel } from '../../../build.interface';

/**
 * Panel fields compared by the diff, in a fixed order so that `changedFields`
 * is deterministic across runs and machines.
 */
export const COMPARED_FIELDS = [
  'type',
  'level',
  'zone',
  'width',
  'height',
  'openings',
  'span',
  'loadBearing',
  'weightKg',
  'status',
] as const satisfies readonly (keyof Panel)[];

export type ComparedField = (typeof COMPARED_FIELDS)[number];

/**
 * How a panel appears across the two revisions. This is a property of the panel
 * itself — never of its neighbours — so classification remains adjacency-free.
 */
export type ChangeKind = 'unchanged' | 'modified' | 'added' | 'removed';

export type ImpactClass =
  | 'no_action'
  | 'requeue'
  | 'remake'
  | 'recall'
  | 'escalate';

/** The three classes that may result in a panel being re-issued to the factory. */
export type ReissueAction = 'requeue' | 'remake' | 'recall';

/**
 * Classification result.
 *
 * AC5 is enforced here at the type level: `escalate` has no `reissue` member,
 * so there is no re-issue instruction on an escalated panel for a caller to
 * read, ignore a flag on, or accidentally act upon. An `installed` panel can
 * only ever produce the `escalate` variant (see `classify.ts`), and therefore
 * can never carry a re-issue action.
 */
export type Classification =
  | { readonly class: 'no_action' }
  | { readonly class: 'requeue'; readonly reissue: ReissueAction }
  | { readonly class: 'remake'; readonly reissue: ReissueAction }
  | { readonly class: 'recall'; readonly reissue: ReissueAction }
  | {
      readonly class: 'escalate';
      readonly blocksApproval: true;
      readonly reason: EscalationReason;
    };

export type EscalationReason =
  | 'panel_installed'
  | 'removed_after_material_committed';

/** A hand-edit signal: geometry moved but a field derived from it did not. */
export interface SuspectFlag {
  readonly panelId: string;
  /** The derived field whose value is not trustworthy. */
  readonly field: ComparedField;
  readonly reason: 'derived_field_stale';
  readonly detail: string;
}

/**
 * Per-panel cost.
 *
 * `excluded` is reached only when a suspect field actually feeds this panel's
 * own cost calculation (AC6). A stale `weightKg` on a flat-rate `remake` does
 * not reach it — the record is untrustworthy, the cost is not.
 */
export type PanelCost =
  | {
      readonly kind: 'priced';
      readonly pence: number;
      readonly unknowns: readonly string[];
    }
  | {
      readonly kind: 'excluded';
      readonly reason: 'suspect_field_feeds_cost';
      readonly fields: readonly ComparedField[];
    }
  | { readonly kind: 'no_automatic_cost'; readonly reason: 'requires_escalation' };

export interface PanelImpact {
  readonly panelId: string;
  readonly changeKind: ChangeKind;
  /** Status as at the revision in which the panel last appears. */
  readonly status: Panel['status'];
  readonly level: number;
  readonly changedFields: readonly ComparedField[];
  readonly classification: Classification;
  readonly cost: PanelCost;
  readonly suspect: readonly SuspectFlag[];
}

export interface CostTotal {
  /** Integer pence. Money is never held as a float. */
  readonly pence: number;
  /** Presentational only; derived by integer arithmetic. */
  readonly formatted: string;
  /** False when any figure the total depends on is unknown or withheld. */
  readonly complete: boolean;
  readonly unknowns: readonly string[];
  readonly countsByClass: Readonly<Record<ImpactClass, number>>;
}

export interface BlockReason {
  readonly panelId: string;
  readonly reason: EscalationReason;
}

/**
 * Approval gate. Derived from the presence of escalations — there is no setter
 * and no boolean for a caller to flip.
 */
export type ApprovalGate =
  | { readonly blocked: true; readonly reasons: readonly BlockReason[] }
  | { readonly blocked: false };

export interface RevisionImpact {
  readonly buildId: string;
  readonly from: number;
  readonly to: number;
  /** `to - from`. Any magnitude is supported; negative denotes a rollback. */
  readonly revisionGap: number;
  /** Sorted by `panelId` so the output is byte-stable and diffable. */
  readonly panels: readonly PanelImpact[];
  readonly suspectData: readonly SuspectFlag[];
  readonly cost: CostTotal;
  readonly approval: ApprovalGate;
}

export interface ReissueInstruction {
  readonly panelId: string;
  readonly action: ReissueAction;
}
