import { describe, expect, it } from 'vitest';
import { classifyRevision, reissueQueue } from '../src/index.js';
import { build, panel, r3, r4 } from './fixtures.js';

describe('edge cases', () => {
  it('handles panels added in the new revision', () => {
    const previous = build(3, [panel({ panelId: 'A' })]);
    const next = build(4, [panel({ panelId: 'A' }), panel({ panelId: 'B' })]);

    const impact = classifyRevision(previous, next);
    const added = impact.panels.find((p) => p.panelId === 'B');

    expect(added?.changeKind).toBe('added');
    expect(added?.classification.class).toBe('requeue');
    expect(impact.cost.pence).toBe(0);
    expect(impact.approval.blocked).toBe(false);
  });

  it('escalates a panel removed after material was committed', () => {
    const previous = build(3, [panel({ panelId: 'A', status: 'manufactured' })]);
    const next = build(4, []);

    const impact = classifyRevision(previous, next);

    expect(impact.panels[0]).toMatchObject({
      panelId: 'A',
      changeKind: 'removed',
      classification: {
        class: 'escalate',
        reason: 'removed_after_material_committed',
      },
    });
    expect(impact.approval.blocked).toBe(true);
    // Nothing was re-made, so nothing is charged. The disposition is a human call.
    expect(impact.cost.pence).toBe(0);
  });

  it('charges nothing and blocks nothing for a removed planned panel', () => {
    const impact = classifyRevision(
      build(3, [panel({ panelId: 'A', status: 'planned' })]),
      build(4, []),
    );

    expect(impact.panels[0]?.classification.class).toBe('no_action');
    expect(impact.approval.blocked).toBe(false);
    expect(impact.cost.pence).toBe(0);
  });

  it('diffs revisions more than one step apart identically', () => {
    // r3 -> r4 and a synthetic r1 -> r4 must classify the same panels the same
    // way: nothing in the library counts steps.
    const far = { ...r3(), revision: 1, supersedes: null };
    const near = classifyRevision(r3(), r4());
    const distant = classifyRevision(far, r4());

    expect(distant.revisionGap).toBe(3);
    expect(near.revisionGap).toBe(1);
    expect(distant.panels.map((p) => p.classification.class)).toEqual(
      near.panels.map((p) => p.classification.class),
    );
    expect(distant.cost.pence).toBe(near.cost.pence);
  });

  it('reports a rollback with a negative gap rather than refusing', () => {
    const impact = classifyRevision(r4(), r3());
    expect(impact.revisionGap).toBe(-1);
    expect(impact.from).toBe(4);
    expect(impact.to).toBe(3);
  });

  it('finds nothing to do between identical revisions', () => {
    const impact = classifyRevision(r4(), r4());

    expect(impact.revisionGap).toBe(0);
    expect(impact.panels.every((p) => p.changeKind === 'unchanged')).toBe(true);
    expect(impact.cost.pence).toBe(0);
    expect(impact.cost.complete).toBe(true);
    expect(impact.suspectData).toEqual([]);
    expect(impact.approval.blocked).toBe(false);
    expect(reissueQueue(impact)).toEqual({ approved: true, instructions: [] });
  });

  it('handles empty builds', () => {
    const impact = classifyRevision(build(3, []), build(4, []));

    expect(impact.panels).toEqual([]);
    expect(impact.cost.pence).toBe(0);
    expect(impact.cost.complete).toBe(true);
    expect(impact.approval.blocked).toBe(false);
  });

  it('handles a build emptied entirely by the new revision', () => {
    const impact = classifyRevision(
      build(3, [panel({ panelId: 'A', status: 'installed' })]),
      build(4, []),
    );
    expect(impact.approval.blocked).toBe(true);
  });

  it('treats a status-only change as a real change', () => {
    const impact = classifyRevision(
      build(3, [panel({ panelId: 'A', status: 'planned' })]),
      build(4, [panel({ panelId: 'A', status: 'manufactured' })]),
    );

    const p = impact.panels[0];
    expect(p?.changeKind).toBe('modified');
    expect(p?.changedFields).toEqual(['status']);
    // Geometry did not move, so no suspect flag despite an unchanged weight.
    expect(p?.suspect).toEqual([]);
    expect(p?.classification.class).toBe('remake');
  });

  it('rejects diffing two different builds', () => {
    expect(() =>
      classifyRevision(build(3, [], 'PLOT3-A'), build(4, [], 'PLOT9-Z')),
    ).toThrow(/Cannot diff different builds/);
  });

  it('rejects a build containing duplicate panel ids', () => {
    expect(() =>
      classifyRevision(
        build(3, [panel({ panelId: 'A' }), panel({ panelId: 'A' })]),
        build(4, []),
      ),
    ).toThrow(/Duplicate panelId/);
  });

  it('does not treat a re-ordered openings array as a change', () => {
    const openings = [
      { x: 600, w: 900, h: 1400 },
      { x: 1800, w: 600, h: 600 },
    ];
    const impact = classifyRevision(
      build(3, [panel({ panelId: 'A', openings })]),
      build(4, [panel({ panelId: 'A', openings: [...openings].reverse() })]),
    );

    expect(impact.panels[0]?.changeKind).toBe('unchanged');
  });

  it('keeps all geometry arithmetic in integers', () => {
    const impact = classifyRevision(r3(), r4());
    expect(Number.isInteger(impact.cost.pence)).toBe(true);
    for (const p of impact.panels) {
      if (p.cost.kind === 'priced') expect(Number.isInteger(p.cost.pence)).toBe(true);
    }
  });
});
