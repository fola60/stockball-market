"use client";

import Link from "next/link";
import { useState } from "react";
import type { IndexFund } from "@/lib/api";
import { fundCategory, groupFunds, hasMovement } from "@/lib/funds";
import { formatChange, formatCurrency, moveTone } from "@/lib/format";
import { FundBadge, PausedTag, categoryAccent } from "../fund-media";
import { Sparkline } from "../sparkline";

const ALL = "All";
const LEAD_SYMBOL = "IDX-SB20";
const CARDS_BESIDE_LEAD = 8;

type Props = { funds: IndexFund[]; prices: Record<string, number[]> };

function ChangeChip({ value }: { value: number }) {
  return (
    <span className={`inline-flex rounded-md px-2 py-1 text-xs font-bold text-white tabular-nums slashed-zero ${value >= 0 ? "bg-[#07852f]" : "bg-[#d91c32]"}`}>{formatChange(value, 1)}</span>
  );
}

function LeadCard({ fund, prices }: { fund: IndexFund; prices: number[] }) {
  const week = Number(fund.basket_change_7d);
  return (
    <Link prefetch={false} href={`/funds/${fund.id}`} className="group relative flex min-w-0 flex-col justify-between gap-5 overflow-hidden rounded-xl border border-[#2a3442] bg-[#111823] p-5 transition-colors hover:border-[#3a4656] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] col-span-2 lg:row-span-2" style={{ borderTopColor: categoryAccent(fund), borderTopWidth: 2 }}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <FundBadge fund={fund} className="size-12" />
          <div className="min-w-0">
            <h3 className="flex items-center gap-2 truncate text-lg font-bold text-white">{fund.display_name}<PausedTag fund={fund} /></h3>
            <p className="mt-0.5 text-[11px] font-medium text-[#818b97]">{fund.symbol} · {fundCategory(fund)}</p>
          </div>
        </div>
        <ChangeChip value={week} />
      </div>
      {fund.description && <p className="max-w-[44ch] text-[13px] leading-5 text-[#b4bdc8]">{fund.description}</p>}
      {hasMovement(prices) && <Sparkline prices={prices} rising={week >= 0} className="h-20 w-full" />}
      {fund.top_holdings.length > 0 && (
        <ol aria-label="Largest holdings" className="grid gap-1.5">
          {fund.top_holdings.map((holding) => (
            <li key={holding.instrument_id} className="grid grid-cols-[minmax(0,1fr)_88px_44px] items-center gap-2.5 text-[11px]">
              <span className="truncate text-[#c5ccd4]">{holding.player_name}</span>
              <span aria-hidden="true" className="h-1 overflow-hidden rounded bg-[#242c37]"><i className="block h-full" style={{ width: `${Math.min(100, Number(holding.weight) * 4)}%`, background: categoryAccent(fund) }} /></span>
              <span className="text-right tabular-nums text-[#8d97a3]">{Number(holding.weight).toFixed(1)}%</span>
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <strong className="block text-[28px] font-semibold leading-none tabular-nums slashed-zero">{formatCurrency(fund.current_price)}</strong>
          <span className="mt-2 block text-[11px] text-[#818b97]">
            {fund.constituent_count} players · <span className={`tabular-nums slashed-zero ${moveTone(fund.basket_change_24h)}`}>{formatChange(fund.basket_change_24h)}</span> today
          </span>
        </div>
        <span className="text-xs font-extrabold text-[#8fb5ff] group-hover:text-[#b8d0ff]">Trade the fund →</span>
      </div>
    </Link>
  );
}

function FundCard({ fund, prices }: { fund: IndexFund; prices: number[] }) {
  const week = Number(fund.basket_change_7d);
  return (
    <Link prefetch={false} href={`/funds/${fund.id}`} aria-label={`${fund.display_name}: ${formatCurrency(fund.current_price)} a unit, ${formatChange(week, 1)} over 7 days`} className="flex min-w-0 flex-col justify-between gap-2.5 rounded-xl border border-[#222a35] bg-[#0e131a] p-3 sm:gap-3 sm:p-3.5 transition-colors hover:border-[#3a4656] hover:bg-[#111823] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]" style={{ borderTopColor: categoryAccent(fund), borderTopWidth: 2 }}>
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="hidden sm:block"><FundBadge fund={fund} className="size-9" /></span>
          <div className="min-w-0">
            <h3 className="flex items-center gap-1.5 truncate text-[13px] font-bold text-white">{fund.display_name}<PausedTag fund={fund} /></h3>
            <p className="mt-0.5 truncate text-[10px] font-medium text-[#818b97]">{fund.symbol}<span className="hidden sm:inline"> · {fund.constituent_count} players</span></p>
          </div>
        </div>
        <b className={`hidden shrink-0 text-[13px] font-bold tabular-nums slashed-zero sm:block ${moveTone(week, 1)}`}>{formatChange(week, 1)}</b>
      </div>
      {fund.top_holdings.length > 0 && (
        <p className="truncate text-[11px] text-[#9ba5b2]">{fund.top_holdings.slice(0, 3).map((holding) => holding.player_name.split(" ").at(-1)).join(" · ")}</p>
      )}
      <div className="flex items-end justify-between gap-3">
        <strong className="text-[15px] font-semibold tabular-nums slashed-zero">{formatCurrency(fund.current_price)}</strong>
        {hasMovement(prices) && <Sparkline prices={prices} rising={week >= 0} area={false} className="hidden h-7 w-24 sm:block" />}
        <b className={`text-[13px] font-bold tabular-nums slashed-zero sm:hidden ${moveTone(week, 1)}`}>{formatChange(week, 1)}</b>
      </div>
    </Link>
  );
}

/** The rule funds: a lead fund, then the biggest movers or one category's funds. */
export function IndexFunds({ funds, prices }: Props) {
  const [category, setCategory] = useState(ALL);
  if (funds.length === 0) return null;

  const groups = groupFunds(funds);
  const shown = category === ALL ? funds : funds.filter((fund) => fundCategory(fund) === category);
  const lead = (category === ALL && shown.find((fund) => fund.symbol === LEAD_SYMBOL)) || shown[0];
  const rest = shown.filter((fund) => fund.id !== lead.id);
  const cards = category === ALL
    ? [...rest].sort((a, b) => Math.abs(Number(b.basket_change_7d)) - Math.abs(Number(a.basket_change_7d))).slice(0, CARDS_BESIDE_LEAD)
    : rest;

  return (
    <section aria-labelledby="index-funds-title" className="rounded-2xl border border-[#222a35] bg-[radial-gradient(120%_140%_at_0%_0%,rgba(143,181,255,0.10),transparent_55%),#0b1017] p-4 md:p-5">
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 id="index-funds-title" className="text-xl font-bold tracking-[-0.02em] md:text-[22px]">Index funds</h2>
          <Link href="/funds" className="text-[11px] font-bold text-[#8fb5ff] hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">All funds →</Link>
        </div>
        <div role="group" aria-label="Fund category" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-0.5 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
          {[ALL, ...groups.map((group) => group.category)].map((option) => (
            <button key={option} type="button" aria-pressed={category === option} onClick={() => setCategory(option)} className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[11px] font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] ${category === option ? "bg-[#8fb5ff] text-[#080b10]" : "border border-[#242c37] text-[#8d97a3] hover:text-white"}`}>
              {option !== ALL && <span aria-hidden="true" className="size-1.5 rounded-full" style={{ background: category === option ? "#080b10" : categoryAccent({ category: option, index_kind: "RULE" }) }} />}
              {option}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2.5 sm:gap-3 lg:auto-rows-fr lg:grid-cols-4">
        <LeadCard fund={lead} prices={prices[lead.id] ?? []} />
        {cards.map((fund) => <FundCard key={fund.id} fund={fund} prices={prices[fund.id] ?? []} />)}
      </div>
    </section>
  );
}
