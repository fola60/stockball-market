import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell, panel } from "../../components/market-shell";
import { getInstrumentPageData, playerName } from "@/lib/api";
import { formatCompact, formatCurrency, formatPercent } from "@/lib/format";
import { PriceChart } from "./price-chart";
import { RadarChart } from "./radar-chart";
import { TradeTicket } from "./trade-ticket";

export const dynamic = "force-dynamic";

type PageProps = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const data = await getInstrumentPageData(id);
  if (!data) return { title: "Player stock not found — Stockball" };
  return { title: `${playerName(data.instrument)} stock — Stockball` };
}

export default async function InstrumentPage({ params }: PageProps) {
  const { id } = await params;
  const data = await getInstrumentPageData(id);
  if (!data) notFound();

  const { account, instrument, history, stats, portfolio, tickerStocks, searchInstruments } = data;
  const name = playerName(instrument);
  const price = Number(instrument.current_price);
  const change = Number(instrument.price_change_24h);
  const positive = change >= 0;
  const marketValue = price * Number(instrument.quantity_outstanding);
  const positionName = instrument.player_position?.split(",")[0] ?? "Player";
  const ownedQuantity = portfolio?.positions.find((position) => position.instrument_id === instrument.id)?.quantity ?? "0";

  return (
    <Shell active="market" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <div className="mx-auto w-full max-w-[1220px] min-w-0 px-3 py-6 md:px-7 md:py-8">
        <Link href="/" className="mb-6 inline-flex h-9 items-center gap-2 rounded-lg px-2 text-[11px] font-semibold text-[#7f8995] hover:bg-white/[0.035] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4" fill="none"><path d="m12.5 4.5-5 5.5 5 5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
          All player stocks
        </Link>

        <header className="mb-7 flex flex-col justify-between gap-6 md:flex-row md:items-end">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-[#7f8995]">
              <span>{instrument.player_club ?? "Club unavailable"}</span><span aria-hidden="true">·</span><span>{positionName}</span>
              <span className={`rounded-md border px-2 py-1 text-[11px] ${instrument.status === "ACTIVE" ? "border-[#35d07f]/25 bg-[#35d07f]/[0.07] text-[#35d07f]" : "border-[#f4bb55]/25 bg-[#f4bb55]/[0.07] text-[#f4bb55]"}`}>{instrument.status}</span>
            </div>
            <h1 className="text-3xl font-semibold leading-tight tracking-[-0.03em] md:text-[42px]">{name}</h1>
            <p className="mt-2 break-all text-[11px] font-medium text-[#818b97]">{instrument.symbol}</p>
          </div>
          <div className="md:text-right">
            <strong className="block text-3xl font-semibold tabular-nums slashed-zero md:text-[42px]">{formatCurrency(price)}</strong>
            <span className={`mt-2 inline-flex rounded-md px-2.5 py-1.5 text-xs font-semibold text-white tabular-nums slashed-zero ${positive ? "bg-[#07852f]" : "bg-[#d91c32]"}`}>{formatPercent(change)} today</span>
          </div>
        </header>

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section aria-labelledby="price-history-title" className={panel}>
          <div className="flex items-center justify-between border-b border-[#202630] px-4 py-4 md:px-5">
            <div><h2 id="price-history-title" className="text-base font-semibold">Price history</h2><p className="mt-1 text-[11px] font-medium text-[#77818e]">Trading-driven share price</p></div>
            <span className="text-[11px] font-medium text-[#818b97]">History loads by range</span>
          </div>
          <PriceChart
            instrumentId={instrument.id}
            history={history}
            currentPrice={price}
            currentTimestamp={instrument.updated_at}
          />
        </section>

        <div className="order-first xl:order-none xl:sticky xl:top-[124px]">
          <TradeTicket instrumentId={instrument.id} playerName={name} status={instrument.status} cashBalance={portfolio?.cash_balance ?? null} ownedQuantity={ownedQuantity} currentPrice={instrument.current_price} />
        </div>
        </div>

        <dl className="grid grid-cols-2 border-x border-b border-[#222a35] bg-[#0b0f15]">
          {[
            ["24h volume", formatCompact(instrument.volume_24h)],
            ["Market cap", formatCurrency(marketValue)],
          ].map(([term, value]) => (
            <div key={term} className="border-r border-[#202630] p-4 last:border-r-0">
              <dt className="text-[11px] font-semibold text-[#818b97]">{term}</dt>
              <dd className="mt-2 text-sm font-semibold text-white tabular-nums slashed-zero">{value}</dd>
            </div>
          ))}
        </dl>

        <section aria-labelledby="player-profile-title" className={`${panel} mt-5`}>
          <div className="border-b border-[#202630] px-4 py-5 md:px-6">
            <h2 id="player-profile-title" className="text-xl font-semibold tracking-[-0.02em]">Player profile</h2>
          </div>

          {stats ? (
            <div className="grid lg:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
              <div className="min-w-0 px-2 py-5 sm:px-6 md:py-7">
                <RadarChart axes={stats.radar_axes} />
              </div>
              <div className="border-t border-[#202630] p-5 lg:border-t-0 lg:border-l lg:p-6">
                <div className="flex items-baseline justify-between gap-3"><h3 className="text-base font-semibold">Season record</h3><span className="text-[11px] text-[#818b97]">{stats.season}/{String((stats.season ?? 0) + 1).slice(-2)}</span></div>
                <dl className="mt-5 divide-y divide-[#202630]">
                  {[
                    ["Appearances", stats.games.toLocaleString("en-GB")],
                    ["Starts", stats.starts.toLocaleString("en-GB")],
                    ["Minutes", stats.minutes.toLocaleString("en-GB")],
                    ["Goals", stats.goals.toLocaleString("en-GB")],
                    ["Assists", stats.assists.toLocaleString("en-GB")],
                    ["Shots on target", `${stats.shots_on_target} / ${stats.shots}`],
                    ["Cards", `${stats.yellow_cards} yellow · ${stats.red_cards} red`],
                  ].map(([term, value]) => <div key={term} className="flex items-center justify-between gap-4 py-3"><dt className="text-[11px] font-medium text-[#7f8995]">{term}</dt><dd className="text-xs font-semibold text-white tabular-nums slashed-zero">{value}</dd></div>)}
                </dl>
              </div>
            </div>
          ) : (
            <div className="px-5 py-12 text-center"><p className="text-sm font-semibold">No player statistics available</p><p className="mt-2 text-xs text-[#77818e]">Price history remains available while football data is being collected.</p></div>
          )}
        </section>

      </div>
    </Shell>
  );
}
