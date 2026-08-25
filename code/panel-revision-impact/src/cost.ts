/**
 * Cost model.
 *
 * Money is integer pence throughout. £180 is 18000, never 180.0.
 *
 * AC6 — a suspect panel is excluded from the total ONLY when the suspect field
 * feeds that panel's own cost calculation. Each rule therefore declares the
 * panel fields its price reads. Exclusion is the intersection of this panel's
 * suspect fields with its class's declared dependencies:
 *
 *   remake reads nothing (flat rate) -> a stale weightKg cannot affect it,
 *                                       so the panel still contributes £180.
 *   recall reads weightKg (logistics may scale with it)
 *                                    -> a stale weightKg does affect it,
 *                                       so the panel is withheld.
 *
 * The rule is derived, not stated: no panel id and no class name appears in the
 * exclusion test.
 */

import type {
  ComparedField,
  CostTotal,
  ImpactClass,
  PanelCost,
  PanelImpact,
  SuspectFlag,
} from './model.js';

/** One re-make of one panel. AC3. */
export const REMAKE_PENCE = 18_000;

interface CostRule {
  /** Automatic cost in pence, or null where there is none to compute. */
  readonly pence: number | null;
  /** Panel fields this price reads. Drives AC6 exclusion. */
  readonly dependsOn: readonly ComparedField[];
  /**
   * Cost components this tool cannot quantify. Never guessed, never zero-filled
   * — their presence makes the total incomplete.
   */
  readonly unknowns: readonly string[];
}

export const COST_RULES: Readonly<Record<ImpactClass, CostRule>> = {
  no_action: { pence: 0, dependsOn: [], unknowns: [] },
  requeue: { pence: 0, dependsOn: [], unknowns: [] },
  remake: { pence: REMAKE_PENCE, dependsOn: [], unknowns: [] },
  recall: {
    pence: REMAKE_PENCE,
    // Logistics is TBC with Robin. Modelled as an explicit unknown, not a
    // number: the total reports itself incomplete rather than understating.
    dependsOn: ['weightKg'],
    unknowns: ['recall_logistics'],
  },
  escalate: { pence: null, dependsOn: [], unknowns: [] },
};

/** Integer-only pence -> "£1,234.56". No floating point anywhere. */
export function formatPence(pence: number): string {
  const negative = pence < 0;
  const abs = Math.abs(pence);
  const pounds = Math.trunc(abs / 100);
  const remainder = abs % 100;
  const grouped = String(pounds).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${negative ? '-' : ''}£${grouped}.${String(remainder).padStart(2, '0')}`;
}

export function costForPanel(
  impactClass: ImpactClass,
  suspect: readonly SuspectFlag[],
): PanelCost {
  const rule = COST_RULES[impactClass];

  if (rule.pence === null) {
    return { kind: 'no_automatic_cost', reason: 'requires_escalation' };
  }

  const conflicting = suspect
    .map((flag) => flag.field)
    .filter((field) => rule.dependsOn.includes(field));

  if (conflicting.length > 0) {
    return {
      kind: 'excluded',
      reason: 'suspect_field_feeds_cost',
      fields: [...new Set(conflicting)].sort(),
    };
  }

  return { kind: 'priced', pence: rule.pence, unknowns: rule.unknowns };
}

const EMPTY_COUNTS: Readonly<Record<ImpactClass, number>> = {
  no_action: 0,
  requeue: 0,
  remake: 0,
  recall: 0,
  escalate: 0,
};

export function totalCost(panels: readonly PanelImpact[]): CostTotal {
  let pence = 0;
  const unknowns: string[] = [];
  const counts: Record<ImpactClass, number> = { ...EMPTY_COUNTS };

  for (const panel of panels) {
    counts[panel.classification.class] += 1;

    switch (panel.cost.kind) {
      case 'priced':
        pence += panel.cost.pence;
        for (const unknown of panel.cost.unknowns) {
          unknowns.push(`${unknown}:${panel.panelId}`);
        }
        break;
      case 'excluded':
        unknowns.push(`suspect_data:${panel.panelId}`);
        break;
      case 'no_automatic_cost':
        // Escalations carry no automatic cost by AC3, and are surfaced through
        // the approval gate rather than as a cost unknown.
        break;
    }
  }

  return {
    pence,
    formatted: formatPence(pence),
    complete: unknowns.length === 0,
    unknowns: unknowns.sort(),
    countsByClass: counts,
  };
}
