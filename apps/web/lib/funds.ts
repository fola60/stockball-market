import type { IndexFund } from "./api";

/** Category order on the site: broad funds first, clubs last. */
export const FUND_CATEGORIES = ["Market", "Positions", "Performance", "Signals", "Club groups", "Nationality and age", "Clubs"] as const;

export const fundCategory = (fund: Pick<IndexFund, "category" | "index_kind">) =>
  fund.category ?? (fund.index_kind === "TEAM" ? "Clubs" : "Other");

/** Funds grouped by category, in site order. */
export function groupFunds<T extends Pick<IndexFund, "category" | "index_kind">>(funds: T[]) {
  const groups = new Map<string, T[]>();
  for (const fund of funds) groups.set(fundCategory(fund), [...(groups.get(fundCategory(fund)) ?? []), fund]);
  const rank = (category: string) => {
    const index = (FUND_CATEGORIES as readonly string[]).indexOf(category);
    return index === -1 ? FUND_CATEGORIES.length : index;
  };
  return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b)).map(([category, members]) => ({ category, funds: members }));
}

/** A price series worth charting: a brand-new fund's flat line says nothing. */
export const hasMovement = (prices: number[]) =>
  prices.length > 1 && Math.max(...prices) - Math.min(...prices) > Math.max(...prices) * 1e-5;
