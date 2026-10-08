export function formatCurrency(value: number | string): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export function formatPercent(value: number | string, decimals = 2): string {
  const number = Number(value);
  return `${number >= 0 ? "+" : "−"}${Math.abs(number).toFixed(decimals)}%`;
}

/** Like formatPercent, but a change too small to show reads as no change, not "−0.00%". */
export function formatChange(value: number | string, decimals = 2): string {
  const number = Number(value);
  const shown = Math.abs(number).toFixed(decimals);
  return `${number >= 0 || Number(shown) === 0 ? "+" : "−"}${shown}%`;
}

/** The direction of a change as displayed: 0 when it rounds to nothing at `decimals`. */
export function direction(value: number | string, decimals = 2): -1 | 0 | 1 {
  const shown = Number(Number(value).toFixed(decimals));
  return shown > 0 ? 1 : shown < 0 ? -1 : 0;
}

/** Text colour for a change: green up, red down, slate when unchanged. */
export function moveTone(value: number | string, decimals = 2): string {
  const sign = direction(value, decimals);
  return sign > 0 ? "text-[#35d07f]" : sign < 0 ? "text-[#f16d73]" : "text-[#9ba5b2]";
}

/** "▲ +17.7%" or "▼ −0.01%": direction is never carried by colour alone. */
export function formatMove(value: number | string, decimals = 2): string {
  const formatted = formatChange(value, decimals);
  return `${formatted.startsWith("+") ? "▲" : "▼"} ${formatted}`;
}

/** Short virtual-money amounts for dense lists: £845, £766.3k, £249.9m, £1.24bn. */
export function formatMoneyShort(value: number | string): string {
  const number = Number(value);
  const sign = number < 0 ? "−" : "";
  const absolute = Math.abs(number);
  if (absolute >= 1e9) return `${sign}£${(absolute / 1e9).toFixed(2)}bn`;
  if (absolute >= 1e6) return `${sign}£${(absolute / 1e6).toFixed(1)}m`;
  if (absolute >= 1e3) return `${sign}£${(absolute / 1e3).toFixed(1)}k`;
  return `${sign}£${absolute.toFixed(0)}`;
}

const londonTime = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit" });
const londonDay = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", weekday: "short", day: "numeric", month: "short" });
const londonWeekday = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", weekday: "short" });

/** Kick-off and lock times are shown in UK time, whatever the server's time zone. */
export function formatUkTime(value: string): string {
  return londonTime.format(new Date(value));
}

/** "Sat 10 Oct" in UK time. */
export function formatUkDay(value: string): string {
  return londonDay.format(new Date(value)).replace(",", "");
}

/** "Sat" in UK time. */
export function formatUkWeekday(value: string): string {
  return londonWeekday.format(new Date(value));
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
