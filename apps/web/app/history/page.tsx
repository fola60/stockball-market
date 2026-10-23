import type { Metadata } from "next";
import Link from "next/link";
import { AuthTrigger } from "../components/auth-dialog";
import { Label, Shell, panel } from "../components/market-shell";
import { HISTORY_PAGE_SIZE, getHistoryPageData } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

export const metadata: Metadata = { title: "Trade history — Stockball" };
export const dynamic = "force-dynamic";

type PageProps = { searchParams: Promise<{ page?: string }> };

function historyHref(page: number): string {
  return page > 1 ? `/history?page=${page}` : "/history";
}

export default async function HistoryPage({ searchParams }: PageProps) {
  const requested = Number((await searchParams).page ?? "1");
  const page = Number.isInteger(requested) && requested > 0 ? requested : 1;
  const { account, trades, hasMore, tickerStocks, searchInstruments } = await getHistoryPageData(page);

  if (!account) {
    return (
      <Shell active="history" account={null} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
        <section className="grid min-h-[calc(100vh-104px)] place-items-center px-4 py-12">
          <div className={`${panel} w-full max-w-[480px] p-8 text-center`}>
            <h1 className="text-2xl font-semibold tracking-[-0.025em]">Your trade history</h1>
            <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-[#8d97a3]">Sign in to see every trade you have made.</p>
            <AuthTrigger className="mt-6 h-11 rounded-lg bg-[#8fb5ff] px-6 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Sign in</AuthTrigger>
          </div>
        </section>
      </Shell>
    );
  }

  const firstNumber = (page - 1) * HISTORY_PAGE_SIZE + 1;

  return (
    <Shell active="history" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <section className="mx-auto w-full max-w-[1100px] min-w-0 px-3 py-6 md:px-7">
        <div className="mb-6">
          <h1 className="text-[30px] font-semibold leading-tight tracking-[-0.03em] md:text-[34px]">Trade history</h1>
          <p className="mt-2 text-sm font-medium text-[#8d97a3]">Every order you have filled, newest first. Totals include the trading fee.</p>
        </div>

        <article className={panel}>
          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-left">
                <thead className="border-b border-[#202832] bg-black/10 text-[11px] uppercase tracking-wider text-[#65707d]">
                  <tr>
                    <th className="py-2.5 pl-5">Date</th>
                    <th>Order</th>
                    <th className="text-right">Quantity</th>
                    <th className="text-right">Avg price</th>
                    <th className="text-right">Fee</th>
                    <th className="pr-5 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => {
                    const bought = trade.side === "BUY";
                    const gross = Number(trade.gross_amount);
                    const fee = Number(trade.fee_amount);
                    return (
                      <tr key={trade.id} className="border-b border-[#202832] text-xs text-[#9ba5b2] last:border-b-0 hover:bg-white/[0.018]">
                        <td className="py-3 pl-5 font-mono text-[11px]">
                          <time dateTime={trade.executed_at}>{new Date(trade.executed_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
                        </td>
                        <td>
                          <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-extrabold ${bought ? "bg-[#35d07f]/10 text-[#35d07f]" : "bg-[#f16d73]/10 text-[#f16d73]"}`}>{bought ? "BUY" : "SELL"}</span>
                          <Link prefetch={false} href={`/instrument/${trade.instrument_id}`} className="font-semibold text-white hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{trade.player_name}</Link>
                        </td>
                        <td className="text-right font-mono">{Number(trade.shares).toLocaleString("en-GB", { maximumFractionDigits: 4 })}</td>
                        <td className="text-right font-mono">{formatCurrency(trade.execution_price)}</td>
                        <td className="text-right font-mono">{fee > 0 ? formatCurrency(fee) : "—"}</td>
                        <td className="pr-5 text-right font-mono font-bold text-white">{bought ? "−" : "+"}{formatCurrency(bought ? gross + fee : gross - fee)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 py-14 text-center">
              <p className="text-base font-semibold text-white">{page > 1 ? "No more trades" : "No trades yet"}</p>
              <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-[#7f8995]">Trades appear here as soon as they fill.</p>
              <Link href={page > 1 ? "/history" : "/"} className="mt-5 inline-flex h-9 items-center rounded-lg bg-[#8fb5ff] px-4 text-[11px] font-extrabold text-[#080b10]">{page > 1 ? "Back to the latest trades" : "Explore player stocks"}</Link>
            </div>
          )}
        </article>

        {(page > 1 || hasMore) && (
          <nav aria-label="Trade history pages" className="mt-4 flex items-center justify-between text-xs">
            <Label>{trades.length > 0 ? `Trades ${firstNumber}–${firstNumber + trades.length - 1}` : ""}</Label>
            <div className="flex gap-2">
              {page > 1 && <Link href={historyHref(page - 1)} className="h-9 rounded-lg border border-[#2a3441] px-4 font-bold leading-9 text-[#c4cbd3] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Newer</Link>}
              {hasMore && <Link href={historyHref(page + 1)} className="h-9 rounded-lg border border-[#2a3441] px-4 font-bold leading-9 text-[#c4cbd3] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Older</Link>}
            </div>
          </nav>
        )}
      </section>
    </Shell>
  );
}
