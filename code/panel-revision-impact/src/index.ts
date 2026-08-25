/** Public surface of the revision-impact library. */

export { classifyRevision, reissueQueue } from './classifyRevision.js';
export { classifyPanel } from './classify.js';
export { COST_RULES, REMAKE_PENCE, costForPanel, formatPence, totalCost } from './cost.js';
export { changedFields, diffPanels } from './diff.js';
export { detectSuspectData, materialQuantity } from './suspect.js';
export type { PanelDiff } from './diff.js';
export type * from './model.js';

// The `Should` geometric consistency check is deliberately NOT re-exported
// here. It is imported from './should/stacking.js' by callers that want it, so
// that deleting the `should/` directory cannot break the core.
