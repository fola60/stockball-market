import type { PlayerBriefing } from "@/lib/api";
import { formatUkDay, formatUkTime } from "@/lib/format";
import { panel } from "../../components/market-shell";

const AVAILABILITY_LABELS: Record<NonNullable<PlayerBriefing["availability"]>["stage"], string> = {
  SUSPECTED_INJURY: "Possible injury",
  CONFIRMED_INJURY: "Injured",
  SUSPECTED_RECOVERY: "Returning from injury",
};

/** "an hour" or "90 minutes": how long before kick-off trading pauses. */
function leadTime(kickoffAt: string, lockAt: string): string {
  const minutes = Math.round((new Date(kickoffAt).getTime() - new Date(lockAt).getTime()) / 60_000);
  return minutes === 60 ? "an hour" : `${minutes} minutes`;
}

/** "Trading pauses Sat 25 Oct at 14:00" for the trade ticket, or null with no match ahead. */
export function pauseNotice(briefing: PlayerBriefing | null): string | null {
  const fixture = briefing?.next_fixture;
  if (!fixture || fixture.locked) return null;
  return `Trading pauses ${formatUkDay(fixture.lock_at)} at ${formatUkTime(fixture.lock_at)} for ${fixture.home_team} v ${fixture.away_team}.`;
}

/**
 * What to know before trading: the next match and when trading pauses for it, any injury the
 * news has reported, and the latest headlines. The market's bots read the same news.
 */
export function Briefing({ briefing }: { briefing: PlayerBriefing | null }) {
  if (!briefing) return null;
  const { next_fixture: fixture, availability, news } = briefing;
  if (!fixture && !availability && news.length === 0) return null;

  return (
    <section aria-labelledby="briefing-title" className={`${panel} mt-5`}>
      <div className="border-b border-[#202630] px-4 py-4 md:px-6">
        <h2 id="briefing-title" className="text-base font-semibold">Before you trade</h2>
        <p className="mt-1 text-[11px] text-[#77818e]">Fixtures, fitness and news. The market&apos;s bots read the same reports.</p>
      </div>
      <div className="grid gap-px bg-[#202630] md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="space-y-4 bg-[#0e131a] p-4 md:p-6">
          <div>
            <h3 className="text-[11px] font-semibold text-[#818b97]">Next match</h3>
            {fixture ? (
              <>
                <p className="mt-2 text-sm font-semibold text-white">{fixture.home_team} v {fixture.away_team}</p>
                <p className="mt-1 text-xs text-[#9ba5b2]">
                  <time dateTime={fixture.kickoff_at}>{formatUkDay(fixture.kickoff_at)} · kick-off {formatUkTime(fixture.kickoff_at)}</time>
                  {" "}· {fixture.is_home ? "home" : "away"}
                </p>
                <p className={`mt-2 rounded-lg border px-3 py-2 text-[11px] leading-4 ${fixture.locked ? "border-[#f4bb55]/25 bg-[#f4bb55]/[0.06] text-[#f4d08a]" : "border-[#273241] text-[#aab3bd]"}`}>
                  {fixture.locked
                    ? `Trading paused at ${formatUkTime(fixture.lock_at)} and reopens once the match is over and settled.`
                    : `Trading pauses at ${formatUkTime(fixture.lock_at)} on ${formatUkDay(fixture.lock_at)}, ${leadTime(fixture.kickoff_at, fixture.lock_at)} before kick-off, and reopens after full time.`}
                </p>
              </>
            ) : <p className="mt-2 text-xs text-[#77818e]">No upcoming match in the fixture list.</p>}
          </div>
          <div>
            <h3 className="text-[11px] font-semibold text-[#818b97]">Fitness</h3>
            {availability ? (
              <p className="mt-2 rounded-lg border border-[#f16d73]/30 bg-[#f16d73]/[0.07] px-3 py-2 text-xs leading-5 text-[#ffb3b7]">
                <strong className="font-semibold text-[#ff9ca1]">{AVAILABILITY_LABELS[availability.stage]}</strong>
                {availability.injury_type ? ` · ${availability.injury_type}` : ""}
                {availability.expected_absence_until ? ` · expected back around ${formatUkDay(availability.expected_absence_until)}` : ""}
                <span className="block text-[11px] text-[#c98f93]">Last reported {formatUkDay(availability.last_evidence_at)}</span>
              </p>
            ) : <p className="mt-2 text-xs text-[#77818e]">No injury reported.</p>}
          </div>
        </div>
        <div className="bg-[#0e131a] p-4 md:p-6">
          <h3 className="text-[11px] font-semibold text-[#818b97]">Latest news</h3>
          {news.length > 0 ? (
            <ul className="mt-2 divide-y divide-[#202630]">
              {news.map((item) => (
                <li key={item.document_id} className="py-2.5 first:pt-1">
                  <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-xs font-semibold leading-5 text-white hover:text-[#b8d0ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{item.title}</a>
                  <p className="mt-0.5 text-[11px] text-[#6f7a87]">{item.source} · <time dateTime={item.published_at}>{formatUkDay(item.published_at)}</time></p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-xs text-[#77818e]">No recent headlines about this player.</p>}
        </div>
      </div>
    </section>
  );
}
