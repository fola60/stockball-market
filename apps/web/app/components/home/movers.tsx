"use client";

import Link from "next/link";
import type { MoverRow, Movers } from "@/lib/market";
import { formatCurrency, formatChange } from "@/lib/format";
import { ClubBadge, PlayerAvatar } from "../player-media";
import { Sparkline } from "../sparkline";

const DECIMALS = 2;

export function BiggestMovers({ movers, totalPlayers }: { movers: Movers; totalPlayers: number }) {
  const { risers, fallers } = movers;

  // Risers and fallers alternate in DOM order; on wide screens the two-column grid turns
  // that sequence into side-by-side columns, padded where one side runs short.
  const slots: ({ row: MoverRow; rising: boolean; rank: number } | null)[] = [];
  for (let index = 0; index < Math.max(risers.length, fallers.length); index++) {
    slots.push(risers[index] ? { row: risers[index], rising: true, rank: index + 1 } : null);
    slots.push(fallers[index] ? { row: fallers[index], rising: false, rank: index + 1 } : null);
  }

  return (
    <section aria-labelledby="movers-title" className="min-w-0 flex-[999_1_620px]">
      <h2 id="movers-title" className="mb-3 text-base font-bold">Biggest movers</h2>

      {slots.length === 0 ? (
        <p className="border-y border-[#222a35] py-14 text-center text-xs text-[#818b97]">No player has moved today yet.</p>
      ) : (
        <ol aria-label="Risers and fallers, alternating" className="grid border-t border-[#222a35] md:grid-cols-2 md:gap-x-6">
          <li aria-hidden="true" className="hidden h-9 items-center border-b border-[#222a35] text-[11px] font-extrabold tracking-[0.08em] text-[#35d07f] md:flex">▲ RISERS</li>
          <li aria-hidden="true" className="hidden h-9 items-center border-b border-[#222a35] text-[11px] font-extrabold tracking-[0.08em] text-[#f16d73] md:flex">▼ FALLERS</li>
          {slots.map((slot, index) => slot ? (
            <li key={`${slot.row.instrument.id}-${slot.rising}`} className="border-b border-[#222a35]">
              <Link prefetch={false} href={`/instrument/${slot.row.instrument.id}`} className="grid min-h-[72px] grid-cols-[minmax(0,1fr)_64px_82px] items-center gap-3 px-0.5 py-2.5 transition-colors hover:bg-white/[0.025] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff]">
                <span className="sr-only">{slot.rising ? "Riser" : "Faller"} rank {slot.rank}, {slot.rising ? "up" : "down"} {Math.abs(slot.row.change).toFixed(DECIMALS)} percent today.</span>
                <span className="flex min-w-0 items-center gap-3">
                  <PlayerAvatar instrument={slot.row.instrument} name={slot.row.name} className="size-10" />
                  <span className="min-w-0">
                    <strong className="block truncate text-[13px] font-semibold text-white">{slot.row.name}</strong>
                    <small className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-[#818b97]"><ClubBadge instrument={slot.row.instrument} /><span className="truncate">{slot.row.instrument.player_club ?? "Club unavailable"} · {slot.row.instrument.player_position?.split(",")[0] ?? "—"}{slot.row.fullyHeld ? " · all shares held" : ""}</span></small>
                  </span>
                </span>
                <Sparkline prices={slot.row.prices} rising={slot.rising} className="h-[30px] w-full" />
                <span className="text-right">
                  <strong className="block text-[13px] font-medium tabular-nums slashed-zero">{formatCurrency(slot.row.instrument.current_price)}</strong>
                  <small className={`mt-1.5 inline-flex min-w-[62px] justify-end rounded-md px-[7px] py-1 text-[11px] font-semibold text-white tabular-nums slashed-zero ${slot.rising ? "bg-[#07852f]" : "bg-[#d91c32]"}`}>{formatChange(slot.row.change, DECIMALS)}</small>
                </span>
              </Link>
            </li>
          ) : <li key={`empty-${index}`} aria-hidden="true" className="hidden border-b border-[#222a35] md:block" />)}
        </ol>
      )}
      <Link href="/players" className="mt-3.5 inline-block text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">All {totalPlayers} players →</Link>
    </section>
  );
}
