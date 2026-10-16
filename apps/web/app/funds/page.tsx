import type { Metadata } from "next";
import Link from "next/link";
import { Shell, panel } from "../components/market-shell";
import { FundBadge, PausedTag } from "../components/fund-media";
import { Sparkline } from "../components/sparkline";
import { getFundsPageData } from "@/lib/api";
import { formatChange, formatCurrency, formatMoneyShort, moveTone } from "@/lib/format";

export const metadata: Metadata = { title: "Team funds — Stockball" };
export const dynamic = "force-dynamic";

export default async function FundsPage() {
  const { funds, prices, ...shell } = await getFundsPageData();
  const listed = funds.filter((fund) => fund.status !== "DELISTED");

  return (
    <Shell active="funds" {...shell}>
      <div className="mx-auto w-full max-w-[1220px] min-w-0 px-3 pb-12 pt-7 md:px-7">
        <header className="mb-5">
          <h1 className="text-[28px] font-semibold leading-none tracking-[-0.03em] md:text-[32px]">Team funds</h1>
          <p className="mt-3 max-w-[68ch] text-xs leading-5 text-[#8d97a3]">
            Back a whole squad in one trade. A unit holds one share of every listed player at the club, so its price is the squad&apos;s total share price. Buying a unit buys each player at their own price, so a fund moves with its players, and pricier players carry more weight.
          </p>
        </header>
        <section aria-label="Team funds" className={panel}>
          {listed.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] border-collapse text-left text-[11px]">
                <thead>
                  <tr className="border-b border-[#202630] bg-black/10 text-[10px] uppercase tracking-[0.08em] text-[#65707d]">
                    <th scope="col" className="py-2.5 pl-[18px] font-bold">Fund</th>
                    <th scope="col" className="px-2 py-2.5 text-right font-bold">Unit price</th>
                    <th scope="col" className="px-2 py-2.5 text-right font-bold">24h</th>
                    <th scope="col" className="px-2 py-2.5 text-right font-bold">7 days</th>
                    <th scope="col" className="px-2 py-2.5 text-right font-bold">Players</th>
                    <th scope="col" className="px-2 py-2.5 text-right font-bold">Traded 24h</th>
                    <th scope="col" className="py-2.5 pl-2 pr-[18px] text-right font-bold">7-day chart</th>
                  </tr>
                </thead>
                <tbody>
                  {listed.map((fund) => {
                    const week = Number(fund.price_change_7d);
                    const series = prices[fund.id] ?? [];
                    return (
                      <tr key={fund.id} className="border-b border-[#1b222c] last:border-b-0 hover:bg-white/[0.018]">
                        <td className="py-2.5 pl-[18px]">
                          <Link prefetch={false} href={`/funds/${fund.id}`} className="flex items-center gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                            <FundBadge fund={fund} />
                            <span className="min-w-0">
                              <strong className="flex items-center gap-2 font-semibold text-white hover:text-[#dce7ff]">{fund.display_name}<PausedTag fund={fund} /></strong>
                              <small className="mt-1 block text-[10px] text-[#818b97]">{fund.symbol}</small>
                            </span>
                          </Link>
                        </td>
                        <td className="px-2 py-2.5 text-right tabular-nums slashed-zero">{formatCurrency(fund.current_price)}</td>
                        <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(fund.price_change_24h)}`}>{formatChange(fund.price_change_24h)}</td>
                        <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(week, 1)}`}>{formatChange(week, 1)}</td>
                        <td className="px-2 py-2.5 text-right tabular-nums text-[#9ba5b2]">{fund.constituent_count}</td>
                        <td className="px-2 py-2.5 text-right tabular-nums slashed-zero text-[#9ba5b2]">{formatMoneyShort(fund.traded_value_24h)}</td>
                        <td className="py-2.5 pl-2 pr-[18px]">{series.length > 1 ? <Sparkline prices={series} rising={week >= 0} area={false} className="ml-auto block h-6 w-24" /> : <span className="block text-right text-[#65707d]">—</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="px-[18px] py-14 text-center text-xs text-[#77818e]">No team funds are listed yet.</p>
          )}
        </section>
      </div>
    </Shell>
  );
}
