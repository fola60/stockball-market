import Link from "next/link";
import type { Fixture, Instrument, Matchday } from "@/lib/api";
import { playerName } from "@/lib/api";
import type { FixtureMarket } from "@/lib/market";
import { formatCurrency, formatMoneyShort, formatMove, formatUkDay, formatUkTime, formatUkWeekday, moveTone } from "@/lib/format";
import { TeamBadge } from "../player-media";

const LIVE_STATES = new Set<Fixture["status"]>(["UPCOMING", "PAUSED", "LIVE"]);

function score(fixture: Fixture) {
  return fixture.score?.replace(/\s*-\s*/, "–") ?? "";
}

function lockDescription(minutes: number) {
  return minutes % 60 === 0 ? `${minutes / 60} hour${minutes === 60 ? "" : "s"}` : `${minutes} minutes`;
}

function LockIcon() {
  return <svg viewBox="0 0 20 20" aria-hidden="true" className="size-2.5 shrink-0" fill="none"><rect x="5" y="9" width="10" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.8" /><path d="M7 9V6.5a3 3 0 0 1 6 0V9" stroke="currentColor" strokeWidth="1.8" /></svg>;
}

/** What a fixture means for trading right now, in a few words. */
function TradingState({ fixture }: { fixture: Fixture }) {
  switch (fixture.status) {
    case "UPCOMING":
      return <span className="flex items-center gap-1 text-[10px] text-[#77818e]"><span className="sr-only">Trading pauses at</span><LockIcon />{formatUkTime(fixture.lock_at)}</span>;
    case "PAUSED":
      return <span className="text-[10px] font-semibold text-[#f4bb55]">Paused</span>;
    case "LIVE":
      return <span className="text-[10px] font-semibold text-[#f4bb55]">Live {score(fixture)}</span>;
    case "FINISHED":
      return <span className="text-[10px] font-semibold text-[#c1c8d0]">FT {score(fixture)}</span>;
    default:
      return <span className="text-[10px] text-[#77818e]">Postponed</span>;
  }
}

function Star({ instrument }: { instrument: Instrument | null }) {
  if (!instrument) return <span className="rounded-lg bg-[#0e131a] p-2 text-[10px] text-[#65707d]">No players listed</span>;
  const change = Number(instrument.price_change_7d);
  return (
    <Link prefetch={false} href={`/instrument/${instrument.id}`} className="rounded-lg bg-[#0e131a] p-2 hover:bg-white/[0.04] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">
      <small className="block truncate text-[10px] text-[#818b97]">{playerName(instrument).split(" ").at(-1)}</small>
      <b className="mt-1 block text-xs tabular-nums slashed-zero">{formatCurrency(instrument.current_price)}</b>
      <small className={`mt-0.5 block text-[10px] tabular-nums slashed-zero ${moveTone(change, 1)}`}>{formatMove(change, 1)} · 7d</small>
    </Link>
  );
}

function FeaturedFixture({ market, signedIn }: { market: FixtureMarket; signedIn: boolean }) {
  const { fixture } = market;
  const pauseNote = fixture.status === "UPCOMING"
    ? `Pauses at ${formatUkTime(fixture.lock_at)}`
    : fixture.status === "PAUSED" || fixture.status === "LIVE"
      ? "Trading reopens after full time"
      : null;
  return (
    <div className="mx-3 flex flex-col gap-2.5 rounded-[10px] border border-[#3a4a63] bg-[#11171f] p-3">
      <div className="flex items-center justify-between gap-2 text-[10px] text-[#8d97a3]">
        <b className="text-[#c1c8d0]">{formatUkWeekday(fixture.kickoff_at).toUpperCase()} {formatUkTime(fixture.kickoff_at)} · TOP FIXTURE</b>
        <TradingState fixture={fixture} />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 text-center">
        {[fixture.home, fixture.away].map((team, index) => (
          <span key={team.team_id} className={`flex flex-col items-center gap-1.5 ${index === 1 ? "order-3" : ""}`}>
            <TeamBadge teamId={team.team_id} version={team.badge_version} className="size-6" />
            <strong className="text-xs font-bold">{team.short_name}</strong>
          </span>
        ))}
        <span className="order-2 text-[11px] text-[#65707d]">{fixture.status === "FINISHED" || fixture.status === "LIVE" ? score(fixture) : "v"}</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Star instrument={market.homeStar} />
        <Star instrument={market.awayStar} />
      </div>
      {signedIn && market.holdings.names.length > 0 ? (
        <p className="text-center text-[10px] leading-relaxed text-[#aeb7c2]">You hold {market.holdings.names.slice(0, 2).join(", ")}{market.holdings.names.length > 2 ? ` and ${market.holdings.names.length - 2} more` : ""} · {formatMoneyShort(market.holdings.value)}</p>
      ) : pauseNote ? (
        <p className="text-center text-[10px] leading-relaxed text-[#77818e]">{pauseNote}</p>
      ) : null}
    </div>
  );
}

export function MatchdayPanel({ matchday, fixtures, signedIn }: { matchday: Matchday | null; fixtures: FixtureMarket[]; signedIn: boolean }) {
  const round = matchday?.next_round;
  if (!round || fixtures.length === 0) {
    return (
      <aside aria-label="Matchday" className="flex min-w-0 flex-[1_1_340px] flex-col justify-center rounded-xl border border-[#222a35] bg-[#0e131a] p-6 text-center">
        <p className="text-sm font-semibold">No fixtures scheduled</p>
        <p className="mt-2 text-xs leading-5 text-[#77818e]">The next matchday appears here once its fixtures are published.</p>
      </aside>
    );
  }

  const candidates = fixtures.filter((market) => LIVE_STATES.has(market.fixture.status));
  const featured = [...(candidates.length > 0 ? candidates : fixtures)].sort((a, b) => b.marketValue - a.marketValue)[0];
  const rest = fixtures.filter((market) => market !== featured);
  const days = rest.reduce<{ label: string; fixtures: Fixture[] }[]>((groups, market) => {
    const label = formatUkDay(market.fixture.kickoff_at);
    const group = groups.find((candidate) => candidate.label === label);
    if (group) group.fixtures.push(market.fixture);
    else groups.push({ label, fixtures: [market.fixture] });
    return groups;
  }, []);
  const first = fixtures[0].fixture.kickoff_at;
  const last = fixtures.at(-1)?.fixture.kickoff_at ?? first;
  const range = formatUkDay(first) === formatUkDay(last) ? formatUkDay(first) : `${formatUkDay(first)} – ${formatUkDay(last)}`;

  return (
    <aside aria-labelledby="matchday-title" className="flex min-w-0 flex-[1_1_340px] flex-col overflow-hidden rounded-xl border border-[#222a35] bg-[#0e131a]">
      <div className="px-4 pb-3 pt-4">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="matchday-title" className="text-base font-bold">Matchday {round.round}</h2>
          <span className="text-[11px] text-[#8d97a3]">{range}</span>
        </div>
        <p className="mt-1.5 text-[10px] leading-relaxed text-[#77818e]">Each club’s players stop trading {lockDescription(matchday.lineup_lock_minutes)} before kick-off and reopen after full time.</p>
      </div>
      <FeaturedFixture market={featured} signedIn={signedIn} />
      <div className="flex-1 pb-2 pt-1">
        {days.map((day) => (
          <div key={day.label}>
            <p className="px-4 pb-1.5 pt-3 text-[10px] font-extrabold tracking-[0.08em] text-[#8d97a3]">{day.label.toUpperCase()}</p>
            <ul>
              {day.fixtures.map((fixture) => (
                <li key={fixture.match_id} className="grid min-h-8 grid-cols-[38px_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-[#1b222c] px-4 py-1.5 text-[11px]">
                  <b className="font-bold text-[#c1c8d0]">{formatUkTime(fixture.kickoff_at)}</b>
                  <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
                    <TeamBadge teamId={fixture.home.team_id} version={fixture.home.badge_version} className="size-3" />
                    <span className="truncate">{fixture.home.short_name}</span>
                    <span className="shrink-0 text-[#65707d]">v</span>
                    <TeamBadge teamId={fixture.away.team_id} version={fixture.away.badge_version} className="size-3" />
                    <span className="truncate">{fixture.away.short_name}</span>
                  </span>
                  <TradingState fixture={fixture} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}
