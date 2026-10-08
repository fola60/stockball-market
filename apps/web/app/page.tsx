import Link from "next/link";
import { redirect } from "next/navigation";
import { Shell, panel } from "./components/market-shell";
import { LiveTrades, TopTraders } from "./components/home/activity";
import { MarketMap } from "./components/home/market-map";
import { MatchdayPanel } from "./components/home/matchday-panel";
import { BiggestMovers } from "./components/home/movers";
import { InTheNews, PortfolioStrip } from "./components/home/news-and-portfolio";
import { MostTraded, TopRated } from "./components/home/ranked-lists";
import { PlayersTable } from "./components/players-table";
import { getHomePageData } from "@/lib/market";

export const dynamic = "force-dynamic";

export default async function MarketPage({ searchParams }: { searchParams: Promise<{ instrument?: string; auth?: string }> }) {
  const { instrument, auth } = await searchParams;
  if (instrument) redirect(`/instrument/${instrument}`);

  const data = await getHomePageData();
  const lastTrade = new Date(data.lastTrade);

  return (
    <Shell active="market" account={data.account} tickerStocks={data.tickerStocks} searchInstruments={data.searchInstruments} initialAuthMode={auth === "register" ? "register" : auth === "login" ? "login" : null}>
      <div className="mx-auto flex w-full max-w-[1220px] min-w-0 flex-col gap-6 px-3 pb-12 pt-7 md:px-7">
        {data.portfolio && <PortfolioStrip summary={data.portfolio} />}

        <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <h1 className="text-[28px] font-semibold leading-none tracking-[-0.03em] md:text-[32px]">Player market</h1>
          <p className="text-[11px] text-[#77818e]">
            <time dateTime={lastTrade.toISOString()}>{lastTrade.toLocaleDateString("en-GB", { timeZone: "Europe/London", weekday: "short", day: "numeric", month: "short" })}</time>
            {" · last trade "}
            <time dateTime={lastTrade.toISOString()} className="text-[#a5aeba] tabular-nums slashed-zero">{lastTrade.toLocaleTimeString("en-GB", { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
          </p>
        </header>

        <div className="-mt-2 flex flex-wrap items-stretch gap-6">
          <BiggestMovers movers={data.movers} totalPlayers={data.listedCount} />
          <MatchdayPanel matchday={data.matchday} fixtures={data.fixtures} signedIn={Boolean(data.account)} />
        </div>

        <MarketMap clubs={data.clubs} />

        <div className="grid gap-5 md:grid-cols-2">
          <MostTraded instruments={data.mostTraded} />
          <TopRated round={data.matchday?.previous_round ?? null} entries={data.topRated} />
        </div>

        <div className="flex flex-wrap items-stretch gap-5">
          <LiveTrades trades={data.trades} />
          <TopTraders leaders={data.leaders} peopleOnBoard={data.peopleOnBoard} account={data.account} />
        </div>

        <section aria-labelledby="all-title" className={panel}>
          <div className="flex flex-wrap items-center justify-between gap-3 px-[18px] py-4">
            <div>
              <h2 id="all-title" className="text-base font-bold">All players</h2>
              <p className="mt-1.5 text-[11px] text-[#77818e]">{data.tradingCount} trading · {data.pausedCount} paused · most valuable first</p>
            </div>
            <Link href="/players" className="text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Filter and sort all players →</Link>
          </div>
          <PlayersTable rows={data.valuable} />
          <Link href="/players" className="block border-t border-[#202630] px-[18px] py-3 text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff]">Browse all {data.listedCount} players →</Link>
        </section>

        <InTheNews items={data.news} />

        <p className="border-t border-[#202630] pt-6 text-[10px] leading-relaxed text-[#65707d]">
          Stockball is a virtual market. Balances and prices are in virtual pounds and can’t be withdrawn. Prices move only when shares are traded; football data informs traders but never sets a price. Stockball’s own synthetic traders are always tagged BOT.
        </p>
      </div>
    </Shell>
  );
}
