import type { Metadata } from "next";
import Link from "next/link";
import { Shell, panel } from "../components/market-shell";
import { PlayersTable } from "../components/players-table";
import { getInstruments, getOptionalAccount, getSparklines, isInMarket, shellData, type Instrument } from "@/lib/api";
import { marketValue } from "@/lib/market";
import { PlayersFilters } from "./filters";
import { POSITIONS, SORTS, playersHref, type PlayersQuery, type PlayersSort, type Position } from "./query";

export const metadata: Metadata = { title: "All players — Stockball" };
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

const SORT_KEYS: Record<PlayersSort, (instrument: Instrument) => number> = {
  value: marketValue,
  day: (instrument) => Number(instrument.price_change_24h),
  week: (instrument) => Number(instrument.price_change_7d),
  traded: (instrument) => Number(instrument.traded_value_24h),
};

type SearchParams = { club?: string; position?: string; sort?: string; page?: string };

export default async function PlayersPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const [account, instruments] = await Promise.all([getOptionalAccount(), getInstruments()]);
  const listed = instruments.filter((instrument) => instrument.status !== "DELISTED");
  const clubs = [...new Set(listed.flatMap((instrument) => (instrument.player_club ? [instrument.player_club] : [])))].sort();

  const query: PlayersQuery = {
    club: params.club && clubs.includes(params.club) ? params.club : null,
    position: POSITIONS.includes(params.position as Position) ? (params.position as Position) : null,
    sort: params.sort && params.sort in SORTS ? (params.sort as PlayersSort) : "value",
  };
  const matching = listed
    .filter((instrument) => !query.club || instrument.player_club === query.club)
    .filter((instrument) => !query.position || (instrument.player_position ?? "").split(",").includes(query.position))
    .sort((a, b) => SORT_KEYS[query.sort](b) - SORT_KEYS[query.sort](a));

  const pages = Math.max(1, Math.ceil(matching.length / PAGE_SIZE));
  const page = Math.min(Math.max(Number.parseInt(params.page ?? "1", 10) || 1, 1), pages);
  const shown = matching.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  let prices: Record<string, number[]> = {};
  try {
    prices = await getSparklines(shown.map((instrument) => instrument.id), "1W");
  } catch {
    // The table still reads without its charts.
  }
  const trading = listed.filter(isInMarket).length;

  return (
    <Shell active="players" {...shellData(account, instruments)}>
      <div className="mx-auto w-full max-w-[1220px] min-w-0 px-3 pb-12 pt-7 md:px-7">
        <header className="mb-5">
          <h1 className="text-[28px] font-semibold leading-none tracking-[-0.03em] md:text-[32px]">All players</h1>
          <p className="mt-2 text-[11px] text-[#77818e]">{trading} trading · {listed.length - trading} paused</p>
        </header>
        <section aria-label="Players" className={panel}>
          <div className="flex flex-wrap items-center justify-between gap-3 px-[18px] py-4">
            <PlayersFilters query={query} clubs={clubs} />
            <p className="text-[11px] text-[#77818e]">{matching.length} player{matching.length === 1 ? "" : "s"}</p>
          </div>
          {shown.length > 0 ? (
            <PlayersTable rows={shown.map((instrument) => ({ instrument, prices: prices[instrument.id] ?? [] }))} startRank={(page - 1) * PAGE_SIZE + 1} />
          ) : (
            <p className="border-t border-[#202630] px-[18px] py-14 text-center text-xs text-[#77818e]">No players match these filters.</p>
          )}
          {pages > 1 && (
            <nav aria-label="Pages" className="flex items-center justify-between gap-3 border-t border-[#202630] px-[18px] py-3 text-[11px] font-bold">
              {page > 1 ? <Link href={playersHref(query, page - 1)} className="text-[#8fb5ff] hover:text-[#b8d0ff]">← Previous</Link> : <span />}
              <span className="font-medium text-[#77818e]">Page {page} of {pages}</span>
              {page < pages ? <Link href={playersHref(query, page + 1)} className="text-[#8fb5ff] hover:text-[#b8d0ff]">Next →</Link> : <span />}
            </nav>
          )}
        </section>
      </div>
    </Shell>
  );
}
