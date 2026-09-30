import type { TraderKind } from "@/lib/api";

export function TraderBadge({ kind, isViewer = false }: { kind: TraderKind; isViewer?: boolean }) {
  if (isViewer) {
    return <span className="rounded-md bg-[#8fb5ff]/15 px-1.5 py-0.5 text-[10px] font-extrabold uppercase tracking-wide text-[#8fb5ff]">You</span>;
  }
  if (kind === "BOT") {
    return <span title="Stockball synthetic trader" className="rounded-md border border-[#2a3441] px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#7f8995]">Bot</span>;
  }
  return null;
}
