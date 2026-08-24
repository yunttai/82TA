export const publicTransitFareReserveKrw = 3_000;
export const maximumTaxiBudgetKrw = 500_000;

export function expectedFareCapToTaxiBudgetKrw(expectedFareCapKrw: number, unconstrained: boolean): number {
  if (unconstrained) return maximumTaxiBudgetKrw;
  return Math.max(0, expectedFareCapKrw - publicTransitFareReserveKrw);
}

export function taxiBudgetToExpectedFareCapKrw(taxiBudgetKrw: number): number {
  if (taxiBudgetKrw >= maximumTaxiBudgetKrw) return maximumTaxiBudgetKrw;
  return Math.min(maximumTaxiBudgetKrw, taxiBudgetKrw + publicTransitFareReserveKrw);
}
