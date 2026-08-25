/**
 * classifyRevision — the public entry point.
 *
 * A pure function of two whole builds. It reads no clock, no filesystem and no
 * global state, mutates neither argument, and returns a plain serialisable
 * object. Called twice with the same inputs it returns byte-identical JSON.
 */

import { classifyPanel } from './classify.js';
import { costForPanel, totalCost } from './cost.js';
import { diffPanels } from './diff.js';
import { detectSuspectData } from './suspect.js';
import type {
  ApprovalGate,
  BlockReason,
  BuildModel,
  PanelImpact,
  ReissueInstruction,
  RevisionImpact,
  SuspectFlag,
} from './model.js';

function approvalGate(panels: readonly PanelImpact[]): ApprovalGate {
  const reasons: BlockReason[] = panels.flatMap((panel) =>
    panel.classification.class === 'escalate'
      ? [{ panelId: panel.panelId, reason: panel.classification.reason }]
      : [],
  );

  return reasons.length > 0 ? { blocked: true, reasons } : { blocked: false };
}

export function classifyRevision(
  previous: BuildModel,
  next: BuildModel,
): RevisionImpact {
  if (previous.buildId !== next.buildId) {
    throw new Error(
      `Cannot diff different builds: ${previous.buildId} vs ${next.buildId}`,
    );
  }

  const panels: PanelImpact[] = diffPanels(previous, next).map((diff) => {
    const suspect = detectSuspectData(diff.previous, diff.next);
    const classification = classifyPanel(diff.kind, diff.current.status);

    return {
      panelId: diff.panelId,
      changeKind: diff.kind,
      status: diff.current.status,
      level: diff.current.level,
      changedFields: diff.changedFields,
      classification,
      cost: costForPanel(classification.class, suspect),
      suspect,
    };
  });

  const suspectData: SuspectFlag[] = panels.flatMap((panel) => panel.suspect);

  return {
    buildId: next.buildId,
    from: previous.revision,
    to: next.revision,
    revisionGap: next.revision - previous.revision,
    panels,
    suspectData,
    cost: totalCost(panels),
    approval: approvalGate(panels),
  };
}

/**
 * The only way to obtain re-issue instructions.
 *
 * Two structural guarantees, neither of them a flag a caller can ignore:
 *
 *  1. While any panel escalates, this returns no instruction list at all. There
 *     is no array to iterate, so a partial re-issue cannot be started and then
 *     regretted.
 *  2. `escalate` carries no `reissue` member, so even once the gate is clear an
 *     installed panel has no action to emit. Both guarantees are enforced by
 *     the compiler, not by review.
 */
export function reissueQueue(
  impact: RevisionImpact,
):
  | { readonly approved: false; readonly blockedBy: readonly BlockReason[] }
  | { readonly approved: true; readonly instructions: readonly ReissueInstruction[] } {
  if (impact.approval.blocked) {
    return { approved: false, blockedBy: impact.approval.reasons };
  }

  const instructions = impact.panels.flatMap((panel) =>
    'reissue' in panel.classification
      ? [{ panelId: panel.panelId, action: panel.classification.reissue }]
      : [],
  );

  return { approved: true, instructions };
}
