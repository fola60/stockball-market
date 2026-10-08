/** A compact price line. Decorative: every sparkline sits next to its signed change. */
export function Sparkline({ prices, rising, className = "h-8 w-full", area = true }: { prices: number[]; rising: boolean; className?: string; area?: boolean }) {
  const values = prices.length > 1 ? prices : [prices[0] ?? 0, prices[0] ?? 0];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const flat = maximum - minimum < 1e-9;
  const points = values.map((value, index) => ({
    x: (index / (values.length - 1)) * 112,
    y: flat ? 16 : 29 - ((value - minimum) / (maximum - minimum)) * 26,
  }));
  const line = points.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const baseline = points[0].y;

  return (
    <svg viewBox="0 0 112 32" preserveAspectRatio="none" aria-hidden="true" className={`${className} ${rising ? "text-[#35d07f]" : "text-[#f16d73]"}`}>
      {area && <polygon points={`0,32 ${line} 112,32`} fill="currentColor" fillOpacity="0.14" />}
      {area && <line x1="0" y1={baseline} x2="112" y2={baseline} stroke="currentColor" strokeWidth="1" strokeDasharray="4 3" strokeOpacity="0.5" vectorEffect="non-scaling-stroke" />}
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
