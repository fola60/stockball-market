import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell, panel } from "../../components/market-shell";
import { FundBadge, PausedTag } from "../../components/fund-media";
import { PlayerAvatar } from "../../components/player-media";
import { PriceChart } from "../../instrument/[id]/price-chart";
import { RadarChart } from "../../instrument/[id]/radar-chart";
import { TradeTicket } from "../../instrument/[id]/trade-ticket";
import { getFundPageData, type IndexFundDetail } from "@/lib/api";
import { formatChange, formatCompact, formatCurrency, formatMoneyShort, formatPercent, moveTone } from "@/lib/format";

export const dynamic = "force-dynamic";

type PageProps = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const data = await getFundPageData(id);
  return { title: data ? `${data.fund.display_name} — Stockball` : "Fund not found — Stockball" };
}

function PausedBanner({ fund }: { fund: IndexFundDetail }) {
  const matchDay = fund.freeze_reason === "MATCH_DAY";
  return (
    <div role="status" className="mb-5 flex items-start gap-3 rounded-xl border border-[#f4bb55]/25 bg-[#f4bb55]/[0.06] p-4">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-[#f4bb55]/15 text-[#f4bb55]" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="size-4" fill="none"><rect x="5" y="9" width="10" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.6"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
      </span>
      <div>
        <p className="text-sm font-semibold text-[#f7d58f]">{matchDay ? "Trading paused for match day" : "Trading paused"}</p>
        <p className="mt-1 text-xs leading-5 text-[#c9b27f]">
          {matchDay
            ? "Players in this fund are paused for their match. A unit trades as a whole, so the fund reopens once the match has been settled."
            : "A player in this fund is paused. A unit trades as a whole, so the fund reopens when every player can trade again."}
        </p>
      </div>
    </div>
  );
}

export default async function FundPage({ params }: PageProps) {
  const { id } = await params;
  const data = await getFundPageData(id);
  if (!data) notFound();

  const { fund, history, portfolio, ...shell } = data;
  const price = Number(fund.current_price);
  const change = Number(fund.price_change_24h);
  const ownedQuantity = portfolio?.positions.find((position) => position.instrument_id === fund.id)?.quantity ?? "0";

  return (
    <Shell active="funds" {...shell}>
      <div className="mx-auto w-full max-w-[1220px] min-w-0 px-3 py-6 md:px-7 md:py-8">
        <Link href="/funds" className="mb-6 inline-flex h-9 items-center gap-2 rounded-lg px-2 text-[11px] font-semibold text-[#7f8995] hover:bg-white/[0.035] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4" fill="none"><path d="m12.5 4.5-5 5.5 5 5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          All team funds
        </Link>

        <header className="mb-7 flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div className="flex min-w-0 items-center gap-4 md:gap-5">
            <FundBadge fund={fund} className="size-16 md:size-24" />
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-[#7f8995]">
                <span>Team fund</span><span aria-hidden="true">·</span><span>{fund.constituent_count} players</span><PausedTag fund={fund} />
              </div>
              <h1 className="text-3xl font-semibold leading-tight tracking-[-0.03em] md:text-[42px]">{fund.display_name}</h1>
              <p className="mt-2 break-all text-[11px] font-medium text-[#818b97]">{fund.symbol}</p>
            </div>
          </div>
          <div className="md:text-right">
            <strong className="block text-3xl font-semibold tabular-nums slashed-zero md:text-[42px]">{formatCurrency(price)}</strong>
            <span className={`mt-2 inline-flex rounded-md px-2.5 py-1.5 text-xs font-semibold text-white tabular-nums slashed-zero ${change >= 0 ? "bg-[#07852f]" : "bg-[#d91c32]"}`}>{formatPercent(change)} today</span>
          </div>
        </header>

        {fund.status !== "ACTIVE" && <PausedBanner fund={fund} />}

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <section aria-labelledby="price-history-title" className={panel}>
            <div className="flex items-center justify-between border-b border-[#202630] px-4 py-4 md:px-5">
              <div><h2 id="price-history-title" className="text-base font-semibold">Unit price history</h2><p className="mt-1 text-[11px] font-medium text-[#77818e]">The value of one share of every player in the fund</p></div>
              <span className="text-[11px] font-medium text-[#818b97]">History loads by range</span>
            </div>
            <PriceChart instrumentId={fund.id} history={history} currentPrice={price} currentTimestamp={fund.updated_at} />
          </section>

          <div className="order-first xl:order-none xl:sticky xl:top-[124px]">
            <TradeTicket kind="fund" instrumentId={fund.id} playerName={fund.display_name} status={fund.status} cashBalance={portfolio?.cash_balance ?? null} ownedQuantity={ownedQuantity} currentPrice={fund.current_price} />
          </div>
        </div>

        <dl className="grid grid-cols-2 border-x border-b border-[#222a35] bg-[#0b0f15] md:grid-cols-3">
          {[
            ["Units traded 24h", formatCompact(fund.volume_24h)],
            ["Traded 24h", formatMoneyShort(fund.traded_value_24h)],
            ["Units held", formatCompact(fund.units_outstanding)],
          ].map(([term, value]) => (
            <div key={term} className="border-r border-[#202630] p-4 last:border-r-0">
              <dt className="text-[11px] font-semibold text-[#818b97]">{term}</dt>
              <dd className="mt-2 text-sm font-semibold text-white tabular-nums slashed-zero">{value}</dd>
            </div>
          ))}
        </dl>

        <section aria-labelledby="squad-profile-title" className={`${panel} mt-5`}>
          <div className="border-b border-[#202630] px-4 py-5 md:px-6">
            <h2 id="squad-profile-title" className="text-xl font-semibold tracking-[-0.02em]">Squad profile</h2>
            <p className="mt-1.5 max-w-[70ch] text-[11px] leading-5 text-[#77818e]">Each player is ranked against their own position, then the squad&apos;s scores are averaged, weighted by each player&apos;s share of a unit. Shot stopping counts only the keepers.</p>
          </div>
          {fund.profile && fund.profile.radar_axes.length > 0 ? (
            <div className="min-w-0 px-2 py-5 sm:px-6 md:py-7">
              <RadarChart axes={fund.profile.radar_axes} />
            </div>
          ) : (
            <div className="px-5 py-12 text-center"><p className="text-sm font-semibold">No squad statistics available</p><p className="mt-2 text-xs text-[#77818e]">The profile appears once this season&apos;s player statistics are collected.</p></div>
          )}
        </section>

        <section aria-labelledby="basket-title" className={`${panel} mt-5`}>
          <div className="border-b border-[#202630] px-4 py-5 md:px-6">
            <h2 id="basket-title" className="text-xl font-semibold tracking-[-0.02em]">What one unit holds</h2>
            <p className="mt-1.5 text-[11px] text-[#77818e]">Weight is each player&apos;s share of the unit price.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-left text-[11px]">
              <thead>
                <tr className="border-b border-[#202630] bg-black/10 text-[10px] uppercase tracking-[0.08em] text-[#65707d]">
                  <th scope="col" className="py-2.5 pl-[18px] font-bold">Player</th>
                  <th scope="col" className="px-2 py-2.5 text-right font-bold">Shares</th>
                  <th scope="col" className="px-2 py-2.5 text-right font-bold">Price</th>
                  <th scope="col" className="px-2 py-2.5 text-right font-bold">24h</th>
                  <th scope="col" className="py-2.5 pl-2 pr-[18px] font-bold">Weight</th>
                </tr>
              </thead>
              <tbody>
                {fund.constituents.map((player) => (
                  <tr key={player.instrument_id} className="border-b border-[#1b222c] last:border-b-0 hover:bg-white/[0.018]">
                    <td className="py-2.5 pl-[18px]">
                      <Link prefetch={false} href={`/instrument/${player.instrument_id}`} className="flex items-center gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                        <PlayerAvatar instrument={{ id: player.instrument_id, player_image_version: player.player_image_version, club_badge_version: null }} name={player.player_name} className="size-[30px]" />
                        <span className="min-w-0">
                          <strong className="flex items-center gap-2 font-semibold text-white hover:text-[#dce7ff]">{player.player_name}{player.status !== "ACTIVE" && <span className="rounded border border-[#f4bb55]/30 px-1 py-px text-[9px] font-bold text-[#f4bb55]">PAUSED</span>}</strong>
                          <small className="mt-1 block text-[10px] text-[#818b97]">{player.player_position?.split(",")[0] ?? "—"}</small>
                        </span>
                      </Link>
                    </td>
                    <td className="px-2 py-2.5 text-right tabular-nums text-[#9ba5b2]">{Number(player.shares_per_unit).toLocaleString("en-GB", { maximumFractionDigits: 6 })}</td>
                    <td className="px-2 py-2.5 text-right tabular-nums slashed-zero">{formatCurrency(player.current_price)}</td>
                    <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(player.price_change_24h)}`}>{formatChange(player.price_change_24h)}</td>
                    <td className="py-2.5 pl-2 pr-[18px]">
                      <div className="flex items-center gap-2"><span className="w-12 tabular-nums">{Number(player.weight).toFixed(1)}%</span><span className="h-1 w-20 overflow-hidden rounded bg-[#242c37]"><i className="block h-full bg-[#8fb5ff]" style={{ width: `${Math.min(100, Number(player.weight))}%` }} /></span></div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </Shell>
  );
}
