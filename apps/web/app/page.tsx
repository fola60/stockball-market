import Link from "next/link";
import { redirect } from "next/navigation";
import { Shell } from "./components/market-shell";
import { ClubBadge, PlayerAvatar } from "./components/player-media";
import { getMarketPageData, playerName, type MarketRow } from "@/lib/api";
import { formatCompact, formatCurrency, formatPercent } from "@/lib/format";

export const dynamic = "force-dynamic";

function Sparkline({ row }: { row: MarketRow }) {
  const { prices, instrument } = row;
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const range = maximum - minimum || 1;
  const points = prices.map((price, index) => ({
    x: prices.length === 1 ? 0 : (index / (prices.length - 1)) * 112,
    y: 28 - ((price - minimum) / range) * 24,
  }));
  const coordinates = points.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const first = points[0] ?? { x: 0, y: 16 };
  const endpoint = points.at(-1) ?? first;
  const area = `0,32 ${coordinates} 112,32`;
  const positive = Number(instrument.price_change_24h) >= 0;
  const gradientId = `spark-${instrument.id}`;

  return (
    <svg viewBox="0 0 112 32" preserveAspectRatio="none" className={`h-8 w-full ${positive ? "text-[#35d07f]" : "text-[#f16d73]"}`} aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gradientId})`} />
      <line x1="0" y1={first.y} x2="112" y2={first.y} stroke="currentColor" strokeWidth="1" strokeDasharray="4 3" strokeOpacity="0.65" vectorEffect="non-scaling-stroke" />
      <polyline points={coordinates} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle cx={endpoint.x} cy={endpoint.y} r="2" fill="currentColor" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function PlayerStocks({ rows }: { rows: MarketRow[] }) {
  if (rows.length === 0) {
    return <div className="border-y border-[#222a35] py-16 text-center text-sm text-[#818b97]">No player stocks have been seeded yet.</div>;
  }

  return (
    <section aria-label="Player stocks">
      <ol className="divide-y divide-[#222a35] border-y border-[#222a35]">
        {rows.map((row) => {
          const { instrument, directionRank } = row;
          const change = Number(instrument.price_change_24h);
          const positive = change >= 0;
          const name = playerName(instrument);

          return (
            <li key={instrument.id}>
              <Link prefetch={false} href={`/instrument/${instrument.id}`} className="group grid min-h-20 grid-cols-[minmax(0,1fr)_4.75rem_5rem] items-center gap-x-3 py-4 transition-colors hover:bg-white/[0.025] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff] sm:grid-cols-[minmax(0,1fr)_8rem_6rem] sm:gap-x-5 md:px-1">
                <span className="sr-only">{positive ? "Gainer" : "Decliner"} rank {directionRank}, {positive ? "up" : "down"} {Math.abs(change).toFixed(2)} percent over 24 hours.</span>
                <span className="flex min-w-0 items-center gap-3">
                  <PlayerAvatar instrument={instrument} name={name} className="size-9 sm:size-11" />
                  <span className="min-w-0">
                    <strong className="block truncate text-sm font-semibold text-white group-hover:text-[#dce7ff] sm:text-base">{name}</strong>
                    <small className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-[#818b97]"><ClubBadge instrument={instrument} /><span className="truncate">{instrument.player_club ?? "Club unavailable"} · {instrument.player_position ?? "—"}<span className="hidden sm:inline"> · VOL {formatCompact(instrument.volume_24h)}</span></span></small>
                  </span>
                </span>
                <span className="flex min-w-0 items-center"><Sparkline row={row} /></span>
                <span className="text-right">
                  <strong className="block text-sm font-medium text-white tabular-nums slashed-zero sm:text-base">{formatCurrency(instrument.current_price)}</strong>
                  <small className={`mt-1.5 inline-flex min-w-[4.5rem] justify-end rounded-md px-2 py-1 text-[11px] font-semibold text-white tabular-nums slashed-zero sm:text-xs ${positive ? "bg-[#07852f]" : "bg-[#d91c32]"}`}>{formatPercent(change)}</small>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default async function MarketPage({ searchParams }: { searchParams: Promise<{ instrument?: string; auth?: string }> }) {
  const { instrument, auth } = await searchParams;
  if (instrument) redirect(`/instrument/${instrument}`);

  const { account, rows, tickerStocks, searchInstruments, updatedAt } = await getMarketPageData();
  const updated = new Date(updatedAt);

  return (
    <Shell active="market" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments} initialAuthMode={auth === "register" ? "register" : auth === "login" ? "login" : null}>
      <section className="mx-auto w-full max-w-[1120px] min-w-0 px-3 py-7 md:px-7 md:py-9">
        <header className="mb-7 flex items-end justify-between md:mb-9">
          <div>
            <h1 className="text-3xl font-semibold leading-none tracking-[-0.03em] md:text-[42px]">Player stocks</h1>
            <p className="mt-2 text-lg font-semibold text-[#666f7a] md:text-xl"><time dateTime={updated.toISOString()}>{updated.toLocaleDateString("en-GB", { day: "numeric", month: "long" })}</time></p>
          </div>
          <p className="hidden text-right text-[11px] font-medium leading-relaxed text-[#707b88] sm:block">Last updated<br/><time dateTime={updated.toISOString()} className="text-[#a5aeba] tabular-nums slashed-zero">{updated.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></p>
        </header>

        <PlayerStocks rows={rows} />

      </section>
    </Shell>
  );
}
