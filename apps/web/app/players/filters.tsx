"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { POSITIONS, SORTS, playersHref, type PlayersQuery, type PlayersSort } from "./query";

const control = "h-[30px] rounded-md border border-[#27303b] bg-[#11171f] px-2 text-[11px] text-[#edf1f5] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]";

export function PlayersFilters({ query, clubs }: { query: PlayersQuery; clubs: string[] }) {
  const router = useRouter();
  const go = (next: Partial<PlayersQuery>) => router.push(playersHref({ ...query, ...next }));

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-[11px] text-[#8d97a3]">
        Club
        <select value={query.club ?? ""} onChange={(event) => go({ club: event.target.value || null })} className={control}>
          <option value="">All clubs</option>
          {clubs.map((club) => <option key={club} value={club}>{club}</option>)}
        </select>
      </label>
      <div role="group" aria-label="Position" className="flex gap-1">
        {[null, ...POSITIONS].map((position) => {
          const active = query.position === position;
          return (
            <Link key={position ?? "all"} href={playersHref({ ...query, position })} aria-current={active ? "true" : undefined} className={`flex h-[30px] items-center rounded-md border px-2.5 text-[11px] font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${active ? "border-[#8fb5ff] bg-[#8fb5ff]/10 text-white" : "border-[#27303b] bg-[#11171f] text-[#9ba5b2] hover:text-white"}`}>{position ?? "All"}</Link>
          );
        })}
      </div>
      <label className="flex items-center gap-2 text-[11px] text-[#8d97a3]">
        Sort
        <select value={query.sort} onChange={(event) => go({ sort: event.target.value as PlayersSort })} className={control}>
          {Object.entries(SORTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
    </div>
  );
}
