/**
 * SHOULD — geometric consistency check. Independent of classification.
 */

import { describe, expect, it } from 'vitest';
import { checkStacking } from '../src/should/stacking.js';
import { classifyRevision } from '../src/index.js';
import { build, panel, r3, r4 } from './fixtures.js';

describe('checkStacking on the real fixtures', () => {
  const report = checkStacking(r3(), r4());

  it('flags exactly one unchanged level-2 wall that no longer stacks', () => {
    expect(report.introduced).toHaveLength(1);
    expect(report.introduced[0]).toMatchObject({
      panelId: 'EW-L2-W1',
      level: 2,
      zone: 'west',
    });
  });

  it('attributes it to the level-1 wall that shrank', () => {
    expect(report.introduced[0]?.attributedTo).toEqual(['EW-L1-W1']);
    expect(report.introduced[0]?.unsupported).toEqual([{ from: 4200, to: 4800 }]);
  });

  it('flags an unchanged panel — the violation is knock-on, not direct', () => {
    const impact = classifyRevision(r3(), r4());
    const flagged = impact.panels.find((p) => p.panelId === 'EW-L2-W1');
    expect(flagged?.changeKind).toBe('unchanged');
    expect(flagged?.classification.class).toBe('no_action');
  });

  it('finds no pre-existing violations in this build', () => {
    expect(report.preExisting).toEqual([]);
  });

  it('does not flag zones where level 1 still spans level 2', () => {
    const flagged = report.introduced.map((v) => v.zone);
    expect(flagged).not.toContain('north');
    expect(flagged).not.toContain('east');
    expect(flagged).not.toContain('south');
    expect(flagged).not.toContain('internal');
  });

  it('reports nothing between identical revisions', () => {
    expect(checkStacking(r4(), r4()).introduced).toEqual([]);
  });
});

describe('checkStacking is independent of classification', () => {
  it('contributes nothing to RevisionImpact', () => {
    const impact = classifyRevision(r3(), r4());
    // The knock-on panel is priced at nothing and blocks nothing.
    expect(impact.cost.pence).toBe(72_000);
    expect(JSON.stringify(impact)).not.toContain('unsupported');
    expect(JSON.stringify(impact)).not.toContain('stacking');
  });

  it('separates violations the revision introduced from ones it inherited', () => {
    const bad = [
      panel({ panelId: 'L1', type: 'external_wall', zone: 'west', level: 1, width: 3000 }),
      panel({ panelId: 'L2', type: 'external_wall', zone: 'west', level: 2, width: 4800 }),
    ];
    const report = checkStacking(build(3, bad), build(4, bad));

    expect(report.introduced).toEqual([]);
    expect(report.preExisting).toHaveLength(1);
    expect(report.preExisting[0]?.panelId).toBe('L2');
  });

  it('ignores floor cassettes and roof panels', () => {
    const panels = [
      panel({ panelId: 'FC', type: 'floor_cassette', zone: 'floor', level: 1, width: 1200 }),
      panel({ panelId: 'RF', type: 'roof_panel', zone: 'roof', level: 2, width: 6000 }),
    ];
    expect(checkStacking(build(3, panels), build(4, panels)).introduced).toEqual([]);
  });

  it('reports every uncovered stretch of a wall', () => {
    const report = checkStacking(
      build(3, []),
      build(4, [
        panel({ panelId: 'L2-A', type: 'external_wall', zone: 'west', level: 2, width: 5000 }),
        panel({ panelId: 'L1-A', type: 'external_wall', zone: 'west', level: 1, width: 2000 }),
      ]),
    );
    expect(report.introduced[0]?.unsupported).toEqual([{ from: 2000, to: 5000 }]);
  });
});
