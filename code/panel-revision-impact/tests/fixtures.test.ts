/**
 * Verification against the real r3 -> r4 fixtures.
 *
 * Panel IDs are asserted here. They are NOT present in the library: every id
 * below is derived by classifyRevision from the two documents.
 */

import { describe, expect, it } from 'vitest';
import { classifyRevision, reissueQueue } from '../src/index.js';
import type { ImpactClass, PanelImpact } from '../src/model.js';
import { r3, r4 } from './fixtures.js';

const impact = classifyRevision(r3(), r4());

const idsWhere = (predicate: (p: PanelImpact) => boolean): string[] =>
  impact.panels.filter(predicate).map((p) => p.panelId).sort();

const idsOfClass = (c: ImpactClass): string[] =>
  idsWhere((p) => p.classification.class === c);

describe('r3 -> r4 fixtures', () => {
  it('covers all twenty panels', () => {
    expect(impact.panels).toHaveLength(20);
    expect(impact.buildId).toBe('PLOT3-A');
    expect(impact.from).toBe(3);
    expect(impact.to).toBe(4);
    expect(impact.revisionGap).toBe(1);
  });

  it('finds exactly seven changed panels, all on level 1', () => {
    const changed = impact.panels.filter((p) => p.changeKind === 'modified');
    expect(changed).toHaveLength(7);
    expect(changed.map((p) => p.panelId).sort()).toEqual([
      'EW-L1-E1',
      'EW-L1-N1',
      'EW-L1-N2',
      'EW-L1-W1',
      'FC-01',
      'FC-02',
      'IW-L1-01',
    ]);
    expect(changed.every((p) => p.level === 1)).toBe(true);
  });

  it('classes the four changed manufactured panels as remake', () => {
    expect(idsOfClass('remake')).toEqual([
      'EW-L1-E1',
      'EW-L1-W1',
      'FC-01',
      'IW-L1-01',
    ]);
  });

  it('classes the two changed planned panels as requeue, at zero cost', () => {
    expect(idsOfClass('requeue')).toEqual(['EW-L1-N2', 'FC-02']);
    for (const p of impact.panels.filter((x) => x.classification.class === 'requeue')) {
      expect(p.cost).toEqual({ kind: 'priced', pence: 0, unknowns: [] });
    }
  });

  it('escalates the changed installed panel and blocks approval', () => {
    expect(idsOfClass('escalate')).toEqual(['EW-L1-N1']);
    expect(impact.approval).toEqual({
      blocked: true,
      reasons: [{ panelId: 'EW-L1-N1', reason: 'panel_installed' }],
    });
  });

  it('leaves the thirteen untouched panels at no_action', () => {
    expect(idsOfClass('no_action')).toHaveLength(13);
    expect(impact.cost.countsByClass).toEqual({
      no_action: 13,
      requeue: 2,
      remake: 4,
      recall: 0,
      escalate: 1,
    });
  });

  it('flags exactly one panel with a stale weightKg', () => {
    expect(impact.suspectData).toHaveLength(1);
    expect(impact.suspectData[0]).toMatchObject({
      panelId: 'IW-L1-01',
      field: 'weightKg',
      reason: 'derived_field_stale',
    });
  });

  it('does not flag panels whose only geometry change is opening position', () => {
    // These three move a window sideways. Same timber, same weight.
    for (const panelId of ['EW-L1-N1', 'EW-L1-N2', 'EW-L1-E1']) {
      const p = impact.panels.find((x) => x.panelId === panelId);
      expect(p?.changedFields).toEqual(['openings']);
      expect(p?.suspect).toEqual([]);
    }
  });

  it('totals £720 — the suspect panel still contributes its £180 (AC6)', () => {
    expect(impact.cost.pence).toBe(72_000);
    expect(impact.cost.formatted).toBe('£720.00');
    expect(impact.cost.complete).toBe(true);
    expect(impact.cost.unknowns).toEqual([]);

    const suspectPanel = impact.panels.find((p) => p.panelId === 'IW-L1-01');
    expect(suspectPanel?.cost).toEqual({ kind: 'priced', pence: 18_000, unknowns: [] });
    expect(suspectPanel?.suspect).toHaveLength(1);
  });

  it('refuses to emit any re-issue instruction while a panel is installed', () => {
    const queue = reissueQueue(impact);
    expect(queue.approved).toBe(false);
    expect(queue).not.toHaveProperty('instructions');
  });

  it('is deterministic and serialisable', () => {
    const a = JSON.stringify(classifyRevision(r3(), r4()));
    const b = JSON.stringify(classifyRevision(r3(), r4()));
    expect(a).toBe(b);
    expect(impact.panels.map((p) => p.panelId)).toEqual(
      [...impact.panels.map((p) => p.panelId)].sort(),
    );
  });

  it('does not mutate its inputs', () => {
    const before = r3();
    const snapshot = JSON.stringify(before);
    classifyRevision(before, r4());
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});
