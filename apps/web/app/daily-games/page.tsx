import type { Metadata } from "next";
import Link from "next/link";
import { Shell } from "@/app/components/market-shell";
import { apiRequest, getOptionalAccount, getInstruments, getSearchFunds, shellData } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Game } from "./game";
import type { Media, Round } from "./types";

export const metadata: Metadata = { title: "Daily Games — Stockball" };
export const dynamic = "force-dynamic";

function previousDay(day: string) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

function dayLabel(day: string) {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Dublin",
  }).format(new Date(`${day}T12:00:00Z`));
}

export default async function DailyGamesPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const query = typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const [account, players, funds, round] = await Promise.all([
    getOptionalAccount(), getInstruments(), getSearchFunds(),
    apiRequest<Round>(`/v1/blind-market${query}`).catch(() => null),
  ]);
  const prior = round && previousDay(round.day);
  const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";
  const link = `font-semibold text-[#8fb5ff] underline-offset-4 hover:text-[#a9c6ff] hover:underline ${focus}`;
  const pill = `rounded-lg px-2.5 py-1.5 font-semibold text-[#8fb5ff] hover:bg-[#8fb5ff]/[0.12] hover:text-[#a9c6ff] ${focus}`;

  // Portraits only for players already revealed, so a face never gives a card away.
  const revealed = new Set((round?.results ?? []).flatMap((result) => result ? [result.instrument_id] : []));
  const media: Record<string, Media> = Object.fromEntries(players.filter((player) => revealed.has(player.id)).map((player) => [
    player.id, { player_image_version: player.player_image_version, club_badge_version: player.club_badge_version },
  ]));

  return (
    <Shell active="daily-games" {...shellData(account, players, funds)}>
      <div className="mx-auto w-full max-w-[880px] min-w-0 px-4 py-7 selection:bg-[#8fb5ff]/30 md:px-7 md:py-10">
        <header className="mb-7 flex flex-col items-center gap-3 text-center">
          <h1 className="text-3xl font-bold tracking-[-0.03em] text-white md:text-[42px]">Daily Games</h1>
          <p className="text-sm text-[#a8b4c2]">Guess where each mystery player’s price went next.</p>
          {round && <nav aria-label="Game dates" className="flex items-center gap-1 rounded-xl bg-white/[0.04] p-1 text-xs">
            {prior && <Link className={pill} href={`/daily-games?day=${prior}`} prefetch={false} aria-label="Previous day">‹</Link>}
            <time className="px-1.5 font-mono text-[#dbe4f0]" dateTime={round.day}>{dayLabel(round.day)}</time>
            {round.day !== round.today && <Link className={pill} href="/daily-games" prefetch={false}>Today ›</Link>}
          </nav>}
        </header>

        {round ? <Game key={round.day} round={round} signedIn={Boolean(account)} media={media} /> : (
          <section className="mx-auto max-w-[420px] rounded-3xl border border-white/[0.08] bg-[#0d121a] p-6 text-center">
            <h2 className="text-lg font-semibold">Today’s game is temporarily unavailable</h2>
            <p className="my-2 text-sm text-[#a8b4c2]">Try opening it again.</p>
            <Link href="/daily-games" prefetch={false} className={link}>Open today’s game</Link>
          </section>
        )}

        {round && <details className="mx-auto mt-10 max-w-[420px] border-t border-white/[0.07] pt-4 text-sm">
          <summary className={`cursor-pointer ${link}`}>How scoring works</summary>
          <p className="mt-3 leading-relaxed text-[#a8b4c2]">
            One coin for the right direction, another for the right size. Six coins earns the full weekly top-up of {formatCurrency(round.weekly_topup)} in virtual cash. Beat your best score of the week to earn the difference. Weeks start on Monday, and each day’s game closes at midnight, Dublin time.
          </p>
          <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-3">
            {round.payout_percent.map((percent, points) => points >= 1 && (
              <div key={points}>
                <dt className="text-xs text-[#a8b4c2]">{points === 1 ? "0–1" : points}/6 coins</dt>
                <dd className="mt-1 font-mono">{percent}%</dd>
              </div>
            ))}
          </dl>
        </details>}
      </div>
    </Shell>
  );
}
