import type { Metadata } from "next";
import Link from "next/link";
import { AuthTrigger } from "../components/auth-dialog";
import { Label, Shell, panel } from "../components/market-shell";
import { ClubBadge, PlayerAvatar } from "../components/player-media";
import { getPortfolioPageData, playerName, type Instrument } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";

export const metadata: Metadata = { title: "Portfolio — Stockball" };
export const dynamic = "force-dynamic";

type Holding = {
  instrument: Instrument;
  quantity: number;
  value: number;
  dayChange: number;
  dayPnl: number;
  allocation: number;
};

export default async function PortfolioPage() {
  const { account, instruments, portfolio, activity, tickerStocks, searchInstruments } = await getPortfolioPageData();

  if (!account || !portfolio) {
    return (
      <Shell active="portfolio" account={null} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
        <section className="grid min-h-[calc(100vh-104px)] place-items-center px-4 py-12">
          <div className={`${panel} w-full max-w-[520px] p-7 text-center sm:p-10`}>
            <div className="mx-auto grid size-12 place-items-center rounded-xl bg-[#8fb5ff]/10 text-[#8fb5ff]" aria-hidden="true">
              <svg viewBox="0 0 24 24" className="size-6" fill="none"><rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" strokeWidth="1.7"/><path d="M7 10h10M7 14h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>
            </div>
            <h1 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">Your portfolio starts here</h1>
            <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-[#8d97a3]">Browse every player stock without an account. Sign in when you are ready to trade with virtual cash and track your holdings.</p>
            <div className="mx-auto mt-7 grid max-w-xs gap-3 sm:grid-cols-2">
              <AuthTrigger className="h-11 rounded-lg bg-[#8fb5ff] px-5 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Sign in</AuthTrigger>
              <AuthTrigger mode="register" className="h-11 rounded-lg border border-[#2a3441] px-5 text-xs font-bold text-[#c4cbd3] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Create account</AuthTrigger>
            </div>
            <Link href="/" className="mt-6 inline-flex text-xs font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Explore the market →</Link>
          </div>
        </section>
      </Shell>
    );
  }

  const instrumentById = new Map(instruments.map((instrument) => [instrument.id, instrument]));
  const rawHoldings = portfolio.positions.flatMap((position) => {
    const instrument = instrumentById.get(position.instrument_id);
    if (!instrument) return [];
    const quantity = Number(position.quantity);
    const price = Number(instrument.current_price);
    const dayChange = Number(instrument.price_change_24h);
    const previousPrice = 1 + dayChange / 100 > 0 ? price / (1 + dayChange / 100) : price;
    return [{ instrument, quantity, value: quantity * price, dayChange, dayPnl: quantity * (price - previousPrice) }];
  });
  const invested = rawHoldings.reduce((total, holding) => total + holding.value, 0);
  const holdings: Holding[] = rawHoldings
    .map((holding) => ({ ...holding, allocation: invested > 0 ? (holding.value / invested) * 100 : 0 }))
    .sort((a, b) => b.value - a.value);
  const cash = Number(portfolio.cash_balance);
  const portfolioValue = cash + invested;
  const dayPnl = holdings.reduce((total, holding) => total + holding.dayPnl, 0);
  const dayPercent = portfolioValue - dayPnl > 0 ? (dayPnl / (portfolioValue - dayPnl)) * 100 : 0;
  const allocation = holdings.reduce<Record<string, number>>((groups, holding) => {
    const role = holding.instrument.player_position ?? "Other";
    groups[role] = (groups[role] ?? 0) + holding.value;
    return groups;
  }, {});

  return (
    <Shell active="portfolio" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <section className="mx-auto w-full max-w-[1500px] min-w-0 px-3 py-6 md:px-7">
        <div className="mb-7 flex items-end justify-between">
          <div>
            <h1 className="text-[30px] font-semibold leading-tight tracking-[-0.03em] md:text-[34px]">Portfolio</h1>
            <p className="mt-2 max-w-[62ch] text-sm font-medium leading-relaxed text-[#8d97a3]">Signed in as <span className="text-[#c5ccd4]">{account.display_name}</span></p>
          </div>
          <Link href="/" className="hidden h-10 items-center rounded-lg bg-[#8fb5ff] px-4 text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] sm:flex">Explore market <span className="ml-3 text-base">→</span></Link>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4 md:gap-4">
          {[
            ["Portfolio value", formatCurrency(portfolioValue), `${holdings.length} active holding${holdings.length === 1 ? "" : "s"}`],
            ["Available cash", formatCurrency(cash), `${portfolioValue > 0 ? ((cash / portfolioValue) * 100).toFixed(1) : "0.0"}% buying power`],
            ["Invested", formatCurrency(invested), "Current market value"],
            ["Today", formatCurrency(dayPnl), formatPercent(dayPercent)],
          ].map((metric, index) => (
            <article key={metric[0]} className={`${panel} p-4`}>
              <Label>{metric[0]}</Label>
              <strong className="font-mono text-xl font-semibold">{metric[1]}</strong>
              <p className={`mt-1.5 text-[11px] ${index === 3 ? (dayPnl >= 0 ? "text-[#35d07f]" : "text-[#f16d73]") : "text-[#77818e]"}`}>{metric[2]}</p>
            </article>
          ))}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(720px,1.65fr)_minmax(290px,0.62fr)]">
          <article className={panel}>
            <div className="flex items-center justify-between p-5 pb-4">
              <div><Label>Open positions</Label><h2 className="text-base font-bold">Your holdings</h2></div>
              <span className="text-[11px] font-semibold text-[#77818e]">Live database</span>
            </div>
            {holdings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] border-collapse text-left">
                  <thead className="border-y border-[#202832] bg-black/10 text-[11px] uppercase tracking-wider text-[#65707d]"><tr><th className="py-2.5 pl-5">Player</th><th>Shares</th><th>Current</th><th>Market value</th><th>24h</th><th>Allocation</th></tr></thead>
                  <tbody>{holdings.map((holding) => (
                    <tr key={holding.instrument.id} className="border-b border-[#202832] text-[11px] text-[#9ba5b2] hover:bg-white/[0.018]">
                      <td className="py-3 pl-5"><div className="flex items-center gap-3"><PlayerAvatar instrument={holding.instrument} name={playerName(holding.instrument)} className="size-8" /><div className="min-w-0"><strong className="block text-xs text-white">{playerName(holding.instrument)}</strong><small className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[#697481]"><ClubBadge instrument={holding.instrument} className="size-3" />{holding.instrument.player_club ?? "Club unavailable"} · {holding.instrument.player_position ?? "—"}</small></div></div></td>
                      <td className="font-mono">{holding.quantity.toLocaleString("en-GB", { maximumFractionDigits: 4 })}</td>
                      <td className="font-mono font-bold text-white">{formatCurrency(holding.instrument.current_price)}</td>
                      <td className="font-mono font-bold text-white">{formatCurrency(holding.value)}</td>
                      <td className={`font-mono ${holding.dayChange >= 0 ? "text-[#35d07f]" : "text-[#f16d73]"}`}>{formatPercent(holding.dayChange)}</td>
                      <td><div className="flex items-center gap-2"><span className="w-12 font-mono">{holding.allocation.toFixed(1)}%</span><span className="h-1 w-12 overflow-hidden rounded bg-[#242c37]"><i className="block h-full bg-[#8fb5ff]" style={{ width: `${holding.allocation}%` }}/></span></div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : (
              <div className="border-t border-[#202832] px-5 py-14 text-center">
                <p className="text-base font-semibold text-white">No player stocks yet</p>
                <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-[#7f8995]">Your database-backed portfolio is ready. Explore the market to make its first virtual trade.</p>
                <Link href="/" className="mt-5 inline-flex h-9 items-center rounded-lg bg-[#8fb5ff] px-4 text-[11px] font-extrabold text-[#080b10]">Explore player stocks</Link>
              </div>
            )}
          </article>

          <article className={`${panel} p-5`}>
            <div className="flex items-end justify-between"><div><Label>Allocation</Label><h2 className="text-base font-bold">By position</h2></div><span className="text-[11px] text-[#77818e]">{holdings.length} holdings</span></div>
            {Object.keys(allocation).length > 0 ? (
              <div className="mt-5 space-y-4">{Object.entries(allocation).sort((a, b) => b[1] - a[1]).map(([role, value]) => {
                const percentage = invested > 0 ? (value / invested) * 100 : 0;
                return <div key={role}><div className="mb-2 flex justify-between text-xs"><span className="text-[#9aa4af]">{role}</span><strong className="font-mono font-medium">{percentage.toFixed(1)}%</strong></div><div className="h-1.5 overflow-hidden rounded-full bg-[#242c37]"><i className="block h-full bg-[#8fb5ff]" style={{ width: `${percentage}%` }}/></div></div>;
              })}</div>
            ) : <p className="mt-5 text-xs leading-relaxed text-[#77818e]">Position allocation will appear after the first trade.</p>}
          </article>
        </div>

        <article id="activity" className={`${panel} mt-4 p-5`}>
          <div><Label>Latest trades</Label><h2 className="text-base font-bold">Recent activity</h2></div>
          {activity.length > 0 ? <div className="mt-3 divide-y divide-[#202832]">{activity.map((trade) => {
            const bought = trade.side === "BUY";
            return <div key={trade.id} className="grid grid-cols-[34px_minmax(0,1fr)_auto] items-center gap-3 py-3"><span className={`grid size-8 place-items-center rounded-full text-xs ${bought ? "bg-[#35d07f]/10 text-[#35d07f]" : "bg-[#f16d73]/10 text-[#f16d73]"}`}>{bought ? "↗" : "↘"}</span><p className="min-w-0"><strong className="block truncate text-[11px]">{bought ? "Bought" : "Sold"} {Number(trade.shares).toLocaleString("en-GB", { maximumFractionDigits: 4 })} {trade.player_name}</strong><small className="mt-1 block text-[11px] text-[#65707d]"><time dateTime={trade.executed_at}>{new Date(trade.executed_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</time> · {formatCurrency(trade.execution_price)} per share</small></p><strong className="font-mono text-[11px]">{formatCurrency(trade.gross_amount)}</strong></div>;
          })}</div> : <p className="mt-4 border-t border-[#202832] pt-5 text-xs text-[#77818e]">No trades have been recorded for this account.</p>}
        </article>

        <p className="mt-4 text-center text-[11px] text-[#555f6b]">Stockball uses virtual cash. Balances, positions, and trades are read from the live Stockball database.</p>
      </section>
    </Shell>
  );
}
