import type { IndexFund } from "@/lib/api";
import { fundCategory } from "@/lib/funds";
import { ClubBadge } from "./player-media";

type BadgeFund = Pick<IndexFund, "id" | "club_badge_version" | "symbol" | "index_kind" | "category">;

/** Each category's accent, shared by badges and the homepage filters. */
export const CATEGORY_ACCENTS: Record<string, string> = {
  Market: "#8fb5ff",
  Positions: "#35d07f",
  Performance: "#f4bb55",
  Signals: "#c49bff",
  "Club groups": "#5fd4e0",
  "Nationality and age": "#f58fb5",
  Clubs: "#a6afba",
};

export const categoryAccent = (fund: Pick<IndexFund, "category" | "index_kind">) =>
  CATEGORY_ACCENTS[fundCategory(fund)] ?? "#a6afba";

/** The fund's ticker without its prefix: "IDX-SB20" is "SB20". */
export const fundCode = (symbol: string) => symbol.replace(/^IDX-/, "");

/**
 * A team fund shows its club badge; a rule fund shows its ticker in its category's colour.
 * Framed like a player avatar so fund rows line up with player rows.
 */
export function FundBadge({ fund, className = "size-[30px]" }: { fund: BadgeFund; className?: string }) {
  if (fund.index_kind === "TEAM" && fund.club_badge_version) {
    return (
      <span aria-hidden="true" className={`grid shrink-0 place-items-center rounded-lg bg-[#1a212b] ring-1 ring-white/[0.06] ${className}`}>
        <ClubBadge instrument={{ id: fund.id, player_image_version: null, club_badge_version: fund.club_badge_version }} className="size-[62%]" />
      </span>
    );
  }
  const code = fundCode(fund.symbol);
  const accent = categoryAccent(fund);
  return (
    <span aria-hidden="true" className={`grid shrink-0 place-items-center rounded-lg ring-1 ring-white/[0.06] ${className}`} style={{ background: `${accent}1f`, color: accent }}>
      <svg viewBox="0 0 40 40" className="size-full">
        <text x="20" y="20" textAnchor="middle" dominantBaseline="central" fill="currentColor" fontWeight="800" fontSize={code.length >= 5 ? 10 : code.length === 4 ? 11.5 : 13} letterSpacing="-0.02em" fontFamily="inherit">{code}</text>
      </svg>
    </span>
  );
}

/** Why a fund is not trading: a player in it is in a match, or another pause. */
export function PausedTag({ fund }: { fund: Pick<IndexFund, "status" | "freeze_reason"> }) {
  if (fund.status === "ACTIVE") return null;
  return <span className="rounded border border-[#f4bb55]/30 px-1 py-px text-[9px] font-bold text-[#f4bb55]">{fund.freeze_reason === "MATCH_DAY" ? "MATCH DAY" : "PAUSED"}</span>;
}

/** How often a rule fund is checked against its rule. */
export function reviewCadence(days: number) {
  if (days <= 1) return "Daily";
  if (days === 7) return "Weekly";
  if (days >= 28 && days <= 31) return "Monthly";
  return `Every ${days} days`;
}
