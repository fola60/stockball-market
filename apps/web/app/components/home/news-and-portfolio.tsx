import Link from "next/link";
import type { Instrument, NewsItem } from "@/lib/api";
import { formatCurrency, formatMove, formatChange, formatUkTime, formatUkWeekday, moveTone } from "@/lib/format";
import { playerName } from "@/lib/api";
import type { PortfolioSummary } from "@/lib/market";

export function InTheNews({ items }: { items: { item: NewsItem; instrument: Instrument }[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="news-title">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id="news-title" className="text-base font-bold">In the news</h2>
        <span className="text-[11px] text-[#77818e]">From reviewed club and press feeds</span>
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        {items.map(({ item, instrument }) => {
          const change = Number(instrument.price_change_24h);
          return (
            <article key={item.document_id} className="flex flex-col gap-3 rounded-xl border border-[#222a35] bg-[#0e131a] px-[18px] py-4">
              <p className="flex justify-between gap-2 text-[10px] text-[#77818e]"><span className="truncate">{item.source}</span><time dateTime={item.published_at} className="shrink-0">{formatUkWeekday(item.published_at)} {formatUkTime(item.published_at)}</time></p>
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-[13px] font-semibold leading-relaxed text-white hover:text-[#dce7ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{item.title}<span className="sr-only"> (opens {item.source} in a new tab)</span></a>
              <Link prefetch={false} href={`/instrument/${instrument.id}`} className="mt-auto flex items-center justify-between gap-2 rounded-lg bg-[#11171f] px-2.5 py-2 text-[11px] hover:bg-white/[0.05] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                <span className="truncate text-[#c1c8d0]">{playerName(instrument)}</span>
                <span className="shrink-0 tabular-nums slashed-zero"><b className="font-semibold">{formatCurrency(instrument.current_price)}</b> <span className={moveTone(change)}>{formatMove(change)}</span></span>
              </Link>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function PortfolioStrip({ summary }: { summary: PortfolioSummary }) {
  const up = summary.dayPnl >= 0;
  const exposure = summary.exposure;
  return (
    <section aria-label="Your portfolio today" className="flex flex-wrap items-center gap-x-9 gap-y-4 rounded-xl border border-[#222a35] bg-[#0e131a] px-[22px] py-4">
      <div><p className="mb-1.5 text-[10px] font-semibold text-[#77818e]">Your portfolio · virtual</p><strong className="text-xl font-semibold tabular-nums slashed-zero">{formatCurrency(summary.netWorth)}</strong></div>
      <div><p className="mb-1.5 text-[10px] font-semibold text-[#77818e]">Today</p><strong className={`text-sm font-semibold tabular-nums slashed-zero ${up ? "text-[#35d07f]" : "text-[#f16d73]"}`}>{up ? "▲ +" : "▼ −"}{formatCurrency(Math.abs(summary.dayPnl))} ({formatChange(summary.dayPercent)})</strong></div>
      <div><p className="mb-1.5 text-[10px] font-semibold text-[#77818e]">Cash</p><strong className="text-sm font-semibold tabular-nums slashed-zero">{formatCurrency(summary.cash)}</strong></div>
      {summary.best && <div><p className="mb-1.5 text-[10px] font-semibold text-[#77818e]">Best holding today</p><strong className="text-xs font-semibold">{playerName(summary.best.instrument)} <span className={moveTone(summary.best.change)}>{formatChange(summary.best.change)}</span></strong></div>}
      {exposure && <div className="min-w-0 flex-[1_1_260px]"><p className="mb-1.5 text-[10px] font-semibold text-[#77818e]">Biggest matchday exposure</p><strong className="text-xs font-semibold">{exposure.fixture.home.short_name} v {exposure.fixture.away.short_name} · {formatUkWeekday(exposure.fixture.kickoff_at)} {formatUkTime(exposure.fixture.kickoff_at)} · {Math.round(exposure.share)}% of holdings</strong></div>}
      <Link href="/portfolio" className="text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">View portfolio →</Link>
    </section>
  );
}
