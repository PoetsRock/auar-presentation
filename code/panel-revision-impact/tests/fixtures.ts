import { readFileSync } from 'node:fs';
import type { BuildModel } from '../src/model.js';

function load(name: string): BuildModel {
  const url = new URL(`../../${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, 'utf-8')) as BuildModel;
}

/** The real revisions shipped in the repo root. Never mutated by tests. */
export const r3 = (): BuildModel => load('build-r3.json');
export const r4 = (): BuildModel => load('build-r4.json');

/** A minimal synthetic build, for edge cases the fixtures do not contain. */
export function build(
  revision: number,
  panels: BuildModel['panels'],
  buildId = 'PLOT3-A',
): BuildModel {
  return {
    buildId,
    projectName: 'Synthetic',
    revision,
    supersedes: revision - 1,
    panels,
  };
}

export function panel(
  overrides: Partial<BuildModel['panels'][number]> & { panelId: string },
): BuildModel['panels'][number] {
  return {
    type: 'internal_wall',
    level: 1,
    zone: 'internal',
    width: 2400,
    height: 2700,
    openings: [],
    span: null,
    loadBearing: false,
    weightKg: 58,
    status: 'planned',
    ...overrides,
  };
}
