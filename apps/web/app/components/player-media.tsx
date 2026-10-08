/* eslint-disable @next/next/no-img-element -- small, hash-versioned PNGs served by our own proxy route; next/image adds an optimizer round-trip for no gain */
import type { Instrument } from "@/lib/api";

type PlayerMedia = Pick<Instrument, "id" | "player_image_version" | "club_badge_version">;

function imageUrl(instrumentId: string, image: "player-image" | "club-badge", version: string) {
  return `/api/instruments/${instrumentId}/${image}?v=${encodeURIComponent(version)}`;
}

function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? words.at(-1)?.[0] ?? "" : "";
  return (first + last).toLocaleUpperCase();
}

/**
 * Round player portrait, falling back to initials when no portrait is stored. Decorative:
 * the player's name is always rendered next to it.
 */
export function PlayerAvatar({ instrument, name, className = "size-10" }: { instrument: PlayerMedia; name: string; className?: string }) {
  const version = instrument.player_image_version;
  return (
    <span aria-hidden="true" className={`@container relative grid shrink-0 place-items-center overflow-hidden rounded-full bg-[#1a212b] ring-1 ring-white/[0.06] ${className}`}>
      {version ? (
        <img src={imageUrl(instrument.id, "player-image", version)} alt="" loading="lazy" decoding="async" className="size-full object-cover object-top" />
      ) : (
        <span className="text-[36cqw] font-bold leading-none tracking-wide text-[#8a95a3]">{initials(name)}</span>
      )}
    </span>
  );
}

/** Club badge shown beside the club name; renders nothing when no badge is stored. */
export function ClubBadge({ instrument, className = "size-3.5" }: { instrument: PlayerMedia; className?: string }) {
  const version = instrument.club_badge_version;
  if (!version) return null;
  return <img src={imageUrl(instrument.id, "club-badge", version)} alt="" aria-hidden="true" loading="lazy" decoding="async" className={`shrink-0 object-contain ${className}`} />;
}

/** A club badge by FotMob team, for fixtures; renders nothing when no badge is stored. */
export function TeamBadge({ teamId, version, className = "size-3.5" }: { teamId: string; version: string | null; className?: string }) {
  if (!version) return null;
  return <img src={`/api/teams/${teamId}/badge?v=${encodeURIComponent(version)}`} alt="" aria-hidden="true" loading="lazy" decoding="async" className={`shrink-0 object-contain ${className}`} />;
}
