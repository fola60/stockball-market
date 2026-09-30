import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Label, Shell, panel } from "../../components/market-shell";
import { YouBadge } from "../../components/trader-identity";
import { getTraderPageData } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";

export const dynamic = "force-dynamic";

type PageProps = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const data = await getTraderPageData(id);
  if (!data) return { title: "Trader not found — Stockball" };
  return { title: `${data.profile.trader.display_name} — Stockball` };
}

export default async function TraderPage({ params }: PageProps) {
  const { id } = await params;
  const data = await getTraderPageData(id);
  if (!data) notFound();

  const { account, tickerStocks, searchInstruments, profile } = data;
  const { trader, holdings, recent_trades: trades } = profile;
  const isViewer = account?.id === trader.account_id;
  const holdingsValue = Number(trader.holdings_value);
  const netWorth = Number(trader.net_worth);

  return (
    <Shell active="leaderboard" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <section className="mx-auto w-full max-w-[1220px] min-w-0 px-3 py-6 md:px-7 md:py-8">
        <Link href="/leaderboard" className="mb-6 inline-flex h-9 items-center gap-2 rounded-lg px-2 text-[11px] font-semibold text-[#7f8995] hover:bg-white/[0.035] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4" fill="none"><path d="m12.5 4.5-5 5.5 5 5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Leaderboard
        </Link>

        <header className="mb-7 flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div className="flex min-w-0 items-center gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-3xl font-semibold leading-tight tracking-[-0.03em] md:text-[38px]">{trader.display_name}</h1>
                {isViewer && <YouBadge />}
              </div>
              <p className="mt-1.5 text-xs font-medium text-[#818b97]">Rank #{trader.rank.toLocaleString("en-GB")}</p>
            </div>
          </div>
          {isViewer && <Link href="/portfolio" className="inline-flex h-10 items-center self-start rounded-lg bg-[#8fb5ff] px-4 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] md:self-auto">Manage your portfolio <span className="ml-3 text-base">→</span></Link>}
        </header>

        <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4 md:gap-4">
          {[
            ["Net worth", formatCurrency(trader.net_worth), `Rank #${trader.rank.toLocaleString("en-GB")}`],
            ["Cash", formatCurrency(trader.cash_balance), `${netWorth > 0 ? ((Number(trader.cash_balance) / netWorth) * 100).toFixed(1) : "0.0"}% of net worth`],
            ["Holdings", formatCurrency(trader.holdings_value), "At current prices"],
            ["Players held", trader.holdings_count.toLocaleString("en-GB"), `${trades.length > 0 ? "Active" : "No recent"} trading`],
          ].map(([label, value, detail]) => (
            <article key={label} className={`${panel} p-4`}>
              <Label>{label}</Label>
              <strong className="font-mono text-xl font-semibold tabular-nums slashed-zero">{value}</strong>
              <p className="mt-1.5 text-[11px] text-[#77818e]">{detail}</p>
            </article>
          ))}
        </div>

        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,0.7fr)]">
          <article className={panel}>
            <div className="p-5 pb-4"><Label>Portfolio</Label><h2 className="text-base font-bold">Holdings</h2></div>
            {holdings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] border-collapse text-left">
                  <thead className="border-y border-[#202832] bg-black/10 text-[11px] uppercase tracking-wider text-[#65707d]"><tr><th className="py-2.5 pl-5">Player</th><th className="text-right">Shares</th><th className="text-right">Price</th><th className="text-right">Value</th><th className="text-right">24h</th><th className="pr-5 text-right">Share</th></tr></thead>
                  <tbody>{holdings.map((holding) => {
                    const change = Number(holding.price_change_24h);
                    const allocation = holdingsValue > 0 ? (Number(holding.market_value) / holdingsValue) * 100 : 0;
                    return (
                      <tr key={holding.instrument_id} className="border-b border-[#202832] text-[11px] text-[#9ba5b2] last:border-b-0 hover:bg-white/[0.018]">
                        <td className="py-3 pl-5"><Link href={`/instrument/${holding.instrument_id}`} className="block text-xs font-bold text-white hover:text-[#dce7ff]">{holding.player_name}</Link><small className="mt-0.5 block text-[11px] text-[#697481]">{holding.player_club ?? "Club unavailable"} · {holding.player_position ?? "—"}</small></td>
                        <td className="text-right font-mono">{Number(holding.quantity).toLocaleString("en-GB", { maximumFractionDigits: 4 })}</td>
                        <td className="text-right font-mono">{formatCurrency(holding.current_price)}</td>
                        <td className="text-right font-mono font-bold text-white">{formatCurrency(holding.market_value)}</td>
                        <td className={`text-right font-mono ${change >= 0 ? "text-[#35d07f]" : "text-[#f16d73]"}`}>{formatPercent(change)}</td>
                        <td className="pr-5 text-right font-mono">{allocation.toFixed(1)}%</td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            ) : (
              <p className="border-t border-[#202832] px-5 py-12 text-center text-xs text-[#77818e]">{trader.display_name} doesn&apos;t hold any player shares right now.</p>
            )}
          </article>

          <article className={`${panel} p-5`}>
            <Label>Latest trades</Label><h2 className="text-base font-bold">Recent activity</h2>
            {trades.length > 0 ? <div className="mt-3 divide-y divide-[#202832]">{trades.map((trade) => {
              const bought = trade.side === "BUY";
              return (
                <div key={trade.trade_id} className="grid grid-cols-[30px_minmax(0,1fr)_auto] items-center gap-3 py-3">
                  <span className={`grid size-7 place-items-center rounded-full text-xs ${bought ? "bg-[#35d07f]/10 text-[#35d07f]" : "bg-[#f16d73]/10 text-[#f16d73]"}`} aria-hidden="true">{bought ? "↗" : "↘"}</span>
                  <p className="min-w-0"><strong className="block truncate text-[11px]">{bought ? "Bought" : "Sold"} {Number(trade.shares).toLocaleString("en-GB", { maximumFractionDigits: 4 })} <Link href={`/instrument/${trade.instrument_id}`} className="hover:text-[#dce7ff]">{trade.player_name}</Link></strong><small className="mt-1 block text-[11px] text-[#65707d]"><time dateTime={trade.executed_at}>{new Date(trade.executed_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</time> · {formatCurrency(trade.execution_price)}</small></p>
                  <strong className="font-mono text-[11px]">{formatCurrency(trade.gross_amount)}</strong>
                </div>
              );
            })}</div> : <p className="mt-4 border-t border-[#202832] pt-5 text-xs text-[#77818e]">No trades yet.</p>}
          </article>
        </div>

        <p className="mt-4 text-center text-[11px] text-[#555f6b]">Stockball uses virtual cash. Only display names, holdings, and trades are public.</p>
      </section>
    </Shell>
  );
}
