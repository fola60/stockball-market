import type { Metadata } from "next";
import Link from "next/link";
import { Shell } from "@/app/components/market-shell";
import { apiRequest, getOptionalAccount, getInstruments, getSearchFunds, shellData } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Claim, Game } from "./game";
import type { Round } from "./types";

export const metadata: Metadata = { title: "Blind Market — Stockball" };
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

export default async function BlindMarketPage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const query = typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const [account, players, funds, round] = await Promise.all([
    getOptionalAccount(), getInstruments(), getSearchFunds(),
    apiRequest<Round>(`/v1/blind-market${query}`).catch(() => null),
  ]);
  const prior = round && previousDay(round.day);
  const link = "font-semibold text-[#b8d0ff] underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#8fb5ff]";

  return (
    <Shell active="blind-market" {...shellData(account, players, funds)}>
      <div className="mx-auto w-full max-w-[1260px] min-w-0 px-3 py-7 md:px-7 md:py-9">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] md:text-[42px]">Blind Market</h1>
            <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-[#a8b4c2]">
              Three anonymous player stocks. Read the clues, then predict the direction and size of each 24-hour move.
            </p>
          </div>
          {round && <nav aria-label="Replay dates" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
            {prior && <Link className={link} href={`/blind-market?day=${prior}`} prefetch={false}>Previous round</Link>}
            <time className="font-mono text-[#a8b4c2]" dateTime={round.day}>{dayLabel(round.day)}</time>
            {round.day !== round.today && <Link className={link} href="/blind-market" prefetch={false}>Today</Link>}
          </nav>}
        </header>

        {round && Number(round.pending_reward) > 0 && <div className="mb-5"><Claim amount={round.pending_reward} /></div>}

        {round?.entry?.score !== undefined && (
          <section aria-label="Your result" className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-[#26303d] py-4">
            <strong className="font-mono text-lg">{round.entry.score}/6 points</strong>
            <span className="text-sm text-[#a8b4c2]">{Number(round.entry.reward) > 0 ? `This round earned ${formatCurrency(round.entry.reward ?? "0")} in virtual cash.` : "Your weekly reward did not increase this round."}</span>
          </section>
        )}

        {round ? <Game key={round.day} round={round} signedIn={Boolean(account)} /> : (
          <section className="rounded-xl border border-[#26303d] bg-[#0e131a] p-6">
            <h2 className="text-lg font-semibold">Replay temporarily unavailable</h2>
            <p className="my-2 text-sm text-[#a8b4c2]">Try opening today’s replay again.</p>
            <Link href="/blind-market" prefetch={false} className={link}>Open today’s replay</Link>
          </section>
        )}

        {round && <details className="mt-7 border-y border-[#26303d] py-4 text-sm">
          <summary className={`cursor-pointer ${link}`}>Scoring and weekly rewards</summary>
          <p className="mt-3 max-w-[68ch] leading-relaxed text-[#a8b4c2]">
            Earn one point for each correct direction and another for the correct size. Six points earns the full weekly top-up of {formatCurrency(round.weekly_topup)} in virtual cash. Improve your best daily score during the week to earn the difference. Weeks start on Monday.
          </p>
          <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-3">
            {round.payout_percent.map((percent, score) => score >= 1 && (
              <div key={score}>
                <dt className="text-xs text-[#a8b4c2]">{score === 1 ? "0–1" : score}/6 points</dt>
                <dd className="mt-1 font-mono">{percent}%</dd>
              </div>
            ))}
          </dl>
        </details>}
      </div>
    </Shell>
  );
}
