"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { Instrument } from "@/lib/api";
import { ClubBadge, PlayerAvatar } from "./player-media";

type SearchableInstrument = Pick<
  Instrument,
  | "id" | "display_name" | "player_name" | "player_club" | "player_position" | "symbol" | "status"
  | "player_image_version" | "club_badge_version"
>;

function playerName(instrument: SearchableInstrument): string {
  return instrument.player_name ?? instrument.display_name.replace(/\s+Share$/i, "");
}

function matchRank(instrument: SearchableInstrument, query: string): number | null {
  const name = playerName(instrument).toLocaleLowerCase();
  const symbol = instrument.symbol.toLocaleLowerCase();
  const club = instrument.player_club?.toLocaleLowerCase() ?? "";

  if (name === query || symbol === query || club === query) return 0;
  if (name.startsWith(query) || symbol.startsWith(query) || club.startsWith(query)) return 1;
  if (name.includes(query) || symbol.includes(query) || club.includes(query)) return 2;
  return null;
}

export function PlayerSearch({ instruments }: { instruments: SearchableInstrument[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const resultsId = useId();
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const results = useMemo(
    () => normalizedQuery
      ? instruments
        .filter((instrument) => instrument.status !== "DELISTED")
        .map((instrument) => ({ instrument, rank: matchRank(instrument, normalizedQuery) }))
        .filter((match): match is { instrument: SearchableInstrument; rank: number } => match.rank !== null)
        .sort((a, b) => a.rank - b.rank || playerName(a.instrument).localeCompare(playerName(b.instrument)))
        .slice(0, 8)
      : [],
    [instruments, normalizedQuery],
  );

  function showSearch() {
    setOpen(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function closeSearch() {
    setOpen(false);
    setQuery("");
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        showSearch();
      }
      if (event.key === "Escape" && open) closeSearch();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  return <>
    <button ref={triggerRef} type="button" aria-label="Search players or clubs" aria-haspopup="dialog" aria-expanded={open} aria-controls={resultsId} onClick={showSearch} className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#242c37] bg-[#0e131a] px-0 text-[#a6afba] transition-colors hover:border-[#516074] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] sm:w-52 sm:justify-start sm:px-3">
      <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4 shrink-0" fill="none"><circle cx="8.6" cy="8.6" r="4.9" stroke="currentColor" strokeWidth="1.6"/><path d="m12.3 12.3 4.1 4.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
      <span className="sr-only sm:not-sr-only sm:ml-2 sm:text-xs">Search</span>
      <kbd className="ml-auto hidden rounded border border-white/10 px-1 py-0.5 font-mono text-[11px] text-[#78828e] sm:block">⌘K</kbd>
    </button>

    {open ? <>
      <button type="button" aria-label="Close search" onClick={closeSearch} className="fixed inset-0 z-30 cursor-default bg-[#080b10]/55" />
      <section id={resultsId} role="dialog" aria-modal="true" aria-label="Search player stocks" className="fixed inset-x-3 top-[80px] z-40 overflow-hidden rounded-xl border border-[#303b4b] bg-[#0e131a] sm:left-auto sm:right-7 sm:w-[32rem]">
        <div className="flex items-center gap-3 border-b border-[#202630] px-4">
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4 shrink-0 text-[#8fb5ff]" fill="none"><circle cx="8.6" cy="8.6" r="4.9" stroke="currentColor" strokeWidth="1.6"/><path d="m12.3 12.3 4.1 4.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
          <label htmlFor="player-stock-search" className="sr-only">Search player stocks</label>
          <input ref={inputRef} id="player-stock-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Player, ticker or club" autoComplete="off" className="h-14 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-[#697481]" />
          <button type="button" onClick={closeSearch} className="rounded px-1.5 py-1 text-[11px] font-semibold text-[#8c97a5] hover:bg-white/[0.05] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">ESC</button>
        </div>

        <div className="max-h-[min(26rem,calc(100vh-10rem))] overflow-y-auto p-2">
          {!normalizedQuery ? <p className="px-3 py-8 text-center text-xs leading-5 text-[#818b97]">Search by player name, ticker, or club.</p> : null}
          {normalizedQuery && results.length === 0 ? <p className="px-3 py-8 text-center text-xs leading-5 text-[#818b97]">No player stocks match “{query.trim()}”.</p> : null}
          {results.map(({ instrument }) => <Link prefetch={false} key={instrument.id} href={`/instrument/${instrument.id}`} onClick={closeSearch} className="flex items-center justify-between gap-4 rounded-lg px-3 py-3 transition-colors hover:bg-white/[0.045] focus:bg-white/[0.045] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
            <span className="flex min-w-0 items-center gap-3"><PlayerAvatar instrument={instrument} name={playerName(instrument)} className="size-9" /><span className="min-w-0"><strong className="block truncate text-sm font-semibold text-white">{playerName(instrument)}</strong><small className="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-[#818b97]"><ClubBadge instrument={instrument} /><span className="truncate">{instrument.player_club ?? "Club unavailable"} · {instrument.player_position ?? "—"}</span></small></span></span>
            <span className="shrink-0 text-[11px] font-semibold text-[#8fb5ff]">{instrument.symbol}</span>
          </Link>)}
        </div>
      </section>
    </> : null}
  </>;
}
