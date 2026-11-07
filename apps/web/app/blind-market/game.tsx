"use client";

import Link from "next/link";
import { useActionState } from "react";
import { AuthTrigger } from "@/app/components/auth-dialog";
import { formatCurrency } from "@/lib/format";
import { claimReward, lockGuesses } from "./actions";
import { BANDS, type Card, type Guess, type Result, type Round } from "./types";

const action = "inline-flex min-h-11 items-center justify-center rounded-lg bg-[#8fb5ff] px-5 text-sm font-bold text-[#080b10] hover:bg-[#adc9ff] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#8fb5ff] disabled:cursor-wait disabled:opacity-65";
const muted = "text-[#9ba8b8]";
const number = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
const exactMove = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 6 });

function ReplayChart({ values, split }: { values: (number | null)[]; split?: number }) {
  const known = values.filter((value): value is number => value !== null);
  const min = Math.min(100, ...known) - 0.5;
  const max = Math.max(100, ...known) + 0.5;
  const x = (index: number) => 6 + index * 288 / (values.length - 1);
  const y = (value: number) => 65 - (value - min) * 59 / (max - min);
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
  const last = values[cutoff];
  const start = known[0];
  const trend = last === null || start === undefined ? "unavailable" : last > start ? "rose" : last < start ? "fell" : "was flat";
  return (
    <figure className="mt-4">
      <svg viewBox="0 0 300 71" className="w-full" role="img" aria-label={`Indexed price chart. The price ${trend === "unavailable" ? "trend was unavailable" : trend} before the cutoff.`}>
        <path d={`M6,${y(100)}H294`} stroke="#344052" strokeDasharray="3 4" />
        <path d={path(0, cutoff)} stroke="#8fb5ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        {split !== undefined && <>
          <path d={`M${x(split)},3V68`} stroke="#8191a7" strokeDasharray="3 4" />
          <path d={path(split, values.length - 1)} stroke="#f4ca79" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </>}
        {last !== null && <circle cx={x(cutoff)} cy={y(last)} r="3" fill="#8fb5ff" />}
      </svg>
      <figcaption className={`flex justify-between gap-2 text-[11px] ${muted}`}>
        <span>7 days earlier</span>
        {split !== undefined && <span>Replay cutoff</span>}
        <span>{split === undefined ? "Replay cutoff" : "24h later"}</span>
      </figcaption>
    </figure>
  );
}

function Clues({ card }: { card: Card }) {
  const { form, trading } = card;
  const regulationMinutes = form.appearances * 90;
  const minutes = form.minutes_low === regulationMinutes
    ? `about ${form.minutes_low} min`
    : `${form.minutes_low}–${form.minutes_low + 49} min`;
  return (
    <>
      <ReplayChart values={card.chart} />
      <section aria-label="Recent form" className="mt-5 border-t border-[#26303d] pt-4">
        <h3 className="text-sm font-semibold">Recent form</h3>
        <p className={`mt-1 text-xs leading-relaxed ${muted}`}>
          {form.appearances > 0 ? <>
            Last {form.appearances} {form.appearances === 1 ? "appearance" : "appearances"} · {minutes}
            {form.rating !== null && <> · {number.format(form.rating)} avg. rating</>}
          </> : "No verified appearances before the cutoff."}
        </p>
        {form.limited_minutes ? (
          <p className={`mt-2 text-xs ${muted}`}>Limited minutes for a form comparison.</p>
        ) : form.metrics.length > 0 && (
          <dl className="mt-2 divide-y divide-[#26303d] text-xs">
            {form.metrics.map((metric) => (
              <div className="flex items-start justify-between gap-3 py-2" key={metric.label}>
                <dt>{metric.label}</dt>
                <dd className="shrink-0 text-right">
                  <span className="font-mono">{number.format(metric.value)}{metric.unit === "%" ? "%" : " / 90"}</span>
                  {metric.comparison && <span className={`mt-0.5 block text-[11px] ${muted}`}>{metric.comparison}</span>}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <section aria-label="Market clues" className="mt-4 border-t border-[#26303d] pt-4">
        <h3 className="text-sm font-semibold">Previous 24 hours</h3>
        <p className={`mt-1 text-xs leading-relaxed ${muted}`}>
          {trading.buy_share_low === null ? "No trades recorded" : `${trading.buy_share_low}–${trading.buy_share_low + 10}% buy volume · ${trading.activity.toLowerCase()} activity`}
        </p>
        {(card.match_status || card.attention) && <p className={`mt-2 text-xs leading-relaxed ${muted}`}>{[card.match_status, card.attention].filter(Boolean).join(" · ")}</p>}
      </section>
    </>
  );
}

function Choices({ slot }: { slot: number }) {
  return (
    <fieldset className="mt-auto pt-5">
      <legend className="float-left mb-2 w-full text-sm font-semibold">Your 24h prediction<span className="sr-only"> for player {slot + 1}</span></legend>
      <div className="clear-both grid grid-cols-2 gap-1.5">
        {Object.entries(BANDS).flatMap(([band, label]) => (["up", "down"] as const).map((direction) => (
          <label key={`${direction}:${band}`} className="relative min-w-0 cursor-pointer">
            <input className="peer sr-only" type="radio" name={`guess-${slot}`} value={`${direction}:${band}`} required />
            <span className="flex min-h-10 items-center justify-center gap-1 rounded-md border border-[#354155] px-1.5 text-center text-[11px] leading-tight text-[#d9e1ee] hover:border-[#7086a4] peer-checked:border-[#8fb5ff] peer-checked:bg-[#8fb5ff]/15 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[#8fb5ff]">
              <strong>{direction === "up" ? "Up" : "Down"}</strong> {label.toLowerCase()}
            </span>
          </label>
        )))}
      </div>
    </fieldset>
  );
}

function Answer({ result, split }: { result: Result; split: number }) {
  const move = Number(result.move);
  return (
    <>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
        <strong className={`font-mono text-2xl ${move > 0 ? "text-[#63dca0]" : "text-[#ff939a]"}`}>{move > 0 ? "+" : "−"}{exactMove.format(Math.abs(move))}%</strong>
        <span className={`text-xs ${muted}`}>{formatCurrency(result.opening)} to {formatCurrency(result.closing)}</span>
      </div>
      <ReplayChart values={result.chart} split={split} />
      <p className={`mt-3 text-xs leading-relaxed ${muted}`}>
        {result.trading.trades} trades · {number.format(Number(result.trading.buys))} shares bought · {number.format(Number(result.trading.sells))} sold
      </p>
      <details className="mt-4 border-t border-[#26303d] pt-4 text-xs">
        <summary className="cursor-pointer font-semibold text-[#b8d0ff] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#8fb5ff]">Exact form and match stats</summary>
        <p className={`mt-3 ${muted}`}>{result.form.minutes} minutes{result.form.rating !== null && ` · ${number.format(result.form.rating)} average rating`}</p>
        {result.form.metrics.map((metric) => <p key={metric.label} className="mt-1">{metric.label}: {number.format(metric.value)}{metric.unit === "%" ? "%" : " per 90"}</p>)}
        <ul className="mt-3 divide-y divide-[#26303d]">
          {result.form.matches.map((match) => (
            <li key={match.kickoff} className="py-2">
              <p className="font-medium">{match.opponent}</p>
              <p className={`mt-0.5 ${muted}`}>{match.minutes} min{match.rating !== null && ` · ${number.format(match.rating)} rating`}</p>
              {Object.entries(match.stats).map(([label, value]) => <p key={label} className={muted}>{label}: {number.format(value)}</p>)}
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

function Pick({ guess, points }: { guess: Guess; points?: number }) {
  return <p className={`mt-4 border-t border-[#26303d] pt-3 text-xs leading-relaxed ${muted}`}>
    You picked <strong className="text-white">{guess.direction} {BANDS[guess.band].toLowerCase()}</strong>
    {points !== undefined && <> · {points}/2 points</>}
  </p>;
}

export function Game({ round, signedIn }: { round: Round; signedIn: boolean }) {
  const [state, submit, saving] = useActionState(lockGuesses.bind(null, round.day), {});
  const guesses = round.entry?.guesses ?? state.guesses;
  const open = round.state === "open";
  if (round.state === "unavailable") {
    return <div className="rounded-xl border border-[#26303d] bg-[#0e131a] p-6">
      <h2 className="text-lg font-semibold">No replay for this day</h2>
      <p className={`mt-2 text-sm ${muted}`}>A round needs three players with enough recorded trading and match data.</p>
    </div>;
  }
  return (
    <form action={submit}>
      <div className="grid gap-3.5 lg:grid-cols-3">
        {round.cards.map((card, index) => {
          const result = round.results?.[index];
          const guess = guesses?.[index];
          return (
            <article key={index} className="flex min-w-0 flex-col rounded-xl border border-[#26303d] bg-[#0e131a] p-4 md:p-5">
              <header>
                <h2 className="text-lg font-semibold tracking-[-0.02em]">
                  {result ? <Link href={`/instrument/${result.instrument_id}`} className="hover:text-[#b8d0ff] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#8fb5ff]">{result.name}</Link> : `Player ${index + 1}`}
                </h2>
                <p className={`mt-1 text-xs ${muted}`}>{card.position}{result?.club && ` · ${result.club}`}</p>
              </header>
              {result ? <Answer result={result} split={card.chart.length - 1} /> : <Clues card={card} />}
              {guess ? <Pick guess={guess} points={round.entry?.points?.[index]} /> : open && <Choices slot={index} />}
            </article>
          );
        })}
      </div>
      {open && <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[#26303d] pt-4">
        {guesses ? <p role="status" className="text-sm font-semibold text-[#b8d0ff]">Guesses locked. Come back after midnight for the reveal.</p> : <>
          <p className={`text-sm ${muted}`}>The three players are revealed at midnight, Dublin time.</p>
          {signedIn ? <button type="submit" className={action} disabled={saving}>{saving ? "Locking guesses…" : "Lock all three guesses"}</button> : <AuthTrigger className={action}>Sign in to play</AuthTrigger>}
        </>}
        {state.error && <p role="alert" className="w-full text-sm text-[#ff939a]">{state.error}</p>}
      </div>}
    </form>
  );
}

export function Claim({ amount }: { amount: string }) {
  const [state, submit, pending] = useActionState(claimReward, {});
  return <form action={submit} className="flex flex-wrap items-center gap-3">
    <button type="submit" className={action} disabled={pending}>
      {pending ? "Claiming…" : `Claim ${formatCurrency(amount)} virtual cash`}
    </button>
    {state.error && <span role="alert" className="text-sm text-[#ff939a]">{state.error}</span>}
  </form>;
}
