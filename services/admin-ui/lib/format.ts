export function label(value: string) {
  return value
    ? value
        .toLowerCase()
        .split("_")
        .map((v) => v[0].toUpperCase() + v.slice(1))
        .join(" ")
    : "-";
}
export function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function time(value?: string) {
  return value ? new Date(value).toLocaleString() : "-";
}
export function metricText(run: Run) {
  const metrics = run.metrics ?? {};
  if (metrics.dry_run)
    return `Preview: ${formatNumber(metrics.projected_positions ?? run.successful_items)} positions · ${formatNumber(metrics.bot_shares)} bot shares`;
  if (metrics.credited_amount !== undefined)
    return `${formatNumber(metrics.configured_policies)} policies · ${money(String(metrics.credited_amount))} credited`;
  const entries = Object.entries(metrics);
  return entries.length
    ? entries
        .slice(0, 2)
        .map(([k, v]) => `${label(k)}: ${v}`)
        .join(" · ")
    : "-";
}
export function duration(run: Run) {
  if (typeof run.metrics?.elapsed_ms === "number")
    return `${run.metrics.elapsed_ms} ms`;
  if (run.completed_at)
    return `${Math.max(0, Math.round((new Date(run.completed_at).getTime() - new Date(run.enqueued_at).getTime()) / 1000))} s`;
  return "-";
}
export function money(value: string) {
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
export function signedMoney(value?: string) {
  if (value === undefined) return "-";
  const amount = Number(value);
  return `${amount > 0 ? "+" : ""}${money(value)}`;
}
export function priceMove(oldPrice?: string, newPrice?: string) {
  return oldPrice === undefined || newPrice === undefined
    ? "-"
    : `${money(oldPrice)} → ${money(newPrice)}`;
}
export function metricNumber(value: unknown, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
export function formatNumber(value: unknown) {
  return metricNumber(value).toLocaleString();
}
export function rangeText(minimum: unknown, maximum: unknown, average: unknown) {
  if (minimum === undefined || maximum === undefined) return "-";
  return `${formatNumber(minimum)}-${formatNumber(maximum)} (avg ${formatNumber(average)})`;
}

