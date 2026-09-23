export function formatCurrency(value: number | string): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export function formatPercent(value: number | string): string {
  const number = Number(value);
  return `${number >= 0 ? "+" : "−"}${Math.abs(number).toFixed(2)}%`;
}

export function formatCompact(value: number | string): string {
  return new Intl.NumberFormat("en-GB", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number(value));
}

export function initials(value: string): string {
  return value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "SB";
}
