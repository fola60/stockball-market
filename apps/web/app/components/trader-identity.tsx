export function YouBadge() {
  return <span className="rounded-md bg-[#8fb5ff]/15 px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wide text-[#8fb5ff]">You</span>;
}

/** Marks Stockball's synthetic traders wherever their activity is shown. */
export function BotBadge() {
  return <span title="Stockball synthetic trader" className="shrink-0 rounded border border-[#3a4554] px-1.5 py-0.5 text-[9px] font-extrabold tracking-[0.06em] text-[#aab4c1]">BOT</span>;
}
