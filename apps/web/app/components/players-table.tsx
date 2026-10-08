import Link from "next/link";
import { playerName, type Instrument } from "@/lib/api";
import { formatCurrency, formatMoneyShort, formatChange, moveTone } from "@/lib/format";
import { marketValue } from "@/lib/market";
import { ClubBadge, PlayerAvatar } from "./player-media";
import { Sparkline } from "./sparkline";

function Change({ value, decimals }: { value: number; decimals: number }) {
  return <td className={`px-2 py-2.5 text-right tabular-nums slashed-zero ${moveTone(value, decimals)}`}>{formatChange(value, decimals)}</td>;
}

export function PlayersTable({ rows, startRank = 1 }: { rows: { instrument: Instrument; prices: number[] }[]; startRank?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-left text-[11px]">
        <thead>
          <tr className="border-y border-[#202630] bg-black/10 text-[10px] uppercase tracking-[0.08em] text-[#65707d]">
            <th scope="col" className="py-2.5 pl-[18px] font-bold">#</th>
            <th scope="col" className="px-2 py-2.5 font-bold">Player</th>
            <th scope="col" className="px-2 py-2.5 text-right font-bold">Price</th>
            <th scope="col" className="px-2 py-2.5 text-right font-bold">24h</th>
            <th scope="col" className="px-2 py-2.5 text-right font-bold">7 days</th>
            <th scope="col" className="px-2 py-2.5 text-right font-bold">Market value</th>
            <th scope="col" className="px-2 py-2.5 text-right font-bold">Traded 24h</th>
            <th scope="col" className="py-2.5 pl-2 pr-[18px] text-right font-bold">7-day chart</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ instrument, prices }, index) => {
            const name = playerName(instrument);
            const week = Number(instrument.price_change_7d);
            return (
              <tr key={instrument.id} className="border-b border-[#1b222c] last:border-b-0 hover:bg-white/[0.018]">
                <td className="py-2.5 pl-[18px] text-[#65707d] tabular-nums">{startRank + index}</td>
                <td className="px-2 py-2.5">
                  <Link prefetch={false} href={`/instrument/${instrument.id}`} className="flex items-center gap-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
                    <PlayerAvatar instrument={instrument} name={name} className="size-[30px]" />
                    <span className="min-w-0">
                      <strong className="flex items-center gap-2 font-semibold text-white hover:text-[#dce7ff]">{name}{instrument.status === "FROZEN" && <span className="rounded border border-[#f4bb55]/30 px-1 py-px text-[9px] font-bold text-[#f4bb55]">PAUSED</span>}</strong>
                      <small className="mt-1 flex items-center gap-1.5 text-[10px] text-[#818b97]"><ClubBadge instrument={instrument} className="size-3" />{instrument.player_club ?? "Club unavailable"} · {instrument.player_position?.split(",")[0] ?? "—"}</small>
                    </span>
                  </Link>
                </td>
                <td className="px-2 py-2.5 text-right tabular-nums slashed-zero">{formatCurrency(instrument.current_price)}</td>
                <Change value={Number(instrument.price_change_24h)} decimals={2} />
                <Change value={week} decimals={1} />
                <td className="px-2 py-2.5 text-right tabular-nums slashed-zero">{formatMoneyShort(marketValue(instrument))}</td>
                <td className="px-2 py-2.5 text-right text-[#9ba5b2] tabular-nums slashed-zero">{formatMoneyShort(instrument.traded_value_24h)}</td>
                <td className="py-2.5 pl-2 pr-[18px]">{prices.length > 1 ? <Sparkline prices={prices} rising={week >= 0} area={false} className="ml-auto block h-6 w-24" /> : <span className="block text-right text-[#65707d]">—</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
