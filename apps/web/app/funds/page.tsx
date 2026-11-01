import type { Metadata } from "next";
import Link from "next/link";
import { Shell, panel } from "../components/market-shell";
import { FundBadge, PausedTag, categoryAccent } from "../components/fund-media";
import { Sparkline } from "../components/sparkline";
import { getFundsPageData, type IndexFund } from "@/lib/api";
import { groupFunds, hasMovement } from "@/lib/funds";
import { formatChange, formatCurrency, formatMoneyShort, moveTone } from "@/lib/format";

export const metadata: Metadata = { title: "Index funds — Stockball" };
export const dynamic = "force-dynamic";

const slug = (category: string) => category.toLowerCase().replace(/[^a-z]+/g, "-");

function FundRow({ fund, prices }: { fund: IndexFund; prices: number[] }) {
  const week = Number(fund.basket_change_7d);
  return (
    <tr className="border-b border-[#1b222c] last:border-b-0 hover:bg-white/[0.018]">
      <td className="py-2.5 pl-[18px]">
        <Link prefetch={false} href={`/funds/${fund.id}`} className="flex items-center gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
          <FundBadge fund={fund} />
          <span className="min-w-0 flex-1">
            <strong className="flex items-center gap-2 font-semibold text-white hover:text-[#dce7ff]">{fund.display_name}<PausedTag fund={fund} /></strong>
            <small className="mt-1 block truncate text-[10px] text-[#818b97]">{fund.description ? `${fund.symbol} · ${fund.description}` : fund.symbol}</small>
          </span>
        </Link>
      </td>
      <td className="px-2 py-2.5 text-right tabular-nums slashed-zero">{formatCurrency(fund.current_price)}</td>
      <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(fund.basket_change_24h)}`}>{formatChange(fund.basket_change_24h)}</td>
      <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(week, 1)}`}>{formatChange(week, 1)}</td>
      <td className="px-2 py-2.5 text-right tabular-nums text-[#9ba5b2]">{fund.constituent_count}</td>
      <td className="px-2 py-2.5 text-right tabular-nums slashed-zero text-[#9ba5b2]">{formatMoneyShort(fund.traded_value_24h)}</td>
      <td className="py-2.5 pl-2 pr-[18px]">{hasMovement(prices) ? <Sparkline prices={prices} rising={week >= 0} area={false} className="ml-auto block h-6 w-24" /> : <span className="block text-right text-[#65707d]">—</span>}</td>
    </tr>
  );
}

export default async function FundsPage() {
  const { funds, prices, ...shell } = await getFundsPageData();
  const groups = groupFunds(funds.filter((fund) => fund.status !== "DELISTED"));

  return (
    <Shell active="funds" {...shell}>
      <div className="mx-auto w-full max-w-[1220px] min-w-0 px-3 pb-12 pt-7 md:px-7">
        <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <h1 className="text-[28px] font-semibold leading-none tracking-[-0.03em] md:text-[32px]">Index funds</h1>
          {groups.length > 1 && (
            <nav aria-label="Fund categories" className="flex flex-wrap gap-1.5">
              {groups.map(({ category, funds: members }) => (
                <a key={category} href={`#${slug(category)}`} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[#242c37] px-2.5 text-[11px] font-semibold text-[#a6afba] hover:border-[#516074] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                  <span aria-hidden="true" className="size-1.5 rounded-full" style={{ background: categoryAccent(members[0]) }} />
                  {category}
                  <span className="tabular-nums text-[#65707d]">{members.length}</span>
                </a>
              ))}
            </nav>
          )}
        </header>
        {groups.length > 0 ? (
          <div className="flex flex-col gap-5">
            {groups.map(({ category, funds: members }) => (
              <section key={category} id={slug(category)} aria-labelledby={`${slug(category)}-title`} className={`${panel} scroll-mt-28`}>
                <h2 id={`${slug(category)}-title`} className="flex items-center gap-2 px-[18px] py-3.5 text-sm font-bold">
                  <span aria-hidden="true" className="size-2 rounded-full" style={{ background: categoryAccent(members[0]) }} />
                  {category}
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[820px] table-fixed border-collapse text-left text-[11px]">
                    <colgroup>
                      <col />
                      <col className="w-[110px]" />
                      <col className="w-[80px]" />
                      <col className="w-[80px]" />
                      <col className="w-[72px]" />
                      <col className="w-[96px]" />
                      <col className="w-[132px]" />
                    </colgroup>
                    <thead>
                      <tr className="border-y border-[#202630] bg-black/10 text-[10px] uppercase tracking-[0.08em] text-[#65707d]">
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
                      {members.map((fund) => <FundRow key={fund.id} fund={fund} prices={prices[fund.id] ?? []} />)}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        ) : (
          <section className={panel}><p className="px-[18px] py-14 text-center text-xs text-[#77818e]">No index funds are listed yet.</p></section>
        )}
      </div>
    </Shell>
  );
}
