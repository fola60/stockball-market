"use client";

import Link from "next/link";
import { useActionState, useId, useRef, useState, useTransition, type CSSProperties, type ReactNode } from "react";
import { AuthTrigger } from "@/app/components/auth-dialog";
import { ClubBadge, PlayerAvatar } from "@/app/components/player-media";
import { RadarHexagon, type RadarPoint } from "@/app/components/radar-hexagon";
import { formatCurrency } from "@/lib/format";
import { callPlayer, claimReward } from "./actions";
import type { Card, Guess, Media, Result, Round } from "./types";

// Each colour has one job: blue is the hidden card and your choices,
// green and red are the price direction, gold is coins.
const MYSTERY = "#8fb5ff";
const UP = "#35d07f";
const DOWN = "#f16d73";
const GOLD = "#f4bb55";
const SIZES = { small: "<2%", medium: "2–5%", large: "5%+" } as const;
const BARS = { small: 1, medium: 2, large: 3 } as const;

const muted = "text-[#9ba8b8]";
const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";
export const primaryAction = `inline-flex min-h-12 items-center justify-center rounded-xl bg-[#8fb5ff] px-6 text-sm font-bold text-[#080b10] transition-colors hover:bg-[#a9c6ff] ${focus} disabled:cursor-not-allowed disabled:bg-[#2a3544] disabled:text-[#8d97a3]`;
const number = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });

// Signals arrive as sentences; the card has room for a word or two.
const SIGNALS: Record<string, string> = {
  "Trading paused for a match": "Match on",
  "Trading recently reopened after a match": "Just played",
  "Reported injury concern": "Injury doubt",
  "Reported injured": "Injured",
  "Reported close to returning": "Nearly fit",
  "Recently cleared to play": "Fit again",
  "Recent coverage leaned positive": "Good press",
  "Recent coverage leaned negative": "Bad press",
  "The player appeared in several trusted reports": "In the news",
};

type Reveal = { result: Result; points: number | null; guess: Guess | null; media?: Media | null };
type Coin = { x: number; y: number; peak: number; r: number; delay: number; size: number };
type Burst = { id: number; x: number; y: number; points: number; coins: Coin[] };

function signed(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
}

function weekMove(chart: (number | null)[]) {
  const known = chart.filter((value): value is number => value !== null);
  return known.length > 1 ? (known[known.length - 1] / known[0] - 1) * 100 : null;
}

/** The card's clues as six 0–100 axes: football on the right, market on the left. */
function clueAxes(card: Card): RadarPoint[] {
  const { form, trading } = card;
  const clamp = (value: number) => Math.max(6, Math.min(100, Math.round(value)));
  const week = weekMove(card.chart);
  const comparisons = form.limited_minutes ? [] : form.metrics.flatMap((metric) => metric.comparison ? [metric.comparison] : []);
  const heat = comparisons.length
    ? comparisons.reduce((sum, comparison) => sum + (comparison === "Above usual" ? 90 : comparison === "Below usual" ? 25 : 55), 0) / comparisons.length
    : null;
  const share = trading.buy_share_low;
  const activity: Record<string, number> = { High: 90, Typical: 55, Low: 25 };
  return [
    { label: "Form", score: form.rating === null ? 0 : clamp((form.rating - 5.5) / 3 * 100), display: form.rating === null ? "—" : number.format(form.rating) },
    { label: "Minutes", score: form.appearances ? clamp(form.minutes_low / 450 * 100) : 0, display: form.appearances ? `${form.minutes_low}+` : "—" },
    { label: "Output", score: heat === null ? 0 : clamp(heat), display: heat === null ? "—" : heat >= 70 ? "Hot" : heat <= 40 ? "Cold" : "Steady" },
    { label: "Momentum", score: week === null ? 0 : clamp(50 + week * 5), display: week === null ? "—" : signed(week) },
    { label: "Buying", score: share === null ? 0 : clamp(share + 5), display: share === null ? "—" : `${share}–${share + 10}%` },
    { label: "Activity", score: activity[trading.activity] ?? 0, display: share === null ? "None" : trading.activity },
  ];
}

function Arrow({ up, className = "size-4" }: { up: boolean; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={`shrink-0 ${className}`} fill="none">
      <path d={up ? "M8 13V3.5M4 7.5l4-4 4 4" : "M8 3v9.5M4 8.5l4 4 4-4"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Ascending bars: one for a small move, three for a big one. */
function Bars({ count }: { count: number }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 18 14" className="h-3.5 w-[18px]">
      {[0, 1, 2].map((index) => (
        <rect key={index} x={index * 6.5} y={10 - index * 4} width="4.5" height={4 + index * 4} rx="1" fill="currentColor" opacity={index < count ? 1 : 0.22} />
      ))}
    </svg>
  );
}

function CoinIcon({ className = "size-5", dim = false }: { className?: string; dim?: boolean }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={className} opacity={dim ? 0.22 : 1}>
      <defs>
        <radialGradient id={`${id}g`} cx="35%" cy="30%" r="75%">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset="0.45" stopColor={GOLD} />
          <stop offset="1" stopColor="#c9861a" />
        </radialGradient>
      </defs>
      <circle cx="12" cy="12" r="11" fill={dim ? "#56606d" : `url(#${id}g)`} />
      <circle cx="12" cy="12" r="7.6" fill="none" stroke={dim ? "#2c333d" : "#b8781a"} strokeOpacity="0.55" strokeWidth="1.2" />
      <path d="M9.4 9.6c.4-1 1.4-1.6 2.6-1.6 1.5 0 2.5.8 2.5 1.9 0 2.4-5 1.4-5 4 0 1.2 1.1 2.1 2.6 2.1 1.2 0 2.2-.6 2.6-1.6" fill="none" stroke={dim ? "#2c333d" : "#9a6512"} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** The hidden player: a grey head and shoulders behind a question mark. */
function Silhouette({ accent = MYSTERY }: { accent?: string }) {
  return (
    <span aria-hidden="true" className="relative grid size-20 shrink-0 place-items-center rounded-full p-[3px]" style={{ background: accent }}>
      <svg viewBox="0 0 80 80" className="size-full rounded-full bg-[#161c25]">
        <circle cx="40" cy="31" r="14" fill="#3b4451" />
        <path d="M12 80c2-18 13-28 28-28s26 10 28 28z" fill="#3b4451" />
      </svg>
      <span className="absolute -right-1 -bottom-1 grid size-7 place-items-center rounded-full text-sm font-bold text-[#080b10]" style={{ background: accent }}>?</span>
    </span>
  );
}

/** The revealed face, ringed in the colour of where the price went. */
function Face({ result, media }: { result: Result; media?: Media | null }) {
  const instrument = { id: result.instrument_id, player_image_version: media?.player_image_version ?? null, club_badge_version: media?.club_badge_version ?? null };
  return (
    <span className="relative shrink-0 rounded-full p-[3px]" style={{ background: Number(result.move) > 0 ? UP : DOWN }}>
      <PlayerAvatar instrument={instrument} name={result.name} className="size-[74px] bg-[#161c25]" />
      {media?.club_badge_version && (
        <span className="absolute -right-1 -bottom-1 grid size-7 place-items-center rounded-full bg-[#0d121a] ring-2 ring-[#0d121a]">
          <ClubBadge instrument={instrument} className="size-5" />
        </span>
      )}
    </span>
  );
}

function ReplayChart({ values, accent, split, after }: { values: (number | null)[]; accent: string; split?: number; after?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const known = values.filter((value): value is number => value !== null);
  const min = Math.min(100, ...known) - 0.5;
  const max = Math.max(100, ...known) + 0.5;
  const x = (index: number) => 3 + index * 294 / (values.length - 1);
  const y = (value: number) => 50 - (value - min) * 46 / (max - min);
  const path = (start: number, end: number) => {
    let drawing = false;
    return values.map((value, i) => {
      if (value === null || i < start || i > end) {
        drawing = false;
        return "";
      }
      const point = `${drawing ? "L" : "M"}${x(i)},${y(value)}`;
      drawing = true;
      return point;
    }).join(" ");
  };
  const cutoff = split ?? values.length - 1;
  const before = values.slice(0, cutoff + 1).flatMap((value, i) => value === null ? [] : [[x(i), y(value)] as const]);
  const area = before.length > 1 ? `M${before[0][0]},56 ${before.map(([px, py]) => `L${px},${py}`).join(" ")} L${before[before.length - 1][0]},56Z` : "";
  const last = values[cutoff];
  const week = weekMove(values.slice(0, cutoff + 1));
  return (
    <svg viewBox="0 0 300 58" className="w-full overflow-visible" role="img" aria-label={`Price over the 7 days before the replay${week === null ? "" : `: ${signed(week)}`}${split === undefined ? "" : ", then the 24 hours after it"}.`}>
      <defs>
        <linearGradient id={`${id}fill`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={accent} stopOpacity="0.38" />
          <stop offset="1" stopColor={accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`M3,${y(100)}H297`} stroke="#2c3646" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
      {area && <path d={area} fill={`url(#${id}fill)`} />}
      <path d={path(0, cutoff)} stroke={accent} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" vectorEffect="non-scaling-stroke" />
      {split !== undefined && <>
        <path d={`M${x(split)},2V56`} stroke="#5b6678" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
        <path d={path(split, values.length - 1)} stroke={after} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" vectorEffect="non-scaling-stroke" />
      </>}
      {last !== null && split === undefined && <>
        <circle cx={x(cutoff)} cy={y(last)} r="5" fill={accent} opacity="0.25" />
        <circle cx={x(cutoff)} cy={y(last)} r="2.4" fill={accent} />
      </>}
    </svg>
  );
}

/** Shares bought against shares sold, as one split bar. */
function Flow({ buys, sells, trades }: { buys: number; sells: number; trades: number }) {
  const total = buys + sells;
  const share = total ? buys / total * 100 : 50;
  return (
    <div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={`${number.format(buys)} shares bought and ${number.format(sells)} sold in ${trades} trades`}>
        <span className="rounded-l-full" style={{ width: `${share}%`, background: UP }} />
        <span className="flex-1 rounded-r-full" style={{ background: DOWN }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] font-semibold">
        <span style={{ color: UP }}>{compact.format(buys)} bought</span>
        <span className={muted}>{trades} trades</span>
        <span style={{ color: DOWN }}>{compact.format(sells)} sold</span>
      </div>
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[#8fb5ff]/[0.12] px-2.5 py-1 text-[11px] font-bold text-[#c6d7f5]">
      {children}
    </span>
  );
}

function CallLabel({ guess }: { guess: Guess }) {
  const up = guess.direction === "up";
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color: up ? UP : DOWN }}>
      <Arrow up={up} className="size-3.5" />
      <Bars count={BARS[guess.band]} />
      <span className="text-white">{SIZES[guess.band]}</span>
    </span>
  );
}

function Front({ card, pick, onPick, onFlip, signedIn, open, pending, error }: {
  card: Card; pick: Partial<Guess>; onPick: (pick: Partial<Guess>) => void; onFlip: () => void;
  signedIn: boolean; open: boolean; pending: boolean; error?: string;
}) {
  const accent = MYSTERY;
  const axes = clueAxes(card);
  const signals = [card.match_status, card.attention].flatMap((text) => text ? text.split(" · ") : []).map((text) => SIGNALS[text] ?? text);
  const ready = Boolean(pick.direction && pick.band);
  const choice = (selected: boolean, color: string): CSSProperties => selected
    ? { background: color, color: "#080b10" }
    : { background: `${color}14`, color, boxShadow: `inset 0 0 0 1px ${color}4d` };
  return (
    <>
      <header className="flex items-center gap-4">
        <Silhouette />
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-[-0.02em]">Mystery {card.position === "Player" ? "player" : card.position.toLowerCase()}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {signals.length ? signals.map((signal) => <Chip key={signal}>{signal}</Chip>) : <Chip>No news</Chip>}
          </div>
        </div>
      </header>

      <div className="mx-auto mt-3 w-full max-w-[330px]">
        <RadarHexagon size="card" showScores accent={accent} axes={axes} label={`Clues: ${axes.map((axis) => `${axis.label} ${axis.display}`).join(", ")}`} />
      </div>

      <div className="mt-1">
        <ReplayChart values={card.chart} accent={accent} />
        <p className={`mt-1 flex justify-between text-[10px] font-semibold ${muted}`}><span>7 days ago</span><span>Now?</span></p>
      </div>

      {open && <div className="mt-4 grid gap-2" role="group" aria-label="Your call for the next 24 hours">
        <div className="grid grid-cols-2 gap-2">
          {(["up", "down"] as const).map((direction) => (
            <button key={direction} type="button" aria-pressed={pick.direction === direction} onClick={() => onPick({ ...pick, direction })} className={`flex h-12 items-center justify-center gap-1.5 rounded-xl text-sm font-bold transition-[background-color,color,box-shadow,transform] active:scale-[0.97] ${focus}`} style={choice(pick.direction === direction, direction === "up" ? UP : DOWN)}>
              <Arrow up={direction === "up"} /> {direction === "up" ? "Up" : "Down"}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2">
          {(Object.keys(SIZES) as Guess["band"][]).map((band) => (
            <button key={band} type="button" aria-pressed={pick.band === band} aria-label={`Move of ${SIZES[band]}`} onClick={() => onPick({ ...pick, band })} className={`flex h-11 items-center justify-center gap-1.5 rounded-xl text-xs font-bold transition-[background-color,color,box-shadow,transform] active:scale-[0.97] ${focus}`} style={choice(pick.band === band, accent)}>
              <Bars count={BARS[band]} /> {SIZES[band]}
            </button>
          ))}
        </div>
        {signedIn
          ? <button type="button" className={`${primaryAction} mt-1 w-full`} disabled={!ready || pending} onClick={onFlip}>{pending ? "Flipping…" : "Flip the card"}</button>
          : <AuthTrigger className={`${primaryAction} mt-1 w-full`}>Sign in to flip</AuthTrigger>}
        {error && <p role="alert" className="text-center text-xs text-[#f16d73]">{error}</p>}
      </div>}
    </>
  );
}

function Back({ card, reveal, onNext, nextLabel }: { card: Card; reveal: Reveal; onNext: () => void; nextLabel: string }) {
  const { result, points, guess, media } = reveal;
  const move = Number(result.move);
  const tone = move > 0 ? UP : DOWN;
  const verdict = points === 2 ? "Spot on" : points === 1 ? "Right way" : points === 0 ? "Missed" : null;
  return (
    <>
      <header className="flex items-center gap-4">
        <Face result={result} media={media} />
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold tracking-[-0.02em]">
            <Link href={`/instrument/${result.instrument_id}`} className={`hover:underline ${focus}`}>{result.name}</Link>
          </h2>
          <p className={`mt-0.5 truncate text-xs ${muted}`}>{[result.club, card.position].filter(Boolean).join(" · ")}</p>
        </div>
      </header>

      <div className="mt-6 text-center">
        <strong className="inline-flex items-center gap-2 font-mono text-5xl font-bold tracking-[-0.03em]" style={{ color: tone }}>
          <Arrow up={move > 0} className="size-8" />
          {move > 0 ? "+" : "−"}{number.format(Math.abs(move))}%
        </strong>
        <p className={`mt-1 text-[11px] font-semibold ${muted}`}>in the next 24 hours</p>
      </div>

      <div className="mt-5">
        <ReplayChart values={result.chart} accent={MYSTERY} split={card.chart.length - 1} after={tone} />
        <p className={`mt-1 flex justify-between text-[10px] font-semibold ${muted}`}><span>7 days ago</span><span>+24h</span></p>
      </div>

      <div className="mt-5"><Flow buys={Number(result.trading.buys)} sells={Number(result.trading.sells)} trades={result.trading.trades} /></div>

      <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl bg-white/[0.045] px-4 py-3">
        {guess ? <span className="text-xs font-bold"><CallLabel guess={guess} /></span> : <span className={`text-xs ${muted}`}>Not played</span>}
        {points !== null && (
          <span className="flex items-center gap-2">
            <span className="text-xs font-bold" style={{ color: points > 0 ? GOLD : "#9ba8b8" }}>{verdict}</span>
            <span className="flex" aria-label={`${points} of 2 points`}>
              <CoinIcon className="size-6" dim={points < 1} />
              <CoinIcon className="-ml-1.5 size-6" dim={points < 2} />
            </span>
          </span>
        )}
      </div>

      <div className="mt-auto pt-4"><button type="button" onClick={onNext} className={`${primaryAction} w-full gap-2`}>{nextLabel} <span aria-hidden="true">→</span></button></div>
    </>
  );
}

/** Coins burst out of the card and fall across the screen. */
function CoinShower({ burst }: { burst: Burst }) {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-50 overflow-hidden motion-reduce:hidden">
      {burst.coins.map((coin, index) => (
        <span
          key={index}
          className="absolute"
          style={{
            left: burst.x, top: burst.y, width: coin.size, height: coin.size,
            animation: `coin-fly 1500ms cubic-bezier(0.2, 0.7, 0.4, 1) ${coin.delay}ms both`,
            "--x": `${coin.x}px`, "--y": `${coin.y}px`, "--peak": `${coin.peak}px`, "--r": `${coin.r}deg`,
          } as CSSProperties}
        >
          <CoinIcon className="size-full drop-shadow-[0_4px_8px_rgba(0,0,0,0.45)]" />
        </span>
      ))}
      <span
        className="absolute font-mono text-4xl font-bold"
        style={{ left: burst.x, top: burst.y - 40, color: burst.points ? GOLD : "#8d97a3", textShadow: "0 4px 18px rgba(0,0,0,0.6)", animation: "score-pop 1400ms ease-out 350ms both" }}
      >
        +{burst.points}
      </span>
    </div>
  );
}

function Summary({ round, reveals, score, reward, pending }: { round: Round; reveals: (Reveal | null)[]; score: number | null; reward: string | null; pending: number }) {
  return (
    <>
      <h2 className="text-center text-lg font-semibold tracking-[-0.02em]">{score === null ? "Not played" : "Your score"}</h2>
      {score !== null && <>
        <p className="mt-2 text-center font-mono text-6xl font-bold" style={{ color: GOLD }}>{score}<span className="text-2xl text-[#9ba8b8]">/6</span></p>
        <div className="mt-3 flex justify-center gap-1" aria-hidden="true">
          {Array.from({ length: 6 }, (_, index) => <CoinIcon key={index} className="size-7" dim={index >= score} />)}
        </div>
      </>}
      <ul className="mt-6 grid grid-cols-3 gap-2">
        {reveals.map((reveal, index) => (
          <li key={index} className="flex flex-col items-center gap-2 rounded-2xl bg-white/[0.04] px-2 py-3 text-center">
            {reveal ? <Face result={reveal.result} media={reveal.media} /> : <Silhouette />}
            <span className="w-full truncate text-[11px] font-semibold">{reveal?.result.name ?? `Player ${index + 1}`}</span>
            {reveal?.points !== null && reveal?.points !== undefined && (
              <span className="flex" aria-label={`${reveal.points} of 2 points`}>
                <CoinIcon className="size-4" dim={reveal.points < 1} />
                <CoinIcon className="-ml-1 size-4" dim={reveal.points < 2} />
              </span>
            )}
          </li>
        ))}
      </ul>
      {reward !== null && Number(reward) > 0 && <p className="mt-5 text-center text-sm font-semibold" style={{ color: GOLD }}>+{formatCurrency(reward)} virtual cash</p>}
      {reward !== null && Number(reward) === 0 && <p className={`mt-5 text-center text-xs ${muted}`}>Beat your best score this week to earn more.</p>}
      {pending > 0 && <div className="mt-4 flex justify-center"><Claim amount={String(pending)} /></div>}
      <p className={`mt-5 text-center text-xs ${muted}`}>
        {round.day === round.today ? "New players at midnight." : <Link href="/daily-games" className={`font-semibold text-[#8fb5ff] underline-offset-4 hover:text-[#a9c6ff] hover:underline ${focus}`}>Play today’s game</Link>}
      </p>
    </>
  );
}

/** The row of mini cards: face down, flipped with points, then the score. */
function Deck({ reveals, slot, onSelect, finished }: { reveals: (Reveal | null)[]; slot: number; onSelect: (slot: number) => void; finished: boolean }) {
  return (
    <nav aria-label="Cards" className="flex items-center justify-center gap-2.5">
      {reveals.map((reveal, index) => {
        const active = index === slot;
        const up = reveal ? Number(reveal.result.move) > 0 : false;
        const accent = reveal ? (up ? UP : DOWN) : MYSTERY;
        return (
          <button
            key={index}
            type="button"
            aria-current={active ? "step" : undefined}
            aria-label={`Card ${index + 1}${reveal ? `, ${reveal.result.name}` : ", face down"}`}
            onClick={() => onSelect(index)}
            className={`relative grid h-14 w-10 place-items-center rounded-lg transition-transform ${active ? "-translate-y-1" : "opacity-70 hover:opacity-100"} ${focus}`}
            style={reveal
              ? { background: "#161c25", boxShadow: `inset 0 0 0 1.5px ${accent}${active ? "" : "80"}` }
              : { background: `repeating-linear-gradient(135deg, ${accent}40 0 4px, ${accent}18 4px 8px)`, boxShadow: `inset 0 0 0 1.5px ${accent}${active ? "" : "70"}` }}
          >
            {reveal
              ? <span className="flex flex-col items-center gap-0.5" style={{ color: accent }}>
                  <Arrow up={up} className="size-3.5" />
                  {reveal.points !== null && <span className="font-mono text-[10px] font-bold" style={{ color: GOLD }}>+{reveal.points}</span>}
                </span>
              : <span className="text-sm font-bold" style={{ color: accent }}>?</span>}
          </button>
        );
      })}
      <button
        type="button"
        aria-current={slot === reveals.length ? "step" : undefined}
        aria-label="Your score"
        disabled={!finished}
        onClick={() => onSelect(reveals.length)}
        className={`grid h-14 w-10 place-items-center rounded-lg bg-[#161c25] transition-transform disabled:opacity-30 ${slot === reveals.length ? "-translate-y-1" : "opacity-70 hover:opacity-100"} ${focus}`}
        style={{ boxShadow: `inset 0 0 0 1.5px ${GOLD}${slot === reveals.length ? "" : "70"}` }}
      >
        <CoinIcon className="size-5" dim={!finished} />
      </button>
    </nav>
  );
}

export function Game({ round, signedIn, media }: { round: Round; signedIn: boolean; media: Record<string, Media> }) {
  const open = round.state === "open";
  const [local, setLocal] = useState<Record<number, Reveal>>({});
  const [score, setScore] = useState<{ score: number | null; reward: string | null } | null>(null);
  const [picks, setPicks] = useState<Partial<Guess>[]>(() => round.cards.map(() => ({})));
  const [error, setError] = useState<string>();
  const [burst, setBurst] = useState<Burst | null>(null);
  const [pending, startTransition] = useTransition();
  const card = useRef<HTMLDivElement>(null);

  const reveals: (Reveal | null)[] = round.cards.map((_, index) => {
    if (local[index]) return local[index];
    const result = round.results?.[index];
    if (!result) return null;
    return { result, points: round.entry?.points?.[index] ?? null, guess: round.entry?.guesses?.[index] ?? null, media: media[result.instrument_id] };
  });
  const finished = reveals.every(Boolean);
  const total = score?.score ?? round.entry?.score ?? null;
  const reward = score?.reward ?? round.entry?.reward ?? null;
  const [slot, setSlot] = useState(() => {
    const first = reveals.findIndex((reveal) => !reveal);
    return first === -1 ? (round.entry?.score !== null && round.entry ? reveals.length : 0) : first;
  });

  if (round.state === "unavailable") {
    return (
      <div className="mx-auto max-w-[420px] rounded-3xl bg-[#0d121a] p-8 text-center shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]">
        <div className="mx-auto w-fit"><Silhouette accent="#5b6678" /></div>
        <h2 className="mt-4 text-lg font-semibold">No game today</h2>
        <p className={`mt-1 text-sm ${muted}`}>Not enough trading to deal three cards.</p>
      </div>
    );
  }

  const next = () => {
    const upcoming = [1, 2, 3].map((step) => (slot + step) % reveals.length).find((index) => !reveals[index]);
    setSlot(upcoming ?? reveals.length);
  };
  const flip = () => {
    const pick = picks[slot];
    if (!pick.direction || !pick.band) return;
    const guess = { direction: pick.direction, band: pick.band };
    setError(undefined);
    startTransition(async () => {
      const response = await callPlayer(round.day, slot, guess);
      if (response.error || !response.called) {
        setError(response.error ?? "Your call could not be saved. Try again.");
        return;
      }
      const { called } = response;
      const points = called.points[slot] ?? 0;
      setLocal((current) => ({ ...current, [slot]: { result: called.result, points, guess: called.guesses[slot], media: response.media } }));
      if (called.score !== null) setScore({ score: called.score, reward: called.reward });
      const rect = card.current?.getBoundingClientRect();
      const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
      const y = rect ? rect.top + Math.min(rect.height / 2, window.innerHeight / 2) : window.innerHeight / 2;
      const count = points === 2 ? 22 : points === 1 ? 10 : 0;
      const spread = Math.max(window.innerWidth, 600);
      setBurst({
        id: Date.now(), x, y, points,
        coins: Array.from({ length: count }, () => ({
          x: (Math.random() - 0.5) * spread,
          y: window.innerHeight * (0.45 + Math.random() * 0.5),
          peak: -(140 + Math.random() * 220),
          r: (Math.random() - 0.5) * 900,
          delay: 380 + Math.random() * 220,
          size: 22 + Math.random() * 16,
        })),
      });
    });
  };

  const summary = slot === reveals.length;
  const current = reveals[slot];
  // The card's edge shows its state: blue while hidden, green or red once flipped.
  const accent = current ? (Number(current.result.move) > 0 ? UP : DOWN) : MYSTERY;
  const lastUnflipped = reveals.filter((reveal) => !reveal).length === 0;
  const pendingReward = Number(round.pending_reward);

  return (
    <div>
      <Deck reveals={reveals} slot={slot} onSelect={setSlot} finished={finished} />

      <div ref={card} key={slot} className="mx-auto mt-5 max-w-[420px] [perspective:1400px] motion-safe:animate-game-in">
        {summary ? (
          <section aria-label="Your score" className="rounded-3xl bg-[#0d121a] p-6" style={{ boxShadow: `inset 0 0 0 1px ${GOLD}40, 0 24px 48px -24px rgba(0,0,0,0.7)`, backgroundImage: `radial-gradient(120% 70% at 50% 0%, ${GOLD}14, transparent 60%)` }}>
            <Summary round={round} reveals={reveals} score={total} reward={reward} pending={pendingReward} />
          </section>
        ) : (
          <div
            className="grid transition-transform duration-700 ease-[cubic-bezier(0.3,1.3,0.5,1)] motion-reduce:transition-none"
            style={{ transformStyle: "preserve-3d", transform: current ? "rotateY(180deg)" : "none" }}
          >
            {[false, true].map((back) => (
              <section
                key={String(back)}
                aria-label={back ? "Revealed player" : `Card ${slot + 1} of ${reveals.length}`}
                inert={back ? !current : Boolean(current)}
                className="flex flex-col [grid-area:1/1] rounded-3xl bg-[#0d121a] p-5 sm:p-6"
                style={{
                  backfaceVisibility: "hidden", WebkitBackfaceVisibility: "hidden",
                  transform: back ? "rotateY(180deg)" : undefined,
                  boxShadow: `inset 0 0 0 1px ${accent}45, 0 24px 48px -24px rgba(0,0,0,0.7)`,
                  backgroundImage: `radial-gradient(120% 60% at 100% 0%, ${accent}17, transparent 60%)`,
                }}
              >
                {back
                  ? current && <Back card={round.cards[slot]} reveal={current} onNext={next} nextLabel={lastUnflipped ? "See your score" : "Next card"} />
                  : <Front card={round.cards[slot]} pick={picks[slot]} onPick={(pick) => setPicks((all) => all.map((item, index) => index === slot ? pick : item))} onFlip={flip} signedIn={signedIn} open={open} pending={pending} error={error} />}
              </section>
            ))}
          </div>
        )}
      </div>

      {burst && <CoinShower key={burst.id} burst={burst} />}
    </div>
  );
}

export function Claim({ amount }: { amount: string }) {
  const [state, submit, pending] = useActionState(claimReward, {});
  if (state.claimed) return <p role="status" className="text-sm font-semibold" style={{ color: GOLD }}>Added to your cash.</p>;
  return <form action={submit} className="flex flex-col items-center gap-2">
    <button type="submit" className={primaryAction} disabled={pending}>
      {pending ? "Claiming…" : `Claim ${formatCurrency(amount)}`}
    </button>
    {state.error && <span role="alert" className="text-sm text-[#f16d73]">{state.error}</span>}
  </form>;
}
