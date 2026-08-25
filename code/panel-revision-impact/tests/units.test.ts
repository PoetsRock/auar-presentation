import { describe, expect, it } from 'vitest';
import { classifyPanel } from '../src/classify.js';
import { COST_RULES, costForPanel, formatPence, REMAKE_PENCE } from '../src/cost.js';
import { detectSuspectData, materialQuantity } from '../src/suspect.js';
import type { ChangeKind, ImpactClass, PanelStatus, SuspectFlag } from '../src/model.js';
import { panel } from './fixtures.js';

describe('classifyPanel — the (changed, status) matrix', () => {
  const cases: [ChangeKind, PanelStatus, ImpactClass][] = [
    ['unchanged', 'planned', 'no_action'],
    ['unchanged', 'manufactured', 'no_action'],
    ['unchanged', 'in_transit', 'no_action'],
    ['unchanged', 'installed', 'no_action'],
    ['modified', 'planned', 'requeue'],
    ['modified', 'manufactured', 'remake'],
    ['modified', 'in_transit', 'recall'],
    ['modified', 'installed', 'escalate'],
    ['added', 'planned', 'requeue'],
    ['added', 'manufactured', 'remake'],
    ['added', 'in_transit', 'recall'],
    ['added', 'installed', 'escalate'],
    ['removed', 'planned', 'no_action'],
    ['removed', 'manufactured', 'escalate'],
    ['removed', 'in_transit', 'escalate'],
    ['removed', 'installed', 'escalate'],
  ];

  it.each(cases)('(%s, %s) -> %s', (kind, status, expected) => {
    expect(classifyPanel(kind, status).class).toBe(expected);
  });

  it('never attaches a re-issue action to an installed panel (AC5)', () => {
    for (const kind of ['unchanged', 'modified', 'added', 'removed'] as ChangeKind[]) {
      const result = classifyPanel(kind, 'installed');
      expect(result).not.toHaveProperty('reissue');
    }
  });

  it('attaches a re-issue action to every re-issuable class', () => {
    for (const status of ['planned', 'manufactured', 'in_transit'] as PanelStatus[]) {
      expect(classifyPanel('modified', status)).toHaveProperty('reissue');
    }
  });
});

describe('materialQuantity', () => {
  it('subtracts opening area from face area', () => {
    const p = panel({
      panelId: 'A',
      width: 3600,
      height: 2700,
      openings: [{ x: 1200, w: 1200, h: 1400 }],
    });
    expect(materialQuantity(p)).toEqual({
      netAreaMm2: 3600 * 2700 - 1200 * 1400,
      spanMm: null,
    });
  });

  it('is unaffected by where an opening sits', () => {
    const at = (x: number) =>
      materialQuantity(panel({ panelId: 'A', openings: [{ x, w: 900, h: 1400 }] }));
    expect(at(600)).toEqual(at(1500));
  });
});

describe('detectSuspectData', () => {
  const base = panel({ panelId: 'A', width: 2400, height: 2700, weightKg: 58 });

  it('flags a changed material quantity with an unmoved weight', () => {
    const flags = detectSuspectData(base, { ...base, height: 2750 });
    expect(flags).toHaveLength(1);
    expect(flags[0]).toMatchObject({ panelId: 'A', field: 'weightKg' });
  });

  it('does not flag when weight moved with the geometry', () => {
    expect(detectSuspectData(base, { ...base, height: 2750, weightKg: 59 })).toEqual([]);
  });

  it('does not flag an opening that only moved', () => {
    const withOpening = { ...base, openings: [{ x: 300, w: 600, h: 900 }] };
    const moved = { ...base, openings: [{ x: 900, w: 600, h: 900 }] };
    expect(detectSuspectData(withOpening, moved)).toEqual([]);
  });

  it('flags a resized opening with an unmoved weight', () => {
    const withOpening = { ...base, openings: [{ x: 300, w: 600, h: 900 }] };
    const resized = { ...base, openings: [{ x: 300, w: 1200, h: 900 }] };
    expect(detectSuspectData(withOpening, resized)).toHaveLength(1);
  });

  it('flags a changed span with an unmoved weight', () => {
    const cassette = panel({ panelId: 'F', type: 'floor_cassette', span: 4800 });
    expect(detectSuspectData(cassette, { ...cassette, span: 4200 })).toHaveLength(1);
  });

  it('says nothing about added or removed panels', () => {
    expect(detectSuspectData(null, base)).toEqual([]);
    expect(detectSuspectData(base, null)).toEqual([]);
  });
});

describe('cost — AC6 field-dependency exclusion', () => {
  const staleWeight: SuspectFlag[] = [
    { panelId: 'A', field: 'weightKg', reason: 'derived_field_stale', detail: '' },
  ];

  it('prices a remake despite a stale weight, because remake never reads it', () => {
    expect(COST_RULES.remake.dependsOn).toEqual([]);
    expect(costForPanel('remake', staleWeight)).toEqual({
      kind: 'priced',
      pence: REMAKE_PENCE,
      unknowns: [],
    });
  });

  it('withholds a recall with a stale weight, because logistics reads it', () => {
    expect(COST_RULES.recall.dependsOn).toContain('weightKg');
    expect(costForPanel('recall', staleWeight)).toEqual({
      kind: 'excluded',
      reason: 'suspect_field_feeds_cost',
      fields: ['weightKg'],
    });
  });

  it('marks a clean recall incomplete rather than inventing a logistics figure', () => {
    const cost = costForPanel('recall', []);
    expect(cost).toEqual({
      kind: 'priced',
      pence: REMAKE_PENCE,
      unknowns: ['recall_logistics'],
    });
  });

  it('gives an escalated panel no automatic cost', () => {
    expect(costForPanel('escalate', [])).toEqual({
      kind: 'no_automatic_cost',
      reason: 'requires_escalation',
    });
  });

  it('formats pence without floating point', () => {
    expect(formatPence(0)).toBe('£0.00');
    expect(formatPence(18_000)).toBe('£180.00');
    expect(formatPence(72_000)).toBe('£720.00');
    expect(formatPence(123_456_789)).toBe('£1,234,567.89');
  });
});
