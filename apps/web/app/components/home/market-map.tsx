"use client";

import Link from "next/link";
import { useState } from "react";
import type { ClubTile } from "@/lib/market";
import { formatMoneyShort, formatChange, moveTone } from "@/lib/format";
import { TeamBadge } from "../player-media";

type Period = "day" | "week";

/** The club's change as displayed, so colour never contradicts the printed figure. */
const change = (club: ClubTile, period: Period) =>
  Number((period === "week" ? club.change7d : club.change1d).toFixed(period === "week" ? 1 : 2));

/** Green or red by direction, stronger with size, scaled to this period's largest move. */
function heat(value: number, largest: number) {
  if (Math.abs(value) < 1e-9 || largest === 0) return "rgba(58, 69, 84, 0.45)";
  const alpha = (0.2 + 0.65 * Math.min(Math.abs(value) / largest, 1)).toFixed(2);
  return value > 0 ? `rgba(7, 133, 47, ${alpha})` : `rgba(217, 28, 50, ${alpha})`;
}

/**
 * Rows of tiles whose areas are proportional to market value: a row's height is its share
 * of the total and each tile's width its share of the row.
 */
function rows(clubs: ClubTile[]) {
  const sizes = clubs.length <= 6 ? [clubs.length] : clubs.length <= 13 ? [Math.ceil(clubs.length / 2)] : [6, 7];
  const result: ClubTile[][] = [];
  let start = 0;
  for (const size of sizes) {
    result.push(clubs.slice(start, start + size));
    start += size;
  }
  if (start < clubs.length) result.push(clubs.slice(start));
  return result.filter((row) => row.length > 0);
}

export function MarketMap({ clubs }: { clubs: ClubTile[] }) {
  const [period, setPeriod] = useState<Period>("week");
  if (clubs.length === 0) return null;

  const decimals = period === "week" ? 1 : 2;
  const largest = Math.max(...clubs.map((club) => Math.abs(change(club, period))));
  const ranked = [...clubs].sort((a, b) => change(b, period) - change(a, period));
  const compact = ranked.length > 7 ? [...ranked.slice(0, 5), ...ranked.slice(-2)] : ranked;
  const toggle = (
    <div role="group" aria-label="Map period" className="flex gap-0.5 rounded-[9px] border border-[#242c37] bg-[#0b0f15] p-[3px]">
      {(["day", "week"] as const).map((option) => (
        <button key={option} type="button" aria-pressed={period === option} onClick={() => setPeriod(option)} className={`h-7 rounded-md px-3 text-[11px] font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${period === option ? "bg-[#8fb5ff] text-[#080b10]" : "text-[#8d97a3] hover:text-white"}`}>{option === "day" ? "Today" : "7 days"}</button>
      ))}
    </div>
  );

  return (
    <section aria-labelledby="map-title" className="overflow-hidden rounded-xl border border-[#222a35] bg-[#0e131a]">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 md:px-[18px]">
        <div>
          <h2 id="map-title" className="text-base font-bold"><span className="md:hidden">Clubs {period === "week" ? "this week" : "today"}</span><span className="hidden md:inline">Market map</span></h2>
          <p className="mt-1.5 hidden text-[11px] text-[#77818e] md:block">Clubs sized by market value, coloured by price change. The colour scale fits the period.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3.5">
          <div aria-hidden="true" className="hidden items-center gap-1.5 text-[10px] text-[#8d97a3] md:flex">
            <span>{formatChange(-largest, decimals)}</span>
            {[-1, -0.5, 0, 0.5, 1].map((step) => <span key={step} className="h-2.5 w-[22px] rounded-sm" style={{ background: heat(step * largest, largest) }} />)}
            <span>{formatChange(largest, decimals)}</span>
          </div>
          {toggle}
        </div>
      </div>

      <div className="hidden h-[480px] flex-col gap-[3px] px-[18px] pb-[18px] md:flex">
        {rows(clubs).map((row, rowIndex) => (
          <div key={rowIndex} className="flex min-h-0 gap-[3px]" style={{ flex: `${row.reduce((total, club) => total + club.marketValue, 0)} 1 0px` }}>
            {row.map((club) => {
              const value = change(club, period);
              return (
                <Link key={club.club} prefetch={false} href={`/players?club=${encodeURIComponent(club.club)}`} aria-label={`${club.club}: ${formatChange(value, decimals)}, market value ${formatMoneyShort(club.marketValue)}`} className={`flex min-w-0 flex-col justify-between gap-1.5 overflow-hidden rounded-md text-white transition-[filter] hover:brightness-125 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${rowIndex === 0 ? "p-3" : rowIndex === 1 ? "p-2.5" : "p-2"}`} style={{ flex: `${club.marketValue} 1 0px`, background: heat(value, largest) }}>
                  <span className="flex min-w-0 items-start justify-between gap-1.5">
                    <span className="min-w-0">
                      <strong className={`flex min-w-0 items-center gap-1.5 font-bold ${rowIndex === 0 ? "text-[13px]" : rowIndex === 1 ? "text-[11px]" : "text-[10px]"}`}>
                        {rowIndex < 2 && club.team && <TeamBadge teamId={club.team.team_id} version={club.team.badge_version} className="size-3.5" />}
                        <span className="truncate">{club.team?.short_name ?? club.club}</span>
                      </strong>
                      {rowIndex < 2 && <small className="mt-0.5 block whitespace-nowrap text-[10px] text-white/70">{formatMoneyShort(club.marketValue)}</small>}
                    </span>
                    <b className={`shrink-0 font-bold tabular-nums slashed-zero ${rowIndex === 0 ? "text-[15px]" : rowIndex === 1 ? "text-xs" : "text-[11px]"}`}>{formatChange(value, decimals)}</b>
                  </span>
                  {rowIndex === 0 && (
                    <span className="flex flex-col gap-1 text-[10px] text-white/85">
                      {club.players.map((player) => (
                        <span key={player.id} className="flex justify-between gap-1.5"><span className="truncate">{player.name}</span><span className="tabular-nums slashed-zero">{formatChange(period === "week" ? player.change7d : player.change1d, decimals)}</span></span>
                      ))}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      <ol className="border-t border-[#222a35] md:hidden">
        {compact.map((club) => {
          const value = change(club, period);
          return (
            <li key={club.club} className="border-b border-[#222a35] last:border-b-0">
              <Link prefetch={false} href={`/players?club=${encodeURIComponent(club.club)}`} className="grid min-h-11 grid-cols-[minmax(0,1fr)_96px_56px] items-center gap-2.5 px-4 text-[11px] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff]">
                <span className="flex min-w-0 items-center gap-2 font-semibold">{club.team && <TeamBadge teamId={club.team.team_id} version={club.team.badge_version} className="size-3.5" />}<span className="truncate">{club.team?.short_name ?? club.club}</span></span>
                <span aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-[#1a212b]"><span className="block h-full" style={{ width: `${largest > 0 ? (Math.abs(value) / largest) * 100 : 0}%`, background: value > 0 ? "#35d07f" : "#f16d73" }} /></span>
                <b className={`text-right font-bold tabular-nums slashed-zero ${moveTone(value, decimals)}`}>{formatChange(value, decimals)}</b>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
