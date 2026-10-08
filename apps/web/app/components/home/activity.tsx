import Link from "next/link";
import type { Account, MarketTrade, TraderStanding } from "@/lib/api";
import { formatCurrency, formatMove, formatUkTime, moveTone } from "@/lib/format";
import { AuthTrigger } from "../auth-dialog";
import { panel } from "../market-shell";
import { BotBadge } from "../trader-identity";

export function LiveTrades({ trades }: { trades: MarketTrade[] }) {
  return (
    <section aria-labelledby="tape-title" className={`${panel} min-w-0 flex-[3_1_600px]`}>
      <div className="px-[18px] pb-3 pt-4">
        <h2 id="tape-title" className="text-sm font-bold">Live trades</h2>
        <p className="mt-1.5 text-[10px] text-[#77818e]">Largest trades in the last 3 hours</p>
      </div>
      {trades.length === 0 ? (
        <p className="border-t border-[#1b222c] px-[18px] py-10 text-center text-xs text-[#77818e]">No trades in the last 3 hours.</p>
      ) : (
        <ol>
          {trades.map((trade) => {
            const bought = trade.side === "BUY";
            return (
              <li key={trade.trade_id} className="grid grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3 border-t border-[#1b222c] px-[18px] py-2.5 text-[11px] sm:grid-cols-[44px_minmax(0,1.1fr)_minmax(0,1.4fr)_72px]">
                <time dateTime={trade.executed_at} className="text-[#77818e] tabular-nums">{formatUkTime(trade.executed_at)}</time>
                <span className="min-w-0">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <Link prefetch={false} href={`/traders/${trade.account_id}`} className="truncate text-xs font-semibold text-white hover:text-[#dce7ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{trade.trader_name}</Link>
                    {trade.trader_kind === "BOT" && <BotBadge />}
                  </span>
                  {trade.strategy && <small className="mt-1 block truncate text-[10px] text-[#77818e]">{trade.strategy}</small>}
                  <small className="mt-1 block truncate text-[10px] text-[#c1c8d0] sm:hidden"><b className={bought ? "text-[#35d07f]" : "text-[#f16d73]"}>{bought ? "Bought" : "Sold"}</b> {trade.player_name}</small>
                </span>
                <span className="hidden min-w-0 truncate text-[#c1c8d0] sm:block"><b className={bought ? "text-[#35d07f]" : "text-[#f16d73]"}>{bought ? "Bought" : "Sold"}</b> {Number(trade.shares).toLocaleString("en-GB", { maximumFractionDigits: 1 })} <Link prefetch={false} href={`/instrument/${trade.instrument_id}`} className="hover:text-[#dce7ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{trade.player_name}</Link> at {formatCurrency(trade.execution_price)}</span>
                <b className="text-right text-xs font-semibold tabular-nums slashed-zero">{formatCurrency(Math.round(Number(trade.gross_amount))).replace(/\.00$/, "")}</b>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function TopTraders({ leaders, peopleOnBoard, account }: { leaders: TraderStanding[]; peopleOnBoard: number; account: Account | null }) {
  return (
    <section aria-labelledby="leaders-title" className={`${panel} flex min-w-0 flex-[2_1_340px] flex-col`}>
      <div className="flex items-center justify-between gap-2.5 px-[18px] pb-3 pt-4">
        <h2 id="leaders-title" className="text-sm font-bold">Top traders</h2>
        <Link href="/leaderboard" className="text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Leaderboard →</Link>
      </div>
      <ol>
        {leaders.map((leader) => {
          const change = Number(leader.day_change_percent);
          return (
            <li key={leader.account_id} className="border-t border-[#1b222c]">
              <Link prefetch={false} href={`/traders/${leader.account_id}`} className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2.5 px-[18px] py-2.5 hover:bg-white/[0.025] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff]">
                <span className="text-[11px] font-bold text-[#65707d]">{leader.rank}</span>
                <strong className="min-w-0 truncate text-xs font-semibold">{leader.display_name}</strong>
                <span className="text-right">
                  <b className="block text-xs font-semibold tabular-nums slashed-zero">{formatCurrency(Math.round(Number(leader.net_worth))).replace(/\.00$/, "")}</b>
                  <small className={`mt-1 block text-[10px] tabular-nums slashed-zero ${moveTone(change)}`}>{formatMove(change)} today</small>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      {!account && (
        <div className="mt-auto border-t border-[#202630] px-[18px] py-3.5">
          <p className="text-[11px] leading-relaxed text-[#aeb7c2]">{peopleOnBoard === 0 ? "No people on the board yet. " : ""}Start with £100,000 in virtual cash and see where you finish.</p>
          <AuthTrigger mode="register" className="mt-2.5 h-[34px] rounded-lg bg-[#8fb5ff] px-3.5 text-[11px] font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e131a]">Join the leaderboard</AuthTrigger>
        </div>
      )}
    </section>
  );
}
