import type { Metadata } from "next";
import Link from "next/link";
import { Shell, panel } from "../components/market-shell";
import { YouBadge } from "../components/trader-identity";
import { LEADERBOARD_PAGE_SIZE, getLeaderboardPageData, type TraderStanding } from "@/lib/api";
import { formatCompact, formatCurrency } from "@/lib/format";

export const metadata: Metadata = { title: "Leaderboard — Stockball" };
export const dynamic = "force-dynamic";

type PageProps = { searchParams: Promise<{ page?: string }> };

function leaderboardHref(page: number): string {
  return page > 1 ? `/leaderboard?page=${page}` : "/leaderboard";
}

function traderHref(entry: TraderStanding): string {
  return `/traders/${entry.account_id}`;
}

function Money({ value, className = "" }: { value: string; className?: string }) {
  return (
    <span className={`font-mono tabular-nums slashed-zero ${className}`}>
      <span className="sm:hidden">£{formatCompact(value)}</span>
      <span className="hidden sm:inline">{formatCurrency(value)}</span>
    </span>
  );
}

/** Today's move in a trader's net worth: ▲ £12.3k 0.03%, green up, red down, a dash when flat. */
function DayChange({ entry, className = "" }: { entry: TraderStanding; className?: string }) {
  const change = Number(entry.day_change);
  const magnitude = Math.abs(change);
  if (magnitude < 0.5) {
    return <span className={`font-mono text-[#56616d] ${className}`} aria-label="No change today">—</span>;
  }
  const up = change > 0;
  const percent = Math.abs(Number(entry.day_change_percent));
  const amount = magnitude < 1_000 ? `£${Math.round(magnitude)}` : `£${formatCompact(magnitude)}`;
  const percentLabel = percent < 0.01 ? "<0.01%" : `${percent.toFixed(2)}%`;
  return (
    <span
      className={`font-mono tabular-nums slashed-zero ${up ? "text-[#35d07f]" : "text-[#f16d73]"} ${className}`}
      aria-label={`${up ? "Up" : "Down"} ${formatCurrency(magnitude)} today`}
    >
      {up ? "▲" : "▼"} {amount} <span className="opacity-75">{percentLabel}</span>
    </span>
  );
}

function Chevron({ className = "" }: { className?: string }) {
  return <svg viewBox="0 0 20 20" aria-hidden="true" className={`size-4 shrink-0 ${className}`} fill="none"><path d="m7.5 4.5 5 5.5-5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

const MEDALS = [
  { label: "1st", disc: "border-[#f4cf68]/70 bg-[#f4cf68]/15", text: "text-[#f4cf68]", glow: "from-[#f4cf68]/[0.16]", lift: "md:-translate-y-4" },
  { label: "2nd", disc: "border-[#c7d0db]/60 bg-[#c7d0db]/10", text: "text-[#d5dce5]", glow: "from-[#c7d0db]/[0.10]", lift: "" },
  { label: "3rd", disc: "border-[#d99a6c]/60 bg-[#d99a6c]/10", text: "text-[#e2a77c]", glow: "from-[#d99a6c]/[0.10]", lift: "" },
] as const;

function Podium({ entries, viewerId }: { entries: TraderStanding[]; viewerId: string | null }) {
  // Second, first, third on wide screens so the leader stands in the middle.
  const order = [1, 0, 2];
  return (
    <ol aria-label="Top three traders" className="mb-6 grid items-end gap-2.5 md:mb-8 md:grid-cols-3 md:gap-3 md:pt-4">
      {order.map((index) => {
        const entry = entries[index];
        const medal = MEDALS[index];
        if (!entry) return null;
        return (
          <li key={entry.account_id} className={`min-w-0 ${index === 0 ? "order-first md:order-none" : ""} ${medal.lift}`}>
            <Link
              href={traderHref(entry)}
              aria-label={`${medal.label} place, ${entry.display_name}, ${formatCurrency(entry.net_worth)}. View portfolio`}
              className={`group relative flex h-full items-center gap-4 overflow-hidden rounded-2xl border border-[#242c37] bg-gradient-to-r ${medal.glow} to-[#0e131a] to-70% p-4 transition duration-200 hover:border-[#3a4757] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] md:flex-col md:gap-0 md:bg-gradient-to-b md:to-60% md:px-5 md:pb-5 md:pt-7 md:text-center md:hover:-translate-y-1 md:hover:shadow-[0_18px_40px_-20px_rgba(0,0,0,0.9)]`}
            >
              {index === 0 && (
                <svg viewBox="0 0 24 24" aria-hidden="true" className="absolute right-4 top-3.5 hidden size-5 text-[#f4cf68] md:block" fill="currentColor"><path d="M4 18h16l1-10-5 4-4-7-4 7-5-4 1 10Z" /></svg>
              )}
              <span aria-hidden="true" className={`grid size-11 shrink-0 place-items-center rounded-full border-2 font-mono text-lg font-bold tabular-nums md:size-16 md:text-2xl ${medal.disc} ${medal.text}`}>{entry.rank}</span>
              <span className="flex min-w-0 flex-1 flex-col md:mt-4 md:w-full md:flex-none md:items-center">
                <span className="flex max-w-full items-center gap-2">
                  <strong className="truncate text-sm md:text-base">{entry.display_name}</strong>
                  {entry.account_id === viewerId && <YouBadge />}
                </span>
                <span className="mt-0.5 text-[11px] text-[#77818e] md:order-last md:mt-1">{entry.holdings_count} player{entry.holdings_count === 1 ? "" : "s"} held</span>
                <span className="mt-1 hidden text-xl font-semibold md:block"><Money value={entry.net_worth} /></span>
              </span>
              <span className="text-base font-semibold md:hidden"><Money value={entry.net_worth} /></span>
              <Chevron className="text-[#8fb5ff] md:hidden" />
              <span className="mt-4 hidden items-center gap-1 text-[11px] font-bold text-[#8fb5ff] opacity-80 transition group-hover:gap-2 group-hover:opacity-100 md:inline-flex">
                View portfolio <Chevron className="size-3.5" />
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

function StandingRow({ entry, isViewer }: { entry: TraderStanding; isViewer: boolean }) {
  return (
    <li>
      <Link
        href={traderHref(entry)}
        className={`group grid grid-cols-[2.75rem_minmax(0,1fr)_auto_1.25rem] items-center gap-3 rounded-xl border px-3 py-3 transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] sm:grid-cols-[3.25rem_minmax(0,1fr)_minmax(8rem,13rem)_10.5rem_6.5rem] sm:gap-4 sm:px-4 ${
          isViewer
            ? "border-[#8fb5ff]/40 bg-[#8fb5ff]/[0.07] hover:bg-[#8fb5ff]/[0.11]"
            : "border-transparent hover:border-[#2c3643] hover:bg-[#111822]"
        }`}
      >
        <span className="text-center font-mono text-sm font-semibold text-[#7f8995] tabular-nums group-hover:text-white">{entry.rank.toLocaleString("en-GB")}</span>
        <span className="flex min-w-0 items-center">
          <span className="min-w-0">
            <span className="flex items-center gap-2">
              <strong className="truncate text-sm font-semibold text-white">{entry.display_name}</strong>
              {isViewer && <YouBadge />}
            </span>
            <span className="mt-0.5 block truncate text-[11px] text-[#6f7a87]">
              {entry.holdings_count} player{entry.holdings_count === 1 ? "" : "s"}<span className="hidden sm:inline"> · {formatCompact(entry.cash_balance)} cash</span>
            </span>
          </span>
        </span>
        <DayChange entry={entry} className="hidden text-xs font-semibold sm:block" />
        <span className="text-right">
          <strong className="block text-sm font-semibold"><Money value={entry.net_worth} /></strong>
          <DayChange entry={entry} className="mt-0.5 block text-[11px] sm:hidden" />
        </span>
        <span className="flex justify-end">
          <span className="inline-flex items-center gap-1 rounded-lg text-[11px] font-bold text-[#4d5866] transition-colors group-hover:text-[#8fb5ff] group-focus-visible:text-[#8fb5ff] sm:border sm:border-[#252d38] sm:px-2.5 sm:py-1.5 sm:text-[#8d97a3] sm:group-hover:border-[#8fb5ff]/50 sm:group-hover:bg-[#8fb5ff]/10">
            <span className="hidden sm:inline">View</span>
            <Chevron className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          </span>
        </span>
      </Link>
    </li>
  );
}

function ViewerCard({ standing, total }: { standing: TraderStanding; total: number }) {
  const percentile = total > 0 ? Math.max(1, Math.ceil((standing.rank / total) * 100)) : 100;
  return (
    <Link
      href={traderHref(standing)}
      className="group mb-6 flex items-center gap-4 rounded-2xl border border-[#8fb5ff]/30 bg-gradient-to-r from-[#8fb5ff]/[0.10] to-transparent p-4 transition-colors hover:border-[#8fb5ff]/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] sm:p-5"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#8fb5ff]">Your standing</span>
        <span className="mt-1 block text-sm text-[#c5ccd4]">
          <strong className="text-white">#{standing.rank.toLocaleString("en-GB")}</strong> of {total.toLocaleString("en-GB")} · top {percentile}%
        </span>
      </span>
      <span className="text-right">
        <strong className="block text-lg font-semibold"><Money value={standing.net_worth} /></strong>
        <span className="text-[11px] font-bold text-[#8fb5ff]">View your portfolio</span>
      </span>
      <Chevron className="text-[#8fb5ff] transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

function Pagination({ page, pageCount }: { page: number; pageCount: number }) {
  if (pageCount <= 1) return null;
  const pages = Array.from(new Set([1, page - 1, page, page + 1, pageCount]))
    .filter((candidate) => candidate >= 1 && candidate <= pageCount)
    .sort((a, b) => a - b);
  const button = "grid h-9 min-w-9 place-items-center rounded-lg px-3 text-xs font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]";
  return (
    <nav aria-label="Leaderboard pages" className="mt-6 flex flex-wrap items-center justify-center gap-1.5">
      {page > 1 && <Link href={leaderboardHref(page - 1)} className={`${button} border border-[#2a3441] text-[#c4cbd3] hover:border-[#46566b] hover:text-white`}>← Prev</Link>}
      {pages.map((candidate, index) => (
        <span key={candidate} className="flex items-center gap-1.5">
          {index > 0 && candidate - pages[index - 1] > 1 && <span className="px-1 text-[#4d5866]">…</span>}
          <Link
            href={leaderboardHref(candidate)}
            aria-current={candidate === page ? "page" : undefined}
            className={`${button} ${candidate === page ? "bg-[#8fb5ff] text-[#080b10]" : "text-[#8d97a3] hover:bg-white/[0.05] hover:text-white"}`}
          >
            {candidate}
          </Link>
        </span>
      ))}
      {page < pageCount && <Link href={leaderboardHref(page + 1)} className={`${button} border border-[#2a3441] text-[#c4cbd3] hover:border-[#46566b] hover:text-white`}>Next →</Link>}
    </nav>
  );
}

export default async function LeaderboardPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const requestedPage = Math.max(1, Number.parseInt(query.page ?? "1", 10) || 1);
  const { account, tickerStocks, searchInstruments, leaderboard, viewerStanding } = await getLeaderboardPageData("ALL", requestedPage);
  const pageCount = Math.max(1, Math.ceil(leaderboard.total / LEADERBOARD_PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  const viewerId = account?.id ?? null;
  const showPodium = page === 1 && leaderboard.entries.length >= 3;
  const rows = showPodium ? leaderboard.entries.slice(3) : leaderboard.entries;

  return (
    <Shell active="leaderboard" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <section className="relative mx-auto w-full max-w-[1040px] min-w-0 px-3 py-7 md:px-7 md:py-10">
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 -top-10 h-72 bg-[radial-gradient(60%_60%_at_50%_0%,rgba(143,181,255,0.10),transparent)]" />
        <header className="relative mb-6 text-center md:mb-8">
          <span className="inline-flex items-center gap-2 rounded-full border border-[#8fb5ff]/25 bg-[#8fb5ff]/[0.07] px-3 py-1 text-[11px] font-bold uppercase tracking-wider text-[#8fb5ff]">
            <span className="size-1.5 rounded-full bg-[#35d07f]" /> Live standings
          </span>
          <h1 className="mt-4 text-3xl font-semibold leading-none tracking-[-0.03em] md:text-[46px]">Leaderboard</h1>
        </header>

        {viewerStanding && <ViewerCard standing={viewerStanding} total={leaderboard.total} />}

        {leaderboard.entries.length === 0 ? (
          <div className={`${panel} px-5 py-16 text-center`}>
            <p className="text-base font-semibold">No traders here yet</p>
            <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-[#7f8995]">Once people start trading, the richest portfolios will appear here.</p>
          </div>
        ) : (
          <>
            {showPodium && <Podium entries={leaderboard.entries.slice(0, 3)} viewerId={viewerId} />}
            {rows.length > 0 && (
              <div className={`${panel} p-2 sm:p-3`}>
                <div className="hidden grid-cols-[3.25rem_minmax(0,1fr)_minmax(8rem,13rem)_10.5rem_6.5rem] gap-4 px-4 pb-2 pt-1 text-[10px] font-bold uppercase tracking-wider text-[#5d6875] sm:grid" aria-hidden="true">
                  <span className="text-center">Rank</span><span>Trader</span><span>Today</span><span className="text-right">Net worth</span><span />
                </div>
                <ol aria-label={`Traders ranked ${rows[0]?.rank ?? ""} to ${rows.at(-1)?.rank ?? ""}`} className="space-y-1">
                  {rows.map((entry) => (
                    <StandingRow key={entry.account_id} entry={entry} isViewer={entry.account_id === viewerId} />
                  ))}
                </ol>
              </div>
            )}
            <Pagination page={page} pageCount={pageCount} />
            <p className="mt-3 text-center text-[11px] text-[#65707d]">{leaderboard.total.toLocaleString("en-GB")} traders ranked</p>
          </>
        )}

        <p className="mx-auto mt-10 max-w-[64ch] text-center text-[11px] leading-relaxed text-[#56616d]">
          Net worth = virtual cash + (shares held × current share price). Stockball uses virtual cash only; standings are not investment returns.
        </p>
      </section>
    </Shell>
  );
}
