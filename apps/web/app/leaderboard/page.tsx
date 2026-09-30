import type { Metadata } from "next";
import Link from "next/link";
import { Label, Shell, panel } from "../components/market-shell";
import { TraderBadge } from "../components/trader-badge";
import {
  LEADERBOARD_PAGE_SIZE,
  getLeaderboardPageData,
  type LeaderboardFilter,
  type TraderStanding,
} from "@/lib/api";
import { formatCurrency, initials } from "@/lib/format";

export const metadata: Metadata = { title: "Leaderboard — Stockball" };
export const dynamic = "force-dynamic";

const FILTERS: Array<[LeaderboardFilter, string]> = [
  ["ALL", "Everyone"],
  ["PEOPLE", "People"],
  ["BOTS", "Bots"],
];

type PageProps = { searchParams: Promise<{ filter?: string; page?: string }> };

function parseFilter(value: string | undefined): LeaderboardFilter {
  return FILTERS.some(([filter]) => filter === value) ? (value as LeaderboardFilter) : "ALL";
}

function leaderboardHref(filter: LeaderboardFilter, page = 1): string {
  const params = new URLSearchParams();
  if (filter !== "ALL") params.set("filter", filter);
  if (page > 1) params.set("page", String(page));
  const query = params.toString();
  return query ? `/leaderboard?${query}` : "/leaderboard";
}

const PODIUM_ACCENTS = ["text-[#f4cf68]", "text-[#c7d0db]", "text-[#d99a6c]"];

function Podium({ entries, viewerId }: { entries: TraderStanding[]; viewerId: string | null }) {
  return (
    <ol className="mb-4 grid gap-3 md:grid-cols-3">
      {entries.map((entry, index) => (
        <li key={entry.account_id}>
          <Link href={`/traders/${entry.account_id}`} className={`${panel} flex h-full items-center gap-4 p-5 transition-colors hover:border-[#34404f] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]`}>
            <span className={`min-w-7 shrink-0 text-2xl font-semibold tabular-nums ${PODIUM_ACCENTS[index] ?? "text-[#8d97a3]"}`}>{entry.rank}</span>
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-[#8fb5ff]/10 text-[11px] font-extrabold text-[#8fb5ff]">{initials(entry.display_name)}</span>
            <span className="min-w-0">
              <span className="flex items-center gap-2"><strong className="truncate text-sm">{entry.display_name}</strong><TraderBadge kind={entry.kind} isViewer={entry.account_id === viewerId} /></span>
              <span className="mt-1 block font-mono text-lg font-semibold tabular-nums slashed-zero">{formatCurrency(entry.net_worth)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

export default async function LeaderboardPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const filter = parseFilter(query.filter);
  const requestedPage = Math.max(1, Number.parseInt(query.page ?? "1", 10) || 1);
  const { account, tickerStocks, searchInstruments, leaderboard } = await getLeaderboardPageData(filter, requestedPage);
  const pageCount = Math.max(1, Math.ceil(leaderboard.total / LEADERBOARD_PAGE_SIZE));
  const page = Math.min(requestedPage, pageCount);
  const viewerId = account?.id ?? null;
  // Ranks are global, so medals only make sense on the unfiltered first page.
  const showPodium = filter === "ALL" && page === 1 && leaderboard.entries.length >= 3;
  const rows = showPodium ? leaderboard.entries.slice(3) : leaderboard.entries;

  return (
    <Shell active="leaderboard" account={account} tickerStocks={tickerStocks} searchInstruments={searchInstruments}>
      <section className="mx-auto w-full max-w-[1120px] min-w-0 px-3 py-7 md:px-7 md:py-9">
        <header className="mb-7 flex flex-col gap-5 md:mb-9 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-3xl font-semibold leading-none tracking-[-0.03em] md:text-[42px]">Leaderboard</h1>
            <p className="mt-3 max-w-[60ch] text-sm leading-relaxed text-[#8d97a3]">The richest traders by net worth: virtual cash plus player shares at today&apos;s prices. Bots are Stockball&apos;s synthetic traders.</p>
          </div>
          <nav aria-label="Filter traders" className="flex rounded-lg border border-[#252d38] bg-[#0b0f15] p-1">
            {FILTERS.map(([value, label]) => (
              <Link key={value} href={leaderboardHref(value)} aria-current={filter === value ? "page" : undefined} className={`h-8 rounded-md px-3.5 text-xs font-bold leading-8 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${filter === value ? "bg-[#8fb5ff] text-[#080b10]" : "text-[#8d97a3] hover:text-white"}`}>{label}</Link>
            ))}
          </nav>
        </header>

        {leaderboard.entries.length === 0 ? (
          <div className={`${panel} px-5 py-16 text-center`}>
            <p className="text-base font-semibold">No traders here yet</p>
            <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-[#7f8995]">Once people start trading, the richest portfolios will appear here.</p>
          </div>
        ) : (
          <>
            {showPodium && <Podium entries={leaderboard.entries.slice(0, 3)} viewerId={viewerId} />}
            {rows.length > 0 && (
              <article className={panel}>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-collapse text-left">
                    <thead className="border-b border-[#202832] bg-black/10 text-[11px] uppercase tracking-wider text-[#65707d]">
                      <tr><th className="w-16 py-3 pl-5">Rank</th><th>Trader</th><th className="text-right">Net worth</th><th className="text-right">Cash</th><th className="text-right">Holdings</th><th className="pr-5 text-right">Players</th></tr>
                    </thead>
                    <tbody>
                      {rows.map((entry) => {
                        const isViewer = entry.account_id === viewerId;
                        return (
                          <tr key={entry.account_id} className={`border-b border-[#202832] text-xs last:border-b-0 ${isViewer ? "bg-[#8fb5ff]/[0.06]" : "hover:bg-white/[0.018]"}`}>
                            <td className="py-3.5 pl-5 font-mono font-semibold text-[#8d97a3] tabular-nums">{entry.rank}</td>
                            <td>
                              <Link href={`/traders/${entry.account_id}`} className="flex items-center gap-2 font-semibold text-white hover:text-[#dce7ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                                <span className="truncate">{entry.display_name}</span><TraderBadge kind={entry.kind} isViewer={isViewer} />
                              </Link>
                            </td>
                            <td className="text-right font-mono font-semibold text-white tabular-nums slashed-zero">{formatCurrency(entry.net_worth)}</td>
                            <td className="text-right font-mono text-[#9ba5b2] tabular-nums slashed-zero">{formatCurrency(entry.cash_balance)}</td>
                            <td className="text-right font-mono text-[#9ba5b2] tabular-nums slashed-zero">{formatCurrency(entry.holdings_value)}</td>
                            <td className="pr-5 text-right font-mono text-[#9ba5b2] tabular-nums">{entry.holdings_count}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </article>
            )}
            <nav aria-label="Leaderboard pages" className="mt-4 flex items-center justify-between text-xs text-[#7f8995]">
              <span>{leaderboard.total.toLocaleString("en-GB")} traders · page {page} of {pageCount}</span>
              <span className="flex gap-2">
                {page > 1 && <Link href={leaderboardHref(filter, page - 1)} className="rounded-lg border border-[#2a3441] px-3 py-2 font-bold text-[#c4cbd3] hover:border-[#46566b] hover:text-white">← Previous</Link>}
                {page < pageCount && <Link href={leaderboardHref(filter, page + 1)} className="rounded-lg border border-[#2a3441] px-3 py-2 font-bold text-[#c4cbd3] hover:border-[#46566b] hover:text-white">Next →</Link>}
              </span>
            </nav>
          </>
        )}

        <div className="mt-8"><Label>How it&apos;s calculated</Label><p className="max-w-[70ch] text-[11px] leading-relaxed text-[#65707d]">Net worth = virtual cash + (shares held × current share price). Stockball uses virtual cash only; standings are not investment returns.</p></div>
      </section>
    </Shell>
  );
}
