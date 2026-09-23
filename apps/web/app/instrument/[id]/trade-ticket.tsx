"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { formatCurrency } from "@/lib/format";
import type { OrderExecution, OrderQuote, OrderSide } from "@/lib/api";
import { AuthTrigger } from "@/app/components/auth-dialog";

type Props = {
  instrumentId: string;
  playerName: string;
  status: "ACTIVE" | "FROZEN" | "DELISTED";
  cashBalance: string | null;
  ownedQuantity: string;
  currentPrice: string;
};

export function TradeTicket(props: Props) {
  const router = useRouter();
  const [side, setSide] = useState<OrderSide>("BUY");
  const [amount, setAmount] = useState("");
  const [quote, setQuote] = useState<OrderQuote | null>(null);
  const [execution, setExecution] = useState<OrderExecution | null>(null);
  const [requestId, setRequestId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const owned = Number(props.ownedQuantity);
  const active = props.status === "ACTIVE";
  const cashBalance = props.cashBalance;
  const authenticated = cashBalance !== null;
  const currentPrice = Number(props.currentPrice);
  const positionValue = owned * currentPrice;
  const availableAmount = side === "BUY" ? Number(cashBalance ?? 0) : positionValue;

  function chooseSide(next: OrderSide) {
    setSide(next);
    setAmount("");
    setQuote(null);
    setExecution(null);
    setError("");
    setRequestId("");
  }

  function updateAmount(value: string) {
    setAmount(value);
    setQuote(null);
    setExecution(null);
    setError("");
    setRequestId("");
  }

  async function requestQuote(event: FormEvent) {
    event.preventDefault();
    const numeric = Number(amount);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }
    if (numeric > availableAmount + 0.005) {
      setError(side === "BUY" ? "This amount is higher than your available cash." : "This amount is higher than your current position value.");
      return;
    }
    if (!Number.isFinite(currentPrice) || currentPrice <= 0) {
      setError("A live price is not available for this player. Try again shortly.");
      return;
    }
    const settlementQuantity = quantityForAmount(numeric, currentPrice, side, owned, positionValue);
    const id = requestId || crypto.randomUUID();
    setRequestId(id);
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/orders/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: id, instrument_id: props.instrumentId, side, quantity: settlementQuantity }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(orderError(body));
        return;
      }
      setQuote(body);
    } catch {
      setError("The quote could not be loaded. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    if (!quote || !requestId) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId, instrument_id: props.instrumentId, side, quantity: quote.quantity }),
      });
      const body = await response.json();
      if (!response.ok) {
        setQuote(null);
        setError(orderError(body));
        return;
      }
      setExecution(body);
      setQuote(null);
      router.refresh();
    } catch {
      setError("The result is uncertain. Do not submit again yet; refresh your portfolio to verify the trade.");
    } finally {
      setBusy(false);
    }
  }

  if (execution) {
    return (
      <section aria-live="polite" className="rounded-xl border border-[#35d07f]/35 bg-[#35d07f]/[0.06] p-5">
        <div className="flex size-10 items-center justify-center rounded-lg bg-[#35d07f] text-[#07110c]" aria-hidden="true">
          <svg viewBox="0 0 24 24" className="size-5" fill="none"><path d="m5 12 4 4L19 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>
        <h2 className="mt-4 text-lg font-semibold">Trade completed</h2>
        <p className="mt-2 text-xs leading-5 text-[#9fb3a8]">{side === "BUY" ? `Invested ${formatCurrency(execution.gross_amount)} in` : `Sold ${formatCurrency(execution.gross_amount)} of`} {props.playerName}.</p>
        <dl className="mt-5 divide-y divide-[#35d07f]/15 border-y border-[#35d07f]/15 text-xs">
          <Row label={side === "BUY" ? "Total paid" : "Total received"} value={formatCurrency(execution.gross_amount)} />
          <Row label="Position value" value={formatCurrency(Number(execution.position_quantity_after) * Number(execution.new_price))} />
          <Row label="Cash remaining" value={formatCurrency(execution.cash_balance_after)} />
        </dl>
        <button type="button" onClick={() => { setExecution(null); setSide("BUY"); setAmount(""); setRequestId(""); }} className="mt-5 h-10 w-full rounded-lg border border-[#35d07f]/35 text-xs font-bold text-[#75dfa7] hover:bg-[#35d07f]/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Make another trade</button>
      </section>
    );
  }

  if (!authenticated) {
    return (
      <section aria-labelledby="trade-title" className="rounded-xl border border-[#273241] bg-[#0e131a] p-5">
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="trade-title" className="text-lg font-semibold">Trade {props.playerName}</h2><p className="mt-1 text-[11px] text-[#77818e]">Immediate virtual-market order</p></div>
          <span className={`rounded-md px-2 py-1 text-[11px] font-bold ${active ? "bg-[#35d07f]/10 text-[#5ee09a]" : "bg-[#f4bb55]/10 text-[#f4bb55]"}`}>{props.status}</span>
        </div>
        <p className="mt-5 text-xs leading-5 text-[#8d97a3]">Sign in to review live buy and sell quotes, then trade with virtual cash.</p>
        <AuthTrigger className="mt-5 h-11 w-full rounded-lg bg-[#8fb5ff] text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e131a]">Sign in to trade</AuthTrigger>
        <AuthTrigger mode="register" className="mt-3 h-10 w-full rounded-lg border border-[#2a3441] text-xs font-bold text-[#aab3bd] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Create an account</AuthTrigger>
      </section>
    );
  }

  return (
    <section aria-labelledby="trade-title" className="rounded-xl border border-[#273241] bg-[#0e131a] p-5">
      <div className="flex items-start justify-between gap-4">
        <div><h2 id="trade-title" className="text-lg font-semibold">Trade {props.playerName}</h2><p className="mt-1 text-[11px] text-[#77818e]">Immediate virtual-market order</p></div>
        <span className={`rounded-md px-2 py-1 text-[11px] font-bold ${active ? "bg-[#35d07f]/10 text-[#5ee09a]" : "bg-[#f4bb55]/10 text-[#f4bb55]"}`}>{props.status}</span>
      </div>

      <div className="mt-5 grid grid-cols-2 rounded-lg border border-[#273241] bg-[#090d12] p-1">
        {(["BUY", "SELL"] as const).map((value) => (
          <button key={value} type="button" onClick={() => chooseSide(value)} disabled={!active || (value === "SELL" && owned <= 0)} aria-pressed={side === value} className={`h-10 rounded-md text-xs font-extrabold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] disabled:cursor-not-allowed disabled:text-[#4e5966] ${side === value ? value === "BUY" ? "bg-[#35d07f] text-[#07110c]" : "bg-[#f16d73] text-[#160709]" : "text-[#8d97a3] hover:text-white"}`}>{value === "BUY" ? "Buy" : "Sell"}</button>
        ))}
      </div>

      {!active ? <p className="mt-4 rounded-lg border border-[#f4bb55]/25 bg-[#f4bb55]/[0.06] px-3 py-3 text-xs leading-5 text-[#e3bd75]">Trading is paused for this player. You can return when the market is active.</p> : (
        <form onSubmit={requestQuote} className="mt-5">
          <div className="flex items-end justify-between gap-3"><label htmlFor="cash-amount" className="text-xs font-semibold text-[#aab3bd]">Amount</label><span className="text-[11px] text-[#77818e]">{side === "BUY" ? "Available" : "Position value"} {formatCurrency(availableAmount)}</span></div>
          <div className="relative mt-2">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-base font-semibold text-[#77818e]" aria-hidden="true">£</span>
            <input id="cash-amount" name="amount" aria-label="Amount in pounds" value={amount} onChange={(event) => updateAmount(event.target.value)} inputMode="decimal" autoComplete="off" placeholder="0.00" required className="h-12 w-full rounded-lg border border-[#2a3441] bg-[#090d12] pl-8 pr-3 text-base font-semibold tabular-nums text-white outline-none placeholder:text-[#59636f] focus:border-[#8fb5ff] focus:ring-2 focus:ring-[#8fb5ff]/20" />
          </div>
          <div className="mt-2 flex gap-2" aria-label="Quick amounts">
            {[25, 100, 500].filter((value) => value <= availableAmount).map((value) => <button key={value} type="button" onClick={() => updateAmount(String(value))} className="h-8 flex-1 rounded-md border border-[#273241] text-[11px] font-bold text-[#8d97a3] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">{formatCurrency(value)}</button>)}
            {side === "SELL" && owned > 0 && <button type="button" onClick={() => updateAmount(positionValue.toFixed(2))} className="h-8 flex-1 rounded-md border border-[#273241] text-[11px] font-bold text-[#8fb5ff] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Max</button>}
          </div>
          <div className="mt-4 flex items-center justify-between text-xs"><span className="text-[#77818e]">{side === "BUY" ? "Cash after order" : "Available cash"}</span><strong className="tabular-nums text-white">{formatCurrency(side === "BUY" ? Math.max(0, Number(cashBalance) - Number(amount || 0)) : cashBalance)}</strong></div>

          {error && <div role="alert" className="mt-4 rounded-lg border border-[#f16d73]/35 bg-[#f16d73]/[0.08] px-3 py-3 text-xs leading-5 text-[#ff9ca1]">{error}</div>}

          {quote && (
            <div className="mt-5 border-y border-[#273241] py-4" aria-live="polite">
              <h3 className="text-xs font-bold text-white">Review your {side.toLowerCase()}</h3>
              <dl className="mt-3 divide-y divide-[#202832] text-xs">
                <Row label={side === "BUY" ? "Cash to invest" : "Cash to receive"} value={formatCurrency(quote.gross_amount)} />
                <Row label="Position after order" value={formatCurrency(Number(quote.position_quantity_after) * Number(quote.new_price))} />
                <Row label="Cash after order" value={formatCurrency(quote.cash_balance_after)} />
              </dl>
              <p className="mt-3 text-[11px] leading-4 text-[#687380]">The market may move before execution. Your receipt will show the final cash amount.</p>
            </div>
          )}

          {quote ? (
            <div className="mt-4 grid grid-cols-[0.7fr_1.3fr] gap-2">
              <button type="button" onClick={() => setQuote(null)} disabled={busy} className="h-11 rounded-lg border border-[#2a3441] text-xs font-bold text-[#aab3bd] hover:border-[#46566b] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff]">Back</button>
              <button type="button" onClick={execute} disabled={busy} className={`h-11 rounded-lg text-xs font-extrabold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] disabled:cursor-not-allowed disabled:bg-[#46566e] ${side === "BUY" ? "bg-[#35d07f] text-[#07110c] hover:bg-[#62e3a0]" : "bg-[#f16d73] text-[#160709] hover:bg-[#ff8a90]"}`}>{busy ? "Submitting…" : `Confirm ${side.toLowerCase()}`}</button>
            </div>
          ) : <button type="submit" disabled={busy || !amount} className="mt-5 h-11 w-full rounded-lg bg-[#8fb5ff] text-xs font-extrabold text-[#080b10] hover:bg-[#a9c6ff] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8fb5ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0e131a] disabled:cursor-not-allowed disabled:bg-[#46566e] disabled:text-[#aab4c1]">{busy ? "Loading quote…" : "Review order"}</button>}
        </form>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 py-2.5"><dt className="text-[#77818e]">{label}</dt><dd className="font-semibold tabular-nums text-white">{value}</dd></div>;
}

function quantityForAmount(amount: number, price: number, side: OrderSide, owned: number, positionValue: number) {
  const quantity = side === "SELL" && amount >= positionValue - 0.005 ? owned : amount / price;
  return quantity.toFixed(6);
}

function orderError(body: { code?: string; message?: string; detail?: unknown }) {
  const messages: Record<string, string> = {
    insufficient_cash: "You do not have enough available cash for this order.",
    insufficient_position: "You do not own enough shares to complete this sale.",
    instrument_frozen: "Trading is currently paused for this player.",
    instrument_not_tradable: "This player stock is not currently tradable.",
    idempotency_request_mismatch: "This order changed after submission. Start a new order and try again.",
  };
  return (body.code && messages[body.code]) || body.message || "The order could not be completed. Review it and try again.";
}
