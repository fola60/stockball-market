import Link from "next/link";
import type { ReactNode } from "react";
import { playerName, type Instrument, type RatedPlayer } from "@/lib/api";
import { formatCurrency, formatMoneyShort, formatMove, moveTone } from "@/lib/format";
import { panel } from "../market-shell";
import { PlayerAvatar } from "../player-media";

function goals(count: number) {
  if (count >= 3) return count === 3 ? "Hat-trick" : `${count} goals`;
  return count === 2 ? "Two goals" : count === 1 ? "Goal" : null;
}

function Row({ instrument, lead, detail, metric, change, changeLabel }: { instrument: Instrument; lead: ReactNode; detail: string; metric: string; change: number; changeLabel: string }) {
  const name = playerName(instrument);
  return (
    <li className="border-t border-[#1b222c]">
      <Link prefetch={false} href={`/instrument/${instrument.id}`} className="grid grid-cols-[auto_32px_minmax(0,1fr)_auto] items-center gap-2.5 px-[18px] py-2.5 hover:bg-white/[0.025] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#8fb5ff]">
        {lead}
        <PlayerAvatar instrument={instrument} name={name} className="size-8" />
        <span className="min-w-0">
          <strong className="block truncate text-xs font-semibold">{name}</strong>
          <small className="mt-1 block truncate text-[10px] text-[#818b97]">{detail}</small>
        </span>
        <span className="text-right">
          <b className="block text-xs font-semibold tabular-nums slashed-zero">{metric}</b>
          <small className={`mt-1 block text-[10px] tabular-nums slashed-zero ${moveTone(change, changeLabel === "today" ? 2 : 1)}`}>{formatMove(change, changeLabel === "today" ? 2 : 1)} · {changeLabel}</small>
        </span>
      </Link>
    </li>
  );
}

function ListPanel({ id, title, note, children }: { id: string; title: string; note: string; children: ReactNode }) {
  return (
    <article aria-labelledby={id} className={panel}>
      <div className="flex items-baseline justify-between gap-2 px-[18px] pb-3 pt-4">
        <h2 id={id} className="text-sm font-bold">{title}</h2>
        <span className="text-[10px] text-[#77818e]">{note}</span>
      </div>
      <ol>{children}</ol>
    </article>
  );
}

export function MostTraded({ instruments }: { instruments: Instrument[] }) {
  return (
    <ListPanel id="traded-title" title="Most traded today" note="by value traded">
      {instruments.length === 0 && <li className="border-t border-[#1b222c] px-[18px] py-8 text-center text-xs text-[#77818e]">No trades in the last 24 hours.</li>}
      {instruments.map((instrument, index) => (
        <Row
          key={instrument.id}
          instrument={instrument}
          lead={<span className="w-3.5 text-[11px] font-bold text-[#65707d]">{index + 1}</span>}
          detail={`${instrument.player_club ?? "Club unavailable"} · ${instrument.player_position?.split(",")[0] ?? "—"}`}
          metric={formatMoneyShort(instrument.traded_value_24h)}
          change={Number(instrument.price_change_24h)}
          changeLabel="today"
        />
      ))}
    </ListPanel>
  );
}

export function TopRated({ round, entries }: { round: number | null; entries: { rated: RatedPlayer; instrument: Instrument }[] }) {
  if (round === null || entries.length === 0) return null;
  return (
    <ListPanel id="rated-title" title={`Top rated · Matchday ${round}`} note="FotMob ratings">
      {entries.map(({ rated, instrument }) => {
        const result = `${rated.home_team} ${rated.score?.replace(/\s*-\s*/, "–") ?? "v"} ${rated.away_team}`;
        const scored = goals(rated.goals);
        return (
          <Row
            key={instrument.id}
            instrument={instrument}
            lead={<span className="w-[38px] rounded-md border border-[#2b3542] py-1 text-center text-[11px] font-bold tabular-nums">{rated.rating}</span>}
            detail={scored ? `${scored} · ${result}` : result}
            metric={formatCurrency(instrument.current_price)}
            change={Number(instrument.price_change_7d)}
            changeLabel="7d"
          />
        );
      })}
    </ListPanel>
  );
}
