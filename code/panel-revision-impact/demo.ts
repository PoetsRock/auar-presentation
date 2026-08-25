/**
 * Demo entry point. Not part of the library — it only reads the two revisions
 * from the repo root and prints what classifyRevision returns.
 *
 *   npm run demo         human-readable report
 *   npm run demo:json    the serialisable change record
 */

import { readFileSync } from 'node:fs';
import { classifyRevision, formatPence, reissueQueue } from './src/index.js';
import { checkStacking } from './src/should/stacking.js';
import type { BuildModel, PanelImpact } from './src/model.js';

const B = '\x1b[1m';
const DIM = '\x1b[2m';
const RED = '\x1b[31m';
const AMBER = '\x1b[33m';
const GREEN = '\x1b[32m';
const R = '\x1b[0m';

function load(name: string): BuildModel {
  return JSON.parse(
    readFileSync(new URL(`../${name}`, import.meta.url), 'utf-8'),
  ) as BuildModel;
}

const argv = process.argv.slice(2);
const flags = argv.filter((a) => a.startsWith('--'));
const files = argv.filter((a) => !a.startsWith('--'));

const previous = load(files[0] ?? 'build-r3.json');
const next = load(files[1] ?? 'build-r4.json');

const impact = classifyRevision(previous, next);

if (flags.includes('--json')) {
  console.log(JSON.stringify(impact, null, 2));
  process.exit(0);
}

const COLOUR: Record<string, string> = {
  no_action: DIM,
  requeue: GREEN,
  remake: AMBER,
  recall: AMBER,
  escalate: RED,
};

const line = (n = 74) => console.log(DIM + '─'.repeat(n) + R);

console.log(
  `\n${B}${impact.buildId}${R} — ${next.projectName}` +
    `   revision ${B}${impact.from} → ${impact.to}${R}` +
    (Math.abs(impact.revisionGap) > 1 ? `  ${AMBER}(${impact.revisionGap} steps)${R}` : ''),
);
line();

const actionable = impact.panels.filter((p) => p.classification.class !== 'no_action');
const unchanged = impact.panels.length - actionable.length;

console.log(
  `${B}${actionable.length}${R} of ${impact.panels.length} panels need a decision.` +
    `  ${DIM}${unchanged} unaffected.${R}\n`,
);

const row = (p: PanelImpact) => {
  const c = COLOUR[p.classification.class] ?? '';
  const cost =
    p.cost.kind === 'priced'
      ? formatPence(p.cost.pence)
      : p.cost.kind === 'excluded'
        ? 'withheld'
        : '—';
  const unknown = p.cost.kind === 'priced' && p.cost.unknowns.length > 0 ? ' + logistics' : '';
  const flag = p.suspect.length > 0 ? `  ${AMBER}⚑ suspect data${R}` : '';
  console.log(
    `  ${p.panelId.padEnd(11)} ${DIM}${p.status.padEnd(13)}${R}` +
      `${c}${p.classification.class.padEnd(10)}${R}` +
      `${(cost + unknown).padStart(13)}${flag}`,
  );
};

console.log(`  ${DIM}${'PANEL'.padEnd(11)} ${'STATUS'.padEnd(13)}${'ACTION'.padEnd(10)}${'COST'.padStart(13)}${R}`);
actionable.forEach(row);

line();
console.log(
  `  ${B}Total${R}${impact.cost.formatted.padStart(28)}` +
    (impact.cost.complete ? `   ${GREEN}complete${R}` : `   ${AMBER}INCOMPLETE${R}`),
);
if (!impact.cost.complete) {
  console.log(`  ${AMBER}unknowns:${R} ${impact.cost.unknowns.join(', ')}`);
}

if (impact.suspectData.length > 0) {
  console.log(`\n${B}Data quality${R}`);
  for (const flag of impact.suspectData) {
    console.log(`  ${AMBER}⚑${R} ${flag.panelId} — ${flag.detail}`);
    console.log(`    ${DIM}flagged, but still priced: remake is flat rate and never reads ${flag.field}.${R}`);
  }
}

const stacking = checkStacking(previous, next);
if (stacking.introduced.length > 0) {
  console.log(`\n${B}Geometric consistency${R} ${DIM}(Should — separate from classification)${R}`);
  for (const v of stacking.introduced) {
    const gaps = v.unsupported.map((g) => `${g.from}–${g.to}mm`).join(', ');
    console.log(
      `  ${AMBER}⚑${R} ${v.panelId} (level ${v.level}, ${v.zone}) unsupported over ${gaps}`,
    );
    console.log(`    ${DIM}caused by ${v.attributedTo.join(', ')} — this panel did not change.${R}`);
  }
}

line();
const queue = reissueQueue(impact);
if (queue.approved) {
  console.log(`${GREEN}${B}Approved.${R} ${queue.instructions.length} instructions ready for the factory queue.`);
} else {
  console.log(`${RED}${B}APPROVAL BLOCKED${R} — cannot auto-re-issue:`);
  for (const r of queue.blockedBy) {
    console.log(`  ${RED}✕${R} ${r.panelId} — ${r.reason.replace(/_/g, ' ')}`);
  }
  console.log(`  ${DIM}No re-issue instructions are emitted at all while this stands.${R}`);
}
console.log();
