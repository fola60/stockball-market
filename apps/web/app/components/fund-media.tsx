import type { IndexFund } from "@/lib/api";
import { ClubBadge } from "./player-media";

/** A fund's club badge, framed like a player avatar so fund rows line up with player rows. */
export function FundBadge({ fund, className = "size-[30px]" }: { fund: Pick<IndexFund, "id" | "club_badge_version">; className?: string }) {
  return (
    <span aria-hidden="true" className={`grid shrink-0 place-items-center rounded-lg bg-[#1a212b] ring-1 ring-white/[0.06] ${className}`}>
      <ClubBadge instrument={{ id: fund.id, player_image_version: null, club_badge_version: fund.club_badge_version }} className="size-[62%]" />
    </span>
  );
}

/** Why a fund is not trading: a player at the club is in a match, or another pause. */
export function PausedTag({ fund }: { fund: Pick<IndexFund, "status" | "freeze_reason"> }) {
  if (fund.status === "ACTIVE") return null;
  return <span className="rounded border border-[#f4bb55]/30 px-1 py-px text-[9px] font-bold text-[#f4bb55]">{fund.freeze_reason === "MATCH_DAY" ? "MATCH DAY" : "PAUSED"}</span>;
}
